# TASK-010 — Activity Log Migration + Model

| Field       | Value                                    |
|-------------|------------------------------------------|
| **ID**      | 010                                      |
| **Title**   | Activity log migration + model           |
| **Status**  | done                                     |
| **Depends** | 005 (migrations), 006 (Superpos/Hive models) |
| **Branch**  | `task/010-activity-log-model`            |

---

## Objective

Create the `activity_log` database table and the corresponding Eloquent model.
Activity logging captures every state change in Superpos for auditability.
Every agent action, task state transition, and system event is recorded.
Entries are hive-scoped by default but support apiary-level actions
(where hive_id is null). This is a cross-cutting foundation — per coding
standards, "all state changes → activity_log".

## Schema

### `activity_log` table

| Column     | Type         | Constraints                          |
|------------|--------------|--------------------------------------|
| id         | BIGSERIAL    | PRIMARY KEY (auto-increment)         |
| superpos_id  | CHAR(26)     | FK → apiaries, NOT NULL              |
| hive_id    | CHAR(26)     | FK → hives, NULLABLE                 |
| agent_id   | CHAR(26)     | FK → agents, NULLABLE                |
| task_id    | CHAR(26)     | FK → tasks, NULLABLE                 |
| action     | VARCHAR(100) | NOT NULL                             |
| details    | JSONB        | DEFAULT '{}'                         |
| created_at | TIMESTAMP    | DEFAULT NOW()                        |

Indexes:
- Hive timeline: `(hive_id, created_at DESC)`
- Superpos timeline: `(superpos_id, created_at DESC)`

## Model

### `App\Models\ActivityLog`

- Traits: `HasFactory`
- No HasUlid (uses auto-incrementing BIGSERIAL)
- No BelongsToHive (hive_id is nullable; manual scoping)
- Table: `activity_log`
- Timestamps: only `created_at` (no `updated_at` — log entries are immutable)
- Fillable: superpos_id, hive_id, agent_id, task_id, action, details
- Casts: details → array, created_at → datetime
- Relationships:
  - `apiary()` — BelongsTo → Superpos
  - `hive()` — BelongsTo → Hive (nullable)
  - `agent()` — BelongsTo → Agent (nullable)
  - `task()` — BelongsTo → Task (nullable)
- Scopes:
  - `scopeForApiary(Builder $query, string $apiaryId)`
  - `scopeForHive(Builder $query, string $hiveId)`
  - `scopeForAgent(Builder $query, string $agentId)`
  - `scopeForTask(Builder $query, string $taskId)`
  - `scopeAction(Builder $query, string $action)` — filter by action
  - `scopeRecent(Builder $query, int $minutes = 60)` — created within N minutes

## Hive Relationship

Add `activityLog(): HasMany` to the Hive model.

## Tests

- Auto-increment primary key (not ULID)
- Fillable fields
- Casts (details → array)
- Immutable: only created_at, no updated_at
- Relationships: log → apiary, log → hive, log → agent, log → task
- Nullable relationships (hive, agent, task)
- Scopes: forApiary, forHive, forAgent, forTask, action, recent
- Hive has activityLog relationship
- Index coverage queries (hive timeline, apiary timeline)
- Foreign key constraints (cascade on apiary/hive delete, null on agent/task delete)

## Acceptance Criteria

- [ ] Migration creates `activity_log` table with all columns and indexes
- [ ] ActivityLog model with correct table name and timestamps config
- [ ] All relationships defined and working
- [ ] Scopes for filtering
- [ ] Hive model has activityLog relationship
- [ ] All tests pass
- [ ] No regressions in existing test suite
