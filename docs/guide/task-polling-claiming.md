# Task Polling & Atomic Claiming

TASK-017 introduces the agent work-consumption loop:

1. Agents poll for claim-eligible tasks
2. Agents claim a single task atomically
3. Only one agent can win a race for the same task

This guide documents the polling/claiming contract, eligibility rules, and race-safety behavior.

## Endpoints

### Poll

```http
GET /api/v1/hives/{hive}/tasks/poll
Authorization: Bearer <agent-token>
```

Optional query params:
- `capability` — capability filter
- `limit` — result size (`1..20`)

Required permission:
- `tasks.claim` (or wildcard/admin equivalent)

### Claim

```http
PATCH /api/v1/hives/{hive}/tasks/{task}/claim
Authorization: Bearer <agent-token>
```

Required permission:
- `tasks.claim` (or wildcard/admin equivalent)

## Eligibility Rules

A task is pollable/claimable only when all checks pass:

- Task belongs to the requested hive
- Task belongs to the same apiary as the agent
- Agent has hive-level access (same hive or `tasks.cross_hive`)
- Task status is `pending`
- If `target_agent_id` is set, it must match the polling/claiming agent
- If `target_capability` is set, the agent must have that capability

When `?capability=...` is provided, the capability must be in the agent's own capability set; otherwise request is rejected (fail-closed).

## Atomic Claiming

Claim uses an atomic status transition (`pending -> in_progress`) guarded at DB level, so only the first successful claimant wins.

On success:
- `status = in_progress`
- `claimed_by = <agent_id>`
- `claimed_at = now()`

If another agent already claimed the task, response is `409 Conflict`.

## Response Envelope

All responses follow:

```json
{
  "data": {},
  "meta": {},
  "errors": null
}
```

Validation/auth failures use the same envelope with `errors` populated.

## Activity Logging

TASK-017 logs the following events:
- `task.polled`
- `task.claimed`
- `task.claim_failed`

This keeps queue visibility and race outcomes auditable.

## Related

- [Product Specification](../PRODUCT.md)
