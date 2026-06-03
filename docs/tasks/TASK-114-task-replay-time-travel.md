# TASK-114 — Task Replay / Time Travel

**Status:** Done
**Depends On:** TASK-008, TASK-010
**Branch:** `task/114-task-replay-time-travel`

## Summary

Implement task replay / time-travel endpoints that allow agents to inspect the
full execution trace of a task, replay a completed/failed/dead_letter task with
the same (or overridden) payload, and compare two task runs side-by-side.

## What Changed

### New: `TaskReplayService`

Stateless service in `app/Services/TaskReplayService.php` with three operations:

- **`assembleTrace(Task)`** — Assembles a chronological execution trace by
  merging `activity_log` entries (by `task_id`) with `proxy_log` entries
  (correlated by `claimed_by` agent + time window between `claimed_at` and
  `completed_at`). No new storage — query-based assembly from existing tables.

- **`replay(Task, options)`** — Creates a new pending task with the same
  `payload`, `context_refs`, `priority`, `timeout_seconds`, `max_retries`,
  `failure_policy`, and `target_capability` as the original. Sets `parent_task_id`
  to the original task for traceability. Optional `override_payload` replaces the
  payload. Only tasks in terminal statuses (`completed`, `failed`, `dead_letter`)
  are replayable.

- **`compare(Task, Task)`** — Returns `payload_diff`, `result_diff`, and
  `trace_diff` between two tasks. Diffs are field-level (`{key: {a, b}}`) for
  payload/result, and set-difference for trace events.

### New: `TaskReplayController`

Three endpoints in `app/Http/Controllers/Api/TaskReplayController.php`:

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/v1/hives/{hive}/tasks/{task}/trace` | `tasks.read` | Get execution trace |
| POST | `/api/v1/hives/{hive}/tasks/{task}/replay` | `tasks.create` | Create replay task |
| GET | `/api/v1/hives/{hive}/tasks/compare?task_a=&task_b=` | `tasks.read` | Compare two tasks |

All endpoints enforce:
- Sanctum agent authentication
- Permission middleware (`tasks.read` or `tasks.create`)
- Hive resolution + cross-hive permission check
- Superpos isolation (task must belong to agent's apiary)
- Standard JSON envelope `{ data, meta, errors }`

### New: `ReplayTaskRequest`

Form request validation for the replay endpoint. Validates `override_payload`
is an optional array. Uses the standard error envelope for validation failures.

### Task Model Updates

- Added `REPLAYABLE_STATUSES` constant: `['completed', 'failed', 'dead_letter']`
- Added `isReplayable()` helper method

### Activity Logging

Replay operations log `task.replayed` with details including `original_task_id`,
`replay_task_id`, task type, whether payload was overridden, and cross-hive flag.

### SDK Updates

**Python SDK** (`sdk/python/src/superpos_sdk/client.py`):
- `get_task_trace(hive_id, task_id)` — GET trace
- `replay_task(hive_id, task_id, override_payload=)` — POST replay
- `compare_tasks(hive_id, task_a=, task_b=)` — GET compare

**Shell SDK** (`sdk/shell/src/superpos-sdk.sh`):
- `superpos_get_task_trace HIVE_ID TASK_ID`
- `superpos_replay_task HIVE_ID TASK_ID [-d OVERRIDE_PAYLOAD_JSON]`
- `superpos_compare_tasks HIVE_ID TASK_A_ID TASK_B_ID`

## Tests

42 tests in `tests/Feature/TaskReplayApiTest.php`:

- Trace assembly (activity_log + proxy_log correlation)
- Replay eligibility (only terminal statuses)
- Replay creation with correct attributes and parent linkage
- Override payload on replay
- Task comparison (payload_diff, result_diff, trace_diff)
- Permission and authorization checks (tasks.read, tasks.create)
- Hive scoping isolation
- Activity logging on replay
- Envelope compliance (meta as JSON object)
- Non-replayable status rejection (pending, in_progress, cancelled)
- TaskReplayService unit-level tests
- Task model `isReplayable()` helper
