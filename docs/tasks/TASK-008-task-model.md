# TASK-008 — Task Migration + Model

| Field       | Value                                    |
|-------------|------------------------------------------|
| **ID**      | 008                                      |
| **Title**   | Task migration + model                   |
| **Status**  | done                                     |
| **Depends** | 005 (migrations), 006 (Superpos/Hive models) |
| **Branch**  | `task/008-task-model`                    |

---

## Objective

Create the `tasks` database table and the corresponding Eloquent model.
Tasks are the core unit of work in Superpos — agents poll for pending tasks,
claim them atomically, report progress, and complete or fail them. Tasks
are hive-scoped and support cross-hive creation (tracked via `source_hive_id`).

## Schema

### `tasks` table

| Column              | Type         | Constraints                          |
|---------------------|--------------|--------------------------------------|
| id                  | CHAR(26)     | PRIMARY KEY (ULID)                   |
| superpos_id           | CHAR(26)     | FK → apiaries, NOT NULL              |
| hive_id             | CHAR(26)     | FK → hives, NOT NULL                 |
| source_hive_id      | CHAR(26)     | FK → hives, NULLABLE (cross-hive)    |
| type                | VARCHAR(100) | NOT NULL                             |
| source_agent_id     | CHAR(26)     | FK → agents, NULLABLE                |
| target_agent_id     | CHAR(26)     | FK → agents, NULLABLE                |
| target_capability   | VARCHAR(100) | NULLABLE                             |
| claimed_by          | CHAR(26)     | FK → agents, NULLABLE                |
| priority            | SMALLINT     | DEFAULT 2                            |
| status              | VARCHAR(20)  | DEFAULT 'pending'                    |
| payload             | JSONB        | DEFAULT '{}'                         |
| result              | JSONB        | NULLABLE                             |
| progress            | SMALLINT     | DEFAULT 0                            |
| status_message      | TEXT         | NULLABLE                             |
| timeout_seconds     | INTEGER      | DEFAULT from config                  |
| retry_count         | SMALLINT     | DEFAULT 0                            |
| max_retries         | SMALLINT     | DEFAULT from config                  |
| parent_task_id      | CHAR(26)     | FK → tasks (self-ref), NULLABLE      |
| context_refs        | JSONB        | DEFAULT '[]'                         |
| created_at          | TIMESTAMP    |                                      |
| claimed_at          | TIMESTAMP    | NULLABLE                             |
| completed_at        | TIMESTAMP    | NULLABLE                             |

Indexes:
- Polling: `(hive_id, status, priority, target_capability, created_at) WHERE status = 'pending'`
- Agent lookup: `(claimed_by, status)`
- Cross-hive: `(source_hive_id) WHERE source_hive_id IS NOT NULL`

## Model

### `App\Models\Task`

- Traits: `HasFactory`, `HasUlid`, `BelongsToHive`
- Fillable: superpos_id, hive_id, source_hive_id, type, source_agent_id,
  target_agent_id, target_capability, claimed_by, priority, status,
  payload, result, progress, status_message, timeout_seconds, retry_count,
  max_retries, parent_task_id, context_refs
- Casts: payload → array, result → array, context_refs → array,
  last_heartbeat → datetime, claimed_at → datetime, completed_at → datetime,
  priority → integer, progress → integer, timeout_seconds → integer,
  retry_count → integer, max_retries → integer
- Relationships:
  - `hive()` — via BelongsToHive trait
  - `apiary()` — via BelongsToHive trait
  - `sourceHive()` — BelongsTo → Hive (source_hive_id)
  - `sourceAgent()` — BelongsTo → Agent (source_agent_id)
  - `targetAgent()` — BelongsTo → Agent (target_agent_id)
  - `claimedByAgent()` — BelongsTo → Agent (claimed_by)
  - `parentTask()` — BelongsTo → Task (parent_task_id)
  - `subtasks()` — HasMany → Task (parent_task_id)
- Status helpers:
  - `isPending(): bool`
  - `isInProgress(): bool`
  - `isCompleted(): bool`
  - `isFailed(): bool`
  - `isCancelled(): bool`
  - `isCrossHive(): bool`
- Scopes:
  - `scopePending(Builder $query)`
  - `scopeInProgress(Builder $query)`

## Tests

- Task ULID generation and key type
- Fillable fields
- Casts (payload, result, context_refs, timestamps, integers)
- Default values (status, priority, progress, retry_count)
- BelongsToHive auto-scoping (CE mode)
- Relationships: task → hive, task → apiary, task → agents, task → parent/subtasks
- Status helpers
- Cross-hive indicator (source_hive_id)
- Cascade considerations (hive deletion)
- Hive has tasks relationship
- Partial index coverage queries

## Acceptance Criteria

- [ ] Migration creates `tasks` table with all columns and indexes
- [ ] Task model uses HasUlid + BelongsToHive traits
- [ ] All relationships defined and working
- [ ] Status helper methods
- [ ] All tests pass
- [ ] No regressions in existing test suite
