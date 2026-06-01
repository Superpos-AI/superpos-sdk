# Task Progress, Completion & Failure

TASK-018 adds the execution-finalization APIs that agents use after claiming a task:

- report incremental progress
- mark successful completion
- mark failure with error payload

## Endpoints

### Progress

```http
PATCH /api/v1/hives/{hive}/tasks/{task}/progress
Authorization: Bearer <agent-token>
```

Body:
- `progress` (integer `0..100`, required)
- `status_message` (string, optional)

### Complete

```http
PATCH /api/v1/hives/{hive}/tasks/{task}/complete
Authorization: Bearer <agent-token>
```

Body:
- `result` (object/array, optional)
- `status_message` (string, optional)

### Fail

```http
PATCH /api/v1/hives/{hive}/tasks/{task}/fail
Authorization: Bearer <agent-token>
```

Body:
- `error` (object/array, optional)
- `status_message` (string, optional)

Required permission for all three:
- `tasks.update` (or admin/wildcard equivalent)

## State Machine Rules

Supported transitions:

```text
pending -> in_progress   (TASK-017 claim)
in_progress -> completed (complete endpoint)
in_progress -> failed    (fail endpoint)
```

Any transition from a non-`in_progress` task to progress/complete/fail returns **409 Conflict**.

## Ownership & Scope Safety

Before updates are accepted:

- task must belong to requested hive
- task must belong to same apiary as caller
- caller must have hive-level access (same hive or cross-hive permission)
- caller must be the claiming agent (`claimed_by`)

## Concurrency Safety

Progress/complete/fail updates are transaction-protected and resolve the task row with DB locking to prevent conflicting concurrent finalization writes.

This guarantees only one final state write wins under race conditions.

## Output Semantics

On completion:
- `status = completed`
- `progress = 100`
- `completed_at` set
- `result` optionally stored

On failure:
- `status = failed`
- `completed_at` set
- failure payload stored in `result`

## Activity Logging

TASK-018 emits:
- `task.progress`
- `task.completed`
- `task.failed`

All responses follow the standard API envelope `{ data, meta, errors }`.

## Related

- [Task Polling & Atomic Claiming](./task-polling-claiming.md)
