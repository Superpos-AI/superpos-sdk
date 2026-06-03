# TASK-083 — Best-Effort Tasks & Expiry

| Field       | Value                                       |
|-------------|---------------------------------------------|
| Status      | In Progress                                 |
| Priority    | High                                        |
| Depends On  | TASK-074 (Failure policies & progress timeout) |
| Branch      | `task/083-best-effort-tasks-expiry`         |
| Edition     | `shared`                                    |

## Objective

Add `best_effort` guarantee level and `expires_at` expiry to the task system.
Best-effort tasks fail cleanly (no DLQ) and can auto-expire when their
execution window passes, enabling fire-and-forget patterns like cache
refreshes and dashboard pings.

## Design

### Data Model

Two new columns on the `tasks` table:

| Column      | Type              | Purpose                                      |
|-------------|-------------------|----------------------------------------------|
| `guarantee` | varchar(20)       | `at_least_once` (default) or `best_effort`   |
| `expires_at`| timestamp nullable| Auto-expire time for best-effort tasks       |

New status: `expired` — terminal state for tasks that missed their window.

### Semantics

| Aspect              | `at_least_once` (default) | `best_effort`                |
|---------------------|--------------------------|------------------------------|
| On max retries      | `dead_letter` or `fail`  | Always `fail` (no DLQ)       |
| Expiry              | Not available             | Optional `expires_at`        |
| Dashboard alerts    | Prominent on failure      | Logged but not alerted       |

### Enforcement

- **Poll/claim:** Skip tasks with `expires_at` in the past
- **CleanupExpiredTasks:** Scheduler bulk-updates expired pending tasks to `expired`
- **Timeout services:** Defense-in-depth guard prevents best-effort → dead_letter
- **Idempotency:** Expired tasks allow re-creation via same key
- **Replay:** Expired tasks are replayable (guarantee copied, expires_at not)

## Files Changed

- `database/migrations/2026_03_08_100000_add_guarantee_and_expires_at_to_tasks_table.php`
- `app/Models/Task.php` — new status, constants, casts, scopes, helpers
- `app/Http/Controllers/Api/TaskController.php` — poll/claim/create/format
- `app/Http/Requests/CreateTaskRequest.php` — validation rules
- `app/Console/Commands/CleanupExpiredTasks.php` — new scheduler command
- `app/Services/TaskExpiryService.php` — expiry logic
- `app/Services/TaskTimeoutService.php` — best-effort guard
- `app/Services/ProgressTimeoutService.php` — best-effort guard
- `app/Services/IdempotencyService.php` — expired in retry-allowed
- `app/Services/TaskReplayService.php` — expired replayable + guarantee copy
- `app/Services/PoolHealthService.php` — expired count in metrics
- `bootstrap/app.php` — scheduler registration
- `database/factories/TaskFactory.php` — bestEffort/withExpiry/expired states
- `sdk/python/src/superpos_sdk/client.py` — guarantee, expires_at params
- `sdk/shell/src/superpos-sdk.sh` — -g, -e options
- `tests/Feature/TaskBestEffortExpiryTest.php`

## Test Plan

- Task creation with valid/invalid guarantee and expires_at
- Poll excludes expired tasks, includes valid ones
- Claim rejects expired tasks (409)
- CleanupExpiredTasks expires pending, skips in_progress/future/null
- Best-effort timeout → fail (not dead_letter)
- Idempotency: expired key allows re-creation
- Replay: expired tasks replayable
- Normal tasks unchanged (backward compat)
