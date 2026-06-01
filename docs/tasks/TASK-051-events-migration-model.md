# TASK-051: Events Migration + Model

**Status:** In Progress
**Branch:** `task/051-events-migration-model`
**Depends On:** 006 (Superpos & Hive models)

## Requirements

Create the `events` table migration and `Event` Eloquent model for the hive-scoped + cross-hive event system described in PRODUCT.md §6.5 and §9.2.

### Schema (from PRODUCT.md)

```sql
CREATE TABLE events (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) REFERENCES hives(id),  -- NULL for cross-hive (apiary.*) events
    type            VARCHAR(100) NOT NULL,
    source_agent_id VARCHAR(26),
    payload         JSONB NOT NULL DEFAULT '{}',
    is_cross_hive   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_events_hive ON events (hive_id, type, created_at);
CREATE INDEX idx_events_cross_hive ON events (superpos_id, created_at) WHERE is_cross_hive = TRUE;
```

### Model Requirements

- ULID primary key (HasUlid trait)
- BelongsToApiary trait (not BelongsToHive — hive_id is nullable for cross-hive events)
- Immutable records (no updated_at, block updates like ActivityLog)
- Relationships: apiary, hive, sourceAgent
- Scope helpers: isCrossHive(), isHiveScoped()
- Query scopes: forHive, forType, crossHive, recent
- Factory with forHive, crossHive, forAgent states

### Key Design Decisions

- Events use BelongsToApiary (not BelongsToHive) because hive_id is nullable for cross-hive events — same pattern as KnowledgeEntry
- Events are immutable audit records — no updated_at, block updates at model level
- Cross-hive events have `is_cross_hive = true` and `hive_id = NULL`
- Partial index on cross-hive events (PostgreSQL) for efficient cross-hive queries

## Test Plan

- ULID auto-generation and non-incrementing PK
- Fillable fields persist correctly
- Default values (is_cross_hive=false, payload={})
- Casts (payload→array, is_cross_hive→boolean, created_at→datetime)
- Relationships: apiary, hive, sourceAgent
- Scope helpers: isCrossHive, isHiveScoped
- Query scopes: forHive, forType, crossHive, recent
- BelongsToApiary auto-sets superpos_id in CE mode
- Cloud mode fails without context
- Immutability: updates blocked
- Cascade: deleting apiary cascades, deleting hive nullifies hive_id
- Deleting agent nullifies source_agent_id
- Cross-hive events allow null hive_id
- Hive and Agent hasMany relationship on parent models

## Validation Checklist

- [ ] Migration creates events table with correct schema
- [ ] Indexes match PRODUCT.md spec
- [ ] Model uses HasUlid + BelongsToApiary
- [ ] Events are immutable (no updates)
- [ ] Factory supports all event states
- [ ] All tests pass
- [ ] PSR-12 compliant (Pint)
