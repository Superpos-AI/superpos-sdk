# TASK-078: Scheduled / Recurring Tasks

**Status:** Complete
**Depends On:** 008 (Task model), 011 (ActivityLogger)
**Edition Scope:** shared

## Summary

Add a `task_schedules` table and service layer that allows agents to
define recurring task templates.  A scheduler command dispatches pending
tasks into the existing task queue when they come due.

## Requirements

1. **Trigger types:** `once` (one-shot at a specific time), `interval`
   (every N seconds, min 10 s), `cron` (standard 5-field expression).
2. **Overlap policies:** `skip` (don't create a new task if the previous
   one is still pending/in_progress), `allow` (always create),
   `cancel_previous` (cancel the running task and create a new one).
3. **Lifecycle:** `active` / `paused` / `expired`.  Schedules expire
   automatically after the optional `expires_at` deadline or (for `once`
   schedules) after the first dispatch.
4. **API:** Full CRUD + pause/resume, permission-gated with
   `schedules.read` and `schedules.write`.
5. **Dispatcher:** `apiary:dispatch-scheduled-tasks` artisan command,
   registered to run every minute via the Laravel scheduler.
6. **Safe interaction with queues:** Tasks are created as standard
   `pending` rows — they flow through the existing claim/retry/timeout
   pipeline unchanged.

## Implementation

### Database

- Migration `2026_03_08_100000_create_task_schedules_table.php`
- Partial index on `(next_run_at) WHERE status='active'` (PostgreSQL) /
  composite `(status, next_run_at)` (SQLite)

### Model

- `App\Models\TaskSchedule` with `BelongsToHive`, `HasUlid` traits
- Constants: `TRIGGER_TYPES`, `OVERLAP_POLICIES`, `STATUSES`
- Scopes: `active()`, `due()`
- Relationships: `createdByAgent()`, `targetAgent()`, `lastTask()`

### Service

- `App\Services\TaskScheduleService`
  - `computeNextRunAt()` — trigger-type-aware next-run computation
  - `dispatchDueSchedules()` — batch dispatcher (system-level, cross-hive)
  - `dispatchSchedule()` — single schedule dispatch with locking
  - Overlap policy enforcement with activity logging
  - Expiry detection with automatic status transition

### Command

- `App\Console\Commands\DispatchScheduledTasks`
- Registered in `bootstrap/app.php` scheduler: `everyTenSeconds()`,
  `withoutOverlapping()`, `runInBackground()`

### API

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/hives/{hive}/schedules` | schedules.read | List schedules |
| GET | `/hives/{hive}/schedules/{id}` | schedules.read | Show schedule |
| POST | `/hives/{hive}/schedules` | schedules.write | Create schedule |
| PUT | `/hives/{hive}/schedules/{id}` | schedules.write | Update schedule |
| DELETE | `/hives/{hive}/schedules/{id}` | schedules.write | Delete schedule |
| PATCH | `/hives/{hive}/schedules/{id}/pause` | schedules.write | Pause schedule |
| PATCH | `/hives/{hive}/schedules/{id}/resume` | schedules.write | Resume schedule |

### SDK

- **Python:** `list_schedules`, `get_schedule`, `create_schedule`,
  `update_schedule`, `delete_schedule`, `pause_schedule`, `resume_schedule`
- **Shell:** `superpos_list_schedules`, `superpos_get_schedule`,
  `superpos_create_schedule`, `superpos_delete_schedule`,
  `superpos_pause_schedule`, `superpos_resume_schedule`

## Tests

- `tests/Feature/TaskScheduleApiTest.php` — API CRUD, auth, permissions,
  validation, scope isolation, activity logging, envelope compliance
- `tests/Feature/TaskScheduleDispatchTest.php` — dispatch logic, trigger
  types, overlap policies, expiry, idempotency, task template fidelity,
  artisan command

## Activity Log Actions

- `schedule.created`, `schedule.updated`, `schedule.deleted`
- `schedule.paused`, `schedule.resumed`
- `schedule.dispatched`, `schedule.expired`
- `schedule.skipped_overlap`, `schedule.cancelled_previous`
