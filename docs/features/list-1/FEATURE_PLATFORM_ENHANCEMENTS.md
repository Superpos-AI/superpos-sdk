# Superpos — Feature: Platform Gaps & Enhancements

## Addendum to PRODUCT.md v4.0

---

## Phase 1 Enhancements (MVP-critical)

---

### 1. Scheduled / Recurring Tasks

#### Problem

No way to say "run code scan every day at 3 AM" or "check inbox every 5 minutes".
The scheduler container exists but only runs framework-level jobs (timeout checks, cleanup).
No user-facing model for recurring work.

#### Design

A **TaskSchedule** is a rule that creates tasks on a cron or interval basis.

```json
POST /api/v1/hives/{hive}/schedules
{
  "name": "Nightly code scan",
  "trigger_type": "cron",
  "cron_expression": "0 3 * * *",
  "timezone": "Europe/Kyiv",
  "task_type": "code_scan",
  "task_target_capability": "scanner",
  "task_payload": { "scope": "full", "branch": "main" },
  "task_failure_policy": {
    "max_retries": 2,
    "guarantee": "at_least_once"
  }
}
```

Trigger types:

| Type       | Config                          | Example                     |
|------------|----------------------------------|-----------------------------|
| `cron`     | `cron_expression` + `timezone`   | `0 3 * * *` (daily 3 AM)   |
| `interval` | `interval_seconds`               | `300` (every 5 min)        |
| `once`     | `run_at` timestamp               | `2025-03-01T09:00:00Z`     |

#### Execution

Laravel scheduler (runs every 10 seconds in scheduler container) checks due schedules:

```php
// App\Console\Kernel or scheduler container
Schedule::command('apiary:dispatch-schedules')->everyTenSeconds();
```

The job:
1. Query task_schedules where `next_run_at <= now()` and `status = 'active'`
2. Create task from template columns (`task_type`, `task_payload`, etc.)
3. Update `next_run_at` based on trigger
4. Track dispatched tasks via `tasks.schedule_id` FK (no separate schedule_log table)

#### Overlap Protection

What if previous run is still in progress?

```json
{
  "trigger": {
    "type": "interval",
    "every": 300
  },
  "overlap_policy": "skip"
}
```

| Policy             | Behavior                                          |
|--------------------|---------------------------------------------------|
| `skip`             | Don't create new task if previous still running   |
| `allow`            | Create anyway (parallel runs OK)                  |
| `cancel_previous`  | Cancel previous task, create new one              |

"Previous run still running" means: the schedule's `last_task_id` references a task with status `pending` or `in_progress`. The `cancel_previous` policy calls the task cancellation endpoint on the previous task, then creates the new task. If cancellation times out (e.g., the previous task is already completing), both tasks may run briefly — this is an acceptable edge case since the new task will proceed regardless.

#### Schema

```sql
CREATE TABLE task_schedules (
    id                      VARCHAR(26) PRIMARY KEY,
    superpos_id               VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id                 VARCHAR(26) NOT NULL REFERENCES hives(id),
    name                    VARCHAR(150) NOT NULL,
    description             VARCHAR(500),

    -- Trigger configuration (separate columns, not a single JSONB)
    trigger_type            VARCHAR(20) NOT NULL,          -- cron, interval, once
    cron_expression         VARCHAR(100),                  -- for type=cron
    timezone                VARCHAR(100),                  -- IANA timezone for cron evaluation
    interval_seconds        UNSIGNED INT,                  -- for type=interval
    run_at                  TIMESTAMP,                     -- for type=once

    -- Task template (columns copied into each dispatched task)
    task_type               VARCHAR(100) NOT NULL,
    task_payload            JSONB DEFAULT '{}',
    task_priority           SMALLINT DEFAULT 2,
    task_target_agent_id    VARCHAR(26) REFERENCES agents(id),
    task_target_capability  VARCHAR(100),
    task_timeout_seconds    INT DEFAULT 1800,
    task_max_retries        SMALLINT DEFAULT 3,
    task_context_refs       JSONB DEFAULT '[]',
    task_failure_policy     JSONB,

    -- Overlap policy: skip | allow | cancel_previous
    overlap_policy          VARCHAR(20) DEFAULT 'skip',

    -- State
    status                  VARCHAR(20) DEFAULT 'active',  -- active | paused | expired
    created_by              VARCHAR(26) REFERENCES agents(id),
    next_run_at             TIMESTAMP,
    last_run_at             TIMESTAMP,
    last_task_id            VARCHAR(26) REFERENCES tasks(id),
    run_count               UNSIGNED INT DEFAULT 0,
    expires_at              TIMESTAMP,

    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_task_schedules_due ON task_schedules (next_run_at)
    WHERE status = 'active' AND next_run_at IS NOT NULL;
CREATE INDEX idx_task_schedules_hive ON task_schedules (hive_id, status);
```

> **Design note:** There is no separate `schedule_log` table. Dispatched tasks
> are tracked via the `tasks.schedule_id` FK that references the originating
> `task_schedules` row. Query task history for a schedule with
> `SELECT * FROM tasks WHERE schedule_id = :id ORDER BY created_at DESC`.

#### API

```
POST   /api/v1/hives/{hive}/schedules              — Create schedule
GET    /api/v1/hives/{hive}/schedules              — List schedules in hive
GET    /api/v1/hives/{hive}/schedules/{id}         — Get schedule details
PUT    /api/v1/hives/{hive}/schedules/{id}         — Update (partial update)
DELETE /api/v1/hives/{hive}/schedules/{id}         — Delete
PATCH  /api/v1/hives/{hive}/schedules/{id}/pause   — Pause schedule
PATCH  /api/v1/hives/{hive}/schedules/{id}/resume  — Resume schedule
```

> **Not yet implemented:** Manual trigger endpoint (`POST .../schedules/{id}/trigger`).

Permission: `schedules.read` / `schedules.write` (agents) or Member+ role (dashboard).

#### Dashboard

- Schedule list with next run time, last run status, enabled toggle
- Schedule detail: run history timeline, task results
- "New Schedule" wizard with cron builder UI

---

### 2. Agent Drain Mode (Graceful Shutdown)

#### Problem

Agent is working on a task. You deploy a new version. Current behavior:
agent process killed → progress_timeout → task retried. Wasteful and noisy.

#### Design

Agent signals it's shutting down. System stops giving it new tasks. Agent finishes current work, then exits cleanly.

Draining is implemented as a **boolean flag** (`is_draining`) separate from the agent's status field. Agent statuses remain: `online`, `busy`, `idle`, `offline`, `error`. Any online/busy/idle agent can additionally have `is_draining = true`.

```
Agent lifecycle:
  online/busy/idle  → is_draining=true (no new anycast work) → offline
```

#### Protocol

**Agent initiates drain:**

```json
POST /api/v1/agents/drain
{
  "reason": "Upgrading to v2.1",
  "deadline_minutes": 2
}
```

Response:

```json
{
  "is_draining": true,
  "active_tasks": ["tsk_abc", "tsk_def"],
  "drain_deadline_at": "2025-02-20T12:02:00Z"
}
```

**What happens:**
1. Agent flag `is_draining` → `true`, `drain_started_at` recorded
2. Poll endpoint returns empty tasks for this agent (no new anycast work)
3. Agent finishes current tasks normally (complete/fail)
4. When all active tasks done → agent calls `POST /api/v1/agents/logout` or just disconnects
5. If `drain_deadline_at` reached and tasks still active → system reassigns them

**To cancel a drain:** `POST /api/v1/agents/undrain` clears the drain flag and returns the agent to normal operation.

**Dashboard shows:** "Agent code-reviewer-1 is draining (2 tasks remaining, deadline in 90s)"

**API endpoints:**
```
POST /api/v1/agents/drain    — Enter drain mode (agent-authenticated)
POST /api/v1/agents/undrain  — Cancel drain mode (agent-authenticated)
GET  /api/v1/agents/drain    — Get drain status (agent-authenticated)
POST /api/v1/agents/logout   — Deregister / go offline
```

#### SDK Support

```python
# In agent code
import signal

def handle_shutdown(signum, frame):
    client.drain(reason="SIGTERM received", deadline_minutes=2)
    # Finish current work...
    client.logout()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)
```

Docker sends SIGTERM before SIGKILL. Agent catches it, drains, exits.

#### Schema Change

```sql
-- Draining is a boolean flag, NOT a status enum value.
-- Agent statuses remain: online, busy, idle, offline, error.

ALTER TABLE agents ADD COLUMN is_draining        BOOLEAN DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN drain_started_at    TIMESTAMP;
ALTER TABLE agents ADD COLUMN drain_deadline_at   TIMESTAMP;
ALTER TABLE agents ADD COLUMN drain_reason        VARCHAR(500);

CREATE INDEX agents_hive_draining_idx ON agents (hive_id, is_draining);
```

#### Poll Query Update

```sql
-- Exclude draining agents from anycast task assignment
SELECT * FROM tasks
WHERE ...
  AND (target_agent_id = :agent_id OR (
    target_agent_id IS NULL
    AND :agent_is_draining = FALSE
  ))
...
```

Draining agents still receive tasks explicitly assigned to them (`target_agent_id`) via poll — they do NOT pick up anycast tasks (capability-matched tasks with no `target_agent_id`). After `drain_deadline_at` passes, even explicitly assigned tasks are reassigned to other capable agents.

---

### 3. File / Blob Storage

#### Problem

Knowledge Store uses JSONB. Works for structured data. Breaks for:
- Code diffs (multi-MB text)
- Screenshots / images
- Generated PDFs / reports
- Log files
- Large CSV exports from Service Workers

#### Design

**Attachments** — files stored in object storage (local disk for CE, S3 for Cloud), referenced from tasks and knowledge entries.

```json
POST /api/v1/hives/{hive}/attachments
Content-Type: multipart/form-data

file: <binary>
metadata: {
  "filename": "pr-42-diff.patch",
  "task_id": "tsk_abc",
  "description": "Full diff for PR #42"
}
```

Response:

```json
{
  "attachment_id": "att_xyz789",
  "filename": "pr-42-diff.patch",
  "size_bytes": 245000,
  "content_type": "text/x-patch",
  "download_url": "/api/v1/hives/{hive}/attachments/att_xyz789/download",
  "expires_at": null
}
```

#### Referencing from Tasks

```json
PATCH /api/v1/tasks/tsk_abc/complete
{
  "result": {
    "summary": "3 issues found",
    "details_attachment": "att_xyz789"
  }
}
```

#### Referencing from Knowledge Store

```json
POST /api/v1/knowledge
{
  "key": "reports:q1-2025",
  "value": {
    "title": "Q1 Report",
    "generated_at": "2025-02-20",
    "attachment_id": "att_report_001"
  },
  "scope": "apiary"
}
```

#### Storage Backend

```php
// config/apiary.php
'attachments' => [
    'disk' => env('SUPERPOS_ATTACHMENT_DISK', 'local'),            // 'local' or 's3'
    'max_size' => (int) env('SUPERPOS_ATTACHMENT_MAX_SIZE', 10485760),  // 10 MB
    'retention_days' => env('SUPERPOS_ATTACHMENT_RETENTION', null), // null = forever
    'presigned_url_ttl' => (int) env('SUPERPOS_ATTACHMENT_URL_TTL', 60), // minutes
    'path_prefix' => env('SUPERPOS_ATTACHMENT_PATH_PREFIX', 'attachments'),
    'quota_bytes' => env('SUPERPOS_ATTACHMENT_QUOTA_BYTES', null),  // null = unlimited
],
```

CE: local filesystem (`storage/app/attachments/`).
Cloud: S3 with per-apiary prefixes. Pre-signed download URLs.

#### Schema

```sql
CREATE TABLE attachments (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    
    filename        VARCHAR(255) NOT NULL,
    content_type    VARCHAR(100) NOT NULL,
    size_bytes      BIGINT NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,      -- disk path or S3 key
    checksum        VARCHAR(64),                -- SHA-256
    
    uploaded_by     VARCHAR(26),                -- agent_id
    task_id         VARCHAR(26) REFERENCES tasks(id),
    
    expires_at      TIMESTAMP,                  -- auto-cleanup
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_attachments_hive ON attachments (hive_id, created_at DESC);
CREATE INDEX idx_attachments_task ON attachments (task_id);
CREATE INDEX idx_attachments_expires ON attachments (expires_at) WHERE expires_at IS NOT NULL;
```

#### API

```
POST   /api/v1/hives/{hive}/attachments              — Upload file
GET    /api/v1/hives/{hive}/attachments               — List attachments
GET    /api/v1/hives/{hive}/attachments/{id}          — Get metadata
GET    /api/v1/hives/{hive}/attachments/{id}/download — Download file (or redirect to pre-signed URL)
DELETE /api/v1/hives/{hive}/attachments/{id}          — Delete
```

#### Quota

Quota limits apply **per-apiary** (Cloud) or are unlimited (CE).

| Plan       | Storage limit | Max file size |
|------------|---------------|---------------|
| CE         | Unlimited     | Unlimited     |
| Free       | 100 MB        | 5 MB          |
| Pro        | 10 GB         | 50 MB         |
| Enterprise | Custom        | Custom        |

Per-file size limit is checked synchronously on upload (returns 413 if exceeded). Total storage quota is checked asynchronously — if the apiary exceeds its total quota, new uploads are rejected with 413 but existing files are preserved.

---

### 4. Agent Pool Concept

#### Problem

Three agents with `code_review` capability. One goes offline. Questions with no answers:
- Is the pool healthy? (2/3 online — OK? 1/3 — warning?)
- Is the pool overloaded? (30 pending tasks, 2 agents — each has 15 task backlog)
- Should I scale up? (based on what metric?)

#### Design

An **Agent Pool** is a logical group of interchangeable agents. Not a new entity — it's a **dashboard view + health tracking** over agents sharing a capability.

System auto-detects pools: agents in the same hive with the same capability = pool.

No configuration needed. No new tables. Pure derived concept.

#### Pool Health Metrics

```json
GET /api/v1/hives/{hive}/pools
-- Also: GET /api/v1/hives/{hive}/pool/health

{
  "pools": [
    {
      "capability": "code_review",
      "hive": "backend",
      "agents": {
        "total": 3,
        "online": 2,
        "busy": 1,
        "draining": 0,
        "offline": 1
      },
      "queue": {
        "pending": 12,
        "in_progress": 2,
        "avg_wait_seconds": 45,
        "avg_completion_seconds": 180
      },
      "health": "healthy",
      "recommendation": null
    },
    {
      "capability": "testing",
      "hive": "backend",
      "agents": {
        "total": 1,
        "online": 1,
        "busy": 1,
        "offline": 0
      },
      "queue": {
        "pending": 28,
        "in_progress": 1,
        "avg_wait_seconds": 340
      },
      "health": "overloaded",
      "recommendation": "Queue depth is 28x agent capacity. Consider adding more testing agents."
    }
  ]
}
```

#### Health Calculation

```
healthy:     pending/online_agents < 5 AND avg_wait < 60s
busy:        pending/online_agents < 15 OR avg_wait < 300s
overloaded:  pending/online_agents >= 15 OR avg_wait >= 300s
degraded:    online_agents < total_agents * 0.5
critical:    online_agents == 0 AND pending > 0
idle:        online_agents == 0 AND pending == 0
```

**Edge cases:**
- If `online_agents = 0` and `pending > 0` → status is `critical` (work waiting, nobody to do it).
- If `online_agents = 0` and `pending = 0` → status is `idle` (pool exists but dormant).
- Draining agents count as online for health calculation until their `drain_deadline_at` passes.

#### Dashboard: Pool View

```
┌─────────────────────────────────────────────────────────┐
│  Agent Pools — Hive: Backend                            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  code_review        🟢 Healthy     3 agents  12 queued  │
│  ████████░░  2/3 online   avg wait: 45s                 │
│                                                         │
│  testing            🔴 Overloaded  1 agent   28 queued  │
│  █████████░  1/1 online   avg wait: 5m 40s              │
│  ⚠️ Consider adding more testing agents                  │
│                                                         │
│  deployer           🟢 Healthy     1 agent   0 queued   │
│  ██████████  1/1 online   avg wait: 0s                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 2-3 Enhancements

---

### 5. Observability & Metrics Export

#### Problem

Dashboard is great for humans. Ops teams need machine-readable metrics for alerting, graphing, trend analysis.

#### Design

**Prometheus endpoint** (requires `metrics:read` permission):

```
GET /api/v1/metrics

# HELP superpos_tasks_total Total tasks created
# TYPE superpos_tasks_total counter
superpos_tasks_total{hive="backend",type="code_review",status="completed"} 1247
superpos_tasks_total{hive="backend",type="code_review",status="failed"} 23

# HELP superpos_tasks_pending Current pending tasks
# TYPE superpos_tasks_pending gauge
superpos_tasks_pending{hive="backend",type="code_review"} 12

# HELP superpos_task_duration_seconds Task completion time
# TYPE superpos_task_duration_seconds histogram
superpos_task_duration_seconds_bucket{hive="backend",type="code_review",le="60"} 890
superpos_task_duration_seconds_bucket{hive="backend",type="code_review",le="300"} 1200

# HELP superpos_agents_online Current online agents
# TYPE superpos_agents_online gauge
superpos_agents_online{hive="backend",capability="code_review"} 2

# HELP superpos_proxy_requests_total Proxy requests
# TYPE superpos_proxy_requests_total counter
superpos_proxy_requests_total{service="github",status="200"} 5420

# HELP superpos_dead_letter_count Dead letter queue depth
# TYPE superpos_dead_letter_count gauge
superpos_dead_letter_count{hive="backend"} 0
```

**Notification endpoints:**

Superpos can POST notifications to external URLs on system events. This is implemented via the `notification_endpoints` table and corresponding API:

```
GET    /api/v1/notification-endpoints          — List endpoints
POST   /api/v1/notification-endpoints          — Create endpoint
GET    /api/v1/notification-endpoints/{id}     — Get endpoint
PATCH  /api/v1/notification-endpoints/{endpoint} — Update endpoint
DELETE /api/v1/notification-endpoints/{id}     — Delete endpoint
```

```json
POST /api/v1/notification-endpoints
{
  "url": "https://hooks.slack.com/services/xxx",
  "events": [
    "agent.offline",
    "task.dead_letter",
    "pool.overloaded",
    "approval.pending",
    "quota.warning"
  ],
  "format": "slack"
}
```

Supported formats: `json` (raw), `slack` (Slack block kit), `discord`, `pagerduty`.

Permission: `manage:notification_endpoints`.

#### Implementation

Laravel package `spatie/laravel-prometheus` or lightweight custom exporter.
Notification endpoints: reuse existing event bus — listen for system events, POST to registered endpoints. Delivery results are logged in the `notification_delivery_log` table.

---

### 6. Agent Context Threads

#### Problem

Agent A reviews PR, finds issue, creates task for Agent B to refactor.
Agent B needs to know: what did A find? what's the PR context? what was already tried?

Current: `context_refs` links to Knowledge Store entries. But there's no concept of a **conversation** — a sequence of related tasks with accumulated context.

#### Design

A **Thread** is a chain of related tasks sharing accumulated context.

Task creation accepts `thread_id` and `context_message` fields:

```json
POST /api/v1/hives/{hive}/tasks
{
  "type": "refactor",
  "target_capability": "refactoring",
  "thread_id": "thr_pr42_review",
  "payload": { "file": "auth.py", "issue": "N+1 query in login" },
  "context_message": "Found N+1 query during code review. See PR comment for details."
}
```

When agent claims a task with `thread_id`, it receives the full thread history:

```json
{
  "task_id": "tsk_refactor_001",
  "thread": {
    "id": "thr_pr42_review",
    "messages": [
      {
        "task_id": "tsk_review_001",
        "agent": "code-reviewer-1",
        "role": "reviewer",
        "message": "Reviewing PR #42: authentication refactor",
        "timestamp": "2025-02-20T10:00:00Z"
      },
      {
        "task_id": "tsk_review_001",
        "agent": "code-reviewer-1",
        "role": "reviewer",
        "message": "Found N+1 query during code review. See PR comment for details.",
        "timestamp": "2025-02-20T10:05:00Z"
      }
    ],
    "context_refs": ["kn_pr42_diff", "kn_pr42_comments"]
  }
}
```

Agent B gets full history without reading scattered Knowledge Store entries.

#### Schema

```sql
CREATE TABLE threads (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    title           VARCHAR(255),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE thread_messages (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       VARCHAR(26) NOT NULL REFERENCES threads(id),
    task_id         VARCHAR(26) REFERENCES tasks(id),
    agent_id        VARCHAR(26) REFERENCES agents(id),
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_thread_messages ON thread_messages (thread_id, created_at);
```

Tasks table addition:

```sql
ALTER TABLE tasks ADD COLUMN thread_id VARCHAR(26) REFERENCES threads(id);
```

#### API

Thread endpoints are hive-scoped:

```
GET    /api/v1/hives/{hive}/threads               — List threads
POST   /api/v1/hives/{hive}/threads               — Create thread
GET    /api/v1/hives/{hive}/threads/{id}           — Get thread + messages
DELETE /api/v1/hives/{hive}/threads/{id}           — Delete thread
POST   /api/v1/hives/{hive}/threads/{id}/messages  — Append message
DELETE /api/v1/hives/{hive}/threads/{id}/messages  — Clear messages
```

Permission: `threads.read` / `threads.write`.

---

### 7. Task Contracts (Schema Validation)

#### Problem

Agent A creates `code_review` task with `{pr: 42}`. Agent B expects `{pull_request_id: 42}`.
Silent failure — agent gets wrong data shape and produces garbage.

#### Design

Task types can have optional JSON Schema contracts. Rather than a separate `task_types` table, contracts are stored in the **`hives.task_contracts` JSONB column** — a map keyed by task type:

```json
// hives.task_contracts JSONB
{
  "code_review": {
    "description": "Review a pull request",
    "payload_schema": {
      "type": "object",
      "required": ["repo", "pr_number"],
      "properties": {
        "repo": { "type": "string", "description": "Full repo name (org/repo)" },
        "pr_number": { "type": "integer" },
        "focus_areas": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Optional areas to focus review on"
        }
      }
    },
    "result_schema": {
      "type": "object",
      "required": ["approved", "comments"],
      "properties": {
        "approved": { "type": "boolean" },
        "comments": { "type": "array" },
        "severity": { "enum": ["clean", "minor", "major", "critical"] }
      }
    }
  }
}
```

When a task is created with type `code_review`, payload is validated against the matching contract's `payload_schema` via `TaskContractService`.
When a task is completed, result is validated against `result_schema`.
Validation failure → 422 with clear error message (`ContractViolationException`).

Optional — task types without a contract work as before (no validation).

#### Schema

```sql
-- No separate task_types table. Contracts live on the hive:
ALTER TABLE hives ADD COLUMN task_contracts JSONB;
```

> **Design note:** Storing contracts as a JSONB column on the `hives` table
> avoids a separate table join and keeps contract definitions co-located with
> the hive configuration. The `TaskContractService` reads `hive.task_contracts`
> on task creation and completion to perform schema validation.

---

### 8. API Key Rotation

#### Problem

Agent token leaked. Current: delete agent, re-register, lose all in-flight tasks.

#### Design

```json
POST /api/v1/agents/key/rotate
{
  "grace_period_minutes": 5
}
```

This endpoint is agent-authenticated (no `{id}` in path — the agent rotates its own key).

Response:

```json
{
  "new_token": "tok_new_xxxxx",
  "key_grace_period_expires_at": "2025-02-20T12:05:00Z",
  "message": "Old token valid for 5 more minutes"
}
```

Both tokens work during grace period. After expiry, old token returns 401.

**Additional endpoints:**

```
POST /api/v1/agents/key/rotate  — Rotate API key (agent-authenticated)
POST /api/v1/agents/key/revoke  — Revoke current key immediately
GET  /api/v1/agents/key/status  — Check key status (rotation in progress, grace period, etc.)
```

Implementation: `agents` table gets `previous_api_token_hash` + `key_grace_period_expires_at` + `key_rotated_at`. Auth middleware checks both hashes.

```sql
ALTER TABLE agents ADD COLUMN previous_api_token_hash       VARCHAR(255);
ALTER TABLE agents ADD COLUMN key_grace_period_expires_at   TIMESTAMP;
ALTER TABLE agents ADD COLUMN key_rotated_at                TIMESTAMP;
```

---

### 9. Per-Agent Rate Limiting

#### Problem

One rogue agent creates 10,000 tasks per second. Swamps the queue for everyone.

#### Design

Rate limiting is implemented as a **single `rate_limit_per_minute`** column on the `agents` table. This applies a unified request-per-minute cap across all API actions for that agent.

```sql
ALTER TABLE agents ADD COLUMN rate_limit_per_minute UNSIGNED INT;  -- NULL = unlimited
```

When set, all API requests from the agent are counted against this single limit using a Redis sliding window counter. Exceeded → 429 with `Retry-After` header.

```json
// Example: set an agent's rate limit
PUT /api/v1/agents/rate-limit
{
  "rate_limit_per_minute": 120
}
```

If `rate_limit_per_minute` is `NULL`, no rate limit is enforced (unlimited).

> **Simplification note:** The original spec described per-action limits
> (`tasks_create`, `proxy_requests`, `knowledge_writes`). The implementation
> uses a single unified limit per agent for simplicity. Per-action limits may
> be added in a future iteration if needed.

---

### 10. Sandbox / Dry-Run Mode

#### Problem

Developer building an agent wants to test against Superpos without real side effects.
No way to: test policy evaluation without executing, test webhook routing without creating tasks, run agent against mock data.

#### Design

**Hive-level sandbox flag:**

```json
POST /api/v1/hives
{
  "name": "Staging",
  "slug": "staging",
  "settings": {
    "sandbox": true
  }
}
```

Sandbox hive behavior:
- Tasks created and processed normally (agents can test full flow)
- Service Proxy returns mock responses instead of calling real APIs
- Approval requests auto-approve after 5 seconds
- Activity log tagged with `sandbox: true`
- No usage metering (Cloud — doesn't count against quotas)

**Task dry-run endpoint:**

The `TaskDryRunService` validates and simulates a task submission without persisting anything. It runs the full validation pipeline (contract + capacity) and returns what would happen:

```json
POST /api/v1/hives/{hive}/tasks/dry-run
{
  "type": "code_review",
  "target_capability": "code_review",
  "payload": { "repo": "acme/backend", "pr_number": 42 }
}
```

Response:

```json
{
  "valid": true,
  "contract_match": "code_review",
  "would_create_task": true,
  "dry_run": true
}
```

> **Not yet implemented:** Policy evaluate dry-run (`POST /api/v1/config/policies/evaluate`)
> and webhook-route evaluate dry-run (`POST /api/v1/config/webhook-routes/evaluate`)
> are planned for a future iteration.

---

## Phase 4+ Enhancements (Competitive Advantages)

---

### 11. LLM-Aware Features

#### Problem

Superpos orchestrates AI agents but knows nothing about the LLMs powering them.
Can't answer: "How much did my agents spend on OpenAI today?" or "Which tasks consume the most tokens?"

#### Design

**Token usage reporting** — agents report LLM usage in heartbeat and task completion:

```json
POST /api/v1/agents/heartbeat
{
  "status": "active",
  "active_tasks": ["tsk_abc"],
  "llm_usage": {
    "model": "claude-sonnet-4-5-20250514",
    "input_tokens": 12500,
    "output_tokens": 3200,
    "estimated_cost_usd": 0.024
  }
}
```

```json
PATCH /api/v1/tasks/tsk_abc/complete
{
  "result": { ... },
  "llm_usage": {
    "total_input_tokens": 45000,
    "total_output_tokens": 8000,
    "total_requests": 3,
    "model": "claude-sonnet-4-5-20250514",
    "estimated_cost_usd": 0.089
  }
}
```

**Dashboard: LLM Cost View**

- Per-agent daily/weekly/monthly token usage and cost
- Per-task-type: "code_review costs avg $0.12, deploy costs avg $0.02"
- Cost trend charts
- Budget alerts: "Agent pool code_review spent $50 today (budget: $100/day)"

**Model routing hints** (future):

```json
POST /api/v1/tasks
{
  "type": "code_review",
  "payload": { "pr": 42 },
  "llm_hint": {
    "complexity": "high",
    "suggested_model": "claude-opus-4-5-20250414",
    "max_cost_usd": 0.50
  }
}
```

Agents can use `llm_hint` to decide which model to use. Platform tracks whether hints correlate with better results.

#### Schema

```sql
CREATE TABLE llm_usage_logs (
    id                  VARCHAR(26) PRIMARY KEY,   -- ULID
    superpos_id           VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id             VARCHAR(26) REFERENCES hives(id),
    agent_id            VARCHAR(26) REFERENCES agents(id),
    task_id             VARCHAR(26) REFERENCES tasks(id),
    persona_id          VARCHAR(26),               -- marketplace persona, if applicable
    
    model               VARCHAR(100) NOT NULL,
    provider            VARCHAR(50) NOT NULL,      -- openai, anthropic, etc.
    prompt_tokens       UNSIGNED INT NOT NULL,
    completion_tokens   UNSIGNED INT NOT NULL,
    total_tokens        UNSIGNED INT NOT NULL,
    cost_usd            DECIMAL(10,6) NOT NULL,
    latency_ms          UNSIGNED INT,              -- request latency
    
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_llm_usage_logs_apiary ON llm_usage_logs (superpos_id, created_at);
CREATE INDEX idx_llm_usage_logs_hive   ON llm_usage_logs (hive_id, created_at);
CREATE INDEX idx_llm_usage_logs_agent  ON llm_usage_logs (agent_id);
CREATE INDEX idx_llm_usage_logs_task   ON llm_usage_logs (task_id);
```

---

### 12. Task Replay / Time Travel

#### Problem

Task produced bad result. What went wrong?
Need to: see everything that happened, reproduce with same inputs, compare runs.

#### Design

**Task Trace** — full execution record:

```json
GET /api/v1/tasks/tsk_abc/trace

{
  "task_id": "tsk_abc",
  "trace": [
    { "t": "2025-02-20T10:00:00Z", "event": "created", "by": "webhook:github" },
    { "t": "2025-02-20T10:00:02Z", "event": "claimed", "by": "agt_reviewer_1" },
    { "t": "2025-02-20T10:00:05Z", "event": "proxy_request", "service": "github", "method": "GET", "path": "/repos/acme/backend/pulls/42", "status": 200, "duration_ms": 340 },
    { "t": "2025-02-20T10:00:06Z", "event": "knowledge_read", "key": "project:backend:conventions" },
    { "t": "2025-02-20T10:00:08Z", "event": "proxy_request", "service": "github", "method": "GET", "path": "/repos/acme/backend/pulls/42/files", "status": 200, "duration_ms": 520 },
    { "t": "2025-02-20T10:00:15Z", "event": "progress", "progress": 50, "message": "Analyzing 12 files" },
    { "t": "2025-02-20T10:00:25Z", "event": "proxy_request", "service": "github", "method": "POST", "path": "/repos/acme/backend/pulls/42/reviews", "status": 201, "duration_ms": 180 },
    { "t": "2025-02-20T10:00:26Z", "event": "knowledge_write", "key": "reviews:pr-42", "scope": "hive" },
    { "t": "2025-02-20T10:00:26Z", "event": "completed", "duration_total_ms": 26000, "llm_cost": 0.089 },
    { "t": "2025-02-20T10:00:26Z", "event": "child_spawned", "task_id": "tsk_notify" }
  ]
}
```

**Replay:**

```json
POST /api/v1/tasks/tsk_abc/replay
{
  "mode": "sandbox",
  "override_payload": null
}
```

Creates new task in sandbox hive with:
- Same payload as original
- Same context_refs
- Proxy returns recorded responses from original trace (mock mode)
- Result can be compared with original

**Diff between runs:**

```json
GET /api/v1/tasks/compare?task_a=tsk_abc&task_b=tsk_abc_replay

{
  "payload_diff": null,
  "result_diff": {
    "approved": { "a": true, "b": false },
    "comments": { "a": 2, "b": 5, "added": ["new comment about XSS vulnerability"] }
  },
  "trace_diff": {
    "a_only": ["proxy: GET /pulls/42/commits"],
    "b_only": ["proxy: GET /pulls/42/comments", "knowledge_read: security:owasp-top-10"]
  }
}
```

#### Implementation Note

Task trace is assembled from existing data: activity_log + proxy_log + knowledge_entries.
No new storage needed — just a query that joins everything by task_id chronologically.

Replay needs recorded proxy responses — store response bodies in proxy_log (or attachments for large responses) when `trace_recording: true` on the hive.

---

### 13. Marketplace Personas (Agent Templates)

#### Problem

Connector Marketplace exists but agents are harder to set up than connectors.
"I want a GitHub code reviewer" requires: register agent, configure capabilities, set up webhook route, configure action policy, deploy the agent process.

#### Design

**Marketplace Persona** — a package that includes everything needed to deploy a pre-configured agent:

```yaml
# marketplace/templates/github-code-reviewer.yaml
name: GitHub Code Reviewer
description: Automated PR review powered by AI
version: 1.0.0
author: apiary-official

agent:
  name: code-reviewer
  type: ai_agent
  capabilities: [code_review]
  permissions:
    - services:github
    - knowledge:read
    - knowledge:write

service_connections:
  - name: github
    type: github
    auth_type: token
    setup: oauth  # one-click OAuth in dashboard

inbox:
  - name: PR Review Trigger
    task_type: code_review
    description: "POST from GitHub webhook when PR opened or updated"

action_policy:
  allow:
    - { method: GET, path: "/repos/*/pulls/*" }
    - { method: GET, path: "/repos/*/pulls/*/files" }
    - { method: POST, path: "/repos/*/pulls/*/reviews" }
    - { method: POST, path: "/repos/*/pulls/*/comments" }
  deny:
    - { method: DELETE, path: "*" }
  require_approval:
    - { method: PUT, path: "*/merge" }

task_types:
  - type: code_review
    payload_schema:
      required: [repo, pr_number]
      properties:
        repo: { type: string }
        pr_number: { type: integer }
    result_schema:
      required: [approved, comments]
      properties:
        approved: { type: boolean }
        comments: { type: array }

runtime:
  type: docker
  image: apiary/code-reviewer:latest
  env:
    - LLM_MODEL=claude-sonnet-4-5-20250514
    - MAX_FILES=50
```

**Install flow:**

```
Marketplace → "GitHub Code Reviewer" → [Install]

1. Creates service connection (GitHub OAuth flow)
2. Creates agent registration (pre-configured capabilities + permissions)
3. Creates inbox for PR webhooks
4. Creates action policy
5. Registers task type with schema
6. Optionally: deploys agent container (Cloud managed agents)

"Your code reviewer is ready! Here's the webhook URL to add to GitHub."
```

#### Schema

```sql
CREATE TABLE marketplace_personas (
    id              VARCHAR(26) PRIMARY KEY,    -- ULID
    superpos_id       VARCHAR(26) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    description     TEXT,
    documents       JSONB DEFAULT '{}',         -- readme, changelog, etc.
    config          JSONB,                      -- full manifest (YAML converted to JSON)
    visibility      VARCHAR(20) DEFAULT 'private',  -- 'public' or 'private'
    tags            JSONB,
    category        VARCHAR(50),                -- code_review, devops, data, monitoring
    install_count   UNSIGNED INT DEFAULT 0,
    is_featured     BOOLEAN DEFAULT FALSE,
    created_by_id   VARCHAR(26),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_marketplace_personas_visibility ON marketplace_personas (visibility, name);
CREATE INDEX idx_marketplace_personas_category   ON marketplace_personas (category);
```

---

## Summary: Implementation Priority

| #  | Feature                  | Phase | Effort  | Impact |
|----|--------------------------|-------|---------|--------|
| 1  | Scheduled tasks          | 1     | 1 week  | High   |
| 2  | Agent drain mode         | 1     | 2 days  | High   |
| 3  | File/blob storage        | 1     | 1 week  | High   |
| 4  | Agent pools (view only)  | 1     | 3 days  | Medium |
| 5  | Observability export     | 2     | 1 week  | High   |
| 6  | Context threads          | 2     | 1 week  | Medium |
| 7  | Task contracts           | 2     | 3 days  | Medium |
| 8  | API key rotation         | 2     | 2 days  | High   |
| 9  | Per-agent rate limiting  | 2     | 3 days  | Medium |
| 10 | Sandbox / dry-run        | 3     | 1 week  | High   |
| 11 | LLM-aware features       | 4     | 2 weeks | High   |
| 12 | Task replay              | 4     | 1 week  | Medium |
| 13 | Marketplace personas      | 4    | 2 weeks | High   |

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0, FEATURE_TASK_SEMANTICS.md, FEATURE_SERVICE_WORKERS.md*
