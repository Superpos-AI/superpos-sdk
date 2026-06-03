# TASK-018: Task Progress, Completion & Failure

**Status:** done
**Branch:** `task/018-task-progress-completion`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/20
**Depends On:** TASK-017 (Task Polling & Atomic Claiming)
**Blocked By:** —

## Requirements

### Progress Endpoint: `PATCH /api/v1/hives/{hive}/tasks/{task}/progress`

Agents report incremental progress on tasks they have claimed.

**Request body:**
- `progress` (required, integer 0-100) — completion percentage
- `status_message` (optional, string max 1000) — human-readable status text

**Behavior:**
- Only the agent that claimed the task (`claimed_by`) may update it
- Task must be in `in_progress` status
- Updates `progress` and optionally `status_message`
- Returns the full task representation

**Permission:** `tasks.update` (or `admin:*`)

### Complete Endpoint: `PATCH /api/v1/hives/{hive}/tasks/{task}/complete`

Marks a claimed task as successfully completed.

**Request body:**
- `result` (optional, object/array) — task output data
- `status_message` (optional, string max 1000) — final status text

**Behavior:**
- Only the agent that claimed the task (`claimed_by`) may complete it
- Task must be in `in_progress` status
- Sets `status` to `completed`
- Sets `progress` to 100
- Sets `completed_at` to current timestamp
- Stores `result` and optional `status_message`
- Returns the full task representation

**Permission:** `tasks.update` (or `admin:*`)

### Fail Endpoint: `PATCH /api/v1/hives/{hive}/tasks/{task}/fail`

Marks a claimed task as failed.

**Request body:**
- `error` (optional, object/array) — error details stored in `result`
- `status_message` (optional, string max 1000) — error description

**Behavior:**
- Only the agent that claimed the task (`claimed_by`) may fail it
- Task must be in `in_progress` status
- Sets `status` to `failed`
- Sets `completed_at` to current timestamp
- Stores error details in `result` and optional `status_message`
- Returns the full task representation

**Permission:** `tasks.update` (or `admin:*`)

### State Machine

```
pending → in_progress (via claim)
in_progress → completed (via complete)
in_progress → failed (via fail)
```

Invalid transitions return 409 Conflict.

### Scope Safety

- Task must belong to the hive specified in the URL
- Task must belong to the agent's apiary
- Agent must be the one who claimed the task (claimed_by check)
- Cross-hive agents with proper permission can update tasks in other hives

### Activity Logging

- `task.progress` — logged on progress updates
- `task.completed` — logged on successful completion
- `task.failed` — logged on failure

### Envelope Compliance

All responses use `{ data, meta, errors }` envelope per TASK-003.

## Implementation Plan

### Files to Create/Modify

1. **`app/Http/Requests/UpdateTaskProgressRequest.php`** — Form Request for progress updates
2. **`app/Http/Requests/CompleteTaskRequest.php`** — Form Request for completion
3. **`app/Http/Requests/FailTaskRequest.php`** — Form Request for failure
4. **`app/Http/Controllers/Api/TaskController.php`** — Add `progress()`, `complete()`, `fail()` methods; update `formatTask()`
5. **`routes/api.php`** — Add progress, complete, fail routes
6. **`tests/Feature/TaskProgressCompletionTest.php`** — Comprehensive test suite

### Key Design Decisions

- Only the claiming agent can update/complete/fail a task (ownership enforcement)
- `completed_at` timestamp set on both completion and failure (represents finalization time)
- `progress` auto-set to 100 on completion
- `result` field stores both success results and error details
- Permission `tasks.update` is separate from `tasks.claim` for granularity

## Test Plan

1. Progress update succeeds for in_progress task by claiming agent
2. Progress update sets progress and status_message correctly
3. Progress update returns 409 for non-in_progress task (pending, completed, failed)
4. Progress update returns 403 when agent is not the claimer
5. Complete succeeds for in_progress task → status=completed, progress=100, completed_at set
6. Complete stores result data correctly
7. Complete returns 409 for non-in_progress task
8. Complete returns 403 when agent is not the claimer
9. Fail succeeds for in_progress task → status=failed, completed_at set
10. Fail stores error data in result field
11. Fail returns 409 for non-in_progress task
12. Fail returns 403 when agent is not the claimer
13. All endpoints return 404 for non-existent task
14. All endpoints return 404 for task in different hive
15. All endpoints return 403 for task in different apiary
16. Cross-hive agent can update tasks in other hives with permission
17. Activity log entries created for progress, complete, and fail
18. Envelope compliance on all responses (success and error)
19. Auth required (401) and permission required (403)
20. Form Request validation (progress range, field types)
