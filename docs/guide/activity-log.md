# Activity Log

The Activity Log provides a tamper-resistant, append-only audit trail for every
state change in Superpos. Every agent action, task transition, hive event, and
administrative operation produces a log entry that cannot be modified or deleted
through application code.

## Data Model

### Schema

| Column       | Type              | Nullable | Description                                      |
|-------------|-------------------|----------|--------------------------------------------------|
| `id`        | `BIGSERIAL` (auto-increment) | No  | Sequential primary key                           |
| `superpos_id` | `CHAR(26)` (ULID) | No       | Owning apiary (tenant)                           |
| `hive_id`   | `CHAR(26)` (ULID) | Yes      | Associated hive; NULL for apiary-level events    |
| `agent_id`  | `CHAR(26)` (ULID) | Yes      | Acting agent; NULL for system/admin actions       |
| `task_id`   | `CHAR(26)` (ULID) | Yes      | Related task; NULL when not task-scoped           |
| `action`    | `VARCHAR(100)`     | No       | Machine-readable action identifier               |
| `details`   | `JSONB`            | No       | Structured metadata (defaults to `{}`)           |
| `created_at`| `TIMESTAMP`        | No       | Automatically set on insert                      |

::: info No `updated_at` column
Activity log entries are write-once. The model sets `UPDATED_AT = null`, so
Laravel never attempts to write an `updated_at` timestamp.
:::

### Primary Key Strategy

Unlike other Superpos models that use ULIDs, the activity log uses an
auto-incrementing `BIGSERIAL` primary key. This gives natural chronological
ordering without relying on timestamp precision — important for high-throughput
audit scenarios where multiple entries may share the same `created_at` value.

## Immutability

Activity log entries are **immutable after creation**. This is enforced at three
independent layers, providing defense-in-depth:

### Layer 1 — Eloquent Model Events

The `ActivityLog::updating()` hook throws a `RuntimeException` on any `save()`
call that would modify an existing row.

### Layer 2 — Custom Eloquent Builder

Mass-update queries like `ActivityLog::where(...)->update([...])` bypass model
events. A custom builder override intercepts these calls and raises the same
exception.

### Layer 3 — Database Trigger

A `BEFORE UPDATE` trigger on the `activity_log` table blocks modifications at
the storage layer. This catches raw SQL updates, maintenance scripts, and any
other path that bypasses the ORM entirely.

**Protected fields:** `id`, `superpos_id`, `hive_id`, `action`, `details`, `created_at`

::: tip FK-Cascade Exceptions
When an agent or task is deleted, the database cascade sets `agent_id` or
`task_id` to NULL. The trigger explicitly permits this FK-driven nullification
while blocking manual `UPDATE` statements that attempt the same change.
:::

## Tenant and Hive Scoping

### Multi-Tenant Isolation (Cloud Edition)

The `BelongsToApiary` trait applies a global scope in Cloud mode that
automatically filters all queries to the current tenant's `superpos_id`. This
means:

- All `ActivityLog` queries are tenant-scoped by default
- Creating an entry without a valid apiary context throws an exception
- Cross-tenant log access is impossible through normal model operations

### Hive Scoping

Hive scoping is **opt-in** for the activity log. Entries can be:

- **Hive-scoped** — `hive_id` is set; represents activity within a specific project
- **Apiary-scoped** — `hive_id` is NULL; represents org-level events (billing changes, team membership, etc.)

Use the `forHive()` scope to filter:

```php
ActivityLog::forHive($hiveId)->recent()->get();
```

### Cloud vs CE Behavior

| Behavior                         | Community Edition       | Cloud Edition                     |
|----------------------------------|------------------------|-----------------------------------|
| `superpos_id`                      | Always `'default'`     | Resolved from tenant context       |
| Global scope on queries          | No filtering           | Auto-filters to current apiary     |
| `superpos_id` on create            | Auto-set to `'default'`| Auto-set from tenant context       |
| Cross-tenant access              | N/A (single tenant)    | Blocked by global scope            |
| Composite FK validation          | Active                 | Active                             |

In CE mode, the `BelongsToApiary` trait resolves `superpos_id` to a constant
(`'default'`), so the scoping machinery has zero overhead.

## Relationships

```php
$entry->apiary;  // Always present — the owning Superpos
$entry->hive;    // Nullable — the associated Hive
$entry->agent;   // Nullable — the acting Agent
$entry->task;    // Nullable — the related Task
```

The `agent()` and `task()` relationships use `withoutGlobalScope('hive')` so
they resolve correctly even when the agent or task belongs to a different hive
than the caller's current hive context. This is essential for cross-hive
activity queries.

### Inverse Relationship

The `Hive` model exposes an `activityLog()` HasMany relationship:

```php
$hive->activityLog()->recent(30)->get();
```

## API-Facing Implications

### What Gets Logged

Every state change in Superpos produces an activity log entry. When building
agents or connectors, expect the following to be recorded automatically:

- **Task lifecycle** — creation, claiming, completion, failure, cancellation
- **Agent registration and heartbeats** — connects, disconnects, capability changes
- **Connector webhook processing** — inbound webhook receipt and routing decisions
- **Policy evaluations** — allow, deny, and approval-required outcomes
- **Administrative actions** — hive creation, permission changes, configuration updates

### Relation Resolution Expectations

When the API returns activity log entries, related entities (`hive`, `agent`,
`task`) may be `null` for two reasons:

1. **The reference was never set** — the event is apiary-scoped or not agent/task-related
2. **The referenced entity was deleted** — the FK cascade nullified the column

API consumers should handle both cases. The `superpos_id` is always present and
never nullified, so tenant context is always preserved.

### Writing Log Entries

Agents and connectors typically do not write activity log entries directly —
the platform's service layer handles this. If your integration does need to
create entries, use `ActivityLog::create()` and ensure:

- `action` follows the dot-separated naming convention (see [Action Naming Convention](#action-naming-convention))
- `details` contains only JSON-serializable data
- `superpos_id` is available in the current context (automatic in web requests, explicit in queue jobs)

## Query Scopes

| Scope                      | Usage                                             |
|---------------------------|---------------------------------------------------|
| `forApiary($apiaryId)`    | Filter by apiary (provided by `BelongsToApiary`)  |
| `forHive($hiveId)`        | Filter by hive                                     |
| `forAgent($agentId)`      | Filter by acting agent                             |
| `forTask($taskId)`        | Filter by related task                             |
| `action($action)`         | Filter by action string                            |
| `recent($minutes = 60)`   | Entries created within the last N minutes          |

Scopes are chainable:

```php
ActivityLog::forHive($hiveId)
    ->forAgent($agentId)
    ->action('task.claimed')
    ->recent(15)
    ->get();
```

## Integrity Constraints

### Composite Foreign Keys

The activity log uses **composite foreign keys** to guarantee that referenced
entities belong to the same apiary as the log entry. This prevents cross-tenant
data corruption at the database level.

| Constraint                                | References              | On Delete        |
|------------------------------------------|-------------------------|------------------|
| `(superpos_id)` → `apiaries(id)`          | Owning apiary           | CASCADE          |
| `(superpos_id, hive_id)` → `hives(superpos_id, id)` | Hive within apiary | CASCADE     |
| `(superpos_id, agent_id)` → `agents(superpos_id, id)` | Agent within apiary | SET NULL (agent_id only) |
| `(superpos_id, task_id)` → `tasks(superpos_id, id)` | Task within apiary | SET NULL (task_id only)  |

::: warning Partial SET NULL
On PostgreSQL 15+, deleting an agent or task nullifies **only** the
`agent_id`/`task_id` column while preserving `superpos_id`. This uses the
`ON DELETE SET NULL (column)` syntax. The log entry remains fully tenant-scoped
even after the referenced entity is removed.
:::

### Model-Level Validation

In addition to database constraints, the model validates on `creating` that any
provided `agent_id` or `task_id` belongs to the same apiary. This catches
mismatches early with a clear error message, before hitting a database constraint
violation.

### Index Strategy

| Index Name                | Columns                       | Use Case                                |
|--------------------------|-------------------------------|-----------------------------------------|
| `idx_activity_hive`      | `(hive_id, created_at)`      | Hive activity feed, sorted by time       |
| `idx_activity_apiary`    | `(superpos_id, created_at)`    | Org-wide activity feed, sorted by time   |
| `idx_activity_apiary_agent` | `(superpos_id, agent_id)`   | Agent activity lookup within tenant      |
| `idx_activity_apiary_task`  | `(superpos_id, task_id)`    | Task audit trail within tenant           |

All indexes are covering for their primary query pattern. The `created_at`
component in time-series indexes supports efficient `ORDER BY ... DESC` queries.

### JSONB `details` Column

The `details` column stores structured metadata as JSONB. It defaults to an
empty object (`{}`). The model casts it to a PHP array automatically.

**Recommended structure:**

```json
{
  "previous_status": "pending",
  "new_status": "claimed",
  "claimed_by": "01HWXYZ..."
}
```

There is no enforced schema for `details` — connectors and agents are free to
include any JSON-serializable data. Keep entries concise; the activity log is
not a replacement for domain-specific storage.

## Operational Notes

### PostgreSQL (Production)

- Composite FKs with partial `SET NULL` require PostgreSQL 15+
- The immutability trigger uses `pg_trigger_depth()` to distinguish FK cascades
  from direct updates
- JSONB column enables indexed queries on `details` if needed in the future
- `BIGSERIAL` primary key provides gap-free sequential ordering per-database

### SQLite (Testing)

SQLite is used in the test suite. Key behavioral differences:

- **No ALTER TABLE for FKs** — foreign keys for `agent_id` and `task_id` are
  declared inline during table creation (simple FKs, not composite)
- **No partial SET NULL** — uses standard `ON DELETE SET NULL` for the entire row
- **Trigger differences** — SQLite FK actions fire user triggers (unlike
  PostgreSQL), so the trigger uses `IS NOT NULL` guards instead of
  `pg_trigger_depth()` to allow cascades
- **Manual nullification** of `agent_id`/`task_id` is blocked at the model
  layer, not the trigger layer, on SQLite

::: warning Testing caveat
If you write raw SQL tests that bypass the Eloquent model, be aware that
SQLite's immutability trigger has slightly different semantics than
PostgreSQL's. Always test critical audit logic against PostgreSQL in CI.
:::

## Gotchas for Connector and Agent Developers

### You Cannot Update or Delete Log Entries

Any attempt to modify an activity log entry — whether through Eloquent, the
query builder, or raw SQL — will fail. Design your connector to treat log
writes as fire-and-forget.

```php
// This works:
ActivityLog::create([
    'hive_id'  => $hiveId,
    'agent_id' => $agentId,
    'action'   => 'connector.webhook_received',
    'details'  => ['source' => 'github', 'event' => 'push'],
]);

// This throws RuntimeException:
$entry->update(['action' => 'something_else']);

// This also throws RuntimeException:
ActivityLog::where('id', $entry->id)->update(['action' => 'something_else']);
```

### Always Provide `superpos_id` Context

In Cloud mode, `superpos_id` is auto-assigned from the current tenant context. If
your code runs outside a tenant context (e.g., a queue job or scheduled task),
you must explicitly set `superpos_id` or the creation will fail.

```php
// In a queue job without tenant context:
ActivityLog::create([
    'superpos_id' => $job->superpos_id,  // explicit
    'action'    => 'job.completed',
    'details'   => ['job_id' => $job->id],
]);
```

### Cross-Tenant References Are Rejected

You cannot create a log entry that references an agent or task from a different
apiary. The model validates this on create and throws a `RuntimeException`.

```php
// Throws: agent_id does not belong to the same apiary
ActivityLog::create([
    'superpos_id' => $apiaryA,
    'agent_id'  => $agentFromApiaryB,  // different tenant
    'action'    => 'agent.action',
]);
```

### Nullable References Are Intentional

`hive_id`, `agent_id`, and `task_id` are all nullable by design. Not every log
entry is scoped to a hive, triggered by an agent, or related to a task. Don't
treat NULL references as errors.

### FK Cascades Nullify, Not Delete

When an agent or task is deleted, the log entry survives — only the reference
column is set to NULL. When a hive or apiary is deleted, associated log entries
are cascade-deleted. Plan your data retention strategy accordingly.

### Action Naming Convention

Use dot-separated, lowercase action identifiers. The `action` column is
`VARCHAR(100)`.

```text
task.created
task.claimed
task.completed
agent.registered
agent.heartbeat
connector.webhook_received
hive.policy_evaluated
```

### Keep `details` Lean

The `details` JSONB column is for supplementary context, not bulk data storage.
Include identifiers, status transitions, and brief context — not full request
bodies or file contents.
