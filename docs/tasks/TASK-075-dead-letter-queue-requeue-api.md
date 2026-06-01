# TASK-075: Dead Letter Queue & Requeue API

**Status:** done
**Branch:** `task/075-dead-letter-requeue-api`
**PR:** [#115](https://github.com/Superpos-AI/superpos-app/pull/115)
**Depends On:** TASK-074
**Blocked By:** —

## Requirements

### 1. List Dead Letter Tasks API
Add a hive-scoped endpoint to list and filter dead-letter tasks:
```
GET /api/v1/hives/{hive}/tasks/dead-letter
```
Query parameters:
- `type` — filter by task type
- `target_agent_id` — filter by target agent
- `target_capability` — filter by capability
- `page` / `per_page` — pagination (default 15, max 100)

Response: paginated list in standard `{ data, meta, errors }` envelope.

### 2. Requeue Dead Letter Task API
Add a hive-scoped endpoint to requeue a dead-letter task:
```
POST /api/v1/hives/{hive}/tasks/{task}/requeue
```
Body (all optional):
- `reset_retries` (bool, default true) — reset retry_count to 0
- `failure_policy` (object) — override failure policy for the requeued task
- `priority` (integer, 0–4) — optionally change priority

Behavior:
- Only tasks with `status = 'dead_letter'` can be requeued
- Transitions task to `pending` status
- Clears `completed_at`, `claimed_at`, `claimed_by`, `retry_after`,
  `last_progress_at`, `result`, `progress`, `status_message`
- Optionally resets `retry_count` to 0 (default)
- Optionally merges new `failure_policy`
- Removes internal flags (`_task_timeout_notified`, `_progress_timeout_notified`)

### 3. Authorization & Isolation
- List: requires `tasks.read` permission
- Requeue: requires `tasks.update` permission
- Both use hive + cross-hive middleware for tenant isolation
- Apiary-level ownership check on requeue
- Row-level locking on requeue to prevent race conditions

### 4. Activity Logging
- `task.requeued` action logged on every successful requeue with details
  including reset_retries, policy changes, and the acting agent

### 5. Show Dead Letter Task API
Add a hive-scoped endpoint to show a single dead-letter task:
```
GET /api/v1/hives/{hive}/tasks/{task}/dead-letter
```
Returns full task details for a dead-letter task. Returns 404 if the task
is not in dead_letter status.

## Implementation Plan

### Files to Create
1. **`app/Http/Controllers/Api/DeadLetterController.php`** — API controller
2. **`app/Http/Requests/RequeueTaskRequest.php`** — Form request validation
3. **`app/Services/DeadLetterService.php`** — Business logic
4. **`tests/Feature/DeadLetterQueueTest.php`** — Comprehensive tests

### Files to Modify
1. **`routes/api.php`** — Add dead letter routes
2. **`app/Models/Task.php`** — Add dead_letter_reason accessor if needed

## Test Plan

1. List dead letter tasks returns only dead_letter status tasks
2. List dead letter tasks respects hive scoping
3. List dead letter tasks supports type filter
4. List dead letter tasks supports target_agent_id filter
5. List dead letter tasks supports target_capability filter
6. List dead letter tasks paginates results
7. List dead letter tasks returns empty for no dead-letter tasks
8. List dead letter tasks requires tasks.read permission
9. Requeue transitions dead_letter task to pending
10. Requeue resets retry_count when reset_retries=true (default)
11. Requeue preserves retry_count when reset_retries=false
12. Requeue clears completed_at, claimed_at, claimed_by, result, progress
13. Requeue clears last_progress_at and retry_after
14. Requeue clears internal flags from failure_policy
15. Requeue merges new failure_policy when provided
16. Requeue rejects non-dead-letter tasks (409 conflict)
17. Requeue rejects tasks from different apiaries (403 forbidden)
18. Requeue requires tasks.update permission
19. Requeue logs task.requeued activity
20. Requeue broadcasts TaskStatusChanged event
21. Requeue validates failure_policy structure
22. Requeue validates priority range
23. Show dead letter returns task details
24. Show dead letter rejects non-dead-letter tasks (404)
25. Cross-hive isolation prevents accessing other hive's dead letters
26. Requeue with priority override updates task priority

## Acceptance Criteria

- [ ] GET dead-letter endpoint lists/filters dead-letter tasks with pagination
- [ ] POST requeue endpoint transitions dead_letter → pending safely
- [ ] Requeue resets retry fields and clears stale state
- [ ] Failure policy override on requeue validates and merges correctly
- [ ] Internal flags stripped from failure_policy on requeue
- [ ] Activity logging on requeue with full details
- [ ] Hive scoping and apiary isolation enforced
- [ ] Permission checks (tasks.read, tasks.update) enforced
- [ ] Standard API envelope on all responses
- [ ] All tests pass
- [ ] PSR-12 compliant
