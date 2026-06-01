# TASK-019: Task Timeout & Retry Scheduler

**Status:** done
**Branch:** `task/019-task-timeout-retry`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/21
**Depends On:** TASK-008 (Task Model), TASK-011 (ActivityLogger Service)
**Blocked By:** —

## Requirements

### Timeout Detection

A scheduled process runs periodically (every minute) to detect in-progress
tasks that have exceeded their `timeout_seconds` deadline.

**Detection query:**
- Tasks with `status = 'in_progress'`
- Where `claimed_at + timeout_seconds < NOW()`

**Behavior on timeout:**
- If `retry_count < max_retries`: reset to `pending` for retry
- If `retry_count >= max_retries`: transition to `failed` (terminal)

### Retry Scheduling

When a timed-out task is eligible for retry:

1. Increment `retry_count`
2. Set `status` back to `pending`
3. Clear `claimed_by`, `claimed_at`, `progress`, `status_message`
4. Preserve original `payload`, `result` (cleared), and all targeting fields
5. Log `task.timed_out` activity with attempt number
6. Log `task.retried` activity with new retry_count and backoff info

**Exponential backoff:** The task is not immediately available. A
`retry_after` timestamp is computed as `NOW() + base * 2^(retry_count - 1)`
where `base = config('apiary.task.retry_backoff')` (default 30s). Tasks
with a `retry_after` in the future are excluded from poll queries.

### Terminal Failure

When `retry_count >= max_retries`:

1. Set `status` to `failed`
2. Set `completed_at` to current timestamp
3. Store timeout metadata in `result`
4. Log `task.timed_out` activity
5. Log `task.max_retries_exceeded` activity

### State Transitions

```
in_progress -> pending  (timeout with retries remaining)
in_progress -> failed   (timeout with retries exhausted)
```

### Scope Safety

- Timeout detection operates across ALL apiaries and hives (system-level)
- No global scopes applied — uses `withoutGlobalScopes()`
- Each task is processed within its own transaction for isolation
- Atomic UPDATE prevents race conditions with concurrent agents

### Activity Logging

- `task.timed_out` — logged whenever a task exceeds its timeout
- `task.retried` — logged when task is reset to pending for retry
- `task.max_retries_exceeded` — logged when task permanently fails

## Implementation Plan

### Files to Create

1. **`app/Services/TaskTimeoutService.php`** — Core business logic for timeout detection, retry scheduling, and terminal failure handling
2. **`app/Console/Commands/CheckTaskTimeouts.php`** — Artisan command that invokes the service
3. **`tests/Feature/TaskTimeoutRetryTest.php`** — Comprehensive test suite
4. **`docs/guide/task-timeout-retry.md`** — VitePress public guide

### Files to Modify

1. **`app/Models/Task.php`** — Add `scopeTimedOut()`, `isRetryable()`, `retryBackoffSeconds()` helpers
2. **`routes/console.php`** — Register scheduled command
3. **`bootstrap/app.php`** — Wire schedule
4. **`docs/index.md`** — Link to new guide
5. **`TASKS.md`** — Mark TASK-018 as done

### Key Design Decisions

- Service class holds all logic (thin command, testable service)
- Per-task transactions with `lockForUpdate()` for race safety
- Exponential backoff via `retry_after` column (migration adds this)
- Poll queries already filter `status = 'pending'`; adding `retry_after` filter
- No new API endpoints — this is an internal scheduler
- ActivityLogger used for all state changes (no agent context for system operations)

## Test Plan

1. Timed-out task with retries remaining is reset to pending
2. retry_count incremented correctly on each timeout
3. claimed_by, claimed_at, progress cleared on retry
4. Timed-out task with retries exhausted transitions to failed
5. completed_at set on terminal failure
6. result stores timeout metadata on terminal failure
7. Task not yet timed out is left untouched
8. Completed tasks are not affected by timeout check
9. Failed tasks are not affected by timeout check
10. Pending tasks are not affected by timeout check
11. Cancelled tasks are not affected by timeout check
12. Activity log entries created for timeout, retry, and max_retries_exceeded
13. Multiple timed-out tasks processed in single run
14. Concurrent timeout check is safe (lockForUpdate)
15. retry_after computed with exponential backoff
16. Tasks with retry_after in future excluded from poll (poll-level)
17. Artisan command executes correctly and reports results
18. Tasks with timeout_seconds = 0 are never timed out (disabled)
19. Cross-hive tasks handled correctly (same logic, different hive_id)
20. Each task processed in its own transaction (isolation)
