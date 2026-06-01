# TASK-011 — ActivityLogger Service

| Field       | Value                                    |
|-------------|------------------------------------------|
| **ID**      | 011                                      |
| **Title**   | ActivityLogger service                   |
| **Status**  | done                                     |
| **Depends** | 010 (ActivityLog model)                  |
| **Branch**  | `task/011-activity-logger-service`       |

---

## Objective

Create a service class that wraps `ActivityLog::create()` with an ergonomic,
fluent builder API. Per coding standards, "all state changes → activity_log"
and "service classes for business logic (thin controllers)". Controllers and
other services will inject `ActivityLogger` instead of calling the model
directly — this centralises context resolution, reduces boilerplate, and
provides a single point for future enhancements (queueing, batching, etc.).

## Design

### `App\Services\ActivityLogger`

An immutable fluent builder — each setter returns a **new instance** so callers
can safely reuse a base logger.

#### Constructor

```php
public function __construct(
    ?string $apiaryId = null,
    ?string $hiveId = null,
    ?string $agentId = null,
    ?string $taskId = null,
)
```

No constructor dependencies → auto-resolvable from Laravel's container.

#### Fluent Context Setters

Each accepts a string ID **or** the corresponding Eloquent model.  When a model
is passed, `superpos_id` and `hive_id` are auto-resolved from it if not already
set — eliminating the need for callers to manually thread IDs.

| Method                              | Sets         | Auto-resolves from model        |
|-------------------------------------|--------------|---------------------------------|
| `forApiary(string\|Superpos $apiary)` | `superpos_id`  | —                               |
| `forHive(string\|Hive $hive)`       | `hive_id`    | `superpos_id`                     |
| `byAgent(string\|Agent $agent)`     | `agent_id`   | `superpos_id`, `hive_id`          |
| `onTask(string\|Task $task)`        | `task_id`    | `superpos_id`, `hive_id`          |

All return `static` (new cloned instance).

#### Core Method

```php
public function log(string $action, array $details = []): ActivityLog
```

Creates and returns an `ActivityLog` entry.  `superpos_id` auto-assignment
is still handled by the `BelongsToApiary` trait when not explicitly set.

## Usage Examples

```php
// Inject via constructor
public function __construct(private ActivityLogger $logger) {}

// Task lifecycle
$this->logger->onTask($task)->byAgent($agent)->log('task.claimed');

// Agent lifecycle
$this->logger->byAgent($agent)->log('agent.registered', ['capabilities' => $caps]);

// Apiary-level (no hive)
$this->logger->forApiary($apiary)->log('apiary.settings_updated', ['changed' => $fields]);

// Reusable base
$hiveLogger = $this->logger->forHive($hive);
$hiveLogger->log('hive.created');
$hiveLogger->byAgent($agent)->log('agent.registered');
```

## Files

| File | Action |
|------|--------|
| `app/Services/ActivityLogger.php` | Create |
| `tests/Feature/ActivityLoggerServiceTest.php` | Create |

## Tests

- `log()` creates an ActivityLog entry with correct fields
- `forApiary()` sets apiary context (model and string)
- `forHive()` sets hive context and auto-resolves superpos_id from model
- `byAgent()` sets agent context and auto-resolves superpos_id + hive_id
- `onTask()` sets task context and auto-resolves superpos_id + hive_id
- Fluent chaining produces correct combined context
- String IDs work identically to model instances
- Immutability — original instance is not mutated by chaining
- Context auto-resolution does not overwrite explicitly set values
- Service is resolvable from the Laravel container
- Details array is passed through correctly (empty, populated, nested)
- Action string naming conventions (dot-separated) are stored correctly

## Acceptance Criteria

- [ ] `App\Services\ActivityLogger` class created
- [ ] Fluent builder API with immutable clone semantics
- [ ] Auto-resolves superpos_id/hive_id from model objects
- [ ] All tests pass
- [ ] No regressions in existing test suite
