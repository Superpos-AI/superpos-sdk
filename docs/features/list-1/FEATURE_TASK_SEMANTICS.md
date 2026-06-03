# Superpos — Feature: Advanced Task Semantics

## Addendum to PRODUCT.md v4.0

---

## 1. Task Delivery Patterns

### 1.1 Overview

| Pattern       | Description                          | Example                                    |
|---------------|--------------------------------------|--------------------------------------------|
| **Unicast**   | Task → specific agent                | "Agent-7, deploy this build"               |
| **Anycast**   | Task → first capable agent           | "Any code_reviewer, review PR #42"         |
| **Fan-out**   | Parent task → N child tasks          | "Test on Chrome, Firefox, Safari"          |
| **Fan-in**    | N child results → parent completes   | "All 3 browser tests passed → deploy"      |
| **Broadcast** | Event to all subscribed agents       | "Deploy completed" (use Event Bus, not tasks) |

### 1.2 Unicast (existing)

```json
POST /api/v1/tasks
{
  "type": "deploy",
  "target_agent_id": "agt_deployer_7",
  "payload": { "build": "v2.5.0" }
}
```

One agent, one claim, one result. Simple.

### 1.3 Anycast (existing)

```json
POST /api/v1/tasks
{
  "type": "code_review",
  "target_capability": "code_review",
  "payload": { "pr": 42 }
}
```

First agent with `code_review` capability claims it. Atomic claim prevents double pickup.

### 1.4 Fan-out + Fan-in (new)

Parent task spawns N children. Parent tracks aggregate completion.

```json
POST /api/v1/tasks
{
  "type": "browser_test_suite",
  "payload": { "url": "https://staging.app.com", "test_suite": "smoke" },
  "children": [
    {
      "type": "browser_test",
      "target_capability": "testing:chrome",
      "payload": { "browser": "chrome" }
    },
    {
      "type": "browser_test",
      "target_capability": "testing:firefox",
      "payload": { "browser": "firefox" }
    },
    {
      "type": "browser_test",
      "target_capability": "testing:safari",
      "payload": { "browser": "safari" }
    }
  ],
  "completion_policy": {
    "type": "all"
  }
}
```

What happens:
1. Parent task created with status `awaiting_children`
2. Three child tasks created, each with `parent_task_id` pointing to parent
3. Children enter the queue independently — different agents can claim them
4. As each child completes, parent checks completion policy
5. When policy is satisfied → parent status becomes `completed`, result aggregated

**Atomicity:** Parent and all children are created within a single DB transaction. If any child creation fails, the entire transaction rolls back — no orphaned parent or partial children. If the transaction fails, the API returns an error indicating which children could not be created.

---

## 2. Completion Policies

The `completion_policy` on a parent task defines when the parent is considered done.

### 2.1 Policy Types

| Policy            | Parent completes when...                    | Parent fails when...                  |
|-------------------|---------------------------------------------|---------------------------------------|
| `all` (default)   | Every child completed                       | Any child failed (and no retries left)|
| `any`             | First child completed                       | All children failed                   |
| `count(n)`        | N children completed                        | Not enough children can succeed       |
| `ratio(0.8)`      | 80% of children completed                   | Impossible to reach ratio             |
| `custom`          | External agent decides (manual fan-in)      | External agent decides                |

**Concurrency safety:** Completion policy evaluation acquires a `FOR UPDATE` lock on the parent row. When multiple children complete simultaneously, their completion handlers serialize through this lock. Evaluation is idempotent — re-evaluating with the same child states produces the same result, so duplicate evaluations are harmless.

### 2.2 Examples

**"All must pass" (test suite):**
```json
{
  "completion_policy": {
    "type": "all",
    "fail_fast": true
  }
}
```
`fail_fast: true` — if one child fails, immediately cancel remaining children and fail parent.
`fail_fast: false` (default) — let all children finish, then report aggregate.

**"First one wins" (redundant execution):**
```json
{
  "completion_policy": {
    "type": "any",
    "cancel_remaining": true
  }
}
```
Send same request to 3 LLM providers, take first response, cancel rest.

**"Need 3 out of 5 reviews":**
```json
{
  "completion_policy": {
    "type": "count",
    "required": 3,
    "cancel_remaining": true
  }
}
```

**"Manual aggregation" (agent collects results itself):**
```json
{
  "completion_policy": {
    "type": "custom",
    "aggregator_capability": "result_aggregator"
  }
}
```
When all children done, creates a new task for an aggregator agent with all child results.

### 2.3 Result Aggregation

When parent completes, `result` contains all child results:

```json
{
  "task_id": "tsk_parent",
  "status": "completed",
  "result": {
    "children": [
      { "task_id": "tsk_child_1", "status": "completed", "result": { "passed": true } },
      { "task_id": "tsk_child_2", "status": "completed", "result": { "passed": true } },
      { "task_id": "tsk_child_3", "status": "failed", "result": { "error": "timeout" } }
    ],
    "summary": {
      "total": 3,
      "completed": 2,
      "failed": 1
    }
  }
}
```

---

## 3. Failure Handling

### 3.1 The Problem

Distributed agents fail in many ways:
- Agent process crashes (hard death — no heartbeat)
- Agent hangs (soft death — heartbeat continues but task stuck)
- Agent is slow (not dead, just taking long)
- Task itself is poison (causes agent to crash every time)

### 3.2 Task-Level Failure Config

Every task can declare its failure behavior at creation time:

```json
POST /api/v1/hives/{hive}/tasks
{
  "type": "code_review",
  "target_capability": "code_review",
  "payload": { "pr": 42 },
  "idempotency_key": "review-pr-42-v1",
  "failure_policy": {
    "task_timeout": 300,
    "progress_timeout": 60,
    "on_timeout": "reassign",
    "max_retries": 3,
    "retry_delay": "exponential",
    "retry_delay_base": 5,
    "retry_jitter": true,
    "on_max_retries_exceeded": "fail"
  }
}
```

### 3.3 Two Timeout Clocks

```
Agent claims task
  │
  ├── progress_timeout (60s) ──── resets on every heartbeat/progress update
  │   "Agent hasn't reported ANY progress in 60s → probably dead"
  │
  └── task_timeout (300s) ──────── absolute, never resets
      "Task has been running for 5 min total → hard deadline"
```

**`progress_timeout`** — detects dead/stuck agents quickly. Resets every time agent calls:
- `PATCH /tasks/{id}/progress` (progress update)
- `POST /agents/heartbeat` with task in active_tasks

**`task_timeout`** — absolute deadline. Even if agent is alive and sending heartbeats.
Catches the "agent thinks it's working but is actually stuck in a loop" case.

### 3.4 On Timeout Actions

| Action       | What happens                                                  |
|--------------|---------------------------------------------------------------|
| `reassign`   | Task returns to `pending`, can be claimed by another agent    |
| `fail`       | Task marked `failed` immediately                              |
| `retry`      | Task returns to `pending` with incremented retry_count        |
| `notify`     | Task stays `in_progress` but approval_request created for human |

`reassign` vs `retry`: functionally similar, but `retry` increments counter and respects `max_retries`. `reassign` does not count as a retry (agent died, not agent's fault).

### 3.5 Retry Strategy

```
retry_delay: "none"          → immediate retry
retry_delay: "fixed"         → wait retry_delay_base seconds each time
retry_delay: "exponential"   → base * 2^(retry_count - 1)
                               5s → 10s → 20s → 40s → ...
retry_delay: "exponential"   → capped by retry_delay_max (default 300s)
```

**`retry_jitter`** (boolean, default `true`): When enabled, adds random jitter to
the computed backoff delay. This prevents the "thundering herd" problem where
multiple tasks with the same retry schedule all retry at the exact same instant.
Set to `false` for deterministic backoff timing (useful in tests).

### 3.6 What Happens After Max Retries

| Action            | What happens                                              |
|-------------------|-----------------------------------------------------------|
| `fail`            | Task marked `failed`, parent notified                     |
| `dead_letter`     | Task moved to `dead_letter` status for manual inspection  |
| `notify`          | Task marked `failed` + approval_request to human          |

```json
{
  "on_max_retries_exceeded": "dead_letter"
}
```

Dashboard shows dead-letter tasks prominently — these need human attention.

### 3.7 Default Failure Policy

If task doesn't specify `failure_policy`, system defaults apply:

```php
// config/apiary.php
'task_defaults' => [
    'task_timeout' => env('SUPERPOS_DEFAULT_TASK_TIMEOUT', 300),
    'progress_timeout' => env('SUPERPOS_DEFAULT_PROGRESS_TIMEOUT', 60),
    'on_timeout' => 'retry',
    'max_retries' => 3,
    'retry_delay' => 'exponential',
    'retry_delay_base' => 5,
    'retry_delay_max' => 300,
    'retry_jitter' => true,
    'on_max_retries_exceeded' => 'fail',
],
```

---

## 4. Idempotency

### 4.1 The Problem

Task times out → reassigned → both old agent (recovered) and new agent execute it.
Result: email sent twice, PR merged twice, deployment runs twice.

### 4.2 Solution: Idempotency Keys

```json
{
  "type": "send_email",
  "payload": { "to": "client@acme.com", "subject": "Report" },
  "idempotency_key": "send-report-client-2025-02-20"
}
```

Rules:
- System stores `idempotency_key` → `task_id` mapping
- If a task with same key already exists and is `completed` → return existing result, don't create new task
- If existing task is `pending`/`in_progress` → return existing task_id (dedup)
- If existing task is `failed`/`dead_letter` → allow new task (retry semantics)
- Keys expire after configurable TTL (default 24h)

### 4.3 Agent-Side Idempotency

For agents executing tasks, the SDK provides a check:

```python
task = client.claim()
if task:
    # Check if this work was already done (by a previous attempt)
    existing = client.knowledge_get(f"idempotent:{task.idempotency_key}")
    if existing:
        client.complete(task.id, result=existing.value)
    else:
        result = do_work(task)
        client.knowledge_set(
            f"idempotent:{task.idempotency_key}",
            result,
            ttl=86400
        )
        client.complete(task.id, result=result)
```

Platform-level idempotency prevents duplicate tasks.
Agent-level idempotency prevents duplicate side effects.

---

## 5. Task Dependencies (Declarative)

### 5.1 The Problem

Agent A creates 3 data requests. Wants to continue only when all 3 complete.
Currently: agent must poll all 3 individually in a loop. Wasteful and complex.

### 5.2 Solution: `depends_on` + Auto-Trigger

```json
POST /api/v1/hives/{hive}/tasks
{
  "type": "generate_report",
  "target_capability": "report_generator",
  "payload": {
    "template": "quarterly_review"
  },
  "depends_on": {
    "tasks": ["tsk_email_data", "tsk_jira_data", "tsk_sales_data"],
    "policy": "all",
    "inject_results": true
  }
}
```

**`depends_on` fields:**

| Field                  | Type     | Required | Description                                                     |
|------------------------|----------|----------|-----------------------------------------------------------------|
| `tasks`                | array    | Yes      | Task IDs to depend on (1-50 items, each a 26-char ULID string) |
| `policy`               | string   | No       | `all` (default) or `any`                                        |
| `inject_results`       | boolean  | No       | Inject dependency results into payload (default `false`)        |
| `on_dependency_failure` | string  | No       | `fail` (default), `partial`, or `wait`                          |

> **Constraint:** `depends_on` and `children` (fan-out) are **mutually exclusive**.
> A task cannot declare both -- the API enforces this with a validation error.
> The two features operate at different levels: fan-out creates subtasks under a
> parent, while `depends_on` waits on existing tasks created elsewhere.

What happens:
1. Task created with status `waiting` (new status — not in queue yet)
2. System monitors the 3 dependency tasks
3. When all 3 complete → task moves to `pending` with dependency results injected
4. Agent polls, sees the task, claims it
5. Task payload now includes results from all dependencies

### 5.3 Injected Results

When agent claims the dependent task, payload includes:

```json
{
  "type": "generate_report",
  "payload": {
    "template": "quarterly_review",
    "_dependencies": {
      "tsk_email_data": {
        "status": "completed",
        "result": { "emails": [...] }
      },
      "tsk_jira_data": {
        "status": "completed",
        "result": { "issues": [...] }
      },
      "tsk_sales_data": {
        "status": "completed",
        "result": { "revenue": 150000 }
      }
    }
  }
}
```

Agent gets all the data it needs in one clean payload. No polling.

**Large results:** If a dependency result exceeds 1MB, only a reference is injected instead of the full data:
```json
"tsk_email_data": {
  "status": "completed",
  "_dependency_ref": "tsk_email_data"
}
```
The agent retrieves the full result separately via `GET /api/v1/tasks/tsk_email_data`. This prevents payload bloat when dependencies produce large datasets.

### 5.4 Dependency Failure

```json
{
  "depends_on": {
    "tasks": ["tsk_a", "tsk_b", "tsk_c"],
    "policy": "all",
    "on_dependency_failure": "fail"
  }
}
```

| Policy on failure | What happens                                          |
|-------------------|-------------------------------------------------------|
| `fail`            | Dependent task fails immediately                      |
| `partial`         | Dependent task gets pending with partial results      |
| `wait`            | Keep waiting (maybe dependency gets retried)          |

### 5.5 Dynamic Dependencies

Agent can add dependencies to existing tasks:

```json
PATCH /api/v1/tasks/tsk_report/dependencies
{
  "add": ["tsk_new_data_request"],
  "remove": []
}
```

Only works while task is in `waiting` status.

### 5.6 Combining with Fan-Out

A common pattern: fan-out work, then fan-in results into a follow-up task.

```json
POST /api/v1/tasks
{
  "type": "cross_browser_test",
  "children": [
    { "type": "test", "target_capability": "testing:chrome", "payload": {"browser": "chrome"} },
    { "type": "test", "target_capability": "testing:firefox", "payload": {"browser": "firefox"} }
  ],
  "completion_policy": { "type": "all" },
  "on_complete": {
    "spawn_task": {
      "type": "deploy_if_green",
      "target_capability": "deployer",
      "depends_on_parent_result": true
    }
  }
}
```

1. Parent creates 2 children (fan-out)
2. Both complete (fan-in)
3. Parent completes → auto-spawns `deploy_if_green` with test results injected

This is a **mini-workflow** defined entirely in task config — no workflow engine needed.

---

## 6. Task Lifecycle (Updated)

### 6.1 Full State Machine

```
                            ┌──────────────────────────────────────────────┐
                            │                                              │
     ┌──────────┐    dependencies    ┌──────────┐    claimed     ┌────────▼──────┐
     │          │    met             │          │   by agent     │               │
────▸│ waiting  │ ──────────────────▸│ pending  │ ──────────────▸│  in_progress  │
     │          │                    │          │                │               │
     └────┬─────┘                    └────┬─────┘                └──┬────┬───┬───┘
          │                               │                         │    │   │
          │ dependency                    │ timeout                 │    │   │ progress_timeout
          │ failed                        │ (no agent               │    │   │ or task_timeout
          │                               │  claimed it)            │    │   │
          ▼                               ▼                         │    │   ▼
     ┌──────────┐                    ┌──────────┐                  │    │  ┌──────────────┐
     │  failed   │                    │  expired  │                  │    │  │  retry /      │
     └──────────┘                    └──────────┘                  │    │  │  reassign     │
                                                                    │    │  └──────┬───────┘
                                          agent completes           │    │         │
                                     ┌──────────────────────────────┘    │         │ back to
                                     │                                   │         │ pending
                                     ▼                                   │         │
                                ┌──────────┐     agent reports failure   │         │
                                │completed │          ┌─────────────────┘         │
                                └──────────┘          │                            │
                                                      ▼                            │
                                ┌──────────┐     ┌──────────┐                      │
                                │cancelled │     │  failed   │                      │
                                └──────────┘     └──────────┘                      │
                                                                                   │
                                ┌──────────┐                                       │
                                │dead_     │◂──── max_retries exceeded ────────────┘
                                │letter    │      with on_exceeded: dead_letter
                                └──────────┘

     ┌───────────────────┐
     │awaiting_children  │◂──── parent with children, waiting for completion_policy
     └────────┬──────────┘
              │ policy satisfied
              ▼
         ┌──────────┐
         │completed │
         └──────────┘
```

> **Note on approvals:** The approval mechanism (`approval_request`) exists for
> proxy actions, but tasks do **not** have a separate `awaiting_approval` status.
> A task remains `in_progress` while its agent awaits human approval for a proxy
> action. The `on_timeout: notify` action similarly keeps the task `in_progress`
> and creates an `approval_request` for a human.

### 6.2 Status Summary

| Status               | Meaning                                          | Transitions to              |
|----------------------|--------------------------------------------------|-----------------------------|
| `waiting`            | Has unmet dependencies                           | pending, failed             |
| `pending`            | In queue, ready to be claimed                    | in_progress, expired        |
| `in_progress`        | Agent is working on it                           | completed, failed, retry    |
| `awaiting_children`  | Parent waiting for child tasks                   | completed, failed           |
| `completed`          | Done successfully                                | (terminal)                  |
| `failed`             | Failed permanently                               | (terminal)                  |
| `cancelled`          | Cancelled by user, agent, or system              | (terminal)                  |
| `expired`            | Sat in pending too long, nobody claimed           | (terminal)                  |
| `dead_letter`        | Failed after all retries, needs manual attention  | pending (manual re-queue)   |

### 6.3 Atomic Claim (unchanged)

```sql
UPDATE tasks
SET status = 'in_progress',
    claimed_by = :agent_id,
    claimed_at = NOW()
WHERE id = :task_id
  AND status = 'pending'
RETURNING *;
```

Zero rows returned → someone else got it. Agent moves on.

---

## 7. Backpressure

### 7.1 The Problem

- Agent creates tasks faster than workers consume → queue grows unbounded
- 500 pending tasks, 1 worker → latency spikes, memory pressure
- No feedback to task creators about queue health

### 7.2 Queue Depth Limits

Per-hive or per-task-type configurable limits:

```json
// Hive settings or task type config
{
  "queue_limits": {
    "code_review": {
      "max_pending": 50,
      "max_in_progress": 10,
      "on_limit": "reject"
    },
    "data_request": {
      "max_pending": 200,
      "max_in_progress": 20,
      "on_limit": "throttle"
    },
    "_default": {
      "max_pending": 500,
      "on_limit": "accept_warn"
    }
  }
}
```

### 7.3 On Limit Actions

| Action         | Behavior                                                    |
|----------------|-------------------------------------------------------------|
| `accept_warn`  | Accept task, return warning header in response              |
| `throttle`     | Accept task, increase `next_poll_ms` for creator            |
| `reject`       | Return 429 with `retry_after` header                        |
| `queue`        | Accept into overflow queue with lower priority              |

### 7.4 Response to Agent

Normal response:
```json
{ "task_id": "tsk_abc", "status": "pending" }
```

Throttled response:
```json
{
  "task_id": "tsk_abc",
  "status": "pending",
  "warnings": ["queue_depth_high"],
  "queue_depth": 187,
  "recommended_delay_ms": 5000
}
```

Rejected response:
```json
{
  "error": "queue_full",
  "queue_type": "code_review",
  "current_depth": 50,
  "retry_after": 30
}
```

**Note:** `recommended_delay_ms` is advisory — it suggests the interval before the agent's **next poll**, not a delay on task creation. SDKs should respect it by default, but agents can override if they have urgent work. Similarly, `retry_after` (on 429 rejection) applies to the next task creation attempt for that queue type.

### 7.5 Dynamic Poll Interval (existing, enhanced)

The system already returns `next_poll_ms` on poll responses. Enhance it:

```json
GET /api/v1/tasks/poll

{
  "tasks": [],
  "next_poll_ms": 5000,
  "queue_status": {
    "pending_for_you": 0,
    "pending_total": 47,
    "pressure": "normal"
  }
}
```

`pressure` values: `low` (queue nearly empty) → `normal` → `high` → `critical` (near limit).
Agents can use this to self-regulate (create fewer tasks when pressure is high).

---

## 8. Guaranteed vs Best-Effort Tasks

### 8.1 Two Delivery Guarantees

Not all tasks are equal. "Send invoice to client" cannot be lost. "Update cache" can.

```json
POST /api/v1/tasks
{
  "type": "send_invoice",
  "guarantee": "at_least_once",
  ...
}
```

```json
POST /api/v1/tasks
{
  "type": "update_cache",
  "guarantee": "best_effort",
  ...
}
```

### 8.2 Guarantee Behaviors

| Aspect                | `at_least_once`                    | `best_effort`                    |
|-----------------------|------------------------------------|----------------------------------|
| **On timeout**        | Always retry/reassign              | May drop after timeout           |
| **Max retries**       | Respected, then dead_letter        | Respected, then fail (no DLQ)    |
| **Persistence**       | Persisted to DB immediately        | Can be Redis-only (faster)       |
| **Expiry**            | No auto-expire                     | Can have `expires_at`            |
| **Idempotency**       | Strongly recommended               | Optional                         |
| **Dashboard**         | Prominent alerts on failure        | Logged but not alerted           |
| **Default failure**   | `on_exceeded: dead_letter`         | `on_exceeded: fail`              |

### 8.3 Best-Effort with Expiry

"Update the dashboard cache, but if nobody picks this up in 30 seconds, skip it — a new one will come."

```json
{
  "type": "refresh_dashboard_cache",
  "guarantee": "best_effort",
  "expires_at": "2025-02-20T12:00:30Z"
}
```

Scheduler sweeps expired pending tasks → marks them `expired`. Clean.

---

## 9. Schema Changes

### 9.1 Tasks Table Additions

```sql
ALTER TABLE tasks ADD COLUMN failure_policy JSONB DEFAULT '{}';
-- {
--   task_timeout, progress_timeout, on_timeout,
--   max_retries, retry_delay, retry_delay_base, retry_delay_max,
--   retry_jitter, on_max_retries_exceeded
-- }

ALTER TABLE tasks ADD COLUMN idempotency_key VARCHAR(255) DEFAULT NULL;
-- Top-level field, not inside failure_policy

ALTER TABLE tasks ADD COLUMN completion_policy JSONB DEFAULT NULL;
-- {
--   type: all|any|count|ratio|custom,
--   fail_fast, cancel_remaining, required, aggregator_capability
-- }

ALTER TABLE tasks ADD COLUMN guarantee VARCHAR(20) DEFAULT 'at_least_once';
-- 'at_least_once' or 'best_effort'

ALTER TABLE tasks ADD COLUMN last_progress_at TIMESTAMP;
-- For progress_timeout tracking

ALTER TABLE tasks ADD COLUMN retry_after TIMESTAMP;
-- Don't pick up before this time (for exponential backoff)

ALTER TABLE tasks ADD COLUMN expires_at TIMESTAMP;
-- For best_effort tasks with expiry

ALTER TABLE tasks ADD COLUMN children_summary JSONB DEFAULT NULL;
-- { total: 3, completed: 2, failed: 0, in_progress: 1 }
-- Cached on parent, updated when children change status

ALTER TABLE tasks ADD COLUMN on_complete JSONB DEFAULT NULL;
-- { spawn_task: { type, target_capability, depends_on_parent_result } }

ALTER TABLE tasks ADD COLUMN depends_on JSONB DEFAULT NULL;
-- {
--   tasks: [string(26), ...] (required, 1-50 items),
--   policy: all|any (optional, default all),
--   inject_results: bool (optional),
--   on_dependency_failure: fail|partial|wait (optional, default fail)
-- }
-- (task list also normalised into task_dependencies table for indexed queries)
```

### 9.2 Task Dependencies Table

```sql
CREATE TABLE task_dependencies (
    task_id         VARCHAR(26) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_id   VARCHAR(26) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status          VARCHAR(20) DEFAULT 'pending',  -- pending, met, failed
    PRIMARY KEY (task_id, depends_on_id)
);

CREATE INDEX idx_task_deps_waiting ON task_dependencies (depends_on_id, status)
    WHERE status = 'pending';
```

### 9.3 Idempotency Keys Table

```sql
CREATE TABLE task_idempotency (
    idempotency_key VARCHAR(255) NOT NULL,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    task_id         VARCHAR(26) NOT NULL REFERENCES tasks(id),
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (superpos_id, hive_id, idempotency_key)
);

CREATE INDEX idx_idempotency_expires ON task_idempotency (expires_at);
```

### 9.4 Queue Limits Config

Stored in `hives.settings` JSONB — no new table:

```json
{
  "queue_limits": {
    "code_review": { "max_pending": 50, "on_limit": "reject" },
    "_default": { "max_pending": 500, "on_limit": "accept_warn" }
  }
}
```

### 9.5 Updated Poll Query

```sql
SELECT * FROM tasks
WHERE hive_id = :hive_id
  AND status = 'pending'
  AND (target_agent_id = :agent_id OR target_agent_id IS NULL)
  AND (target_capability = ANY(:agent_capabilities) OR target_capability IS NULL)
  AND (retry_after IS NULL OR retry_after <= NOW())
  AND (expires_at IS NULL OR expires_at > NOW())
ORDER BY priority ASC, created_at ASC
LIMIT 5;
```

Added: `retry_after` check (backoff), `expires_at` check (best-effort expiry).

---

## 10. Scheduler Jobs

### 10.1 CheckProgressTimeouts (runs every 15s)

Honors the per-task `on_timeout` policy. Uses `COALESCE(last_progress_at, claimed_at)`
so that tasks where the agent dies before sending any progress update are still
detected (the claim SQL sets `claimed_at` but not `last_progress_at`). Both
`retry` and `reassign` clear `last_progress_at` on requeue so the next claim
starts a fresh timeout window — without this, a stale value from the previous
attempt would cause the reclaimed task to time out immediately.

`reassign` and `retry` are handled by **separate** statements with distinct semantics:

- **`retry`** increments `retry_count`, respects `max_retries`, and applies backoff
  delay (`none`/`fixed`/`exponential`) capped by `retry_delay_max`.
- **`reassign`** does **not** increment `retry_count` or apply any backoff — the agent
  crashed, so the task returns to the queue immediately for another agent to claim.

```sql
-- Retry: return to queue with backoff, increment retry_count.
-- last_progress_at is cleared so the next claim starts a fresh timeout window.
UPDATE tasks
SET status = 'pending',
    claimed_by = NULL,
    last_progress_at = NULL,
    retry_count = retry_count + 1,
    retry_after = CASE COALESCE(failure_policy->>'retry_delay', 'exponential')
      WHEN 'none' THEN NULL
      WHEN 'fixed' THEN NOW() + make_interval(
        secs => (failure_policy->>'retry_delay_base')::int
      )
      ELSE /* exponential (default) */ NOW() + make_interval(
        secs => LEAST(
          (failure_policy->>'retry_delay_base')::int
            * POWER(2, retry_count)::int,
          COALESCE((failure_policy->>'retry_delay_max')::int, 300)
        )
      )
    END
WHERE status = 'in_progress'
  AND COALESCE(last_progress_at, claimed_at)
        < NOW() - make_interval(secs => (failure_policy->>'progress_timeout')::int)
  AND retry_count < (failure_policy->>'max_retries')::int
  AND COALESCE(failure_policy->>'on_timeout', 'retry') = 'retry';

-- Reassign: return to queue immediately — no retry_count increment, no backoff.
-- The agent crashed; this is not counted against the task's retry budget.
-- last_progress_at is cleared so the next claim starts a fresh timeout window.
UPDATE tasks
SET status = 'pending',
    claimed_by = NULL,
    last_progress_at = NULL
WHERE status = 'in_progress'
  AND COALESCE(last_progress_at, claimed_at)
        < NOW() - make_interval(secs => (failure_policy->>'progress_timeout')::int)
  AND (failure_policy->>'on_timeout') = 'reassign';

-- Fail: mark as failed immediately
UPDATE tasks
SET status = 'failed',
    completed_at = NOW()
WHERE status = 'in_progress'
  AND COALESCE(last_progress_at, claimed_at)
        < NOW() - make_interval(secs => (failure_policy->>'progress_timeout')::int)
  AND (failure_policy->>'on_timeout') = 'fail';

-- Notify: keep in_progress but create approval_request for human
-- (handled in application code — scheduler dispatches NotifyTimeoutJob
--  for rows matching the predicate with on_timeout = 'notify')
```

Tasks exceeding `max_retries` → handled separately (fail or dead_letter).

### 10.2 CheckTaskTimeouts (runs every 30s)

```sql
-- Hard deadline: task running too long (absolute wall-clock limit)
UPDATE tasks
SET status = CASE
    WHEN (failure_policy->>'on_max_retries_exceeded') = 'dead_letter' THEN 'dead_letter'
    ELSE 'failed'
  END,
  completed_at = NOW()
WHERE status = 'in_progress'
  AND claimed_at + make_interval(secs => (failure_policy->>'task_timeout')::int) < NOW();
```

### 10.3 CheckDependencies (runs every 5s)

The release query must verify that **every** dependency is `met` — not merely that
none are `pending`. Without this check, a task whose dependency failed would be
promoted to `pending`, bypassing `on_dependency_failure` handling.

Three dependency failure policies are supported (read from the top-level `depends_on`
JSONB column, **not** from `failure_policy`):

- **`fail`** (default): fail the waiting task immediately when any dependency fails.
- **`partial`**: release to `pending` once every dependency is resolved (`met` or
  `failed`), letting the task run with whatever data is available.
- **`wait`**: keep waiting — the failed dependency may be retried and eventually
  succeed, or a human can intervene.

```sql
-- Move tasks from waiting → pending when ALL dependencies are met.
-- The EXISTS guard prevents releasing tasks that have no dependency rows at all.
UPDATE tasks t
SET status = 'pending'
WHERE t.status = 'waiting'
  AND NOT EXISTS (
    SELECT 1 FROM task_dependencies td
    WHERE td.task_id = t.id AND td.status <> 'met'
  )
  AND EXISTS (
    SELECT 1 FROM task_dependencies td
    WHERE td.task_id = t.id
  );

-- Fail tasks whose dependencies failed (when on_dependency_failure = 'fail')
UPDATE tasks t
SET status = 'failed',
    completed_at = NOW()
WHERE t.status = 'waiting'
  AND EXISTS (
    SELECT 1 FROM task_dependencies td
    WHERE td.task_id = t.id AND td.status = 'failed'
  )
  AND COALESCE(t.depends_on->>'on_dependency_failure', 'fail') = 'fail';

-- Partial release: move to pending once every dep is resolved (met or failed)
-- and on_dependency_failure = 'partial' — task runs with whatever completed.
UPDATE tasks t
SET status = 'pending'
WHERE t.status = 'waiting'
  AND NOT EXISTS (
    SELECT 1 FROM task_dependencies td
    WHERE td.task_id = t.id AND td.status = 'pending'
  )
  AND EXISTS (
    SELECT 1 FROM task_dependencies td
    WHERE td.task_id = t.id AND td.status = 'failed'
  )
  AND COALESCE(t.depends_on->>'on_dependency_failure', 'fail') = 'partial';

-- on_dependency_failure = 'wait': no action — task remains in 'waiting'
-- until the failed dependency is retried and eventually succeeds or a
-- human intervenes.
```

### 10.4 CleanupExpiredTasks (runs every 60s)

```sql
UPDATE tasks
SET status = 'expired'
WHERE status = 'pending'
  AND expires_at IS NOT NULL
  AND expires_at < NOW();
```

### 10.5 CleanupIdempotencyKeys (runs every hour)

```sql
DELETE FROM task_idempotency WHERE expires_at < NOW();
```

### 10.6 UpdateChildrenSummary (triggered, not scheduled)

On every child task status change, update parent's `children_summary`:

```sql
UPDATE tasks
SET children_summary = (
  SELECT jsonb_build_object(
    'total', COUNT(*),
    'completed', COUNT(*) FILTER (WHERE status = 'completed'),
    'failed', COUNT(*) FILTER (WHERE status = 'failed'),
    'in_progress', COUNT(*) FILTER (WHERE status IN ('pending', 'in_progress')),
    'cancelled', COUNT(*) FILTER (WHERE status = 'cancelled')
  )
  FROM tasks WHERE parent_task_id = :parent_id
)
WHERE id = :parent_id;
```

Then evaluate `completion_policy` to decide if parent should complete/fail.

---

## 11. API Changes

### 11.1 Create Task (expanded)

> **Note:** All task API paths are hive-scoped: `/api/v1/hives/{hive}/tasks/...`
> The simplified `/api/v1/tasks/...` form shown in earlier sections is shorthand.

```json
POST /api/v1/hives/{hive}/tasks
{
  "type": "code_review",
  "delivery_mode": "default",
  "target_capability": "code_review",
  "payload": { "pr": 42 },
  "invoke": {
    "instructions": "Review this PR for security issues",
    "context": { "repo": "acme/api" }
  },

  "idempotency_key": "review-pr-42",
  "guarantee": "at_least_once",

  "failure_policy": {
    "task_timeout": 600,
    "progress_timeout": 120,
    "on_timeout": "retry",
    "max_retries": 3,
    "retry_delay": "exponential",
    "retry_delay_base": 10,
    "retry_jitter": true,
    "on_max_retries_exceeded": "dead_letter"
  },

  "thread_id": null,
  "context_message": null,

  "children": [ /* optional fan-out */ ],
  "completion_policy": { /* optional, for parent tasks */ },
  "depends_on": { /* optional, declarative dependencies — mutually exclusive with children */ },
  "on_complete": { /* optional, auto-spawn follow-up */ },
  "expires_at": null
}
```

| Field             | Type    | Description                                                        |
|-------------------|---------|--------------------------------------------------------------------|
| `delivery_mode`   | string  | `default` or `stream`                                              |
| `invoke`          | object  | Control-plane instructions: `instructions` (string) and `context`  |
| `idempotency_key` | string  | Top-level dedup key (max 255 chars). **Not** inside `failure_policy` |
| `thread_id`       | string  | Link task to an existing thread (26-char ULID)                     |
| `context_message` | string  | Optional message to append to the thread (max 10,000 chars)       |

All new fields are **optional**. Omitted → system defaults. Existing agents keep working with zero changes.

### 11.2 Progress Update (enhanced)

```json
PATCH /api/v1/tasks/tsk_abc/progress
{
  "progress": 45,
  "status_message": "Reviewing file 12 of 27"
}
```

This resets `last_progress_at`. Agent should call this regularly to avoid progress_timeout.

### 11.3 Task Dependencies

```json
GET /api/v1/tasks/tsk_abc/dependencies

{
  "dependencies": [
    { "task_id": "tsk_1", "status": "completed" },
    { "task_id": "tsk_2", "status": "pending" },
    { "task_id": "tsk_3", "status": "in_progress" }
  ],
  "all_met": false
}
```

### 11.4 Dead Letter Management

```json
GET /api/v1/tasks?status=dead_letter

POST /api/v1/tasks/tsk_abc/requeue
{
  "reset_retries": true,
  "override_failure_policy": {
    "max_retries": 1,
    "task_timeout": 600
  }
}
```

---

## 12. Dashboard Additions

### 12.1 Task Board (enhanced)

Kanban columns updated:

```
Waiting → Pending → In Progress → Completed
                         │
              Failed / Dead Letter / Expired
```

Parent tasks show mini-progress bar (3/5 children done).
Dead letter column highlighted in red with requeue button.

### 12.2 Queue Health Panel

Per-task-type:
- Pending count / limit
- Average claim time (how long tasks sit in pending)
- Average completion time
- Retry rate (% of tasks that needed retry)
- Dead letter count (alert if > 0)
- Pressure indicator (low/normal/high/critical)

### 12.3 Dependency Graph

Visual DAG for tasks with dependencies:
```
[tsk_emails ✅] ──┐
[tsk_jira ⏳]   ──┼──▸ [tsk_report ⏸ waiting]
[tsk_sales ✅]  ──┘
```

---

## 13. Implementation Priority

These features layer on top of each other. Recommended build order:

| Priority | Feature               | Why                                        | Phase  |
|----------|-----------------------|--------------------------------------------|--------|
| P0       | Failure policy        | Without this, stuck tasks break everything | Phase 1|
| P0       | Progress timeout      | Core agent liveness detection              | Phase 1|
| P0       | Task timeout          | Hard deadline                              | Phase 1|
| P1       | Retry with backoff    | Essential for reliability                  | Phase 1|
| P1       | Dead letter queue     | Ops visibility into failures               | Phase 1|
| P1       | Idempotency keys      | Safety for at-least-once delivery          | Phase 1|
| P2       | Fan-out (children)    | Multi-agent task patterns                  | Phase 2|
| P2       | Completion policies   | Fan-in aggregation                         | Phase 2|
| P2       | Guarantee levels      | best_effort for non-critical tasks         | Phase 2|
| P3       | Task dependencies     | Declarative workflows without workflow engine | Phase 3|
| P3       | Backpressure          | Stability under load                       | Phase 3|
| P3       | on_complete chaining  | Mini-workflows                             | Phase 3|

P0/P1 items should ship in Phase 1 MVP — they're table stakes for reliable task processing.

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (core task system)*
