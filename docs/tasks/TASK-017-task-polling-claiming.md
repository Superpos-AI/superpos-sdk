# TASK-017: Task Polling & Atomic Claiming

**Status:** done
**Branch:** `task/017-task-polling-claiming`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/19
**Depends On:** TASK-016 (Task Creation API)
**Blocked By:** —

## Requirements

### Poll Endpoint: `GET /api/v1/hives/{hive}/tasks/poll`

Agents poll for available tasks in their hive. The endpoint returns pending
tasks the agent is eligible to claim, ordered by priority (lowest number =
highest priority) then creation time (FIFO within same priority).

**Query parameters:**
- `capability` (optional) — filter tasks matching `target_capability`
- `limit` (optional, default 5, max 20) — number of tasks to return

**Matching rules:**
1. Tasks with `target_agent_id` matching the polling agent are always included
2. Tasks with `target_capability` matching the agent's capabilities are included
3. Tasks with neither `target_agent_id` nor `target_capability` are open to all
4. Tasks targeted at a *different* agent are excluded
5. Tasks with a `target_capability` the agent lacks are excluded (unless the
   agent has `admin:*`)

**Permission:** `tasks.claim` (or `admin:*`)

### Claim Endpoint: `PATCH /api/v1/hives/{hive}/tasks/{task}/claim`

Atomically claims a pending task. Uses `UPDATE ... WHERE status='pending'
RETURNING *` to guarantee race safety — only one agent wins the claim.

**Behavior:**
- Sets `status` to `in_progress`
- Sets `claimed_by` to the agent's ID
- Sets `claimed_at` to current timestamp
- Returns the full task representation on success
- Returns 409 Conflict if the task is no longer pending

**Permission:** `tasks.claim` (or `admin:*`)

**Scope safety:**
- Task must belong to the agent's hive (or agent must have cross-hive access)
- Task must belong to the agent's apiary
- If `target_agent_id` is set and doesn't match, return 403

### Activity Logging

- `task.polled` — logged when an agent polls (with filter details)
- `task.claimed` — logged when an agent successfully claims a task
- `task.claim_failed` — logged when a claim attempt fails (409)

### Envelope Compliance

All responses use `{ data, meta, errors }` envelope per TASK-003.

## Implementation Plan

### Files to Create/Modify

1. **`app/Http/Requests/PollTasksRequest.php`** — Form Request for poll query params
2. **`app/Http/Controllers/Api/TaskController.php`** — Add `poll()` and `claim()` methods
3. **`routes/api.php`** — Add poll and claim routes
4. **`tests/Feature/TaskPollingClaimingTest.php`** — Comprehensive test suite

### Key Design Decisions

- Atomic claim uses raw `UPDATE ... WHERE RETURNING *` on PostgreSQL,
  falls back to `UPDATE + SELECT` with row locking on other drivers
- Poll does NOT auto-claim; agents inspect available tasks then explicitly claim
- Race condition protection: only the first `UPDATE` succeeds due to the
  `WHERE status='pending'` guard

## Test Plan

1. Poll returns pending tasks in correct priority/FIFO order
2. Poll filters by `target_agent_id` (agent-specific tasks)
3. Poll filters by `target_capability` (capability-matched tasks)
4. Poll excludes tasks targeted at other agents
5. Poll excludes tasks with capabilities the agent lacks
6. Poll returns open tasks (no target constraints)
7. Claim succeeds for a pending task → status becomes `in_progress`
8. Claim sets `claimed_by` and `claimed_at` correctly
9. Claim returns 409 when task is already claimed (race condition)
10. Claim returns 403 when task is targeted at a different agent
11. Claim returns 404 for non-existent task
12. Claim returns 403 for task in different apiary
13. Activity log entries created for poll, claim, and failed claim
14. Envelope compliance on all responses
15. Auth required (401) and permission required (403)
16. `limit` parameter respected on poll
