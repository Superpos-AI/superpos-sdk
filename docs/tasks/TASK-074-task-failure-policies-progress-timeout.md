# TASK-074: Task Failure Policies & Progress Timeout Migration

**Status:** done
**Branch:** `task/074-failure-policies-timeout`
**PR:** [#113](https://github.com/Superpos-AI/superpos-app/pull/113)
**Depends On:** TASK-008
**Blocked By:** —

## Requirements

### 1. `failure_policy` JSONB Column
Add a `failure_policy` JSONB column to the `tasks` table that stores per-task
failure/timeout configuration. The schema:
```json
{
  "task_timeout": 300,
  "progress_timeout": 60,
  "on_timeout": "retry",
  "max_retries": 3,
  "retry_delay": "exponential",
  "retry_delay_base": 5,
  "retry_delay_max": 300,
  "on_max_retries_exceeded": "fail"
}
```

### 2. `last_progress_at` Timestamp Column
Add a nullable `last_progress_at` timestamp that tracks the last time an agent
reported progress (via `PATCH /tasks/{id}/progress` or heartbeat with active tasks).
Reset to null on retry/reassign. Used to compute progress timeout:
`COALESCE(last_progress_at, claimed_at) + progress_timeout < NOW()`.

### 3. New Task Statuses
Add `dead_letter` status to the Task model for tasks that fail after exhausting
all retries with `on_max_retries_exceeded: "dead_letter"`.

### 4. `getEffectiveFailurePolicy()` Model Helper
Merges per-task `failure_policy` JSONB with config defaults. Per-task values
take precedence over defaults. Returns a normalized array.

### 5. Progress Timeout Detection
A new `CheckProgressTimeouts` artisan command (runs every 15 seconds) detects
stuck agents by checking `COALESCE(last_progress_at, claimed_at)` against
the `progress_timeout` from the effective failure policy. Handles four actions:
- **retry**: pending + increment retry_count + backoff
- **reassign**: pending + no retry_count increment + no backoff
- **fail**: terminal failure immediately
- **notify**: log only (approval_request creation deferred to TASK-075)

### 6. Refactor TaskTimeoutService
Extend the existing `TaskTimeoutService` to read `task_timeout` from the
effective failure policy and handle `on_max_retries_exceeded` actions
(fail vs dead_letter).

### 7. Update Progress Endpoint
Set `last_progress_at = now()` when agents report progress via the API.

### 8. Update Task Creation
Accept optional `failure_policy` in task creation requests. Validate structure.

### 9. Config Defaults
Add failure policy defaults to `config/apiary.php`:
```php
'failure_policy' => [
    'task_timeout' => 300,
    'progress_timeout' => 60,
    'on_timeout' => 'retry',
    'max_retries' => 3,
    'retry_delay' => 'exponential',
    'retry_delay_base' => 5,
    'retry_delay_max' => 300,
    'on_max_retries_exceeded' => 'fail',
],
```

## Implementation Plan

### Files to Create
1. **`database/migrations/2026_03_06_000000_add_failure_policy_to_tasks_table.php`**
2. **`app/Console/Commands/CheckProgressTimeouts.php`**
3. **`app/Services/ProgressTimeoutService.php`**
4. **`tests/Feature/TaskFailurePolicyTest.php`**

### Files to Modify
1. **`app/Models/Task.php`** — Add statuses, fillable, casts, helper methods
2. **`app/Services/TaskTimeoutService.php`** — Read from effective failure policy
3. **`config/apiary.php`** — Add failure_policy defaults
4. **`database/factories/TaskFactory.php`** — Add factory states
5. **`app/Http/Controllers/Api/TaskController.php`** — Set last_progress_at on progress, accept failure_policy on create
6. **`app/Http/Requests/CreateTaskRequest.php`** — Validate failure_policy
7. **`bootstrap/app.php`** — Register progress timeout scheduler

## Test Plan

1. Migration adds failure_policy and last_progress_at columns
2. getEffectiveFailurePolicy() merges defaults with per-task overrides
3. Progress timeout detects stuck tasks (no progress reports)
4. Progress timeout retry action: pending + increment + backoff
5. Progress timeout reassign action: pending + no increment + no backoff
6. Progress timeout fail action: terminal failure
7. Progress timeout respects progress_timeout value from failure_policy
8. last_progress_at resets progress timeout clock
9. Task timeout reads from effective failure policy
10. on_max_retries_exceeded=dead_letter transitions to dead_letter status
11. on_max_retries_exceeded=fail transitions to failed status
12. Progress endpoint sets last_progress_at
13. Task creation accepts and stores failure_policy
14. Invalid failure_policy rejected with validation error
15. Default failure policy used when none specified
16. Activity logging for all timeout/retry/failure events
17. dead_letter status helper and scope
18. Factory states for failure policy and last_progress_at

## Acceptance Criteria

- [ ] Migration adds failure_policy (JSONB) and last_progress_at (timestamp) columns
- [ ] Task model has getEffectiveFailurePolicy() that merges with config defaults
- [ ] ProgressTimeoutService detects stuck tasks and handles retry/reassign/fail/notify
- [ ] TaskTimeoutService uses effective failure policy for timeout decisions
- [ ] Progress endpoint sets last_progress_at
- [ ] Task creation accepts failure_policy
- [ ] dead_letter status supported
- [ ] All tests pass
- [ ] PSR-12 compliant
