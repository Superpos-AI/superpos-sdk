# TASK-259: Sub-agent definitions migration + model

**Status:** pending
**Branch:** `task/259-sub-agent-definitions-migration`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/460
**Depends on:** —
**Blocks:** TASK-260, TASK-261, TASK-262, TASK-263
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §4, §5

## Objective

Create the `sub_agent_definitions` table and `SubAgentDefinition` Eloquent model. Sub-agent definitions are cloud-stored, versioned persona templates scoped to a hive, enabling reusable agent delegation behavior across tasks. This mirrors the `AgentPersona` model pattern but is hive-scoped (shared) rather than agent-scoped.

## Requirements

### Functional

- [ ] FR-1: Create `sub_agent_definitions` table migration matching feature spec §5.1 with the following columns:
  - `id` — string(26), primary key (ULID)
  - `superpos_id` — string(26), FK → apiaries
  - `hive_id` — string(26), FK → hives (cascadeOnDelete)
  - `slug` — string(100), URL-friendly identifier
  - `name` — string(255), human-readable display name
  - `description` — text, nullable
  - `model` — string(100), nullable (LLM model override, e.g. `claude-sonnet-4-6`)
  - `documents` — json, default `{}` (SOUL, AGENT, RULES, STYLE, EXAMPLES, NOTES document map)
  - `config` — json, default `{}` (LLM/runtime configuration)
  - `allowed_tools` — json, nullable (tool allowlist array)
  - `version` — unsignedInteger, default 1 (monotonic per slug+hive)
  - `is_active` — boolean, default false (only one active per slug+hive)
  - `created_by_type` — string(10), default 'human' (one of: human, agent, system)
  - `created_by_id` — string(26), nullable
  - `created_at` — timestamp, nullable (no `updated_at` — immutable records)
- [ ] FR-2: Composite unique index `uq_sub_agent_slug_version` on `(hive_id, slug, version)` — ensures one row per hive + slug + version combination
- [ ] FR-3: Partial unique index `idx_sub_agent_active` on `(hive_id, slug)` with a driver-specific `WHERE` clause — enforces only one active definition per slug per hive. Implementation must use `DB::statement()` with driver check: `CREATE UNIQUE INDEX ... WHERE is_active = true` for pgsql, `CREATE UNIQUE NONCLUSTERED INDEX ... WHERE is_active = 1` for sqlsrv (SQL Server uses integer boolean), fall back to regular composite index for sqlite, skip for mysql/mariadb (enforced at application level). Follow the pattern in `2026_04_08_200000_add_approvable_columns_to_approval_requests.php`.
- [ ] FR-4: `SubAgentDefinition` Eloquent model with `HasUlid`, `BelongsToApiary`, `BelongsToHive` traits and `HasFactory`
- [ ] FR-5: JSON casts for `documents` (array), `config` (array), `allowed_tools` (array)
- [ ] FR-6: Model relationships and scopes:
  - `hive()` — BelongsTo Hive
  - `apiary()` — BelongsTo Superpos
  - `scopeActive(Builder)` — `where('is_active', true)`
  - `scopeForSlug(Builder, string $slug)` — `where('slug', $slug)`
  - `scopeForHive(Builder, string $hiveId)` — `where('hive_id', $hiveId)`
- [ ] FR-7: `SubAgentDefinitionFactory` for tests with sensible defaults (slug, name, version=1, is_active=true, sample documents)

### Non-Functional

- [ ] NFR-1: No `updated_at` column — set `const UPDATED_AT = null` on model (immutable records, same pattern as AgentPersona)
- [ ] NFR-2: Partial index creation uses `DB::statement()` with `DB::connection()->getDriverName()` check to handle pgsql vs sqlsrv vs sqlite vs mysql differences (same pattern used in `2026_04_08_200000_add_approvable_columns_to_approval_requests.php`)
- [ ] NFR-3: All primary keys use ULIDs via `HasUlid` trait
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/xxxx_create_sub_agent_definitions_table.php` | Table creation migration |
| Create | `app/Models/SubAgentDefinition.php` | Eloquent model |
| Create | `database/factories/SubAgentDefinitionFactory.php` | Test factory |
| Create | `tests/Feature/SubAgentDefinitionModelTest.php` | Model tests |

### Key Design Decisions

- **Mirrors AgentPersona architecture** — same immutable-version pattern, same document structure, same `UPDATED_AT = null` approach. Developers familiar with AgentPersona will immediately understand SubAgentDefinition.
- **Hive-scoped, not agent-scoped** — unlike AgentPersona which has `agent_id`, SubAgentDefinition is shared within a hive via `hive_id`. Any agent in the hive can use any sub-agent definition.
- **No MEMORY document** — sub-agent definitions are stateless templates. Valid document names: SOUL, AGENT, RULES, STYLE, EXAMPLES, NOTES.
- **Partial unique index** — prevents multiple active versions of the same slug in a hive at the database level (where supported). Application-level enforcement in SubAgentDefinitionService handles MySQL.

## Implementation Plan

1. Create the migration file with all columns, foreign keys, composite unique index, and lookup indexes (`idx_sub_agent_hive`, `idx_sub_agent_apiary`)
2. Add partial unique index using `DB::statement()` with driver detection (wrap in try-catch for safety):
   ```php
   $driver = DB::connection()->getDriverName();
   if ($driver === 'pgsql') {
       DB::statement(
           'CREATE UNIQUE INDEX idx_sub_agent_active '
           . 'ON sub_agent_definitions (hive_id, slug) '
           . 'WHERE is_active = true'
       );
   } elseif ($driver === 'sqlsrv') {
       DB::statement(
           'CREATE UNIQUE NONCLUSTERED INDEX idx_sub_agent_active '
           . 'ON sub_agent_definitions (hive_id, slug) '
           . 'WHERE is_active = 1'
       );
   } elseif ($driver === 'sqlite') {
       // SQLite: no partial index support — regular composite index as fallback.
       Schema::table('sub_agent_definitions', function (Blueprint $table) {
           $table->index(
               ['hive_id', 'slug', 'is_active'],
               'idx_sub_agent_active',
           );
       });
   }
   // MySQL / MariaDB: skip — uniqueness enforced at application level
   // in SubAgentDefinitionService.
   ```
3. Create `SubAgentDefinition` model with:
   - `HasUlid`, `BelongsToApiary`, `BelongsToHive`, `HasFactory` traits
   - `const UPDATED_AT = null`
   - Document name constants: `DOCUMENT_SOUL`, `DOCUMENT_AGENT`, `DOCUMENT_RULES`, `DOCUMENT_STYLE`, `DOCUMENT_EXAMPLES`, `DOCUMENT_NOTES`
   - `DOCUMENTS` array constant (assembly order)
   - `CREATED_BY_*` constants matching AgentPersona
   - `$fillable` array with all columns
   - `casts()` method returning JSON casts
   - Relationships: `hive()`, `apiary()`
   - Scopes: `scopeActive()`, `scopeForSlug()`, `scopeForHive()`
   - Helper: `getDocument(string $name): ?string`, `getDocumentNames(): array`
4. Create `SubAgentDefinitionFactory` with defaults:
   - slug: `fake()->slug(2)`
   - name: `fake()->words(3, true)`
   - version: 1
   - is_active: true
   - documents: `['SOUL' => 'You are a helpful assistant.']`
   - config: `[]`
   - created_by_type: 'human'
5. Write model tests

## Database Changes

```sql
CREATE TABLE sub_agent_definitions (
    id VARCHAR(26) PRIMARY KEY,
    superpos_id VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id VARCHAR(26) NOT NULL REFERENCES hives(id) ON DELETE CASCADE,
    slug VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    model VARCHAR(100),
    documents JSON NOT NULL DEFAULT '{}',
    config JSON NOT NULL DEFAULT '{}',
    allowed_tools JSON,
    version INT UNSIGNED NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_type VARCHAR(10) NOT NULL DEFAULT 'human',
    created_by_id VARCHAR(26),
    created_at TIMESTAMP,

    UNIQUE (hive_id, slug, version)
);

CREATE INDEX idx_sub_agent_hive ON sub_agent_definitions (hive_id);
CREATE INDEX idx_sub_agent_apiary ON sub_agent_definitions (superpos_id);

-- Partial unique index (pgsql only — see driver matrix in FR-3)
-- pgsql:
CREATE UNIQUE INDEX idx_sub_agent_active
    ON sub_agent_definitions (hive_id, slug)
    WHERE is_active = true;
-- sqlsrv: CREATE UNIQUE NONCLUSTERED INDEX ... WHERE is_active = 1
-- sqlite: regular composite index on (hive_id, slug, is_active)
-- mysql/mariadb: no index — application-level enforcement only
```

## Test Plan

### Unit Tests

- [ ] Model has correct table name and fillable attributes
- [ ] ULID is auto-generated on create
- [ ] `documents`, `config`, `allowed_tools` are properly cast to arrays
- [ ] `UPDATED_AT` is null (immutable)
- [ ] `getDocument()` returns correct content or null for missing docs
- [ ] `getDocumentNames()` returns correct list of document keys
- [ ] `DOCUMENTS` constant has correct assembly order (SOUL → AGENT → RULES → STYLE → EXAMPLES → NOTES)

### Feature Tests

- [ ] Can create a sub-agent definition via factory
- [ ] `scopeActive()` filters to only `is_active = true` records
- [ ] `scopeForSlug()` filters by slug
- [ ] `scopeForHive()` filters by hive_id
- [ ] Composite unique constraint rejects duplicate (hive_id, slug, version) rows
- [ ] BelongsToHive trait scoping works correctly
- [ ] `hive()` relationship returns correct Hive
- [ ] `apiary()` relationship returns correct Superpos
- [ ] Factory creates valid model with all required fields
- [ ] Partial unique index prevents two active definitions for same slug+hive (on pgsql/sqlsrv)

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] ULIDs for primary keys
- [ ] BelongsToApiary/BelongsToHive traits applied
- [ ] No `updated_at` column (immutable records)
- [ ] Partial index uses DB::statement with driver check
- [ ] Factory produces valid models
