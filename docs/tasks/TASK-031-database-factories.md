# TASK-031 — Database Factories for All Models

| Field       | Value                      |
|-------------|----------------------------|
| **Status**  | Review                     |
| **Depends** | 005, 006                   |
| **Branch**  | `task/031-database-factories` |
| **PR**      | https://github.com/Superpos-AI/superpos-app/pull/38 |

## Objective

Provide Laravel model factories for every core Eloquent model, with
lifecycle/status/scope state methods for common test permutations.
Refactor existing model tests to use factories, eliminating duplicated
private helper methods.

## Scope

### Factories created

| Factory               | Model           | States                                                        |
|-----------------------|-----------------|---------------------------------------------------------------|
| `ApiaryFactory`       | Superpos          | `withOwner`, `cloud`, `pro`, `onTrial`, `withSettings`        |
| `HiveFactory`         | Hive            | `inactive`, `withDescription`, `withSettings`                 |
| `AgentFactory`        | Agent           | `online`, `offline`, `idle`, `busy`, `error`, `stale`, `withCapabilities`, `ofType` |
| `TaskFactory`         | Task            | `pending`, `inProgress`, `completed`, `failed`, `cancelled`, `critical`, `highPriority`, `lowPriority`, `crossHive`, `timedOut`, `targeting`, `withPayload` |
| `ActivityLogFactory`  | ActivityLog     | `forHive`, `forAgent`, `forTask`, `apiaryLevel`, `action`, `withDetails` |
| `KnowledgeEntryFactory` | KnowledgeEntry | `hiveScoped`, `apiaryScoped`, `agentScoped`, `private`, `expiring`, `expired`, `createdBy` |

### Key design decisions

- **`forHive($hive)` pattern**: Agent, Task, KnowledgeEntry, and ActivityLog
  factories derive `superpos_id` from the hive's parent automatically.
- **Auto-creation**: `Agent::factory()->create()` (no args) auto-creates a
  parent Hive and Superpos via nested factory defaults.
- **No AgentPermission factory**: This model uses a composite primary key,
  lacks `HasFactory`, and is idiomatically created via `$agent->grantPermission()`.
- **Raw DB inserts preserved**: Tests that verify DB triggers, race conditions,
  or constraint enforcement keep raw `DB::table()` inserts.

### Tests refactored

- `AgentModelTest` — helpers now use factories
- `TaskModelTest` — helpers now use factories
- `ActivityLogModelTest` — helpers now use factories
- `KnowledgeEntryModelTest` — helpers now use factories

### Tests added

- `DatabaseFactoryTest` — 38 tests covering every factory, every state,
  batch creation, and apiary/hive relationship derivation.

## Verification

```bash
php artisan test
# 1244 passed, 19 skipped (PostgreSQL-only), 0 failures
```

## Files changed

- `database/factories/ApiaryFactory.php` (new)
- `database/factories/HiveFactory.php` (new)
- `database/factories/AgentFactory.php` (new)
- `database/factories/TaskFactory.php` (new)
- `database/factories/ActivityLogFactory.php` (new)
- `database/factories/KnowledgeEntryFactory.php` (new)
- `tests/Feature/DatabaseFactoryTest.php` (new)
- `tests/Feature/AgentModelTest.php` (refactored helpers)
- `tests/Feature/TaskModelTest.php` (refactored helpers)
- `tests/Feature/ActivityLogModelTest.php` (refactored helpers)
- `tests/Feature/KnowledgeEntryModelTest.php` (refactored helpers)
- `docs/guide/database-factories.md` (new — VitePress guide)
- `docs/index.md` (updated — index link)
