# TASK-066: Cross-Hive Task Controller

## Status
In Progress

## Depends On
- TASK-008 (Task migration + model) ✅
- TASK-065 (Cross-hive permission middleware) ✅

## Summary

Add a dedicated `CrossHiveTaskController` with endpoints for listing,
showing, and cancelling cross-hive tasks. The existing `TaskController`
handles hive-scoped CRUD (create/poll/claim/progress/complete/fail) with
cross-hive support, but agents have no way to:

- List outbound cross-hive tasks they created in other hives
- List inbound cross-hive tasks arriving in their home hive
- Retrieve a specific cross-hive task by ID
- Cancel a pending cross-hive task they created

These operations span multiple hives and belong in a dedicated controller
under `/api/v1/cross-hive/tasks`.

## Requirements

1. **Index** `GET /api/v1/cross-hive/tasks` — list cross-hive tasks
   - `direction` filter: `outbound` (default) or `inbound`
   - Outbound: tasks where `source_agent_id` = agent AND `source_hive_id` IS NOT NULL
   - Inbound: tasks where `hive_id` = agent's hive AND `source_hive_id` IS NOT NULL
   - Optional filters: `status`, `type`, `target_hive_id` (outbound), `source_hive_id` (inbound)
   - Paginated (default 20, max 100)
   - Ordered by `created_at desc`
   - Tenant-isolated by `superpos_id`

2. **Show** `GET /api/v1/cross-hive/tasks/{task}` — get a cross-hive task
   - Must be a cross-hive task (`source_hive_id` IS NOT NULL)
   - Agent must belong to same apiary
   - Agent must be source agent OR have cross-hive access to task's hive
   - 404 for non-cross-hive tasks or tasks outside apiary

3. **Cancel** `PATCH /api/v1/cross-hive/tasks/{task}/cancel` — cancel a pending cross-hive task
   - Only the source agent (creator) can cancel
   - Task must be pending
   - Sets status to `cancelled`, records `completed_at`
   - Activity logged
   - Broadcasts TaskStatusChanged event

4. **Fail-closed behavior** — all endpoints deny by default; explicit
   permission + apiary match required.

5. **Activity logging** — all state changes (cancel) logged with
   `cross_hive: true` flag and provenance details.

## Design Decisions

- Controller lives at `app/Http/Controllers/Api/CrossHiveTaskController.php`
- Routes under `/api/v1/cross-hive/tasks` (not hive-scoped — these span hives)
- Requires `auth:sanctum-agent` + permission checks
- Reuses `formatTask()` pattern from `TaskController`
- No new migrations — uses existing `tasks` table with `source_hive_id`
- Cross-hive access verified via `CrossHivePermissionService` for show
- For index: outbound shows agent's own tasks, inbound shows tasks in agent's hive

## Files

| File | Action |
|------|--------|
| `app/Http/Controllers/Api/CrossHiveTaskController.php` | Create |
| `app/Http/Requests/ListCrossHiveTasksRequest.php` | Create |
| `routes/api.php` | Edit |
| `tests/Feature/CrossHiveTaskControllerTest.php` | Create |
| `docs/tasks/TASK-066-cross-hive-task-controller.md` | Create |

## Test Plan

- Index outbound: returns only cross-hive tasks created by agent
- Index inbound: returns only cross-hive tasks arriving in agent's hive
- Index with status filter
- Index with type filter
- Index pagination
- Index excludes same-hive tasks (source_hive_id is null)
- Index cross-apiary isolation (different apiary tasks never visible)
- Show: returns cross-hive task details
- Show: 404 for non-cross-hive task
- Show: 404 for task in different apiary
- Show: accessible by source agent
- Show: accessible by agent with cross-hive permission to task's hive
- Show: 403 for agent without access
- Cancel: successfully cancels pending cross-hive task
- Cancel: 403 if not source agent
- Cancel: 409 if task not pending
- Cancel: 404 for non-cross-hive task
- Cancel: activity logged
- Cancel: broadcasts TaskStatusChanged
- Auth: 401 without token
- Auth: 403 without required permission
