# TASK-296: Knowledge Wiki — Phase A1 Schema Foundation

**Status:** in-progress
**Branch:** `task/296-knowledge-wiki-a1-schema`
**PR:** —
**Depends on:** —
**Blocks:** TASK-297, TASK-298, TASK-299 (all Phase A sub-tasks)

## Objective

Land the additive Phase A schema for the knowledge wiki redesign
(proposal [`docs/proposals/knowledge-wiki-redesign.md`](../proposals/knowledge-wiki-redesign.md)
§9.1). The goal is to make the new typed-page shape *coexist* with
existing `value`-only rows — every legacy row keeps working, every new
column is nullable or defaulted, every partial unique index leaves
legacy rows outside its predicate, the new `knowledge_sources` raw
layer lands with its own dedup contract, the `wiki_links` table is
ready for authored references, and the immutability trigger guards
`knowledge_sources` against content mutation.

Phase A1 is **additive and reversible**: any time before Phase D, a
`git revert` of this PR returns the system to the pre-A1 state without
data loss.

## Requirements

### Functional

- [x] FR-1: New typed columns land on `knowledge_entries`:
  `type` (nullable), `slug` (nullable), `title` (nullable), `body`
  (nullable), `frontmatter` (jsonb default `{}`), `summary` (nullable),
  `tags` (text[] default `{}`), `source_ids` (text[] default `{}`),
  `last_linted_at` (timestamptz nullable), `lint_state` (string
  nullable). All `NOT NULL` is enforced post-Phase-C, not here.
- [x] FR-2: `search_vector` tsvector regenerated from the new shape
  (`title` + `summary` + `body` + `tags`).
- [x] FR-3: New `knowledge_sources` table with `id` (ULID PK),
  `organization_id`, `hive_id` (nullable), `origin` (`hive` | `org`),
  `kind`, `uri`, `content_sha256`, `title`, `raw_excerpt`
  (text ≤ 50,000 chars), `metadata` (jsonb default `{}`),
  `captured_by` (nullable), `captured_at`, timestamps, FKs with
  `cascadeOnDelete()` for org, `nullOnDelete()` for hive and agent.
- [x] FR-4: Two partial unique indexes on `knowledge_sources` —
  `uq_source_dedup_hive` (predicated `origin = 'hive'`) and
  `uq_source_dedup_org` (predicated `origin = 'org'`), partitioning
  on the immutable `origin` discriminator (NOT on `hive_id IS NULL`).
- [x] FR-5: `chk_source_origin` CHECK (origin in `hive`,`org`) and
  `chk_source_origin_org` CHECK (origin != 'org' OR hive_id IS NULL).
- [x] FR-6: New `wiki_links` table for authored `[[wikilink]]`
  references — `source_entry_id`, `target_entry_id` (both FKs to
  `knowledge_entries` with `cascadeOnDelete()`), `link_type`, optional
  `source_span`, `created_at`; unique on
  `(source_entry_id, target_entry_id, link_type)`, indexed both ways.
- [x] FR-7: Two new **partial** unique indexes on `knowledge_entries`:
  `idx_knowledge_hive_slug_scope` (predicated on hive scope + slug/type
  populated) and `idx_knowledge_organization_slug_scope` (predicated on
  organization scope + slug/type populated). Legacy `key` indexes stay
  in place through Phase C.
- [x] FR-8: `pg_trgm` extension enabled (guarded, mirrors
  `2026_04_15_100000_enable_pgvector_extension.php`).
- [x] FR-9: Optional GIN trigram index on `slug`
  (`idx_knowledge_slug_trgm`), built only when `pg_trgm` is available.
- [x] FR-10: GIN array index on `tags` (`idx_knowledge_tags_gin`) and
  on `source_ids` (`idx_knowledge_source_ids_gin`).
- [x] FR-11: Column-aware `BEFORE UPDATE` trigger on
  `knowledge_sources` — rejects any change to
  `raw_excerpt` / `content_sha256` / `uri` / `metadata` / `kind` /
  `title` / `captured_at` / `organization_id`; permits
  `hive_id` / `captured_by` going value → NULL only
  (`nullOnDelete()` cascade direction). INSERT and DELETE are not
  blocked (FK cascade needs them).

### Non-Functional

- [x] NFR-1: All PostgreSQL-only steps are guarded
  (`DB::getDriverName() === 'pgsql'`); SQLite/MySQL degrade gracefully
  with explicit comments explaining the missing behavior.
- [x] NFR-2: All migrations are idempotent on re-run where reasonable
  (`DROP IF EXISTS`, `CREATE OR REPLACE FUNCTION`, etc.).
- [x] NFR-3: Migration comments cross-reference the proposal section
  and the test that pins the contract.
- [x] NFR-4: `down()` reverses `up()` completely.
- [x] NFR-5: All hard-gate tests live under `tests/Feature/Knowledge/`
  (new directory) and follow the `RefreshDatabase` + cross-driver
  `markTestSkipped` for pgsql-only assertions pattern.

## Architecture & Design

### Files to Create

| Action  | Path                                                                                  | Purpose                                                                                |
|---------|---------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| Create  | `database/migrations/2026_06_09_100000_enable_pg_trgm_extension.php`                  | Enable `pg_trgm` (guarded, graceful skip)                                             |
| Create  | `database/migrations/2026_06_09_110000_add_wiki_columns_to_knowledge_entries.php`     | Add typed columns + search_vector regeneration + partial unique + GIN array indexes    |
| Create  | `database/migrations/2026_06_09_120000_create_knowledge_sources_table.php`            | `knowledge_sources` table + 2 partial unique indexes + 2 CHECK constraints             |
| Create  | `database/migrations/2026_06_09_130000_create_wiki_links_table.php`                   | `wiki_links` table + FKs + indexes                                                    |
| Create  | `database/migrations/2026_06_09_140000_add_knowledge_source_immutability_trigger.php` | Column-aware BEFORE UPDATE trigger (rejects content mutation, permits value→NULL)     |
| Create  | `tests/Feature/Knowledge/PhaseAMigrationCompatibilityTest.php`                        | Hard-gate test: ALTER succeeds on populated table, partial index admits legacy rows    |
| Create  | `tests/Feature/Knowledge/KnowledgeSourcesTest.php`                                   | Hard-gate test: source dedup partition, hive-deletion parity, immutability trigger      |
| Create  | `docs/tasks/TASK-296-knowledge-wiki-k1-a1-schema.md`                                  | This file                                                                              |
| Modify  | `TASKS.md`                                                                            | Add Phase 15 section (TASK-296/297/298/299)                                            |

### Files NOT modified in this task

- `app/Models/KnowledgeEntry.php` — fillable/cast updates land in A2
- `app/Http/Controllers/Api/KnowledgeController.php` — controller
  changes land in A2/A3
- `routes/api.php` — new endpoint routes land in A3
- `superpos-agent-core/src/superpos_agent_core/knowledge.py` — new
  SDK methods land in A3 (separate repo)
- `resources/js/Pages/Knowledge/Show.jsx` — UI rewrite lands in A4

### Key Design Decisions

- **Nullable typed columns, not `NOT NULL` with placeholder defaults.**
  The legacy `value`-only rows are live and populated. `ADD COLUMN …
  NOT NULL` with no default would fail the `ALTER`; placeholder
  defaults would collide on the new partial unique indexes
  (every legacy row would carry the same empty `slug`/`type`).
  The partial unique indexes are predicated on
  `slug IS NOT NULL AND type IS NOT NULL` so legacy rows are simply
  *outside* the index until Phase C backfills them.
- **Partial unique indexes, partitioned on `origin` (not
  `hive_id IS NULL`).** The naïve partition on `hive_id IS NULL`
  silently migrates a hive-scoped row into the org partition when its
  hive is deleted (because `hive_id` is `nullOnDelete()`). Two hives
  that ingested the same source would then collide on
  `(organization_id, content_sha256, kind)` and the second `SET NULL`
  would abort the hive deletion. The `origin` discriminator is
  immutable (set at ingest, protected by the column-aware trigger)
  so a row's dedup partition is fixed for its whole life.
- **Legacy `key` unique indexes retained, not re-keyed.** A Phase A
  legacy `POST` for an already-present `key` must still hit the legacy
  unique index and return 409. Re-keying in Phase A would either
  fail (the typed columns are nullable and the partial indexes
  wouldn't apply) or duplicate-key legacy rows would no longer be
  guarded. Dropping the legacy indexes is a Phase C step, not Phase A.
- **Trigger is column-aware, not blanket-update-block.** Content
  immutability is the goal, but `hive_id` / `captured_by` legitimately
  need to move value → NULL when the parent hive or agent is deleted.
  The trigger rejects every content column outright and only
  allows the cascade direction on the FK columns.
- **GIN array indexes on `tags` and `source_ids`.** These are
  first-class `text[]` PostgreSQL arrays. The existing tag-filtering
  code path uses `whereRaw("value->'tags' @> ?::jsonb")`; Phase A2
  rewires that to `tags @> ARRAY[?]::text[]` and the GIN index makes
  it index-scan, not seq-scan.

## Implementation Plan

1. **Migrations (5 files, in this order — timestamps enforce it):**
   1. `2026_06_09_100000_enable_pg_trgm_extension` — `CREATE EXTENSION
      IF NOT EXISTS pg_trgm`, pgsql-only, try/catch.
   2. `2026_06_09_110000_add_wiki_columns_to_knowledge_entries` —
      `Schema::table` for the new columns; raw `ALTER … SET DEFAULT`
      for the array columns; drop-and-recreate `search_vector`; create
      2 partial unique indexes + 2 GIN array indexes + 1 GIN trigram
      index (guarded on `pg_extension`).
   3. `2026_06_09_120000_create_knowledge_sources_table` — `Schema::create`
      + 2 partial unique indexes + 2 CHECK constraints.
   4. `2026_06_09_130000_create_wiki_links_table` — `Schema::create` +
      FKs + indexes.
   5. `2026_06_09_140000_add_knowledge_source_immutability_trigger` —
      pgsql `CREATE OR REPLACE FUNCTION` + `CREATE TRIGGER`; SQLite
      mirror with the value→NULL allow rule.
2. **Tests:**
   - `PhaseAMigrationCompatibilityTest`:
     - Seeding: 5 legacy `value`-only rows with diverse scopes, then
       `RefreshDatabase` runs the migration; assert legacy rows survive
       with `NULL` typed fields and `'{}'`-defaulted jsonb/array fields.
     - Schema shape: assert every new column exists.
     - Nullable behavior: insert a row with `NULL` `type`/`slug`/`body`/
       `title` and assert it persists (proves they're nullable, not
       `NOT NULL`).
     - Skip-on-non-pgsql for partial unique index + `search_vector`
       regeneration assertions.
   - `KnowledgeSourcesTest`:
     - Table shape: every column exists with the right type/nullability.
     - `chk_source_origin` CHECK: `origin = 'invalid'` rejected; valid
       `hive`/`org` accepted.
     - `chk_source_origin_org` CHECK: `origin = 'org'` + non-NULL
       `hive_id` rejected.
     - Two-hive source dedup: two hives in the same org ingest the
       same source (same `content_sha256`+`kind`) with `origin = 'hive'`
       and distinct `hive_id` — both inserts succeed (pgsql-only).
     - Org-wide dedup: a second `origin = 'org'` row with the same
       key is rejected (pgsql-only).
     - Trigger immutability: an `UPDATE` of `raw_excerpt` is rejected
       (`restrict_violation` on pgsql, `RAISE(ABORT)` on SQLite).
     - Trigger value→NULL allowance: an `UPDATE` setting
       `hive_id = NULL` succeeds (FK-cascade direction).
3. **TASKS.md:** add Phase 15 section with TASK-296, 297, 298, 299.
4. **Commit + push + open PR.**

## Database Changes

See proposal [`docs/proposals/knowledge-wiki-redesign.md`](../proposals/knowledge-wiki-redesign.md)
§6.1, §6.2, §6.3, §6.6, §6.7, §9.1 for the full schema. Summary:

- `knowledge_entries` gains 10 new columns (typed, summary, tags,
  source_ids, last_linted_at, lint_state) and a regenerated
  `search_vector` sourced from the new shape.
- `knowledge_entries` gains 2 partial unique indexes
  (`idx_knowledge_hive_slug_scope`,
  `idx_knowledge_organization_slug_scope`) and 2 GIN array indexes
  (`idx_knowledge_tags_gin`, `idx_knowledge_source_ids_gin`).
- `knowledge_entries` optionally gains a GIN trigram index
  (`idx_knowledge_slug_trgm`) when `pg_trgm` is available.
- `knowledge_sources` is a new table with FKs to `organizations`/
  `hives`/`agents`, 2 partial unique indexes, 2 CHECK constraints.
- `wiki_links` is a new table with FKs to `knowledge_entries`.
- `knowledge_sources` gains a column-aware immutability trigger.

## API Changes

None. The API/controller layer changes land in A2 (write path) and A3
(read path, new endpoints). A1 is schema-only.

## Test Plan

### Feature Tests

- [x] `PhaseAMigrationCompatibilityTest::test_knowledge_entries_has_new_columns`
- [x] `PhaseAMigrationCompatibilityTest::test_legacy_value_only_rows_survive_with_null_typed_fields`
- [x] `PhaseAMigrationCompatibilityTest::test_typed_columns_are_nullable_in_phase_a`
- [x] `PhaseAMigrationCompatibilityTest::test_partial_unique_index_does_not_constrain_legacy_rows` (pgsql-only, markTestSkipped on sqlite)
- [x] `PhaseAMigrationCompatibilityTest::test_legacy_key_unique_indexes_still_guard_duplicates`
- [x] `KnowledgeSourcesTest::test_table_has_expected_columns`
- [x] `KnowledgeSourcesTest::test_chk_source_origin_rejects_invalid_value`
- [x] `KnowledgeSourcesTest::test_chk_source_origin_org_rejects_org_with_hive_id`
- [x] `KnowledgeSourcesTest::test_two_hives_can_ingest_same_source` (pgsql-only)
- [x] `KnowledgeSourcesTest::test_org_dedupe_blocks_duplicate_origin_org` (pgsql-only)
- [x] `KnowledgeSourcesTest::test_immutability_trigger_rejects_raw_excerpt_update`
- [x] `KnowledgeSourcesTest::test_immutability_trigger_permits_hive_id_value_to_null`

## Validation Checklist

- [x] All tests pass (`php artisan test --filter='Knowledge'`)
- [x] No existing tests break (run the full feature suite)
- [x] PSR-12 compliant (PHP_CodeSniffer)
- [x] Migration comments cross-reference proposal sections and the
      hard-gate test that pins each contract
- [x] `down()` reverses `up()` completely for every migration
- [x] No new Eloquent model code in A1 (deferred to A2)
- [x] No new controller code in A1 (deferred to A2/A3)
- [x] No new route changes in A1 (deferred to A3)
- [x] No UI changes in A1 (deferred to A4)

## Out of Scope (deferred to later tasks)

- The new `KnowledgeService` write path and dual-shape validation
  (TASK-297)
- The `FrontmatterSchema` registry, `WikiLinkParser`, and source
  attach-time ACL (TASK-297)
- The new `KnowledgeSourceController` / `listByType` / `backlinks` /
  `synthesizeTopic` actions and route ordering (TASK-298)
- The new SDK file `superpos_agent_core/knowledge.py` and
  `wiki/AGENTS.md` (TASK-298, in superpos-agent-core repo)
- The `Show.jsx` rewrite and new dashboard panels (TASK-299)
- The Phase C backfill script `MigrateLegacyKnowledgeEntries` and
  the `knowledge:migration-report` artisan command (Phase C, future)
- Dropping the legacy `value` column (Phase D, future)
- Removing dead code: JSONB GIN on `value`, `_index:*` reservation
  (Phase E, future)
