# TASK-009: Knowledge Entries Migration + Model

**Status:** done
**Branch:** `task/009-knowledge-model`
**PR:** —
**Depends on:** TASK-005, TASK-006
**Blocks:** TASK-020 (Knowledge store API), TASK-021 (Knowledge TTL cleanup), TASK-069 (Apiary-scoped knowledge)

## Objective

Create the `knowledge_entries` database table and `KnowledgeEntry` Eloquent model to provide a JSONB-backed shared context store with three scope levels (hive, apiary, agent-private).

## Requirements

### Functional

- [x] FR-1: Create `knowledge_entries` migration matching the schema in PRODUCT.md section 9.2
- [x] FR-2: Create `KnowledgeEntry` model with `BelongsToHive` trait, `HasUlid` trait
- [x] FR-3: Support three scope levels: `hive` (default), `apiary`, `agent:{id}`
- [x] FR-4: JSONB `value` column with GIN index for search
- [x] FR-5: Unique composite index on `(superpos_id, hive_id, key, scope)`
- [x] FR-6: Partial index for apiary-scoped entries
- [x] FR-7: Version tracking (integer, default 1)
- [x] FR-8: TTL support (nullable timestamp)
- [x] FR-9: Relationships: belongsTo Agent (created_by), belongsTo Hive, belongsTo Superpos
- [x] FR-10: Add `knowledgeEntries()` hasMany on Hive model

### Non-Functional

- [x] NFR-1: ULID primary key (26 chars, string)
- [x] NFR-2: PSR-12 compliant
- [x] NFR-3: Foreign keys with appropriate cascade/nullify behavior
- [x] NFR-4: Indexes match PRODUCT.md schema (unique key+scope, GIN search, apiary scope partial)
- [x] NFR-5: Casts for JSONB, datetime, integer fields

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/0001_01_01_000016_create_knowledge_entries_table.php` | Knowledge entries migration |
| Create | `app/Models/KnowledgeEntry.php` | Eloquent model |
| Modify | `app/Models/Hive.php` | Add `knowledgeEntries()` relationship |
| Modify | `app/Models/Agent.php` | Add `knowledgeEntries()` relationship |
| Create | `tests/Feature/KnowledgeEntryModelTest.php` | Feature tests |

### Key Design Decisions

- Uses `BelongsToHive` trait (which includes `BelongsToApiary`) for tenant scoping, consistent with Agent and Task models
- `hive_id` is nullable to support apiary-scoped entries (scope='apiary') where knowledge is org-wide
- `created_by` references agents table with nullOnDelete (knowledge persists if agent is removed)
- Partial index on apiary-scoped entries for efficient cross-hive knowledge queries

## Database Changes

```sql
CREATE TABLE knowledge_entries (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) REFERENCES hives(id),
    key             VARCHAR(500) NOT NULL,
    value           JSONB NOT NULL,
    scope           VARCHAR(255) DEFAULT 'hive',
    visibility      VARCHAR(20) DEFAULT 'public',
    created_by      VARCHAR(26) REFERENCES agents(id),
    version         INTEGER DEFAULT 1,
    ttl             TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_knowledge_key_scope ON knowledge_entries (superpos_id, hive_id, key, scope);
CREATE INDEX idx_knowledge_search ON knowledge_entries USING gin (value jsonb_path_ops);
CREATE INDEX idx_knowledge_apiary_scope ON knowledge_entries (superpos_id, scope) WHERE scope = 'apiary';
```

## Test Plan

### Feature Tests

- [x] ULID auto-generation and no auto-increment
- [x] All fillable fields persist and round-trip correctly
- [x] Default values: scope='hive', visibility='public', version=1
- [x] JSONB value cast to array
- [x] TTL cast to datetime
- [x] Version cast to integer
- [x] Relationships: hive(), apiary(), creator()
- [x] Hive hasMany knowledgeEntries
- [x] Agent hasMany knowledgeEntries (created_by)
- [x] Scope helpers: isHiveScoped(), isApiaryScoped(), isAgentScoped()
- [x] Query scopes: scopeForScope(), scopeExpired(), scopeNotExpired()
- [x] BelongsToHive trait integration (CE auto-assignment)
- [x] Cloud mode rejects creation without context
- [x] Cascade delete: hive deletion cascades to knowledge entries
- [x] Agent deletion nullifies created_by
- [x] Multiple entries per hive
- [x] Unique key+scope constraint enforcement

## Validation Checklist

- [x] All tests pass (`php artisan test`)
- [x] PSR-12 compliant
- [x] ULIDs for primary keys
- [x] BelongsToHive trait applied
- [x] Foreign keys with correct cascade behavior
- [x] Indexes match PRODUCT.md schema
