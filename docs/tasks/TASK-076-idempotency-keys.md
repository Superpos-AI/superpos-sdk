# TASK-076: Idempotency Keys (Model + Dedup)

**Status:** In Progress
**Depends On:** 008 (Task model)
**Branch:** `task/076-idempotency-keys`

## Requirements

Implement platform-level idempotency key support for task creation, preventing
duplicate task creation when agents or external systems submit the same request
multiple times.

### Functional Requirements

1. **Idempotency key storage**: Persist `idempotency_key → task_id` mapping in
   a dedicated `task_idempotency` table, scoped to `(superpos_id, hive_id)`.
2. **Dedup on task creation**: When `idempotency_key` is provided:
   - If existing task is `completed` → return existing task (HTTP 200, not 201)
   - If existing task is `pending`/`in_progress` → return existing task (HTTP 200)
   - If existing task is `failed`/`dead_letter` → allow new task (retry semantics)
   - If no existing key → create new task normally
3. **Key expiry**: Keys expire after configurable TTL (default 24h). Scheduler
   job cleans up expired entries.
4. **Tenant isolation**: Keys are scoped to `(superpos_id, hive_id)` — no
   cross-tenant or cross-hive collisions.
5. **Fail-closed**: If dedup lookup fails, reject the request rather than
   silently creating a duplicate.

### API Contract

Request field: `idempotency_key` (top-level, string, max 255 chars)

Response includes `meta.idempotent: true` when returning an existing task.

### Database Schema

```sql
CREATE TABLE task_idempotency (
    idempotency_key VARCHAR(255) NOT NULL,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    task_id         VARCHAR(26) NOT NULL REFERENCES tasks(id),
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (superpos_id, hive_id, idempotency_key)
);

CREATE INDEX idx_idempotency_expires ON task_idempotency (expires_at);
```

## Implementation Plan

1. Migration: `create_task_idempotency_table`
2. Model: `TaskIdempotency` with `BelongsToHive`, `HasUlid` (or composite PK)
3. Service: `IdempotencyService` — check/store/cleanup logic
4. Update `CreateTaskRequest` — validate `idempotency_key` field
5. Update `TaskController::store` — dedup before creation
6. Console command: `apiary:cleanup-idempotency-keys`
7. Register cleanup in scheduler
8. Config: `apiary.task.idempotency_ttl` (default 86400)

## Test Plan

1. First request with key → creates task (201)
2. Second request with same key, task pending → returns existing (200, meta.idempotent)
3. Second request with same key, task completed → returns existing (200)
4. Second request with same key, task failed → creates new task (201)
5. Second request with same key, task dead_letter → creates new task (201)
6. Different hives, same key → creates separate tasks (tenant isolation)
7. Different apiaries, same key → creates separate tasks
8. Key longer than 255 chars → validation error (422)
9. Expired key → allows new task creation
10. Cleanup command removes expired entries
11. Request without idempotency_key → normal creation (backward compatible)

## Definition of Done

- [ ] Migration created and runs cleanly
- [ ] Model follows codebase conventions
- [ ] Dedup logic integrated into task creation flow
- [ ] All test cases pass
- [ ] PSR-12 compliant
- [ ] Activity logging on idempotent returns
- [ ] Scheduler cleanup job registered
