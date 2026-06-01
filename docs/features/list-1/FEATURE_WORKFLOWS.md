# Feature Spec: Workflows

> **Status:** Draft
> **Author:** Human + Claude
> **Date:** 2026-03-25
> **Tasks:** 168-185, 191-196 (Phase 7 + Harness Patterns in TASKS.md)
> **Depends on:** Task dependencies (098), Fan-out (096), Completion policies (097), Schedules (078), Webhooks (055-058)

---

## 1. Problem Statement

Superpos has powerful task primitives — dependencies, fan-out, completion policies, on_complete chaining — but no way to compose them into **reusable, multi-step workflows**.

Today, to run "plan → implement → evaluate":

- **Option A (static dependencies):** Pre-create all 3 tasks with `depends_on`. Problem: you must write the implement/evaluate prompts before the plan runs. The agent gets a generic prompt and has to find its instructions buried in `payload._dependencies`.

- **Option B (agent-driven chaining):** Tell the first agent "when done, create the next task." Problem: workflow logic is scattered across agent prompts. No visibility, no reusability, no dashboard control. If the agent forgets to chain, the workflow breaks silently.

Neither approach gives you: a named, versioned, triggerable workflow definition that you can see in the dashboard, re-run, inspect, and share.

---

## 2. Design Principles

1. **Build on existing primitives** — workflows create tasks, use dependencies and fan-out. No parallel execution engine.
2. **Workflow run = parent task** — a running workflow is a task with type `workflow_run`. Steps are child tasks. Visible in the existing task board.
3. **Accumulated context** — each step gets all previous steps' results as a conversation thread. Step 3 sees outputs from steps 1 and 2.
4. **Handlebars templates** — step prompts use `{{steps.plan.result.output}}`, `{{trigger.payload.pr_number}}` syntax. Server renders before creating each step task.
5. **Auto-versioned** — every edit creates a new version. Running instances use the version they started with.
6. **Dashboard + API** — humans design workflows in the visual builder, agents create/trigger them via API.
7. **Webhooks as triggers and wait-steps** — external events can start workflows and pause them mid-flight.

---

## 3. Concepts

### 3.1 Workflow Definition

A **workflow** is a named, versioned DAG of steps belonging to a hive.

```json
{
  "id": "wf_01ABC...",
  "hive_id": "hive_01...",
  "name": "PR Review Pipeline",
  "slug": "pr-review-pipeline",
  "description": "Plan review, implement fixes, verify results",
  "version": 3,
  "is_active": true,
  "trigger_config": { ... },
  "steps": { ... },
  "settings": { ... }
}
```

### 3.2 Step

A **step** is a unit of work in the workflow. Each step becomes a task when the workflow runs.

Step types:

| Type | Description |
|------|-------------|
| `agent` | Creates a task targeting an agent/capability. The core step type. |
| `fan_out` | Creates parallel child tasks, waits for completion policy. |
| `condition` | Evaluates an expression, routes to different next steps. |
| `webhook_wait` | Pauses the workflow until an external webhook arrives. |
| `delay` | Pauses the workflow for a fixed duration. |
| `loop` | Generator-evaluator iterative refinement cycle with exit condition. |

### 3.3 Workflow Run

A **workflow run** is a single execution of a workflow definition. Implemented as a parent task with type `workflow_run` and status `awaiting_children`.

```
Workflow Run (parent task, type=workflow_run)
  ├── Step 1: plan (child task, type=workflow_step)
  ├── Step 2: implement (child task, type=workflow_step)
  └── Step 3: evaluate (child task, type=workflow_step)
```

### 3.4 Workflow Thread

Each workflow run has an accumulated **thread** — an ordered list of step results. When a step completes, its result is appended to the thread. Subsequent steps receive the full thread in their payload.

---

## 4. Schema

### 4.1 `workflows` Table

```sql
CREATE TABLE workflows (
    id              VARCHAR(26) PRIMARY KEY,    -- ULID
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL,
    description     TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    steps           JSONB NOT NULL,             -- DAG definition
    settings        JSONB NOT NULL DEFAULT '{}',
    created_by      VARCHAR(26),                -- agent or user ID
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMP NULL,             -- soft-delete; NULL = active

    UNIQUE (hive_id, slug)
);

-- Partial index excludes soft-deleted workflows from normal lookups.
CREATE INDEX idx_workflows_hive ON workflows (hive_id, is_active) WHERE deleted_at IS NULL;
```

### 4.2 `workflow_versions` Table

```sql
CREATE TABLE workflow_versions (
    id              VARCHAR(26) PRIMARY KEY,
    workflow_id     VARCHAR(26) NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    steps           JSONB NOT NULL,
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    settings        JSONB NOT NULL DEFAULT '{}',
    created_by      VARCHAR(26),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE (workflow_id, version)
);

CREATE INDEX idx_workflow_versions ON workflow_versions (workflow_id, version DESC);
```

### 4.3 `workflow_runs` Table

```sql
CREATE TABLE workflow_runs (
    id              VARCHAR(26) PRIMARY KEY,    -- ULID
    workflow_id     VARCHAR(26) NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    workflow_version INTEGER NOT NULL,
    task_id         VARCHAR(26) NOT NULL REFERENCES tasks(id),  -- parent task
    status          VARCHAR(20) NOT NULL DEFAULT 'running',     -- running, completed, failed, cancelled
    trigger_type    VARCHAR(50),                -- manual, schedule, webhook, api
    trigger_payload JSONB DEFAULT '{}',         -- data from the trigger
    thread          JSONB NOT NULL DEFAULT '[]', -- accumulated step results
    step_states     JSONB NOT NULL DEFAULT '{}', -- per-step status tracking
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_workflow_runs_workflow ON workflow_runs (workflow_id, status);
CREATE INDEX idx_workflow_runs_task ON workflow_runs (task_id);
CREATE INDEX idx_workflow_runs_tenant ON workflow_runs (superpos_id, hive_id);
```

### 4.4 Tasks Table Additions

```sql
ALTER TABLE tasks ADD COLUMN workflow_run_id VARCHAR(26) REFERENCES workflow_runs(id);
ALTER TABLE tasks ADD COLUMN workflow_step_key VARCHAR(100); -- e.g. "plan", "implement"

-- Prevents duplicate step task creation under concurrent fan-in completions.
-- onStepCompleted() must also hold a SELECT FOR UPDATE lock on workflow_runs
-- before evaluating deps and inserting; this index is the hard safety net.
CREATE UNIQUE INDEX idx_tasks_workflow_step
    ON tasks (workflow_run_id, workflow_step_key)
    WHERE workflow_run_id IS NOT NULL AND workflow_step_key IS NOT NULL;
```

---

## 5. Step Definition Format

### 5.1 Agent Step

```json
{
  "plan": {
    "type": "agent",
    "name": "Plan the implementation",
    "target_capability": "planning",
    "prompt": "Review PR #{{trigger.payload.pr_number}} and create an implementation plan.\n\nPR Title: {{trigger.payload.title}}\nPR Diff URL: {{trigger.payload.diff_url}}",
    "timeout_seconds": 600,
    "next": "implement"
  }
}
```

### 5.2 Fan-Out Step

```json
{
  "parallel_review": {
    "type": "fan_out",
    "name": "Review all changed files",
    "children_from": "{{steps.plan.result.files}}",
    "child_template": {
      "target_capability": "code-review",
      "prompt": "Review file {{item.path}}:\n\n{{item.diff}}"
    },
    "completion_policy": { "type": "all" },
    "next": "aggregate"
  }
}
```

- `children_from`: Handlebars expression resolving to an array. Each element becomes `{{item}}` in the child template.
- `child_template`: Template for each child task.
- Falls back to static `children` array if `children_from` is not set.

### 5.3 Condition Step

```json
{
  "check_result": {
    "type": "condition",
    "name": "Check if plan found issues",
    "conditions": [
      {
        "if": "{{steps.plan.result.has_issues}} == true",
        "then": "implement"
      },
      {
        "if": "{{steps.plan.result.severity}} == 'critical'",
        "then": "escalate"
      }
    ],
    "default": "done"
  }
}
```

- Conditions evaluated top-to-bottom, first match wins.
- Supported operators: `==`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `is_empty`, `is_not_empty`.
- `default`: step key if no condition matches.

### 5.4 Webhook Wait Step

```json
{
  "wait_for_ci": {
    "type": "webhook_wait",
    "name": "Wait for CI pipeline to finish",
    "match": {
      "service_connection_id": "svc_github_01...",
      "event_type": "workflow_run.completed",
      "field_filters": {
        "workflow_run.head_sha": "{{trigger.payload.head_sha}}",
        "workflow_run.name": "CI",
        "workflow_run.conclusion": "success"
      }
    },
    "timeout_seconds": 3600,
    "on_timeout": "fail",
    "next": "deploy"
  }
}
```

- Creates a task in `waiting` status that listens for a matching webhook.
- **`service_connection_id` is required** in the match contract. A webhook
  arriving from a different service connection will never match this wait step,
  even if `event_type` and `field_filters` match. This prevents a webhook from
  one GitHub installation from waking a wait step that was configured for a
  different one.
- When a webhook matches all three criteria (service connection, event type,
  and field filters), the task completes with the webhook payload as its result.
- The workflow thread receives the webhook data and continues to the next step.
- **Use specific `field_filters`** to avoid false matches: filtering only on
  `workflow_run.head_sha` would allow any completed workflow run on that commit
  (including failed runs or unrelated workflows) to unblock the wait step.
  Adding `workflow_run.name` and `workflow_run.conclusion: "success"` ensures
  the wait step only unblocks when the specific named workflow succeeds.

### 5.5 Delay Step

```json
{
  "cooldown": {
    "type": "delay",
    "name": "Wait 5 minutes before deploying",
    "delay_seconds": 300,
    "next": "deploy"
  }
}
```

### 5.6 Loop Step (Generator-Evaluator Refinement)

Inspired by the [Anthropic harness design pattern](https://www.anthropic.com/engineering/harness-design-long-running-apps):
agents can't reliably self-evaluate. Separating generator and evaluator into
different agents with different prompts (and personas) produces significantly
better results. The `loop` step type formalizes this as a first-class workflow
primitive.

```json
{
  "design_loop": {
    "type": "loop",
    "name": "Iterative design refinement",
    "max_iterations": 10,
    "generator": {
      "target_capability": "frontend-dev",
      "prompt": "Build a landing page for {{trigger.payload.product_name}}.\n\n{{#if loop.feedback}}Previous feedback:\n{{loop.feedback}}\n\nIteration {{loop.iteration}} of {{loop.max_iterations}}.{{/if}}"
    },
    "evaluator": {
      "target_capability": "design-qa",
      "prompt": "Evaluate this landing page design.\n\nGenerator output:\n{{loop.generator_output}}\n\nScore each criterion 1-10:\n1. Design quality\n2. Originality\n3. Craft\n4. Functionality\n\nReturn JSON: { \"score\": <avg>, \"feedback\": \"<specific improvements>\", \"pass\": <bool> }"
    },
    "exit_condition": "approved",
    "on_max_iterations": "use_last",
    "next": "deploy"
  }
}
```

**How it works:**
1. Engine creates the generator task with the step prompt.
2. Generator completes → engine creates the evaluator task with generator's result injected.
3. Evaluator completes → engine checks `exit_condition`.
4. If condition met → loop exits, continues to `next` step. The thread receives the final generator result.
5. If not met → engine creates a new generator task with `loop.feedback` set to evaluator's feedback. Iteration counter increments.
6. If `max_iterations` reached → `on_max_iterations` determines behavior:
   - `use_last`: accept the last generator result and continue
   - `fail`: fail the workflow

**Loop template variables (generator phase):**

| Variable | Description |
|----------|-------------|
| `{{loop.iteration}}` | Current iteration (1-based) |
| `{{loop.max_iterations}}` | Maximum iterations configured |
| `{{loop.feedback}}` | Evaluator's feedback from previous iteration (null on first) |

**Loop template variables (evaluator phase):**

| Variable | Description |
|----------|-------------|
| `{{loop.iteration}}` | Current iteration (1-based) |
| `{{loop.max_iterations}}` | Maximum iterations configured |
| `{{loop.generator_output}}` | Generator's result from the current iteration |

**Evaluator calibration:** The evaluator agent should use a persona with few-shot
grading examples in its EXAMPLES document. This calibrates scoring to match human
judgment and prevents the "everything looks great" bias. See Section 17.2.

### 5.7 Knowledge References on Steps

Steps can declare knowledge store entries they read or write, making inter-step
data flow explicit beyond the thread:

```json
{
  "generate_report": {
    "type": "agent",
    "target_capability": "data-analysis",
    "prompt": "Analyze the dataset and write a report.",
    "knowledge_writes": ["workflow:{{workflow.run_id}}:report"],
    "next": "review_report"
  },
  "review_report": {
    "type": "agent",
    "target_capability": "qa",
    "prompt": "Review the report at knowledge key: workflow:{{workflow.run_id}}:report",
    "knowledge_reads": ["workflow:{{workflow.run_id}}:report"],
    "next": "done"
  }
}
```

- `knowledge_writes`: keys the step is expected to write (documented, not enforced).
- `knowledge_reads`: keys the step needs (engine verifies they exist before starting the step; fails gracefully if missing).
- Useful for large artifacts (>1MB) that don't fit in the thread, or for data that other agents outside the workflow need to access.

---

## 6. Triggers

### 6.1 Manual Trigger

```json
{
  "trigger_config": {
    "type": "manual",
    "input_schema": {
      "pr_number": { "type": "integer", "required": true },
      "branch": { "type": "string", "default": "main" }
    }
  }
}
```

User clicks "Run" in dashboard or calls `POST /api/v1/hives/{hive}/workflows/{workflow}/run` with input payload.

### 6.2 Webhook Trigger

```json
{
  "trigger_config": {
    "type": "webhook",
    "service_connection_id": "svc_github_01...",
    "event_type": "pull_request.opened",
    "field_filters": {
      "payload.action": "opened",
      "payload.pull_request.base.ref": "main"
    }
  }
}
```

When a matching webhook arrives, a new workflow run is created with the webhook payload as `trigger.payload`.

### 6.3 Schedule Trigger

```json
{
  "trigger_config": {
    "type": "schedule",
    "cron": "0 9 * * 1-5",
    "timezone": "America/New_York"
  }
}
```

Reuses existing `TaskSchedule` infrastructure. Schedule creates a `workflow_run` task instead of a regular task.

#### 6.3.1 Timezone Normalization

The current `TaskSchedule` model and service compute `next_run_at` in server time only. Workflow schedule triggers introduce the `timezone` field, which requires an explicit extension to that infrastructure. The rules are:

1. **Storage** — `timezone` is stored as an [IANA timezone string](https://www.iana.org/time-zones) (e.g. `America/New_York`, `Europe/London`, `UTC`) inside `trigger_config` on the `workflows` row as the **canonical source of truth**. When the scheduler creates or updates the corresponding `TaskSchedule`, it must propagate the timezone value from `trigger_config` into a `timezone` field on the `TaskSchedule` row so that schedule recomputation works without re-reading the workflow definition.

2. **`next_run_at` is always UTC** — the scheduler always writes `next_run_at` as a UTC timestamp. The timezone is only used to interpret the cron expression; it is never stored as a wall-clock time.

3. **Computation** — when computing `next_run_at`, the scheduler must use Carbon's timezone-aware API rather than relying on `date_default_timezone_get()`:
   ```php
   $now      = Carbon::now($timezone);          // current moment in the named zone
   $next     = (new CronExpression($cron))->getNextRunDate($now);
   $nextUtc  = Carbon::instance($next)->utc();  // normalise to UTC before storing
   ```
   This ensures DST transitions are handled correctly by the underlying `dragonmantank/cron-expression` library.

4. **DST behaviour** — the UTC offset varies with DST. For example, `0 9 * * 1-5` with `America/New_York` resolves to **14:00 UTC** during Eastern Standard Time (UTC−5) and **13:00 UTC** during Eastern Daylight Time (UTC−4). Each `next_run_at` is recalculated from the current moment after every dispatch, so DST changes are automatically picked up on the next cycle.

5. **Default** — if `timezone` is omitted or `null`, the scheduler falls back to `UTC` (i.e. the cron expression is evaluated as-is in UTC, matching the existing behaviour).

6. **`TaskSchedule` extension required** — implementing this feature requires adding a `timezone` column to `TaskSchedule` and updating `TaskScheduleService::computeNextRunAt()` to read and apply it. The column is populated from `trigger_config.timezone` when a workflow schedule is created or updated. This is a **required** change before deploying workflow schedule triggers; shipping without it will cause all timezone-aware crons to fire at the wrong wall-clock time.

### 6.4 Event Trigger

```json
{
  "trigger_config": {
    "type": "event",
    "event_type": "task.completed",
    "field_filters": {
      "task_type": "data_import"
    }
  }
}
```

Internal Superpos events can trigger workflows.

### 6.5 API Trigger

```
POST /api/v1/hives/{hive}/workflows/{workflow}/run
{
  "payload": {
    "pr_number": 42,
    "branch": "feature/auth"
  }
}
```

Agents or external systems trigger workflows via API.

---

## 7. Context & Thread Model

### 7.1 Thread Structure

The workflow thread is an ordered array of step completions:

```json
[
  {
    "step_key": "plan",
    "step_name": "Plan the implementation",
    "status": "completed",
    "result": { "output": "Plan: 1) Fix auth.py 2) Add tests...", "files": ["auth.py"] },
    "summary": { "description": "...", "output_excerpt": "..." },
    "started_at": "2026-03-25T10:00:00Z",
    "completed_at": "2026-03-25T10:02:30Z",
    "duration_seconds": 150
  },
  {
    "step_key": "implement",
    "step_name": "Implement the fix",
    "status": "completed",
    "result": { "output": "Fixed N+1 query in auth.py...", "files_changed": ["auth.py"] },
    "summary": { ... },
    "started_at": "2026-03-25T10:02:31Z",
    "completed_at": "2026-03-25T10:05:00Z",
    "duration_seconds": 149
  }
]
```

### 7.2 Template Variables

Available in Handlebars templates:

| Variable | Description |
|----------|-------------|
| `{{trigger.type}}` | How the workflow was triggered (manual, webhook, schedule, api) |
| `{{trigger.payload}}` | The trigger input data |
| `{{trigger.payload.FIELD}}` | Specific trigger field |
| `{{steps.STEP_KEY.result}}` | Full result object from a completed step |
| `{{steps.STEP_KEY.result.FIELD}}` | Specific field from a step's result |
| `{{steps.STEP_KEY.status}}` | Status of a step (completed, failed) |
| `{{steps.STEP_KEY.summary}}` | TaskSummary for a step |
| `{{thread}}` | Full thread array (all completed steps) |
| `{{workflow.name}}` | Workflow definition name |
| `{{workflow.run_id}}` | Current run ID |
| `{{item}}` | Current item in fan_out `children_from` iteration |
| `{{item_index}}` | Index of current item in fan_out iteration |

### 7.3 Step Payload Construction

When a step task is created, the server builds its payload:

```json
{
  "prompt": "... (rendered Handlebars template) ...",
  "workflow_run_id": "run_01...",
  "workflow_step": "implement",
  "trigger": { "type": "webhook", "payload": { ... } },
  "_thread": [
    { "step_key": "plan", "status": "completed", "result": { ... } }
  ]
}
```

The agent receives a fully rendered prompt plus the thread for additional context. The `_thread` is always included so agents can reference any previous step's output even if the prompt template doesn't explicitly include it.

---

## 8. Execution Engine

### 8.1 Workflow Run Lifecycle

```
Trigger fires (webhook, manual, schedule, API)
        │
        ▼
WorkflowExecutionService::startRun()
        │
        ├─ Create parent task (type=workflow_run, status=awaiting_children)
        ├─ Create workflow_runs row (status=running)
        ├─ Find entry steps (steps with no incoming edges)
        └─ Create task for each entry step
                │
                ▼
        Step task claimed by agent → executes → completes
                │
                ▼
WorkflowExecutionService::onStepCompleted()
        │
        ├─ Acquire row-level lock: SELECT FOR UPDATE on workflow_runs row
        ├─ Append step result to thread
        ├─ Update step_states
        ├─ Evaluate conditions for next steps
        ├─ Render prompt templates with updated thread
        ├─ Create tasks for next steps (if deps met)
        │    └─ Unique constraint on (workflow_run_id, step_key) prevents
        │       duplicate step task creation under concurrent completions
        └─ If no more steps → complete parent task → run completed

> **Concurrency note:** The `SELECT FOR UPDATE` lock on `workflow_runs` is
> required before evaluating fan-in conditions and enqueuing downstream step
> tasks. Without it, two parallel steps completing simultaneously can both
> pass the "all deps met" check and each enqueue the next step, causing
> duplicate execution. The unique index on `(workflow_run_id, step_key)` in
> `workflow_step_tasks` (or the `tasks` table via the columns added in §4.4)
> acts as a hard safety net: even if the lock is somehow bypassed, the DB
> will reject the duplicate insert.
```

### 8.2 Step State Machine

```
pending → running → completed
                  → failed → (retry or workflow fails)
                  → skipped (condition evaluated to different branch)
```

### 8.3 DAG Evaluation

Each step declares its `next` (or `conditions` for branching). The engine tracks which steps have completed and creates the next step tasks when all incoming edges are satisfied.

For parallel steps:
```json
{
  "fetch_data": { "type": "agent", "next": "merge" },
  "fetch_config": { "type": "agent", "next": "merge" },
  "merge": {
    "type": "agent",
    "depends_on_steps": ["fetch_data", "fetch_config"],
    "prompt": "Merge data: {{steps.fetch_data.result}} with config: {{steps.fetch_config.result}}"
  }
}
```

`merge` only starts when both `fetch_data` and `fetch_config` have completed.

### 8.4 Error Handling

Per-step:
```json
{
  "implement": {
    "type": "agent",
    "on_failure": "retry",
    "max_retries": 2,
    "fallback_step": "manual_review"
  }
}
```

| `on_failure` | Behavior |
|-------------|----------|
| `retry` | Retry the step (uses task retry infrastructure) |
| `fail_workflow` | Fail the entire workflow run |
| `skip` | Mark step as skipped, continue to next |
| `fallback_step` | Route to a different step on failure |

Workflow-level:
```json
{
  "settings": {
    "on_step_failure": "fail_workflow",
    "timeout_seconds": 7200,
    "max_concurrent_steps": 10
  }
}
```

---

## 9. API Endpoints

### 9.1 Workflow Definition CRUD

```
POST   /api/v1/hives/{hive}/workflows              Create workflow
GET    /api/v1/hives/{hive}/workflows              List workflows
GET    /api/v1/hives/{hive}/workflows/{workflow}   Get workflow
PUT    /api/v1/hives/{hive}/workflows/{workflow}   Update workflow (creates new version)
DELETE /api/v1/hives/{hive}/workflows/{workflow}   Delete workflow (soft-delete)
```

**Deletion semantics:** `DELETE` performs a **soft-delete** — it sets `deleted_at` on the `workflows` row. The workflow is excluded from normal list/get queries (the `idx_workflows_hive` partial index filters on `deleted_at IS NULL`). Soft-delete is rejected if the workflow has any runs in `running` status. If a workflow is later hard-deleted at the database level (e.g., during a data purge), its `workflow_runs` rows are removed automatically via `ON DELETE CASCADE` on the `workflow_runs.workflow_id` FK.

### 9.2 Workflow Versions

```
GET    /api/v1/hives/{hive}/workflows/{workflow}/versions          List versions
GET    /api/v1/hives/{hive}/workflows/{workflow}/versions/{ver}    Get specific version
POST   /api/v1/hives/{hive}/workflows/{workflow}/rollback          Rollback to version
```

### 9.3 Workflow Runs

```
POST   /api/v1/hives/{hive}/workflows/{workflow}/run       Start a run
GET    /api/v1/hives/{hive}/workflows/{workflow}/runs       List runs
GET    /api/v1/hives/{hive}/workflow-runs/{run}             Get run details + thread
POST   /api/v1/hives/{hive}/workflow-runs/{run}/cancel      Cancel a running workflow
POST   /api/v1/hives/{hive}/workflow-runs/{run}/retry       Retry a failed workflow
```

### 9.4 Dashboard Routes

```
GET    /dashboard/workflows                          List workflows
GET    /dashboard/workflows/create                   Create workflow (visual builder)
GET    /dashboard/workflows/{workflow}                View workflow + run history
GET    /dashboard/workflows/{workflow}/edit           Edit workflow (visual builder)
GET    /dashboard/workflow-runs/{run}                  View run (live step progress)
```

---

## 10. Dashboard: Visual Workflow Builder

### 10.1 Builder UI (React Flow)

```
┌─────────────────────────────────────────────────────────┐
│  PR Review Pipeline                    [Save] [Run]     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────────┐                                          │
│   │ Webhook  │ (pull_request.opened)                    │
│   │ Trigger  │                                          │
│   └────┬─────┘                                          │
│        │                                                │
│        ▼                                                │
│   ┌──────────┐                                          │
│   │  Plan    │  target: planning                        │
│   │  (agent) │  prompt: "Review PR #{{...}}..."         │
│   └────┬─────┘                                          │
│        │                                                │
│        ▼                                                │
│   ┌──────────┐    ┌───────────┐                         │
│   │ Has      │───▶│ Implement │  target: coding         │
│   │ issues?  │yes │  (agent)  │                         │
│   │(condition│    └─────┬─────┘                         │
│   └────┬─────┘          │                               │
│     no │                ▼                               │
│        │          ┌───────────┐                          │
│        │          │ Wait CI   │  (webhook_wait)          │
│        │          │           │  workflow_run.completed   │
│        │          └─────┬─────┘                          │
│        │                │                               │
│        │                ▼                               │
│        │          ┌───────────┐                          │
│        └─────────▶│  Done     │  (complete workflow)     │
│                   └───────────┘                          │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Step Properties (right panel)                          │
│  ┌─────────────────────────────────────┐                │
│  │ Name: Plan                          │                │
│  │ Type: agent                         │                │
│  │ Target: planning                    │                │
│  │ Prompt:                             │                │
│  │ ┌─────────────────────────────────┐ │                │
│  │ │ Review PR #{{trigger.payload.   │ │                │
│  │ │ pr_number}} and create a plan...│ │                │
│  │ └─────────────────────────────────┘ │                │
│  │ Timeout: 600s                       │                │
│  │ On failure: [fail_workflow ▾]       │                │
│  └─────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

### 10.2 Run Viewer

```
┌─────────────────────────────────────────────────────────┐
│  Run #run_01ABC...          Status: ● Running           │
│  Workflow: PR Review Pipeline v3     [Cancel]           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────────┐                                          │
│   │ Webhook  │ ✅ Triggered by PR #42                    │
│   │ Trigger  │ 10:00:00                                 │
│   └────┬─────┘                                          │
│        │                                                │
│        ▼                                                │
│   ┌──────────┐                                          │
│   │  Plan    │ ✅ Completed (2m 30s)                     │
│   │          │ "Found 3 issues: N+1 query..."           │
│   └────┬─────┘                                          │
│        │                                                │
│        ▼                                                │
│   ┌──────────┐                                          │
│   │ Has      │ → yes (has_issues=true)                  │
│   │ issues?  │                                          │
│   └────┬─────┘                                          │
│        │                                                │
│        ▼                                                │
│   ┌──────────┐                                          │
│   │Implement │ 🔄 In Progress (1m 20s)                  │
│   │          │ Progress: 60%                            │
│   └──────────┘                                          │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Thread (accumulated context)                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Step 1 (plan): Found 3 issues in auth.py...     │    │
│  │ Step 2 (implement): In progress...              │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 11. Full Example: PR Review Pipeline

### 11.1 Workflow Definition

```json
{
  "name": "PR Review Pipeline",
  "slug": "pr-review-pipeline",
  "description": "Automated PR review: plan, implement fixes, wait for CI, verify",
  "trigger_config": {
    "type": "webhook",
    "service_connection_id": "svc_github_01...",
    "event_type": "pull_request.opened",
    "field_filters": {
      "payload.pull_request.base.ref": "main"
    }
  },
  "steps": {
    "plan": {
      "type": "agent",
      "name": "Analyze PR",
      "target_capability": "code-review",
      "prompt": "Review PR #{{trigger.payload.pull_request.number}}.\n\nTitle: {{trigger.payload.pull_request.title}}\nAuthor: {{trigger.payload.pull_request.user.login}}\nDiff: {{trigger.payload.pull_request.diff_url}}\n\nAnalyze the changes and report:\n1. What issues exist (if any)\n2. Severity (critical, major, minor)\n3. Suggested fixes",
      "timeout_seconds": 600,
      "next": "check_issues"
    },
    "check_issues": {
      "type": "condition",
      "name": "Issues found?",
      "conditions": [
        {
          "if": "{{steps.plan.result.has_issues}} == true",
          "then": "implement"
        }
      ],
      "default": "approve"
    },
    "implement": {
      "type": "agent",
      "name": "Fix the issues",
      "target_capability": "coding",
      "prompt": "The code review found these issues:\n\n{{steps.plan.result.output}}\n\nFix them and push to the PR branch.",
      "timeout_seconds": 1200,
      "on_failure": "fail_workflow",
      "next": "wait_ci"
    },
    "wait_ci": {
      "type": "webhook_wait",
      "name": "Wait for CI to pass",
      "match": {
        "service_connection_id": "svc_github_01...",
        "event_type": "workflow_run.completed",
        "field_filters": {
          "payload.workflow_run.head_sha": "{{trigger.payload.pull_request.head.sha}}",
          "payload.workflow_run.name": "CI",
          "payload.workflow_run.conclusion": "success"
        }
      },
      "timeout_seconds": 3600,
      "on_timeout": "fail_workflow",
      "next": "verify"
    },
    "verify": {
      "type": "agent",
      "name": "Verify CI results",
      "target_capability": "code-review",
      "prompt": "CI completed for PR #{{trigger.payload.pull_request.number}}.\n\nCI Result: {{steps.wait_ci.result.payload.workflow_run.conclusion}}\nFixes applied: {{steps.implement.result.output}}\n\nVerify the fixes are correct and CI passed. If all good, approve the PR.",
      "timeout_seconds": 300,
      "next": "approve"
    },
    "approve": {
      "type": "agent",
      "name": "Post approval comment",
      "target_capability": "code-review",
      "prompt": "Post an approval comment on PR #{{trigger.payload.pull_request.number}} summarizing the review.\n\nThread summary:\n{{#each thread}}\n- {{this.step_name}}: {{this.summary.output_excerpt}}\n{{/each}}",
      "timeout_seconds": 120
    }
  },
  "settings": {
    "on_step_failure": "fail_workflow",
    "timeout_seconds": 7200
  }
}
```

### 11.2 Execution Trace

```
10:00:00  Webhook: pull_request.opened (PR #42)
          → WorkflowExecutionService::startRun()
          → Parent task created (type=workflow_run, awaiting_children)
          → Step "plan" task created (pending)

10:00:05  Agent claims "plan" task
10:02:30  Agent completes "plan" → result: { has_issues: true, output: "Found N+1 query..." }
          → Thread: [{ step_key: "plan", result: {...} }]
          → Condition "check_issues": has_issues == true → route to "implement"
          → Step "implement" task created with rendered prompt

10:02:35  Agent claims "implement" task
10:05:00  Agent completes "implement" → result: { output: "Fixed auth.py..." }
          → Thread: [..., { step_key: "implement", result: {...} }]
          → Step "wait_ci" created (webhook_wait, waiting)

10:05:01  ... waiting for CI ...

10:12:00  Webhook: workflow_run.completed (matching head_sha, name="CI", conclusion="success")
          → "wait_ci" task completed with webhook payload
          → Thread: [..., { step_key: "wait_ci", result: { payload: { workflow_run: { name: "CI", conclusion: "success" } } } }]
          → Step "verify" task created

10:12:05  Agent claims "verify" task
10:14:00  Agent completes "verify"
          → Step "approve" task created

10:14:05  Agent claims "approve" task
10:14:30  Agent completes "approve"
          → No more steps → parent task completed
          → workflow_run status = completed
```

---

## 12. Implementation Plan

### Phase A: Core Engine (tasks 168-169)

| # | Task | Description |
|---|------|-------------|
| 168a | Workflow & WorkflowVersion models + migrations | Tables, model, versioning logic |
| 168b | WorkflowRun model + migration | Run tracking, thread storage |
| 168c | Tasks table additions (workflow_run_id, workflow_step_key) | Link tasks to workflow runs |
| 169a | WorkflowExecutionService — startRun() | Create parent task, evaluate entry steps, create first step tasks |
| 169b | WorkflowExecutionService — onStepCompleted() | Thread accumulation, condition evaluation, next step creation |
| 169c | Handlebars template rendering service | Render step prompts with thread/trigger context |
| 169d | Condition evaluator | Parse and evaluate condition expressions |
| 169e | Webhook wait step integration | Create waiting task, match incoming webhooks to waiting steps |
| 169f | Hook into TaskController::complete() | Detect workflow step completion, trigger onStepCompleted() |

### Phase B: API + Triggers (new tasks)

| # | Task | Description |
|---|------|-------------|
| 168d | Workflow CRUD API | Create, list, get, update, delete workflows |
| 168e | Workflow run API | Start, list, get, cancel, retry runs |
| 168f | Workflow version API | List versions, rollback |
| 168g | Webhook trigger integration | Route matching webhooks to workflow starts |
| 168h | Schedule trigger integration | Reuse TaskSchedule for cron/interval triggers |

### Phase C: Dashboard (task 170)

| # | Task | Description |
|---|------|-------------|
| 170a | Dashboard: workflow list page | List workflows with status, last run, trigger info |
| 170b | Dashboard: visual workflow builder (React Flow) | DAG editor, step property panel, prompt editor |
| 170c | Dashboard: workflow run viewer | Live step progress, thread viewer, status timeline |
| 170d | Dashboard: workflow run history | List past runs with status, duration, trigger info |

### Phase D: Harness Patterns (tasks 191-196)

> Informed by [Anthropic harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps)

| # | Task | Description |
|---|------|-------------|
| 191 | Loop step type (generator-evaluator) | Iterative refinement cycle with exit condition, feedback injection |
| 192 | Knowledge references on workflow steps | knowledge_reads/knowledge_writes declarations for inter-step data |
| 193 | Built-in workflow templates (Plan-Build-QA, Code Review, Data Pipeline) | Forkable starter templates shipped with Superpos |
| 194 | QA evaluator persona template | Pre-calibrated skeptical evaluator with few-shot grading examples |
| 195 | Workflow-step-aware LLM cost tracking | Per-step cost/duration breakdown in workflow runs |
| 196 | Workflow run cost summary in dashboard | Visual cost breakdown per step in run viewer |

---

## 13. What This Reuses (No New Invention)

| Concept | Reuses |
|---------|--------|
| Step execution | Regular tasks (Task model, claiming, completion) |
| Parallel steps | Fan-out infrastructure (FanOutService, CompletionPolicyService) |
| Step dependencies | Task dependencies (TaskDependencyService) |
| Context passing | TaskSummaryService (summary) + thread (new, lightweight) |
| Webhook triggers | WebhookRouteEvaluator (route matching, field filters) |
| Schedule triggers | TaskScheduleService (cron, interval) |
| Retry/timeout | Task failure policies (existing infrastructure) |
| Result storage | Task result field + summary field |
| Real-time updates | TaskStatusChanged broadcast (existing WebSocket) |
| Visual DAG | React Flow (same library as dependency graph view, task 103) |

---

## 14. What's New (Net New Code)

| Component | Purpose |
|-----------|---------|
| `Workflow` model | Definition storage with versioning |
| `WorkflowVersion` model | Version history |
| `WorkflowRun` model | Run state + thread accumulation |
| `WorkflowExecutionService` | Core orchestrator: start runs, advance steps, evaluate conditions |
| `WorkflowTemplateService` | Handlebars rendering for step prompts |
| `WorkflowConditionEvaluator` | Parse and evaluate condition expressions |
| `WorkflowTriggerService` | Match triggers (webhook, schedule, event) to workflow starts |
| Dashboard pages | Builder, run viewer, list |

---

## 15. Built-in Workflow Templates

Pre-built workflow templates ship with Superpos (same concept as persona templates).
Users can fork and customize them.

### 15.1 Plan-Build-QA Template

The foundational workflow pattern from Anthropic's
[harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps).

```
Trigger (manual/webhook)
    │
    ▼
┌─────────┐
│ Planner │  "Be ambitious about scope. Focus on product context,
│ (agent) │   not implementation details."
└────┬────┘
     │
     ▼
┌──────────┐
│ Contract │  Planner proposes what will be built + acceptance criteria.
│(condition│  Evaluator reviews the contract before work begins.
└────┬─────┘
     │
     ▼
┌───────────────┐
│  Build Loop   │  Generator builds feature by feature.
│   (loop)      │  Evaluator tests live app via service proxy.
│  max: 5 iter  │  Exit when evaluator passes all criteria.
└───────┬───────┘
        │
        ▼
┌────────────┐
│ Final QA   │  End-to-end verification of full deliverable.
│  (agent)   │
└────────────┘
```

**Key insight from harness research:** The "sprint contract" step — where generator
and evaluator agree on what "done" looks like before any code is written — prevents
the evaluator from being too lenient and the generator from cutting corners.

### 15.2 Code Review Pipeline Template

```
Webhook (pull_request.opened)
  → Plan review → Parallel file reviews (fan_out) → Aggregate → Post comment
```

### 15.3 Data Pipeline Template

```
Schedule (daily 9am)
  → Fetch data (agent) → Transform (agent) → Validate (loop: QA checks)
  → Load (agent) → Notify (agent)
```

---

## 16. Evaluator Calibration & Personas

### 16.1 The Self-Evaluation Problem

Agents are poor self-evaluators. Research shows they "confidently praise their own
work — even when quality is obviously mediocre." The fix: separate the evaluator
into a different agent with a different persona tuned for skepticism.

### 16.2 Calibrating Evaluators with Personas

The evaluator agent should have a dedicated persona with:

**SOUL document:** "You are a rigorous QA reviewer. Your job is to find problems,
not to be encouraging. A pass means the work is genuinely excellent."

**EXAMPLES document:** Few-shot grading calibration samples:
```
## Example 1: Score 3/10 (Fail)
Input: Landing page with generic layout, stock gradients, no custom typography.
Assessment: Template-quality work. No evidence of custom design decisions...
Score: { design: 2, originality: 1, craft: 4, functionality: 5, overall: 3 }

## Example 2: Score 8/10 (Pass)
Input: Dashboard with consistent design system, custom color palette, clear hierarchy.
Assessment: Strong information architecture. Typography creates clear scan path...
Score: { design: 8, originality: 7, craft: 9, functionality: 8, overall: 8 }
```

**Key finding:** "It took several rounds of reading the evaluator's logs, finding
examples where its judgment diverged from mine, and updating the prompt" before
the evaluator graded in a way that matched human expectations. Persona versioning
and performance tracking (tasks 137, 145-146) enable this iterative calibration.

### 16.3 Workflow-Aware Cost Tracking

Each workflow run naturally produces per-step timing (via `TaskSummary.duration_seconds`)
and status. When LLM usage tracking (task 113) is implemented, it should be
workflow-step-aware so operators get breakdowns like:

```
Workflow: PR Review Pipeline (run #42)
  Planner:    $0.46  /  4.7 min
  Build (×3): $71.08 / 2h 7min
  QA (×3):    $10.39 / 25 min
  Total:      $81.93 / 2h 37min
```

This enables cost optimization: if QA is cheap but catches real issues, it's worth
running. If the planner adds negligible cost, keep it. If build iterations are
expensive, invest in better evaluator calibration to reduce iterations.

---

## 17. Harness Evolution

### 17.1 Re-examine With Each Model Update

> "Every component in a harness encodes an assumption about what the model can't
> do on its own, and those assumptions are worth stress testing."
> — Anthropic Engineering

When a new model ships:
1. Run the same workflow with the new model (via persona A/B testing, task 146)
2. Compare: does the loop still need 5 iterations, or does it pass on iteration 1?
3. If so, simplify: replace the loop with a single agent step
4. Re-invest complexity budget: add steps that push the new model's boundaries

Persona versioning + performance tracking provide the infrastructure for this practice.

### 17.2 Superpos's Natural Advantage

Superpos's task-per-step model IS the context reset pattern. Each step runs in a
fresh agent invocation with a clean context window. The workflow thread provides
the structured handoff. This means:

- **No context degradation** — agents don't lose coherence on long workflows
- **No premature wrap-up** — each step has its own timeout, not a shared budget
- **Natural parallelism** — independent steps run on different agents simultaneously
- **Heterogeneous agents** — the planner can be Opus, the builder Sonnet, the QA Haiku

---

## 18. Permissions (unchanged)

| Permission | Grants |
|-----------|--------|
| `workflows.read` | View workflow definitions and runs |
| `workflows.create` | Create and edit workflow definitions |
| `workflows.run` | Trigger workflow runs |
| `workflows.manage` | Delete workflows, cancel runs |

---

## 19. Constraints & Limits

| Constraint | Limit |
|-----------|-------|
| Steps per workflow | 50 max |
| Concurrent runs per workflow | 10 max (configurable per hive) |
| Thread size | 5 MB max (truncate old step results if exceeded) |
| Template render size | 100 KB max per step prompt |
| Workflow timeout | 24h max |
| Fan-out children per step | 50 max (same as existing fan-out limit) |
| Nested workflows | Not supported in MVP (keep flat) |
| Loop max iterations | 20 max per loop step |
| Loop step nesting | No nested loops (loop steps cannot contain other loops) |
