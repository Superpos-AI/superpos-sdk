# ActivityLogger Service

The `ActivityLogger` service provides a fluent, immutable builder for creating
[activity log](./activity-log.md) entries. Instead of assembling raw
`ActivityLog::create()` calls, use the logger to bind context step-by-step with
full validation at every stage.

```php
app(ActivityLogger::class)
    ->byAgent($agent)
    ->onTask($task)
    ->log('task.claimed', ['previous_status' => 'pending']);
```

## Why Use the Logger

- **Auto-resolution** — passing a model instance (e.g. `Agent`) automatically
  populates `superpos_id` and `hive_id` from the model's relationships.
- **Conflict detection** — mismatched context (an agent from one hive, a task
  from another) is caught immediately with a clear `LogicException`.
- **Immutability** — every setter returns a new instance, so a base logger can
  be reused safely across multiple calls without cross-contamination.
- **Lazy string-ID binding** — when only a string ID is available, the logger
  defers database resolution until a later call provides enough context to
  validate. This avoids unnecessary queries in fire-and-forget paths.

## Fluent API Reference

### Construction

```php
// From the container (recommended — fresh instance each time)
$logger = app(ActivityLogger::class);

// With pre-set context (rare — mostly useful in tests)
$logger = new ActivityLogger(
    apiaryId: $apiaryId,
    hiveId:   $hiveId,
    agentId:  $agentId,
    taskId:   $taskId,
);
```

The container does **not** register `ActivityLogger` as a singleton. Each
`app(ActivityLogger::class)` call returns a fresh, empty instance.

### Context Setters

Every setter returns a **new** `ActivityLogger` instance (clone). The original
is never modified.

| Method | Accepts | Sets | Auto-resolves |
|--------|---------|------|---------------|
| `forApiary($apiary)` | `string\|Superpos` | `superpos_id` | — |
| `forHive($hive)` | `string\|Hive` | `hive_id` | `superpos_id` (from model) |
| `byAgent($agent)` | `string\|Agent` | `agent_id` | `superpos_id`, `hive_id` (from model) |
| `onTask($task)` | `string\|Task` | `task_id` | `superpos_id`, `hive_id` (from model) |

### Terminal Method

```php
$entry = $logger->log(string $action, array $details = []): ActivityLog;
```

Calls `ActivityLog::create()` with the accumulated context and returns the
persisted model instance.

## Context Binding Rules

### Auto-Resolution from Model Instances

When you pass a model instance to `byAgent()`, `onTask()`, or `forHive()`, the
logger reads the model's `superpos_id` and `hive_id` properties and fills in any
context that hasn't been set yet:

```php
$logger = app(ActivityLogger::class)
    ->byAgent($agent);
// superpos_id = $agent->superpos_id  (auto-set)
// hive_id   = $agent->hive_id    (auto-set)
// agent_id  = $agent->id

$logger = app(ActivityLogger::class)
    ->forHive($hive);
// superpos_id = $hive->superpos_id   (auto-set)
// hive_id   = $hive->id
```

Auto-resolution uses the `??=` operator — it never overwrites a value that was
already bound.

### String IDs — Lazy Binding

When you pass a plain string ID, the logger stores it without hitting the
database:

```php
$logger = app(ActivityLogger::class)
    ->byAgent('01HWXYZ...');
// agent_id = '01HWXYZ...'
// superpos_id = null  (not resolved)
// hive_id   = null  (not resolved)
```

The database lookup is deferred until a subsequent call provides enough context
to validate. For example:

```php
$logger = app(ActivityLogger::class)
    ->byAgent('01HWXYZ...')    // string — stored, no DB lookup
    ->forApiary($apiaryModel); // now resolves the agent to validate it
                               // belongs to this apiary
```

If no further context is added, the string ID is passed through to
`ActivityLog::create()` as-is and validated by the model's `creating` hook and
the database's composite foreign keys.

### Ordering Invariants

The setters may be called in **any order**. The logger validates context
consistency regardless of call sequence:

```php
// All equivalent — same validation, same result:
->forApiary($apiary)->forHive($hive)->byAgent($agent)->onTask($task)
->onTask($task)->byAgent($agent)->forHive($hive)->forApiary($apiary)
->byAgent($agent)->onTask($task)->log('action')
```

The only constraint is logical consistency — every bound entity must belong to
the same apiary and hive.

### Immutability and Reuse

Each setter clones the instance before modifying it:

```php
$base = app(ActivityLogger::class)->forApiary($apiary)->forHive($hive);

// Two independent entries from the same base:
$base->byAgent($agentA)->log('agent.heartbeat');
$base->byAgent($agentB)->log('agent.heartbeat');

// $base is unchanged — agentId is still null
```

This pattern is safe for building "scoped loggers" that are reused across a
request lifecycle or within a service class.

## Validation and Safety Model

### Mismatch Guards

Every setter validates that the new value is consistent with previously bound
context. If a conflict is detected, a `LogicException` is thrown immediately —
before any database write.

```php
// LogicException: cannot change apiary context
->forApiary($apiaryA)->forApiary($apiaryB)

// LogicException: agent belongs to a different hive
->forHive($hiveA)->byAgent($agentFromHiveB)

// LogicException: task's apiary doesn't match bound agent's apiary
->byAgent($agentInApiaryA)->onTask($taskInApiaryB)
```

**Same-value rebinding is allowed.** Calling `->forApiary($a)->forApiary($a)`
does not throw — the guard only fires when the new value differs from the
existing one.

### Cross-Entity Validation

When an agent or task is bound as a model instance and the other is already
bound as a string ID, the logger resolves the string-ID entity from the
database to validate that both belong to the same apiary and hive:

```php
// String task bound first, then model agent:
->onTask('01TASK...')         // string — stored without lookup
->byAgent($agentModel)       // resolves '01TASK...' to validate
                              // its apiary/hive match the agent
```

Resolution uses `::withoutGlobalScopes()->find()` to bypass Cloud-mode hive
filtering and ensure the lookup succeeds regardless of the caller's current
scope.

### Three-Layer Immutability

Even if a misconfigured logger somehow produces an entry, the
[activity log immutability model](./activity-log.md#immutability) prevents
after-the-fact modification:

1. **Eloquent model events** — block `save()` on existing rows
2. **Custom query builder** — block mass `update()` calls
3. **Database trigger** — block raw SQL `UPDATE` statements

The logger adds a **fourth** layer: pre-creation validation that catches
mismatches before the entry is written.

## Cloud vs CE Behavior

| Behavior | Community Edition | Cloud Edition |
|----------|-------------------|---------------|
| `forApiary()` with no argument | Uses default apiary from config | Resolved from tenant context |
| Global scopes during resolution | No filtering — all entities visible | Bypassed via `withoutGlobalScopes()` |
| String-ID DB lookups | Always find the entity (single tenant) | Use `withoutGlobalScopes()` to bypass tenant filter |
| `superpos_id` on `log()` | Typically the CE default ULID | Resolved from context or explicit binding |

In CE mode, the single-apiary/single-hive model means `forApiary()` and
`forHive()` are often unnecessary — `byAgent()` or `onTask()` alone provides
all the context needed. The logger still validates consistency, so passing an
incorrect apiary will throw even in CE mode.

## Recommended Call Patterns

### Agent claiming a task

```php
app(ActivityLogger::class)
    ->byAgent($agent)
    ->onTask($task)
    ->log('task.claimed');
```

Both `superpos_id` and `hive_id` are auto-resolved from whichever model is
passed first.

### Agent registration (no task)

```php
app(ActivityLogger::class)
    ->byAgent($agent)
    ->log('agent.registered', ['capabilities' => $agent->capabilities]);
```

### Apiary-level event (no hive)

```php
app(ActivityLogger::class)
    ->forApiary($apiary)
    ->log('apiary.settings_updated', ['changed' => ['name', 'plan']]);
```

### Hive-level event (no agent, no task)

```php
app(ActivityLogger::class)
    ->forHive($hive)
    ->log('hive.policy_updated', ['policy_id' => $policyId]);
```

### Reusable base in a service class

```php
class TaskRouter
{
    private ActivityLogger $logger;

    public function __construct(ActivityLogger $logger)
    {
        // Inject via constructor — Laravel auto-resolves a fresh instance
        $this->logger = $logger;
    }

    public function routeTask(Task $task, Agent $agent): void
    {
        $scoped = $this->logger->forHive($task->hive);

        $scoped->onTask($task)->log('task.routing_started');

        // ... routing logic ...

        $scoped->onTask($task)->byAgent($agent)->log('task.routed');
    }
}
```

### Queue job with explicit apiary context

```php
// In a queued job where no tenant context is active:
app(ActivityLogger::class)
    ->forApiary($this->apiaryId)
    ->forHive($this->hiveId)
    ->log('job.completed', ['job_class' => static::class]);
```

## Common Pitfalls

### Forgetting `superpos_id` in queue jobs

Outside of an HTTP request, there is no ambient tenant context. If you call
`->log()` without binding an apiary (and without a model that provides one),
the entry will be created with `superpos_id = null`, which fails the `NOT NULL`
database constraint.

**Fix:** Always bind context explicitly in queue jobs:

```php
->forApiary($this->apiaryId)->log('job.finished');
```

### Assuming setters mutate in place

The fluent API clones on every call. This code logs **without** the agent:

```php
$logger = app(ActivityLogger::class)->forHive($hive);
$logger->byAgent($agent);   // returns new instance — discarded!
$logger->log('task.claimed'); // agent_id is null
```

**Fix:** Chain calls or capture the return value:

```php
$logger = app(ActivityLogger::class)
    ->forHive($hive)
    ->byAgent($agent);
$logger->log('task.claimed');
```

### Mixing entities from different apiaries or hives

```php
// Throws LogicException:
app(ActivityLogger::class)
    ->byAgent($agentInHiveA)
    ->onTask($taskInHiveB)
    ->log('task.claimed');
```

The logger will not silently accept cross-hive or cross-apiary mismatches.
If you need to log a cross-hive event, use the apiary-scoped pattern (no hive
binding) or log separate entries for each side.

### String IDs bypass validation when no context exists

```php
$logger = app(ActivityLogger::class)
    ->byAgent('NONEXISTENT_ID')
    ->log('agent.heartbeat');
```

This will **not** throw at the logger level — the string ID is passed through
and validated later by the model's `creating` hook and database constraints. If
the ID is invalid, the error surfaces at `create()` time, not at `byAgent()`
time.

**Why:** Avoiding a database round-trip for every string-ID binding keeps the
logger lightweight for high-throughput paths. The database constraints provide
the authoritative check.

### Calling `forApiary()` after model-based `byAgent()`

```php
app(ActivityLogger::class)
    ->byAgent($agent)          // auto-sets superpos_id from agent
    ->forApiary($otherApiary)  // throws — apiary already bound
    ->log('action');
```

Model-based setters auto-populate context eagerly. If you need to override the
apiary, call `forApiary()` first:

```php
app(ActivityLogger::class)
    ->forApiary($apiary)
    ->byAgent($agent)   // validates agent matches, doesn't override
    ->log('action');
```

## Testing Notes

### Test Infrastructure

The full test suite is in `tests/Feature/ActivityLoggerServiceTest.php`
(~1400 lines). Tests use SQLite via Laravel's `RefreshDatabase` trait for
isolation.

### What's Covered

- **Container resolution** — each `app()` call returns a fresh instance
- **Model and string-ID binding** for all four context setters
- **Auto-resolution** from model instances (apiary, hive propagation)
- **Conflict guards** — every mismatch combination throws `LogicException`
- **Cross-entity validation** — string-ID + model combinations
- **Immutability** — clones are independent; originals are unmodified
- **Fluent chaining** — full and partial chains produce correct entries
- **Database persistence** — entries are saved with correct column values
- **Reusable bases** — same logger instance reused for multiple entries

### Expected Failure Modes

| Scenario | Exception | When |
|----------|-----------|------|
| Superpos mismatch (explicit vs explicit) | `LogicException` | At the setter call |
| Superpos mismatch (explicit vs model-auto) | `LogicException` | At the setter call |
| Hive mismatch (bound agent/task vs new hive) | `LogicException` | At `forHive()` call |
| Agent apiary/hive mismatch | `LogicException` | At `byAgent()` call |
| Task apiary/hive mismatch | `LogicException` | At `onTask()` call |
| Cross-entity apiary/hive mismatch | `LogicException` | At the later setter call |
| Invalid string ID (nonexistent) | `RuntimeException` or DB error | At `log()` → `create()` |
| Missing `superpos_id` at `log()` | DB constraint violation | At `log()` → `create()` |
| Updating a created entry | `RuntimeException` | On `save()` / `update()` |

### Running the Tests

```bash
# Full suite
php artisan test --filter=ActivityLoggerServiceTest

# Single test
php artisan test --filter=ActivityLoggerServiceTest::test_log_with_full_chain
```

### Writing Custom Tests

When testing code that uses the logger, assert against the `activity_log`
table:

```php
$this->assertDatabaseHas('activity_log', [
    'action'   => 'task.claimed',
    'agent_id' => $agent->id,
    'task_id'  => $task->id,
    'hive_id'  => $hive->id,
]);
```

To test that a mismatch is caught:

```php
$this->expectException(\LogicException::class);

app(ActivityLogger::class)
    ->byAgent($agentInHiveA)
    ->onTask($taskInHiveB)
    ->log('task.claimed');
```

## Related Documentation

- [Activity Log (data model)](./activity-log.md) — schema, immutability,
  scoping, query scopes, and integrity constraints
- [Product Specification](/PRODUCT) — full platform architecture
