# Knowledge Wiki Redesign: From JSONB Blobs to a Karpathy-Style LLM Wiki

Status: Draft for sign-off
Owner: nelson-bighetti (claude-agent) on behalf of the knowledge track
Scope: Major redesign of the Superpos knowledge store. The current
`knowledge_entries` table is a JSONB key-value blob with shallow
`{title, summary, content, tags}` payloads and a heavy
"every entry is a freeform note" culture. This proposal replaces
that shape with a typed, interlinked markdown wiki modelled on
Karpathy's LLM-wiki-as-agent-memory pattern, while preserving the
external API surface (CRUD + search + links) the platform already
exposes.

This is a bigger change than the registry cutover (b2). It touches
the schema, the writer jobs, the SDK, the dashboard, and the curator
prompt — but it does not touch the agent's *execution* path
(claiming, polling, task lifecycle). Knowledge is advisory memory,
not state.

---

## 1. What this proposal does

1. **Add a `type` column to `knowledge_entries`** that classifies
   each page as one of: `entity`, `topic`, `trend`, `source`, `log`,
   `procedure`. The folder-on-disk analogy holds: one table, file
   name encodes the type, the wiki's folders are view-time filters.
2. **Replace the JSONB `value` blob with two typed columns**:
   `body` (markdown) and `frontmatter` (jsonb, validated per type).
   The `value` column is dropped.
3. **Add a `knowledge_sources` table** for the immutable raw layer.
   Wiki pages reference sources by ULID; sources are never edited
   after ingest.
4. **Add a `wiki_links` table** for **authored** `[[wikilink]]`
   references inside page bodies. Auto-detected graph edges
   (current `knowledge_links`) keep their table and semantics.
5. **Rewrite the writer-side**: `RunKnowledgeFillin`, the curator,
   and the in-flight write-back jobs emit TYPED MARKDOWN PAGES,
   not JSON blobs.
6. **Add a `wiki/AGENTS.md` artefact** in the repo root of the
   superpos-agent-core SDK that encodes the procedural schema:
   "when you write a page, follow these conventions." The curator
   and fillin agents read this from disk before writing.
7. **Add backlinks, type-aware rendering, raw-source drilldown, and
   edit history to the dashboard.** Drop the `JSON.stringify(entry.value, null, 2)`
   dump that currently sits at the bottom of `Show.jsx`.
8. **Deprecate and drop the JSONB `value` column, the read-stats
   accessors (`getValueTitleAttribute` etc.), the JSONB GIN index,
   and the JSONB search branches in `KnowledgeController`.**

## 2. What this proposal does NOT do (out of scope)

- **Not a generic markdown editor.** We do not add a WYSIWYG
  editor. The dashboard edit surface is a plain `<textarea>` for
  body + a structured form for frontmatter. Most writes come from
  agents, not humans.
- **Not a change to the agent execution path.** Task claim/poll,
  webhook routing, policy enforcement, event bus, cross-hive
  permissions — all untouched. The `apiary:run-knowledge-*`
  commands, the fillin counter, the activity log shape, and the
  EventBus topics all stay the same.
- **Not a new FTS / vector-search engine.** Embedding and FTS
  columns survive; we just rewire their inputs from `value::text`
  to `body` (markdown is even better for tsvector tokenisation).
  The hybrid RRF ranker (issue #1) and the ranking config stay.
- **Not a CMS / collaborative editing system.** No locking, no
  conflict resolution, no diff/merge. A write is "I rewrote this
  page to v{N+1}." History lives in the activity log.
- **Not a new graph database.** `wiki_links` is an ordinary
  Postgres table; the existing `KnowledgeGraphService` BFS walker
  is reused for both `wiki_links` and `knowledge_links`.
- **Not a public-facing knowledge base.** Wiki pages inherit the
  same scope rules (hive / organization / agent) as current
  entries. The public/private `visibility` column survives.
- **Not a freeze on the agent API.** The SDK gains new methods
  (see §7) and keeps the old ones as shims through Phases A–C.
  The curl-visible API *adds* the new shape when it lands
  (Phase A) and keeps accepting `value=` on `POST /knowledge`
  through Phase C; `value=` is **deprecated and dual-read**
  during Phases A–C and only **rejected (422) in Phase D** —
  that breakage is intentional, phased, and called out in §9.

## 3. The irreversible part — what's given up

After the **full rollout** (i.e. once Phase D has landed — not
in the first release):

- `value` is gone. The column is dropped in Phase D. Through
  Phases A–C `value=` on POST/PUT is still **accepted and
  dual-read** (legacy writes keep working while the fleet rolls
  forward); a caller sending `value=` gets a 422 **only after
  Phase D**. The migration script writes a small `body` /
  `frontmatter` pair for the entries that earn a one-time
  migration (see §9.3); everything else is deleted at the
  migration step and not recoverable.
- The `_index:topics` and `_index:decisions` "index entries" are
  gone. They were a clever use of the JSONB blob to fake a wiki
  index; the new `wiki_links` table is the real thing.
- The `getValueTitleAttribute` / `getValueSummaryAttribute` /
  `getValueContentAttribute` / `getValueSourceAttribute` /
  `getValueConfidenceAttribute` / `getValueTagsAttribute` /
  `getValueFormatAttribute` accessors on `KnowledgeEntry` are
  gone. Callers that still want the title use `entry.frontmatter->title`
  (or, for `topic` type, the first H1 of `body`).
- `formatEntry()` no longer includes `value`. API consumers that
  rely on it get an empty response field documented in the OpenAPI.

This is why the proposal is split into five phases (see §9). Phases
A–C are additive and reversible. Phase D drops the column. Phase E
removes the dead `value` accessors and the JSONB GIN index. Only
after Phases A–C have a bake do we proceed.

---

## 4. Problem statement

The current `knowledge_entries` table (see
`database/migrations/0001_01_01_000016_create_knowledge_entries_table.php`
+ 14 follow-on migrations) holds one shape: a `(key, value jsonb)`
pair. The `value` blob has emerged as an "envelope" with
conventional sub-keys (`title`, `summary`, `content`, `tags`,
`source`, `confidence`, `format`) but no enforcement beyond what
`CreateKnowledgeRequest` and the curators' prompts happen to do
today.

The shape rewards shallow, ad-hoc storage. Surveying a sample
hive's recent entries shows the dominant pattern is:

```json
{
  "title": "Some incident summary",
  "summary": "Quick description of the issue.",
  "content": "There was an incident on Tuesday involving X. Y was the cause.",
  "tags": ["incident", "infra"],
  "source": "discord",
  "confidence": "medium"
}
```

Three problems with this:

1. **Everything is the same shape.** A *fact* about a deploy
   (`facts:redis-runs-on-7100`), a *trend* the curator noticed
   (`trend:auth-sprawl-over-q2`), a *summary* of a meeting
   (`meeting:2026-05-12-retro`), and a *procedure* the agent
   should follow (`procedure:deploy-rollback`) all live in the
   same `value` envelope. The downstream code has to peek at the
   `key` prefix to guess what shape to expect. The shape that
   "feels right" is the one the writer just happens to pick.
2. **The wiki never builds.** Because every entry is a freeform
   note, the wiki never gets cross-linked. `KnowledgeIndexService`
   produces `_index:topics` and `_index:decisions` blobs that *try*
   to fake an index, but they're a separate set of JSON entries
   that no one reads, that get rebuilt on every curator pass, and
   that no author ever explicitly links to. The graph view shows
   one or two clusters per hive because the underlying data has no
   internal structure for an LLM to *find* connections, only to
   *guess* them.
3. **The agent has no way to find what it wrote.** Embedding +
   FTS over `value::text` works for keyword recall, but the agent
   has no idea what the wiki *contains* until it asks. There's no
   catalog. `knowledge_topics()` returns a JSON blob nobody
   formats into a navigable list. The agent's prompt at
   `KnowledgeFillinService` L640-115 has to *list* every recent
   entry inline because there's no index to consult.

The Karpathy model fixes all three: type, body, and frontmatter
encode the *shape* of a memory artifact; the wiki is the agent's
working memory; the schema (`AGENTS.md`) is the procedural
memory that says "when in doubt, write a topic page that links
back to the entity pages." The model is small and old; we just
haven't applied it.

---

## 5. The Karpathy model: three layers, five memory types

Reference: [Karpathy's LLM Wiki as Agent Memory](https://aaif.io/blog/karpathys-llm-wiki-as-agent-memory/),
[original gist by Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The model has three layers. In a real filesystem, the layers
are directories; in Superpos they map to two tables + a repo file.

| Layer | Role | Superpos home | Mutability |
|---|---|---|---|
| `raw/` | Immutable source materials the agent reads but never writes | `knowledge_sources` table (new) | Insert-only |
| `wiki/` | LLM-maintained structured knowledge base | `knowledge_entries` table (modified) + `wiki_links` (new) | Read + replace (versioned) |
| `AGENTS.md` | Procedural schema: how the bookkeeper maintains the wiki | `sdk/src/superpos_agent_core/wiki/AGENTS.md` (new) | Edited by humans, loaded at agent boot |

The wiki maps to **five memory types**, which become the values
of `knowledge_entries.type`:

| Memory type | Wiki analogue | When to write one |
|---|---|---|
| **Entity** | A page for a named thing — person, project, system, session, channel, agent | A recurring entity shows up across ≥2 sources and merits its own page |
| **Semantic / topic** | A synthesised meaning across many sources — a subject, a design decision, a policy | A pattern or decision appears in ≥2 entries and is worth summarising |
| **Trend** | A pattern with date history — "MCP builders increasingly concerned with X" | A pattern is stable enough to track over time; the page records dated observations |
| **Summary** | A compressed version of a raw source | A `knowledge_sources` row is ingested; the curator (or an ad-hoc task) writes a summary page that links back to the source ULID |
| **Episodic / log** | What happened, when | A log entry is appended to `log.md` (in the wiki) for every ingest, query, lint pass, or human-driven edit |
| **Procedure** | Codified how-to | A workflow is repeated enough times that codifying it pays off |

The Karpathy article folds Summary into the general wiki;
Superpos will keep it as a first-class type because the
`raw → summary` pipeline is the highest-value writer-side job and
deserves its own page kind (and its own frontmatter schema).

### 5.1 The key insight: search is a navigator, not the memory

> "Search simply helps the agent navigate it."
> — Angie Jones, summarising Karpathy

Embeddings and FTS stay in the system. They are the *retrieval*
layer over a maintained knowledge base. They do not replace the
knowledge base; they do not "find what we know" by themselves;
they are the *index* the agent uses to pick the right pages out
of the wiki. The wiki is the truth. Embeddings and FTS just tell
the agent which page is "the auth-sprawl page" when the agent's
query is "y'all are doing too much OAuth in the registry."

The implementation: keep the `search_vector` and `embedding`
columns. Repoint them at `body` (markdown) instead of
`value::text`. The hybrid RRF ranker and the search controllers
keep working; they just index different input.

### 5.2 Why the one-table constraint holds

Karpathy's filesystem analogy is "one folder, file names encode
the type." If we modelled entities in `knowledge_entities`,
topics in `knowledge_topics`, and sources in `knowledge_sources`
(separate tables), we lose four things the model needs:

1. **The unified graph.** `wiki_links` is meant to connect any
   page to any other page. If entities and topics live in
   different tables, every `wiki_links` row needs a polymorphic
   target column and every reader needs a UNION query.
2. **The unified catalog.** `wiki/index.md` lists every page
   the agent knows about. That is one query against one table.
3. **The unified `[[wikilink]]` parser.** Body text contains
   `[[trend:auth-sprawl]]`. The parser does a single SELECT
   against the unified table to resolve the link.
4. **The unified curator.** `RunKnowledgeCurator` walks every
   page, computes health per page type, and writes a small
   number of `procedure:` pages that say "if you see X, link
   it to Y." That's a single pass over one table.

Three tables means three passes, three catalogs, three index
queries, three polymorphic-link resolvers. We pay that cost for
nothing — the rows are all `id, body, frontmatter, type, scope,
created_at, updated_at`.

---

## 6. The new data model

### 6.1 `knowledge_entries` — the wiki table

Modifications to the existing table:

| Column | Type | Notes |
|---|---|---|
| `id` | `ulid` PK | unchanged |
| `organization_id` | `ulid` FK | unchanged |
| `hive_id` | `ulid?` FK | unchanged; NULL for org-scoped pages |
| `slug` | `string(255)?` | **NEW** — human-readable identifier like `entity:redis-cluster-prod`. Unique per `(organization_id, hive_id, type, slug, scope)` via the *partial* unique indexes in §6.6 (predicated on `slug IS NOT NULL AND type IS NOT NULL`). Derived from the key prefix + a stable suffix. **Added nullable in Phase A** as a compatibility column so the `ALTER` succeeds on a live table of existing `value`-only rows; populated for kept rows by the Phase C backfill and made `NOT NULL` only afterwards (see §6.1.1 and §9.1). |
| `type` | `string(20)?` | **NEW** — `entity`, `topic`, `trend`, `source` (in-wiki summary), `log`, `procedure`. The `source` value here is *not* the same as the `knowledge_sources` table; see §6.2. **Added nullable in Phase A** for the same compatibility reason as `slug`; backfilled in Phase C and tightened to `NOT NULL` afterwards (§6.1.1, §9.1). |
| `title` | `string(255)` | **NEW** — denormalised from `frontmatter.title` for index listing and the `Show.jsx` H1. Avoids re-parsing markdown on every list render. |
| `body` | `text` | **NEW** — markdown body. Replaces the JSONB `value` column. **Added nullable in Phase A** (existing `value`-only rows have no body yet); backfilled in Phase C, `NOT NULL` enforced afterwards (§6.1.1, §9.1). |
| `frontmatter` | `jsonb` | **NEW** — validated per `type`. See §6.4. Added in Phase A with a `'{}'` default so existing rows get a valid empty object; populated by the Phase C backfill (§6.1.1, §9.1). |
| `summary` | `text?` | **NEW** — denormalised first-paragraph for list views. Filled from `body` at write time so list rendering doesn't have to parse markdown. |
| `tags` | `string[]` | **NEW** — denormalised from `frontmatter.tags`. Preserves the existing GIN index for tag filtering (see §6.6). Added in Phase A defaulting to the empty array `'{}'` so existing rows are valid immediately. |
| `source_ids` | `ulid[]` | **NEW** — refs to `knowledge_sources.id`, stored as a PostgreSQL `text[]` of ULID strings (ULIDs are 26-char strings, not a native PG type). A page can have zero or many sources. The page's body cites them by ULID in `[[source:01HX...]]` form. Queried with `= ANY(source_ids)` and backed by a GIN array index (§6.6). Added in Phase A defaulting to the empty array `'{}'`. |
| `last_linted_at` | `timestamptz?` | **NEW** — last time the curator walked this page. Used for incremental lint passes. |
| `lint_state` | `string(20)?` | **NEW** — `ok`, `needs_attention`, `broken_links`, `stale`. Surfaces in the dashboard. |
| `version` | `int` | unchanged (1 → 2 → 3, etc.) |
| `created_by` | `ulid?` | unchanged |
| `scope`, `visibility`, `ttl` | unchanged |
| `search_vector` | `tsvector` | kept, but generated from `body` (and `title`, `summary`) instead of `value` |
| `embedding` | `vector(1536)` | kept, computed from `body` instead of `value` |
| `read_count`, `last_read_at`, `last_read_by` | unchanged |
| `created_at`, `updated_at` | unchanged |

**Dropped:** `value` (JSONB).

The `search_vector` generation is updated in the migration that
adds the new columns:

```sql
-- Drop the old generated column.
ALTER TABLE knowledge_entries DROP COLUMN IF EXISTS search_vector;

-- Add a new one sourced from title + body + summary + frontmatter->>'tags'.
ALTER TABLE knowledge_entries ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(array_to_string(tags, ' '), '')), 'C')
    ) STORED;
```

Tag filtering stops going through `value->'tags'`. The new
`tags` column is a first-class Postgres `text[]` array, so it
is queried with native array operators, **not** with
`whereJsonContains` — that builder helper compiles to
JSON containment (`@>` against a `jsonb` column) and does not
apply to a real PG array column. All the
`whereRaw("value->'tags' @> ?::jsonb")` fragments in
`KnowledgeController::index` (L92-110) become array containment:

```php
$query->whereRaw('tags @> ARRAY[?]::text[]', [$tag]);
```

backed by a GIN index on the array column
(`idx_knowledge_tags_gin`, see §6.6), which `@>` can use the
same way the old JSONB containment index was used. (If we ever
wanted to keep tags as `jsonb` instead, `whereJsonContains`
would be correct — but the schema declares `tags` as a `text[]`
array column, so the array-operator + GIN path is the
consistent choice.)

### 6.1.1 Stored shape vs. migration shape (typed columns are nullable until Phase C)

The table above describes the **target** stored shape: a fully
converted typed page has `type`, `slug`, `body`, and
`frontmatter` populated. But the columns are **not** added in
that final shape. `knowledge_entries` is a live table full of
existing `value`-only rows, and Phase A is defined as *additive
and reversible* (§9). Adding `type`/`slug`/`body` as `NOT NULL`
in Phase A would either:

1. **abort the `ALTER` immediately** — `ADD COLUMN ... NOT NULL`
   with no default fails on a non-empty table; or
2. **force placeholder values** for every legacy row, which then
   **collide on the new `slug`/`type` unique indexes** (every
   legacy row would carry the same empty/placeholder `slug` and
   `type`), making the typed-page uniqueness constraint
   unsatisfiable and the legacy rows mutually ambiguous.

So Phase A adds them as **nullable / defaulted compatibility
columns**, and the new typed-page uniqueness is expressed as
**partial** unique indexes that only range over rows that have
actually been converted:

- `type`, `slug`, `body` → **nullable** (existing rows hold
  `NULL` until backfilled).
- `frontmatter`, `tags`, `source_ids` → defaulted (`'{}'`) so
  every existing row is immediately valid.
- The `(organization_id, hive_id, slug, type, scope)` /
  `(organization_id, slug, type, scope)` unique indexes are
  **partial**, predicated `WHERE slug IS NOT NULL AND type IS
  NOT NULL` (see §6.6). Legacy `value`-only rows (NULL `slug`,
  NULL `type`) are simply not in the index, so they neither
  collide with each other nor with converted rows.
- Because those legacy rows are outside the partial indexes, the
  **pre-existing legacy `key` unique indexes are kept in place
  through Phases A–C** (not re-keyed in Phase A) so the
  duplicate-key 409 guard `KnowledgeController::store` relies on
  still fires for a legacy `POST` on an already-present `key`.
  They are dropped only in Phase C after the backfill+delete,
  when no NULL-`slug`/`type` rows remain (see §6.6 and §9.3).

The Phase C migration (§9.1 / §9.3) backfills `type`, `slug`,
`body`, `frontmatter` for the kept legacy rows. **Only after**
that backfill — once every retained row carries a populated,
de-duplicated `slug`/`type` — are the `NOT NULL` and full
(non-partial) typed-page uniqueness constraints tightened (the
constraint-tightening migration runs at the tail of Phase C /
start of Phase D, see §9.1 "Phase A" and §9.3). This is the
nullable-then-tighten contract: the additive Phase A `ALTER`
always succeeds on a populated table, and the strict typed-page
invariant is reached without ever passing through a state where
unconverted rows violate it.

### 6.2 `knowledge_sources` — the raw layer

A new table for the immutable source material the agent reads
but never writes. This is the "raw/" folder in the Karpathy
filesystem. Sources are *summarised* into wiki pages; they are
never edited after ingest.

```php
// database/migrations/2026_xx_xx_create_knowledge_sources_table.php
Schema::create('knowledge_sources', function (Blueprint $table) {
    $table->string('id', 26)->primary();                // ULID
    $table->string('organization_id', 26);
    $table->string('hive_id', 26)->nullable();          // NULL for org-wide sources
    $table->string('origin', 4);                         // 'hive' | 'org' — IMMUTABLE dedupe partition set at ingest; never rewritten by FK cascade (see §6.7). NOT a visibility/ACL column (see §6.2.1).
    $table->string('kind', 40);                          // 'url', 'file', 'transcript', 'document', 'task_result'
    $table->string('uri', 1024);                         // canonical locator (URL, path, message id)
    $table->string('content_sha256', 64);                // immutability witness
    $table->text('title')->nullable();
    $table->text('raw_excerpt', 50000)->nullable();      // bounded excerpt; full text lives in object storage
    $table->jsonb('metadata')->default('{}');            // author, captured_at origin, content-type, etc.
    $table->string('captured_by', 26)->nullable();       // agent ULID or NULL for system
    $table->timestamp('captured_at');
    $table->timestamps();

    $table->foreign('organization_id')->references('id')->on('organizations')->cascadeOnDelete();
    $table->foreign('hive_id')->references('id')->on('hives')->nullOnDelete();
    $table->foreign('captured_by')->references('id')->on('agents')->nullOnDelete();

    $table->index(['organization_id', 'hive_id', 'captured_at']);
    $table->index(['organization_id', 'kind']);
});

// `origin` is a closed two-value discriminator. Enforce it at the
// database so no code path can write a third value or leave it NULL.
DB::statement(<<<'SQL'
    ALTER TABLE knowledge_sources
      ADD CONSTRAINT chk_source_origin CHECK (origin IN ('hive', 'org'));
SQL);
// `origin = 'org'` rows NEVER carry a hive_id. This is the one
// origin/hive_id invariant a CHECK can hold for the row's whole life:
// it is true at ingest and stays true forever (org rows have no
// hive FK to be nulled). We deliberately do NOT add the symmetric
// `origin = 'hive' => hive_id IS NOT NULL` check, because a hive-origin
// row legitimately reaches `hive_id IS NULL` after its hive is deleted
// (§6.7); the "a hive source must be ingested WITH a hive_id" rule is an
// ingest-time invariant enforced in `KnowledgeSource::insert()`, not a
// row-lifetime CHECK.
DB::statement(<<<'SQL'
    ALTER TABLE knowledge_sources
      ADD CONSTRAINT chk_source_origin_org CHECK (
        origin <> 'org' OR hive_id IS NULL
      );
SQL);

// Dedup is enforced by TWO partial unique indexes, not a single
// `unique([... , 'hive_id', ...])`. Postgres treats NULLs as
// distinct, so a plain composite unique on `hive_id` would let
// duplicate org-scoped sources (hive_id IS NULL) slip through.
// Partition the constraint on the IMMUTABLE `origin` discriminator,
// NOT on the nullability of `hive_id` — `hive_id` is `nullOnDelete()`,
// so partitioning on `hive_id IS NULL` would silently migrate a
// hive-scoped row into the org partition when its hive is deleted
// (see the orphan note below and §6.6 for the same fix on entries):
DB::statement(<<<'SQL'
    CREATE UNIQUE INDEX uq_source_dedup_hive
      ON knowledge_sources (organization_id, hive_id, content_sha256, kind)
      WHERE origin = 'hive';
SQL);
DB::statement(<<<'SQL'
    CREATE UNIQUE INDEX uq_source_dedup_org
      ON knowledge_sources (organization_id, content_sha256, kind)
      WHERE origin = 'org';
SQL);
```

**Why two partial indexes, not one `unique([...])`.** A single
`unique(['organization_id', 'hive_id', 'content_sha256', 'kind'])`
does *not* dedupe org-wide sources. Postgres treats `NULL` as
distinct from every other `NULL`, so two org-scoped rows with
`hive_id = NULL` and the same `(organization_id, content_sha256,
kind)` both satisfy the constraint and both insert. The
`uq_source_dedup_hive` index covers hive-scoped sources
(`origin = 'hive'`); the `uq_source_dedup_org` index covers
org-wide sources (`origin = 'org'`) on the reduced key that
omits the always-NULL column. (This mirrors the partial-index
approach already used for `knowledge_entries` in §6.6.)

**Why the partition is keyed on `origin`, not on `hive_id IS NULL`.**
`hive_id` is declared `nullOnDelete()` (L387): deleting a hive runs
an `ON DELETE SET NULL` *UPDATE* that rewrites `hive_id` from a value
to `NULL` on every source row that referenced it. If the org dedupe
index were predicated on `hive_id IS NULL` (the naïve partition), that
cascade would silently *move* a deleted hive's source rows into the
org-wide partition. Two hives that had each ingested the same source —
two perfectly legal rows under `uq_source_dedup_hive`, distinguished by
their differing `hive_id` — would, once one or both hives are deleted,
land in `uq_source_dedup_org` on the identical
`(organization_id, content_sha256, kind)` key, and the second
`SET NULL` write would **violate the unique index and abort the hive
deletion**. This is exactly the orphaned-row hazard §6.6 calls out for
`knowledge_entries`, where the org-scoped index is predicated on the
stable `scope` *value* rather than on `hive_id IS NULL` for the same
reason. `knowledge_sources` has no `scope` column (§6.2.1), so it uses
the dedicated, immutable `origin` discriminator instead. Because
`origin` is set once at ingest and never rewritten (the immutability
trigger in §6.7 protects it, and no FK cascade touches it), a row's
dedupe partition is fixed for its whole life: nulling `hive_id` on
hive deletion leaves a `origin = 'hive'` orphan **inside** the hive
partition (where two NULL `hive_id` orphans remain distinct, since
Postgres treats NULLs as distinct) and **never** in the org partition.
The hive deletion always succeeds; orphaned source rows are later
reclaimed by `php artisan knowledge:purge-sources` (§6.7).

Key properties:

- **`content_sha256`** is the immutability witness. If a row's
  `raw_excerpt` ever changes after insert, the SHA is wrong; a
  trigger enforces this (see §6.7).
- **No UPDATE policy.** Application code never updates a source.
  The `KnowledgeSource` model exposes only `insert()` and
  `find()`. A pre-commit hook on the `Eloquent` layer throws
  on `update()` and `delete()` from app code. The database
  trigger enforces *content* immutability on UPDATE — it rejects
  any change to `raw_excerpt` / `content_sha256` / `uri` /
  `metadata` / etc., but permits the `nullOnDelete()` FK columns
  (`hive_id`, `captured_by`) to be set to `NULL` by the parent's
  `ON DELETE SET NULL` cascade. DELETE is left to FK cascade and
  the sanctioned purge path so that `cascadeOnDelete()` from
  `organizations` is not blocked (see §6.7).
- **Sources do not appear in the agent's normal `list_knowledge`
  output.** A page's "Drill into raw sources" panel reaches
  through the `source_ids` array. The source is readable
  directly via a new endpoint (`GET /knowledge/sources/{id}`)
  and via the SDK (`get_source(id)`) **only when the caller can
  already see a page that references it** — see §6.8 for the
  source-visibility contract that prevents a raw source attached
  to an `agent:{id}`-scoped page from leaking to other agents in
  the hive.

### 6.2.1 Source visibility — derived from the referencing pages

`knowledge_sources` rows carry `organization_id` / `hive_id` /
`captured_by` / `origin` but **no `scope` / `visibility` column of
their own**. That is deliberate: a source's audience is *derived*
from the pages that cite it, never asserted independently.

(The `origin` column added in §6.2 is **not** a backdoor scope/
visibility column and does not reopen the decision below. `origin`
is a *dedupe-partition discriminator* — it records, immutably,
whether a row was ingested into the per-hive or the org-wide
uniqueness partition, and is read **only** by the two partial
unique indexes. It asserts nothing about who may *read* the row;
read access is still derived entirely from the citing pages via
the §6.8 rule. A source's `origin` and its audience are
independent: an `origin = 'hive'` source is still invisible to
everyone who cannot read a page that cites it, and an
`origin = 'org'` source is *not* automatically org-readable —
visibility follows its citations, exactly as below.)

The controlling rule (specified in full in §6.8) is:

> A source is visible to an agent **iff** that agent can read at
> least one `knowledge_entries` page whose `source_ids` array
> contains the source's `id`, under the *same* `checkReadAccess`
> semantics applied to pages (organization → all org agents;
> hive → same hive; `agent:{id}` → owner only).

Without this rule the raw layer would bypass the page ACL: a
private `agent:{id}` page can cite a `task_result` source, but
the raw row is only hive-scoped, so any other agent holding
`knowledge.read` in the hive could enumerate or fetch the raw
excerpt directly. The derived-visibility join closes that gap
(see §6.8 and the endpoint contracts in §8.4).

### 6.3 `wiki_links` — authored references

A new table for **authored** `[[wikilink]]` references parsed
out of page bodies. Separate from `knowledge_links`, which holds
**auto-detected** graph edges (the existing TASK-216 machinery).

```php
// database/migrations/2026_xx_xx_create_wiki_links_table.php
Schema::create('wiki_links', function (Blueprint $table) {
    $table->id();                                          // bigserial PK
    $table->string('source_entry_id', 26);                 // page-to-page ONLY: both ends are knowledge_entries
    $table->string('target_entry_id', 26);                 // FK -> knowledge_entries (never a source/task/agent)
    $table->string('link_type', 30)->default('wikilink');  // page->page relations: 'wikilink', 'derived_from', 'supersedes'
    $table->string('source_span', 200)->nullable();        // for back-link snippets: the text of the source link
    $table->timestamp('created_at')->nullable();

    $table->foreign('source_entry_id')->references('id')->on('knowledge_entries')->cascadeOnDelete();
    $table->foreign('target_entry_id')->references('id')->on('knowledge_entries')->cascadeOnDelete();

    $table->unique(['source_entry_id', 'target_entry_id', 'link_type'], 'uq_wiki_link');
    $table->index('target_entry_id');
    $table->index('source_entry_id');
});
```

**Why a separate table from `knowledge_links`?**

- `knowledge_links` is auto-detected by `DetectKnowledgeLinks`
  (TASK-218), keyed by `(source_id, target_id, target_type,
  target_ref, link_type)`, supports `target_type` other than
  `knowledge` (task / channel / agent), and is best-effort
  candidate mining.
- `wiki_links` is *authored*: a `[[trend:auth-sprawl]]` inside
  the body of a page. The author put it there. It is always
  exact (no fuzzy match), always points to a wiki page, and is
  regenerated on every body change by a markdown walker. It
  carries a `source_span` so the dashboard can show the link
  text in the back-link panel.

The two coexist. The graph view renders both. The `type=`
filter on graph queries splits them: `?link_source=authored` vs
`?link_source=auto`.

### 6.4 Frontmatter schema per type

`frontmatter` is JSONB. It is validated at write time by a small
`FrontmatterSchema` registry keyed on `type`. **Empty frontmatter
is a valid write for every type** — the agent can write a
pure-body page and have the curator backfill metadata later. To
make that rule consistent with the per-type metadata that source
and log pages need, the schema separates two tiers:

- **`required`** — hard, rejected at write time. Today this is
  empty for every type, which is what makes empty frontmatter a
  valid write everywhere.
- **`lint_required`** — soft. A page may be *written* without
  these keys, but the linter flags it (`lint_state =
  'needs_attention'`) until the curator backfills them. This is
  where `source_sha256` (source pages) and `event_type` / `actor`
  (log pages) live, so writes stay permissive while the dashboard
  still surfaces the gap.

```php
// app/Knowledge/FrontmatterSchema.php
final class FrontmatterSchema
{
    public const ENTITY = [
        'required' => [],
        'lint_required' => [],
        'optional' => ['aliases', 'kind', 'status', 'owners', 'related_entity_slugs'],
    ];
    public const TOPIC = [
        'required' => [],
        'lint_required' => [],
        'optional' => ['aliases', 'related_topic_slugs', 'superseded_by'],
    ];
    public const TREND = [
        'required' => [],
        'lint_required' => [],
        'optional' => ['first_observed', 'last_refreshed', 'confidence'],
    ];
    public const SOURCE_PAGE = [                  // the in-wiki summary of a raw source
        'required' => [],
        'lint_required' => ['source_sha256'],     // flagged by linter, not rejected at write
        'optional' => ['authored_by', 'published_at'],
    ];
    public const LOG = [
        'required' => [],
        'lint_required' => ['event_type', 'actor'],
        'optional' => ['parent_log_slug', 'related_entry_slugs'],
    ];
    public const PROCEDURE = [
        'required' => [],
        'lint_required' => [],
        'optional' => ['inputs', 'outputs', 'superseded_by', 'review_after_days'],
    ];

    // Reserved system/curator-managed keys. These are written by the
    // curator, linter, and WikiLinkParser — never by the authoring
    // agent — and are allowed on *every* type, independent of the
    // per-type `optional` whitelist. `validate()` always permits them.
    public const SYSTEM = ['broken_links', 'kind', 'lint_notes'];

    // Rejects unknown keys and hard-`required` omissions (write-time, 422).
    // The allowed-key set for a given type is the union of that type's
    // `required` + `lint_required` + `optional` keys with the reserved
    // SYSTEM keys; a key outside that union is the only thing rejected as
    // "unknown". The SYSTEM keys are therefore never rejected on any type.
    public static function validate(string $type, array $frontmatter): array { /* … */ }

    // Returns the missing `lint_required` keys; the curator maps a
    // non-empty result to lint_state='needs_attention'. Never rejects.
    public static function lintMissing(string $type, array $frontmatter): array { /* … */ }
}
```

The agent prompt instructs the model: "If the page is about
`redis-cluster-prod`, set `type: entity` and put any synonyms in
`frontmatter.aliases`. If the page tracks a pattern over time, set
`type: trend` and put `first_observed` and `last_refreshed` in
frontmatter." See the example wiki pages in §10.

### 6.5 `body` — markdown content

`body` is `text` (no length cap at the DB level; we cap at
`text` size for PostgreSQL ~1GB which is well beyond any sensible
wiki page). Markdown is stored verbatim. We do not re-render to
HTML server-side; the dashboard uses a client-side markdown
renderer (likely `react-markdown` + a sane plugin set; see §8).

The body is the place for `[[wikilink]]` references. The parser
follows Obsidian-flavored rules:

- `[[slug]]` — link to a page in the same hive (or org, for
  org-scoped pages).
- `[[slug|alias]]` — render `alias` as the link text.
- `[[source:01HX...]]` — reference a `knowledge_sources` row.
- `[[task:tsk_01HX...]]` — reference a task.
- `[[agent:agt_01HX...]]` — reference an agent.

A `WikiLinkParser` walks the body, resolves every `[[…]]`, and
writes the result in a transaction with the body write. **Where a
ref lands depends on what it points at, because `wiki_links` is
strictly page-to-page** (`source_entry_id` and `target_entry_id`
are both FKs into `knowledge_entries`, §6.3 L411–412), so it
cannot store a `knowledge_sources` / task / agent target:

- **Page refs** (`[[slug]]`, `[[slug|alias]]`) resolve against
  `knowledge_entries` and upsert a `wiki_links` row. These are
  the only refs that become `wiki_links`.
- **`[[source:…]]`** resolves against `knowledge_sources` and is
  appended to the page's `source_ids` array (the existing
  page→source link channel, §6.2 L389–393). It does **not** write
  `wiki_links`.
- **`[[task:…]]` / `[[agent:…]]`** resolve against tasks / agents
  and upsert a `knowledge_links` row, which already supports a
  polymorphic `target_type` of `task` / `agent` / `channel`
  (TASK-218, §6.3). They do **not** write `wiki_links`. This is
  the same rule the write-back path follows for the agent
  `authored_by` edge (§7, L757–759).

Unresolved links are stored in `frontmatter.broken_links` (an
array) so the curator can pick them up next pass. `broken_links`
is a reserved SYSTEM key (§6.4), so this write is allowed on any
type and is not subject to the per-type `optional` whitelist.

### 6.6 Indexes

After the migration, `knowledge_entries` has:

```sql
-- New typed-page uniqueness (partial over CONVERTED rows only — see below).
-- These are ADDED in Phase A but do NOT replace the legacy key indexes yet.
idx_knowledge_hive_slug_scope         -- partial unique, on (organization_id, hive_id, slug, type, scope)
                                      --   WHERE slug IS NOT NULL AND type IS NOT NULL
                                      --     AND hive_id IS NOT NULL AND scope NOT IN ('organization','apiary')
idx_knowledge_organization_slug_scope -- partial unique, on (organization_id, slug, type, scope)
                                      --   WHERE slug IS NOT NULL AND type IS NOT NULL
                                      --     AND scope IN ('organization','apiary')

-- Legacy key uniqueness — RETAINED through Phases A–C, dropped in Phase C
-- AFTER the backfill+delete (see below and §9.3). These keep guarding the
-- legacy `value`-only rows (which have NULL slug/type and are therefore
-- OUTSIDE the partial indexes above) so a legacy POST for an existing key
-- still 409s.
idx_knowledge_hive_key_scope          -- unique, on (organization_id, hive_id, key, scope) [pre-existing]
idx_knowledge_organization_key_scope  -- unique, on (organization_id, key, scope)          [pre-existing]

-- New / replaced
CREATE INDEX idx_knowledge_type ON knowledge_entries (organization_id, hive_id, type);
CREATE INDEX idx_knowledge_tags_gin ON knowledge_entries USING gin (tags);
CREATE INDEX idx_knowledge_source_ids_gin ON knowledge_entries USING gin (source_ids);
CREATE INDEX idx_knowledge_slug_trgm ON knowledge_entries USING gin (slug gin_trgm_ops);  -- fuzzy slug lookup
CREATE INDEX idx_knowledge_lint_state ON knowledge_entries (lint_state) WHERE lint_state IS NOT NULL;
```

The `idx_knowledge_slug_trgm` index uses the `gin_trgm_ops`
operator class, which is **not** part of stock PostgreSQL — it
ships in the `pg_trgm` extension. The Phase A migration therefore
**must** enable `pg_trgm` (`CREATE EXTENSION IF NOT EXISTS
pg_trgm`) *before* this index is created, otherwise the migration
aborts with `operator class "gin_trgm_ops" does not exist` on a
database that has `vector` but not `pg_trgm`. The extension is
enabled in a dedicated, PostgreSQL-guarded migration that mirrors
the existing pgvector migration — see §9.1.

The old `value::text` GIN indexes and the
`idx_knowledge_search` GIN-on-`value` are dropped in Phase D.

The new typed-page unique indexes are keyed on `(organization_id,
hive_id, slug, type, scope)` (and the org-scoped variant on
`(organization_id, slug, type, scope)`). The key now uses the typed
`slug + type` pair in place of the freeform `key` attribute while
**retaining `scope`** — the freeform `key` is replaced by `slug +
type`, but the `scope` dimension stays in the tuple. Keeping `scope`
is required so that an agent-scoped page and a hive-scoped page that
happen to share the same `slug` and `type` do not collide.

**The pre-existing legacy `key` unique indexes are NOT renamed or
re-keyed in place — they are kept alongside the new partial indexes
through Phases A–C and dropped only in Phase C, after the
backfill+delete (§9.3).** This is deliberate: the new typed-page
indexes are *partial* over `slug IS NOT NULL AND type IS NOT NULL`,
so a legacy `value`-only row (NULL `slug`/`type`) is **outside**
them. If the legacy `key` indexes were dropped in Phase A, a
pre-existing `key = facts:x` row would be guarded by *neither* index,
and a Phase A legacy `POST` for the same `key` could be converted to
a typed row and inserted instead of returning the current **409**
conflict that `KnowledgeController::store` relies on. Retaining the
legacy `key` indexes until every legacy row is backfilled or deleted
keeps the duplicate-key guard intact for the entire dual-write
window. Once Phase C has backfilled the kept rows and deleted the
non-kept ones (§9.3, §9.6), no NULL-`slug`/`type` rows remain, the
legacy `key` indexes have nothing left to guard, and they are dropped
in the same Phase C constraint-tightening migration — from that point
the partial `slug`/`type` indexes are the sole uniqueness authority.

The hive-scoped index keeps its
`WHERE hive_id IS NOT NULL AND scope NOT IN
('organization','apiary')` predicate. The legacy "apiary" value in
`scope` was already rewritten to "organization" in migration
`2026_05_26_000001_rename_knowledge_scope_apiary_to_organization.php`,
so the partial-index predicates can stay. (The `'apiary'` value is
retained in the predicates only for backward-compat safety; see
"events with `platform.*`/`apiary.*` prefixes" in the platform
notes — no live `scope` rows still hold it.)

The org-scoped index is predicated on the **scope value**
(`scope IN ('organization','apiary')`), **not** on `hive_id IS
NULL`. These look equivalent for healthy data — an org-scoped page
has `hive_id = NULL` — but `hive_id IS NULL` *also* catches a
hive- or agent-scoped row whose `hive_id` was nulled out when its
hive was deleted (an orphaned row). Once Phase C backfills
`slug`/`type` onto such an orphan, two orphaned non-org rows that
happen to share the same `(organization_id, slug, type, scope)`
would collide on the org index and **abort the Phase C
constraint-tightening migration**, even though neither is actually
an organization page. Predicating on `scope IN
('organization','apiary')` constrains the org index to genuinely
org-scoped pages only, so orphaned hive/agent-scoped rows never
enter it. This also makes the hive and org indexes mutually
exclusive on `scope`, which is the intended partition.

**The predicates also exclude unconverted legacy rows** — they
add `slug IS NOT NULL AND type IS NOT NULL`. This is what keeps
the additive Phase A migration safe on a live table (§6.1.1):
the typed columns are added *nullable* in Phase A, so every
existing `value`-only row carries `NULL` `slug`/`type` and is
simply absent from these unique indexes. Without the
`slug/type IS NOT NULL` clause, all those legacy rows would
share the same `(…, NULL, NULL, …)` key — and although Postgres
treats `NULL` as distinct in a *plain* unique index, the moment
Phase C backfills (or any earlier step forces) a placeholder
`slug`/`type` on them they would collide. Predicating on
populated `slug`/`type` makes the uniqueness apply **only to
converted typed pages**, which is exactly the invariant we want.

Because the partial indexes deliberately ignore unconverted legacy
rows, the **duplicate-key guard for those rows is carried by the
retained legacy `key` unique indexes** for the whole Phase A–C
window (see above) — they are what make a legacy `POST` for an
already-present `key` still return **409** while the typed columns
are NULL. After Phase C has backfilled every kept row and deleted
the non-kept ones, the `NOT NULL` constraints on `slug`/`type` are
added and the now-redundant legacy `key` indexes are dropped (no
NULL-`slug`/`type` rows remain for them to guard). The
`slug IS NOT NULL AND type IS NOT NULL` predicate is then redundant
too (but is left in place — it is harmless and documents intent);
see §6.1.1, §9.1 and §9.3.

### 6.7 Source immutability trigger

A PostgreSQL trigger enforces *content* immutability on
`knowledge_sources`. It must be **column-aware**, not a blanket
"reject every UPDATE": `hive_id` and `captured_by` are declared
`nullOnDelete()` (§6.2, L340–341), and Postgres implements
`ON DELETE SET NULL` as an `UPDATE` on the child row. A trigger
that rejected *every* update would therefore fire on that
cascade and abort with `restrict_violation` — deleting a hive or
the capturing agent would be impossible while any source rows
referenced it. So the trigger rejects changes to *content*
columns while allowing the FK columns to move from a value to
`NULL` (and only in that direction):

```sql
CREATE OR REPLACE FUNCTION knowledge_sources_immutable()
RETURNS trigger AS $$
BEGIN
    -- Content is append-only. The ONLY updates ever permitted are
    -- the FK ON DELETE SET NULL actions on hive_id / captured_by,
    -- which Postgres runs as an UPDATE on this row. Allow those
    -- (value -> NULL only) and reject any change to immutable content.
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.kind           IS DISTINCT FROM OLD.kind
       OR NEW.uri            IS DISTINCT FROM OLD.uri
       OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
       OR NEW.title          IS DISTINCT FROM OLD.title
       OR NEW.raw_excerpt    IS DISTINCT FROM OLD.raw_excerpt
       OR NEW.metadata       IS DISTINCT FROM OLD.metadata
       OR NEW.captured_at    IS DISTINCT FROM OLD.captured_at
       -- origin is the dedupe partition key (§6.2); it must NEVER
       -- change after ingest, or a row could jump partitions and
       -- defeat the orphan-safety guarantee. The FK SET NULL cascade
       -- on hive_id below does not touch origin.
       OR NEW.origin         IS DISTINCT FROM OLD.origin
       -- hive_id / captured_by: a value may be nulled (FK cascade),
       -- but never changed to a different value or un-nulled.
       OR (NEW.hive_id     IS DISTINCT FROM OLD.hive_id     AND NEW.hive_id     IS NOT NULL)
       OR (NEW.captured_by IS DISTINCT FROM OLD.captured_by AND NEW.captured_by IS NOT NULL)
    THEN
        RAISE EXCEPTION 'knowledge_sources is append-only (operation: %)', TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER knowledge_sources_no_update
    BEFORE UPDATE ON knowledge_sources
    FOR EACH ROW EXECUTE FUNCTION knowledge_sources_immutable();
```

**Why there is no `BEFORE DELETE` trigger.** `organization_id`
is declared `cascadeOnDelete()` (§6.2, L324). A blanket
`BEFORE DELETE` trigger that rejects *every* delete would fire
on the child rows of an FK cascade, so deleting an organization
(or any parent that cascades into `knowledge_sources`) would
abort with `restrict_violation` — the org could never be
purged. Immutability is about content, not lifetime: a source's
`raw_excerpt` / `content_sha256` must never change after insert,
but a source *may* be removed when its owning org is deleted.

So the trigger covers content UPDATEs only, and DELETE is governed by:

- **FK cascade** for parent-driven purges (org deletion removes
  the org's sources; `hive_id` / `captured_by` are `nullOnDelete`,
  so hive or agent deletion just detaches the source via the
  FK-null UPDATE the trigger explicitly permits above).
- **The application-level guard** in `KnowledgeSource` (the
  model exposes `insert()` / `find()` but no `update()` /
  `delete()`), which blocks direct/manual deletes from app
  code. Operator-driven hard purges go through an explicit
  console path (`php artisan knowledge:purge-sources`) that
  uses a raw `DELETE` rather than the model, documented as the
  only sanctioned manual deletion route.

The UPDATE trigger remains the belt-and-braces against any code
path that bypasses Eloquent and tries to mutate a stored source.

### 6.8 Source read ACL — visibility through the referencing page

A raw source must never be readable by an agent that cannot read
a page citing it. This closes the gap that `knowledge_sources`
otherwise opens: the table is only org/hive-scoped, but pages
that reference it can be `agent:{id}`-scoped (private). Without an
explicit rule, an agent holding `knowledge.read` in the hive
could `GET /knowledge/sources/{id}` (or `list` them) and read the
raw excerpt of a source that is only ever cited by *another*
agent's private page — bypassing `checkReadAccess` entirely.

**Contract (chosen approach: derive visibility from the
referencing page; no source-level scope column).**

- A source has **no independent `scope` / `visibility`**. Its
  audience is the union of the audiences of the pages that cite
  it. We do **not** add `scope` / `visibility` columns to
  `knowledge_sources`; doing so would create a second source of
  truth that could drift from the page ACL. (Considered and
  rejected: source-level `scope` columns enforced with the same
  `checkReadAccess`. Derived visibility is preferred because a
  source can be cited by several pages at different scopes, so
  the only correct audience is the union of those pages — a
  single stored scope cannot express that and would either
  over- or under-expose.)

- **`GET /knowledge/sources/{id}` (single fetch)** succeeds only
  if the requesting agent can read **at least one** page whose
  `source_ids` contains `{id}`, evaluated with the exact
  `checkReadAccess` semantics already applied to pages
  (`KnowledgeController::checkReadAccess`: organization-scoped →
  visible to all org agents; hive-scoped → same hive only;
  `agent:{id}` → owner only). The visibility check is a join,
  conceptually:

  ```sql
  SELECT 1
  FROM knowledge_entries e
  WHERE e.organization_id = :org
    AND :source_id = ANY(e.source_ids)
    AND (e.ttl IS NULL OR e.ttl > now())   -- mirror notExpired()
    AND (
          e.scope IN ('organization', /* org-wide aliases */)
       OR (e.scope = 'hive'        AND e.hive_id = :target_hive)
       OR (e.scope = 'agent:' || :agent_id)
    )
  LIMIT 1;
  ```

  The `(e.ttl IS NULL OR e.ttl > now())` clause mirrors the
  `KnowledgeEntry::notExpired()` scope the knowledge read flow
  already applies before `checkReadAccess`: an **expired** citing
  page confers no read access to the source it cites. A source
  cited *only* by expired pages therefore returns the same **404**
  (single fetch) — and is absent from `GET /knowledge/sources`
  (list) — exactly as an expired knowledge entry does. If no such
  (live) page exists, the endpoint returns **404 "source not
  found"** — the same not-found shape `checkReadAccess` returns
  for a page the agent may not see (so existence is not leaked).
  A source with **zero** referencing pages is therefore
  unreadable through the read API by anyone; it is reachable only
  via the sanctioned ingest/write-back path and the operator
  console.

- **`GET /knowledge/sources` (list)** returns only sources that
  have at least one visible referencing page for the caller — the
  same join, applied as a `WHERE EXISTS (...)` filter on the
  listing query, plus the existing `kind` / `since` filters. A
  source attached *only* to an `agent:{id}` page belonging to a
  different agent never appears in another agent's list.

- **`POST /knowledge/sources` (ingest)** is unchanged in scope
  semantics — the writer still attaches the source to a page via
  `source_ids`; the ACL is purely on the read side and is derived
  from those references.

- **Attach-time write authorization (`POST` / `PUT /knowledge`
  carrying `source_ids`).** Because the source audience is the
  *union* of its citing pages (above), attaching a source to a
  new or updated page can only ever **widen** that union — so the
  write path must guard against an agent broadening a source it
  cannot already see. Before the page row is persisted, every
  `source_id` in the request must satisfy **one** of:

  - **(a) Newly ingested in the same transaction** — the source
    was created by this same write (the caller is its originator),
    so the caller trivially holds it; or
  - **(b) Already readable by the caller** — the caller can read
    at least one *existing* page citing that source, under the
    **same `checkReadAccess` semantics** used on the read side
    (the §6.8 join above, including the non-expired `ttl`
    predicate); or
  - **(c) Caller is the orphan source's own originator** — the
    source has **zero** existing citing pages (it is an orphan,
    e.g. just created by a standalone `POST /knowledge/sources` /
    `ingest_source()` in a *prior* transaction) **and** its
    `captured_by` equals the calling agent. An orphan source has an
    **empty** derived audience, so the originating agent attaching
    its *own* orphan cannot widen anything that was already
    visible — it is establishing the source's first (and so far
    only) reader, not broadening an existing union. This is the
    narrow rule that keeps the two-step ingest-then-attach flow
    from dead-ending: `ingest_source()` followed by
    `create_page(..., source_ids=[id])` by the **same** agent
    satisfies (c) even though it spans two transactions, while a
    *different* agent attaching someone else's orphan still falls
    through to the widening check below. (Agents that prefer a
    single round-trip can instead use the transactional path in
    §8.1: `create_page` / `POST /knowledge` accepts an inline
    `sources=[…]` array whose descriptors are ingested and attached
    atomically in the same write, satisfying (a) directly.)

  Attaching a source to a page whose audience is **broader** than
  the caller's current read access to that source — i.e. widening
  the derived source ACL (e.g. citing another agent's
  `agent:{id}`-private source from a `hive`- or
  `organization`-scoped page) — is **rejected at write time**. It
  requires an explicit owner / system / admin path rather than an
  ordinary `knowledge.write` agent. This validation runs **inside
  the write transaction, before the page row is persisted**; a
  violation returns **403** and rolls the transaction back, so no
  widening page is ever committed.

This keeps a single ACL (`checkReadAccess` on pages) authoritative
for *both* pages and the raw layer, so the two cannot drift.

---

## 7. The bookkeeper — who writes pages, and how

Three writers produce pages, all of which produce typed
markdown:

1. **`RunKnowledgeCurator`** — a scheduled maintenance pass.
   Rewrites stale topic pages, drafts new entity pages for
   recently-mentioned named things, lints every page in the
   hive, refreshes `_index.md`.
2. **`RunKnowledgeFillin`** — the per-agent "gardening" pass
   (TASK-252). Dispatches a `knowledge_fillin` task to the
   agent; the agent's prompt instructs it to read the existing
   wiki and *add* or *update* typed pages, not emit JSON blobs.
3. **`ProcessKnowledgeWriteBack`** (TASK-220) — the per-task
   write-back. Currently emits `{value: {title, summary,
   content, ...}}`. After the redesign, the task completion
   payload may still be JSON-shaped for backwards compat
   (see §9.4), but the *stored* page has `body` + `frontmatter`
   + `type`, and the agent that wrote the task result also
   produces a typed `source:` page that summarises the task
   and links back to it.

The procedural memory the bookkeeper follows is a single
file, `sdk/src/superpos_agent_core/wiki/AGENTS.md`, shipped
with the SDK and read by the agent at fillin time. It
encodes:

- **Type taxonomy** — when to use `entity` vs `topic` vs
  `trend` vs `procedure`. With worked examples.
- **Slug conventions** — `entity:<noun>-<qualifier>`,
  `topic:<subject>`, `trend:<observed-pattern>`,
  `source:<short-hash>`, `log:<yyyy-mm-dd>-<event>`,
  `procedure:<verb>-<object>`.
- **Body template** — first line is `# <Title>`, second
  paragraph is a one-line summary, then a `## Sources`
  section listing `[[source:…]]` refs, then `## Related`
  for `[[wikilinks]]`, then free-form body. The curator's
  lint pass flags pages that don't follow this shape.
- **Linking rules** — "If you mention a named thing in a
  topic page and that thing has (or should have) an entity
  page, link to it. If you write an entity page, link to
  the topic pages the entity appears in."
- **Refresh cadence** — entity pages refresh when the
  underlying facts change; topic pages refresh when a new
  source contradicts the synthesised claim; trend pages
  append a dated observation; log pages are append-only;
  procedure pages are reviewed every N days (set in
  `frontmatter.review_after_days`).

The AGENTS.md is human-edited, versioned, and shipped in the
SDK. Changes to it are a SemVer-bump to the SDK and a
changelog entry.

### 7.1 What the curator changes

`app/Console/Commands/RunKnowledgeCurator.php` currently does
two things: compute a health score, and write a JSON blob to
`_health:latest`. After the redesign:

- The health score moves to a typed `procedure:health-check`
  page (or stays as a JSON entry on `_index.md` — see §7.3).
- The "write a JSON blob" step is replaced with: "for each
  `procedure:*` page in the hive, look at its
  `frontmatter.review_after_days`; if the last refresh is
  older, dispatch a refresh task to the agent that owns the
  page."
- A new pass: walk the wiki, for each entity page, check
  that its `frontmatter.related_entity_slugs` still resolve
  (i.e. those entity pages exist and aren't stale). Emit a
  list of broken / stale links to `_index.md` (in-wiki, not a
  JSON entry).
- A new pass: walk the wiki, find `entity:*` pages whose
  `frontmatter.status` is `tentative` and that have been
  viewed > 0 times → promote to `established`.
- A new pass: lint every page against the body template; if
  it's missing the `## Sources` section, mark `lint_state =
  needs_attention`.

### 7.2 What the fillin changes

`KnowledgeFillinService` currently constructs a prompt that
shows the agent a list of recent entries and asks it to write
or update "knowledge entries" with `{title, summary, content,
tags}`. After the redesign:

- The prompt shows the agent the existing wiki's `index.md`
  (the catalog) and `log.md` (recent activity), plus the
  per-agent recency slice the agent is allowed to see.
- The output schema changes. The agent is asked to produce a
  small JSON list of `WikiWrite` operations, each of which
  is `{ type, slug, frontmatter, body, source_ids[] }`. The
  fillin service transcribes these into typed pages and runs
  the `WikiLinkParser` over each new body.
- The "Existing knowledge" section in the prompt is replaced
  with a *typed* listing: "Entity pages you might extend:
  `entity:redis-cluster-prod` (last refresh 14d ago, stale)."
  The agent uses the typed listing to decide between *update*
  (rewrite body in place) and *new* (create a sibling page).
- The exemplars in `KnowledgeFillinService::EXEMPLARS`
  (L76-116) are updated to be *full wiki pages* with
  frontmatter and `[[wikilinks]]`, not flat `{title, summary,
  content}` JSON.

### 7.3 The in-wiki `index.md` and `log.md`

There is no filesystem; the catalog and the log are wiki
pages, not files. They live in the same `knowledge_entries`
table:

- `slug = 'index'`, `type = 'topic'`, `body = "## Hive
  Index\n\n- [[entity:redis-cluster-prod]] — production Redis
  cluster (refreshed 2026-05-30)\n- [[topic:auth-sprawl]] —
  …", `frontmatter = { kind: 'index' }`. `kind` is a reserved
  SYSTEM key (§6.4), so this curator-managed write validates on
  `type = 'topic'` even though `kind` is not in TOPIC's per-type
  `optional` list. Hive-scoped and org-scoped variants both
  exist; org-scoped is the cross-hive catalog.
- `slug = 'log'`, `type = 'log'`, `body` is *append-only*
  markdown with one `## YYYY-MM-DD` heading per day. The
  curator appends (not rewrites) new log entries.

A "log entry" is a separate concept from the wiki's `log.md`
page: it can be a child page `log:2026-06-08-knowledge-fillin`
that is itself a `type=log` wiki page, with frontmatter
`{event_type: 'fillin', actor: 'agt_01HX...'}` and a body that
records what happened. The wiki's `log.md` is the *catalog*
of log pages.

The `KnowledgeIndexService` class is gutted. Its three
methods (`updateTopicIndex`, `updateDecisionIndex`,
`updateAgentIndex`) all become *page-write operations* on the
unified `knowledge_entries` table:

- `updateTopicIndex($hive)` → refreshes `slug=index` body
  for the hive.
- `updateDecisionIndex($hive)` → writes a `topic:decisions-*`
  page that lists `procedure:*` and `topic:*` pages tagged
  `decision`.
- `updateAgentIndex($hive, $agent)` → writes
  `log:agent-{id}` that records which pages this agent last
  touched.

The `_index:topics` / `_index:decisions` / `_index:agent:{id}`
JSON-blob entries are *never written* by the new code. The
keys remain reserved (Phase D) so that a stale curator pass
on the old code can't pollute the wiki. A startup check
fails the boot if any `_index:*` rows exist after the
migration.

### 7.4 `ProcessKnowledgeWriteBack` — what changes

`ProcessKnowledgeWriteBack` (TASK-220) is the in-flight
write-back that fires when a task completes with
`auto_link: true`. The job currently:

1. Creates a `derived_from` link to the task.
2. Creates an `authored_by` link to the agent.
3. Dispatches `DetectKnowledgeLinks`.
4. Refreshes the topic index.

After the redesign:

1. The "create a knowledge entry" call from the task
   completion payload is now a *typed page write*. The
   payload is still `value` JSON-shaped for backwards
   compat (see §9.4) but the entry is stored with `body`
   and `frontmatter` derived from it. A small adapter in
   the writer maps `{title, summary, content, tags}` to
   `{type: 'source', body: '# <title>\n\n<content>',
   frontmatter: { tags, source_sha256: <derived from the
   task result>, ... }}`.
2. The `derived_from` link's target is the originating **task**,
   so it stays a `knowledge_link` (polymorphic `target_type =
   task`); it is **not** a `wiki_link`, which can only target a
   wiki page (`target_entry_id` → `knowledge_entries`, §6.3).
   The `derived_from` `link_type` on `wiki_links` is reserved for
   page→page derivation (one entry derived from another entry).
3. The `authored_by` link stays a `knowledge_link`; a
   `wiki_link` is not appropriate because the link target
   is an agent, not a wiki page.
4. The topic-index refresh is replaced by a write to
   `log:<yyyy-mm-dd>-task-<id>` if the task's result
   introduces a new entity, or a *topic page update* if
   the task's result extends a known topic.

---

## 8. API + SDK changes

The external API gets a small set of additive changes. The
write path *adds* the typed shape while continuing to accept
the legacy `value` shape (dual-read) through Phases A–C; the
write path stops accepting `value` (422) only in Phase D. The
read path keeps emitting the old shape through Phase A; the SDK
gains typed methods.

### 8.1 `POST /api/v1/hives/{hive}/knowledge`

**Request body (new — becomes the only accepted shape in
Phase D):**

```json
{
  "type": "entity",
  "slug": "entity:redis-cluster-prod",
  "title": "Production Redis cluster",
  "body": "# Production Redis cluster\n\nThe shared Redis cluster used by services in this hive.\n\n## Sources\n\n- [[source:01HX…]]\n",
  "frontmatter": { "kind": "service", "owners": ["agt_01HX…"] },
  "tags": ["infra", "redis"],
  "scope": "hive",
  "visibility": "public",
  "source_ids": ["01HX…"],
  "sources": [{ "kind": "url", "uri": "https://…", "title": "…", "raw_excerpt": "…" }]
}
```

> Each id in `source_ids` is subject to the **attach-time write
> authorization rule** in §6.8: it must be either newly ingested in
> this same write, already readable by the caller through an
> existing citing page, or an **orphan source the caller itself
> ingested** (clause (c) — `captured_by = caller`, zero existing
> citing pages). Attaching a source the caller cannot
> already see — widening its derived ACL — returns **403** and
> rolls back.
>
> The optional `sources[]` array is the **transactional
> ingest-and-attach** path: each descriptor is ingested (creating
> or deduping a `knowledge_sources` row, §6.2) **and** appended to
> this page's `source_ids` *inside the same write transaction*, so
> it satisfies attach rule (a) directly. This is the single-call
> alternative to the two-step `ingest_source()` →
> `create_page(source_ids=[…])` flow, and both converge on the same
> attach-time authorization — neither can dead-end and neither can
> widen a source the caller cannot already hold.

**Request body (legacy — accepted through Phase C, dropped
in Phase D):**

```json
{
  "key": "facts:redis-cluster-prod",
  "value": { "title": "...", "summary": "...", "content": "..." },
  "scope": "hive"
}
```

The Form Request validates one of two shapes and 422s if
both are present or neither is.

### 8.2 `PUT /api/v1/hives/{hive}/knowledge/{entry}`

Same dual-shape as POST. The legacy `value` is converted
synthetically to a `body` (a markdown rendering of
`title + content`) so that legacy clients see a one-version
"upgrade" rather than an immediate refusal.

### 8.3 `GET /api/v1/hives/{hive}/knowledge/{entry}`

Response includes both new and old fields during the
transition:

```json
{
  "id": "kxe_01HX…",
  "type": "entity",
  "slug": "entity:redis-cluster-prod",
  "title": "Production Redis cluster",
  "summary": "The shared Redis cluster used by services in this hive.",
  "body": "# Production Redis cluster\n\n…",
  "frontmatter": { "kind": "service", "owners": ["agt_01HX…"] },
  "tags": ["infra", "redis"],
  "source_ids": ["01HX…"],
  "wiki_links": { "outgoing": [...], "incoming": [...] },
  "sources": [{ "id": "01HX…", "uri": "https://…", "title": "…", "captured_at": "..." }],
  "scope": "hive",
  "visibility": "public",
  "version": 3,
  "lint_state": "ok",
  "stats": { "read_count": 12, "last_read_at": "..." },
  "created_at": "...", "updated_at": "..."
}
```

The `value` field is removed in Phase D. The current
`formatEntry()` (L1364-1382 in `KnowledgeController`)
becomes a "compose body + frontmatter + type" call.

### 8.4 New endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/hives/{hive}/knowledge/sources` | List raw sources **the agent can see through a referencing page** — only sources cited by at least one page the caller can read under `checkReadAccess` (§6.8); plus the `kind` / `since` filters |
| `GET` | `/api/v1/hives/{hive}/knowledge/sources/{id}` | Fetch a single source (read-only). Succeeds **only if** the caller can read a page whose `source_ids` contains `{id}` (§6.8); otherwise returns 404 (same not-found shape as a hidden page, so existence is not leaked) |
| `POST` | `/api/v1/hives/{hive}/knowledge/sources` | Ingest a new raw source (used by the write-back job, the fillin agent, and the URL-ingest tool). The returned source begins as an **orphan** (zero citing pages); its originator (`captured_by`) may later attach it to a page under §6.8 attach rule (c). For a single-call ingest-and-attach, pass the source inline via `create_page(sources=[…])` (§8.1) instead. |
| `GET` | `/api/v1/hives/{hive}/knowledge/types/{type}/list` | `list_by_type()` — return all pages of a given type in scope order (newest first) |
| `GET` | `/api/v1/hives/{hive}/knowledge/{entry}/backlinks` | `get_backlinks()` — all wiki pages that `[[…]]` this page |
| `POST` | `/api/v1/hives/{hive}/knowledge/synthesize-topic` | `synthesize_topic()` — given a list of source ULIDs, dispatch a topic-synthesis task that writes a new `topic:` page and emits a `log:` entry |

#### Route registration order — literal routes MUST precede the `{entry}` wildcard

The existing `GET /api/v1/hives/{hive}/knowledge/{entry}` (the
show action, §8.3) is a **wildcard** that matches any single path
segment. The new literal segments above — `sources`,
`types`, and the per-entry sub-resource `backlinks` — collide with
it: a request to `/knowledge/sources` would match `{entry}` with
`entry = "sources"` and dispatch to the show action. Laravel
resolves routes **in registration order, first match wins**, so
the only way the literal routes win is to register them **before**
the wildcard. The implementation MUST therefore, in **both**
`routes/api.php` (the agent API) and `routes/web.php` (the
dashboard, which adds the literal `/knowledge/wiki` index/catalog
page, §10), place the literal `/knowledge/...` routes **above**
the `GET /knowledge/{entry}` declaration. As a defence-in-depth
second layer, the wildcard is additionally constrained so it can
**never** capture a reserved literal segment:

```php
// routes/api.php — literal routes FIRST …
Route::get('knowledge/sources',            [KnowledgeSourceController::class, 'index']);
Route::get('knowledge/sources/{id}',       [KnowledgeSourceController::class, 'show']);
Route::post('knowledge/sources',           [KnowledgeSourceController::class, 'store']);
Route::get('knowledge/types/{type}/list',  [KnowledgeController::class, 'listByType']);
Route::get('knowledge/{entry}/backlinks',  [KnowledgeController::class, 'backlinks']);
Route::post('knowledge/synthesize-topic',  [KnowledgeController::class, 'synthesizeTopic']);
// … then the wildcard, constrained so reserved slugs can never be captured:
Route::get('knowledge/{entry}', [KnowledgeController::class, 'show'])
    ->where('entry', '(?!sources$|types$|wiki$|synthesize-topic$).+');
```

The same ordering-then-constraint pattern applies to `routes/web.php`
for the dashboard `/knowledge/wiki` and `/knowledge/sources/{id}`
detail routes (§10). The `whereNotIn`/regex constraint is belt-and-braces:
correct ordering alone is sufficient, but the constraint makes a
future re-ordering regression fail loudly (404 on the wildcard)
rather than silently routing `sources`/`wiki` to the show action.
Route tests for every new literal path are a hard gate — see §8.6
(`KnowledgeRouteOrderingTest`).

### 8.5 SDK changes — `superpos-agent-core`

`/workspace/repos/superpos-agent-core/src/superpos_agent_core/superpos_client.py`
gains new methods (new file
`src/superpos_agent_core/knowledge.py` for the typed layer;
the existing `knowledge` methods stay in `superpos_client.py`
for one release as shims):

| New SDK method | Maps to |
|---|---|
| `create_page(hive, type, slug, body, frontmatter, source_ids=None, sources=None, tags=None, scope='hive', visibility='public')` | `POST /knowledge` with the new shape. `sources=` is the transactional ingest-and-attach list (§6.8/§8.1): each descriptor is ingested and attached in the same write, satisfying attach rule (a). |
| `update_page(hive, entry_id, body=None, frontmatter=None, title=None, tags=None, append_body=None)` | `PUT /knowledge/{id}` — supports partial body updates and "append a paragraph" |
| `get_backlinks(hive, entry_id) -> list[dict]` | `GET /knowledge/{id}/backlinks` |
| `list_by_type(hive, type, limit=50, scope='hive') -> list[dict]` | `GET /knowledge/types/{type}/list` |
| `synthesize_topic(hive, source_ids, slug=None) -> dict` | `POST /knowledge/synthesize-topic` |
| `ingest_source(hive, kind, uri, title=None, raw_excerpt=None, metadata=None) -> dict` | `POST /knowledge/sources` |
| `get_source(hive, source_id) -> dict` | `GET /knowledge/sources/{id}` |
| `list_sources(hive, kind=None, since=None) -> list[dict]` | `GET /knowledge/sources` |
| `get_wiki_index(hive, scope='hive') -> dict` | Returns the in-wiki `slug=index` page (markdown body + parsed link list) |
| `get_wiki_log(hive, since=None) -> dict` | Returns the in-wiki `slug=log` page (markdown body) |

The existing `create_knowledge`, `update_knowledge`,
`get_knowledge`, `list_knowledge`, `search_knowledge` keep
working but route through the legacy-shape branch of the
controller. They become deprecated in the SDK in the same
release and removed in the release *after* Phase E.

The new file `src/superpos_agent_core/wiki/AGENTS.md` is
the procedural schema the bookkeeper follows. It is loaded
by the agent at fillin time and *not* sent on every API
call. The agent constructs its `WikiWrite` operations by
following the rules in AGENTS.md and emits them via
`create_page` / `update_page`.

### 8.6 New tests

**Server-side (PHP feature tests, `tests/Feature/Knowledge/`):**

- `PhaseAMigrationCompatibilityTest.php` — proves the additive
  Phase A migration is safe on a **populated** table (§6.1.1,
  §9.1). These tests are a **hard gate** on the Phase A migration:
  - **`ALTER` succeeds on legacy rows:** seed several existing
    `value`-only `knowledge_entries` rows, run the Phase A
    migration, and assert it completes without error and that the
    legacy rows survive with `NULL` `slug`/`type`/`body` and
    `'{}'`-defaulted `frontmatter`/`tags`/`source_ids` (no
    placeholder slugs, no data loss).
  - **Partial unique index does not collide on legacy rows:**
    with *many* unconverted legacy rows present (all `NULL`
    `slug`/`type`), assert the
    `idx_knowledge_hive_slug_scope` / `idx_knowledge_organization_slug_scope`
    partial indexes accept them all (they are outside the
    `slug IS NOT NULL AND type IS NOT NULL` predicate) and that
    two *converted* rows sharing the same
    `(organization_id, hive_id, slug, type, scope)` are still
    rejected as a duplicate.
  - **Org index does not constrain orphaned non-org rows:** seed
    two hive/agent-scoped rows whose `hive_id` is `NULL` (simulating
    rows orphaned by a deleted hive) that share the same
    `(organization_id, slug, type, scope)` with a non-org `scope`
    (e.g. `scope = 'hive'`), then backfill `slug`/`type` on both
    (the Phase C state). Assert that **both** rows coexist — i.e.
    `idx_knowledge_organization_slug_scope` does **not** reject them,
    because it is predicated on `scope IN ('organization','apiary')`
    and these rows are out of its predicate. A genuinely org-scoped
    pair sharing the tuple is still rejected. This guards against the
    over-broad `hive_id IS NULL` predicate aborting the Phase C
    constraint-tightening migration on orphaned rows (§6.6).
  - **Constraints enforced only post-Phase-C:** assert that in the
    Phase A/B state inserting a typed row with `NULL` `type`/`slug`
    is allowed, and that after the Phase C backfill +
    constraint-tightening migration the same `NULL`-typed insert is
    rejected (`NOT NULL`) and a duplicate converted slug collides on
    the now-effectively-full unique index.
  - **Legacy duplicate-key guard survives the partial re-key (the
    contract the review flagged):** with the codebase in the Phase
    A/B/C state, seed an existing `value`-only `knowledge_entries`
    row with `key = facts:x` (NULL `slug`/`type`, so it is *outside*
    the new partial indexes). Then `POST /knowledge` with the same
    legacy `key = facts:x`. Assert it still returns **409** (the
    legacy `key` unique index is retained through Phases A–C and
    catches the duplicate before `KnowledgeController::store`
    converts it to a typed row) — it must **not** insert a second
    row. Repeat for an org-scoped key against the org-scoped legacy
    index. This guards against the partial `slug`/`type` re-key
    silently dropping the duplicate-key contract for unconverted
    legacy rows (§6.6, §9.1, §9.3).
- `LegacyValueDeprecationContractTest.php` — pins the phased
  `value` deprecation contract (§3, §8, §9.1–§9.4) so the
  overview and the phased plan can never drift apart again.
  These tests are a **hard gate** on the deprecation phases:
  - **Phase A–C dual-write accepted:** with the codebase in the
    Phase A/B/C state, `POST` / `PUT /knowledge` carrying a
    legacy `value=…` payload (no `body`/`type`) **succeeds**
    (2xx) and is converted to a stored `body` + `frontmatter`
    page; a payload carrying the new typed `body` shape also
    succeeds. Both shapes coexist for the whole A–C window.
  - **Phase A–C task write-back dual-shape:** a
    `CompleteTaskRequest` carrying `knowledge_entries.*.value`
    (the legacy write-back shape) **succeeds** in Phases A–C and
    write-back stores a typed page — i.e. the
    `knowledge_entries.*.value` rule is *not* `required`-only, so
    legacy clients and task completion keep working. (Mirrors the
    `ProcessKnowledgeWriteBack` dual-shape tests above.)
  - **422 only in Phase D:** after the Phase D migration, the
    same legacy `value=…` `POST`/`PUT` and the same
    `knowledge_entries.*.value`-only write-back both return
    **422** with a pointer to the typed shape, and *only* then.
    The test asserts the 422 does **not** fire in the A–C state,
    guarding against an early-deprecation regression.
- `SourceVisibilityTest.php` — proves the §6.8 source read ACL.
  These tests are a **hard gate** on the raw-layer endpoints and
  must be added with the Phase C wiring:
  - **Agent-scoped isolation (the core leak the review flagged):**
    agent A creates an `agent:{A}`-scoped private page citing a
    `task_result` source `S`. Agent B (different agent, same hive,
    holds `knowledge.read`) **cannot** `GET /knowledge/sources/{S}`
    (gets 404) and **cannot** see `S` in `GET /knowledge/sources`
    (`list_sources`). Agent A *can* fetch and list `S`.
  - **Hive scoping:** a source cited only by a hive-scoped page in
    hive H1 is invisible to an agent operating in hive H2.
  - **Organization scoping:** a source cited by an
    organization-scoped page is visible to every agent in the org.
  - **Orphan source:** a source with zero referencing pages is
    unreadable via both `GET .../sources/{id}` and the list
    endpoint by everyone (its derived audience is empty until a
    page cites it).
  - **Ingest-then-attach does not dead-end (attach rule (c), the
    flow the review flagged):** agent A calls `ingest_source()`
    (standalone `POST /knowledge/sources`), receiving an orphan
    source `S` (`captured_by = A`, zero citing pages). In a
    *separate* later request A calls
    `create_page(..., source_ids=[S])`. Assert the attach
    **succeeds** — clause (c) holds because A is `S`'s originator
    and `S` is still an orphan — and that after the attach `S` is
    readable by A through the new page. Then assert a **different**
    agent B (same hive, holds `knowledge.write`) attempting the
    same `create_page(source_ids=[S])` against a still-orphan `S`
    it did **not** ingest is **rejected (403)** — clause (c) is
    narrowly the originator's, not a general orphan-attach loophole.
  - **Transactional ingest-and-attach (attach rule (a) via
    `sources=`):** agent A calls
    `create_page(..., sources=[{kind,uri,…}])` in a single request.
    Assert the source is ingested **and** attached atomically (it
    appears in the page's `source_ids`), the whole thing commits in
    one transaction, and a downstream read of the page resolves the
    source — i.e. the single-call path never produces an
    unattachable orphan.
  - **Union audience:** a source cited by *both* an `agent:{A}`
    page and a hive page is visible to the whole hive (the widest
    referencing page wins); removing the hive page re-narrows it
    to agent A.
  - **Not-found shape parity:** the 404 for a source the agent may
    not see is byte-for-byte the same as the 404 `checkReadAccess`
    returns for a hidden page, so existence is never leaked.
  - **No write-side widening (the attach-time rule in §6.8):**
    agent A owns an `agent:{A}`-private page citing source `S`.
    Agent B (same hive, holds `knowledge.write`) attempts to
    `POST` / `PUT` a `hive`- or `organization`-visible page that
    cites `S`. The write is **rejected (403) and rolled back**; `S`
    does **not** become hive-readable, and B still gets a 404 on
    `GET /knowledge/sources/{S}`.
  - **Expired-citation parity:** a source cited *only* by a page
    whose `ttl` has elapsed returns the same **404** (single fetch)
    and is absent from `GET /knowledge/sources` (list), exactly as
    an expired knowledge entry — mirroring `notExpired()` on the
    derived source ACL.

- `KnowledgeRouteOrderingTest.php` — proves the new literal
  routes are dispatched to their own actions and never captured by
  the `GET /knowledge/{entry}` wildcard (§8.4, the route-collision
  the review flagged). A **hard gate** on the route wiring in
  `routes/api.php` and `routes/web.php`:
  - **Literal API routes resolve to their own controllers:**
    `GET /knowledge/sources` resolves to the source-list action
    (not the entry-show action), `GET /knowledge/sources/{id}` to
    the source-show action, `GET /knowledge/types/{type}/list` to
    `listByType`, `GET /knowledge/{entry}/backlinks` to
    `backlinks`, and `POST /knowledge/synthesize-topic` to
    `synthesizeTopic`. Each assertion checks the resolved
    route/controller action (e.g. via `Route::getRoutes()->match()`
    or by asserting the action's distinct response shape), so a
    regression that lets the wildcard swallow `sources`/`types`
    fails the test.
  - **An entry literally named like a reserved segment is still
    not reachable as a page:** assert `GET /knowledge/sources`
    never returns a single-entry show payload even if a row with
    `slug = "sources"` somehow exists — the literal route wins.
  - **Wildcard constraint rejects reserved slugs:** with the
    literal routes deliberately removed/commented (or via a unit
    test on the route's `where` pattern), assert the constrained
    `{entry}` route does **not** match `sources` / `types` / `wiki`
    / `synthesize-topic` (it 404s on the wildcard), proving the
    defence-in-depth constraint holds independently of registration
    order.
  - **Dashboard route parity:** `GET /knowledge/wiki` (web.php)
    resolves to the wiki index/catalog page (§10), not the
    entry-show page, under the same ordering+constraint.
- `KnowledgeSourcesTest.php` — proves the raw-layer dedupe
  partition and the hive-deletion referential action agree (§6.2,
  §6.7). These tests are a **hard gate** on the
  `knowledge_sources` migration and guard the schema-migration
  blocker the review flagged:
  - **Hive deletion with a shared source does not fail (the core
    bug):** two hives `H1` and `H2` in the same org each ingest the
    *same* source — identical `(organization_id, content_sha256,
    kind)`, each with `origin = 'hive'` and its own `hive_id`. Both
    inserts succeed (they are distinct under `uq_source_dedup_hive`).
    Delete `H1`, then delete `H2`. Assert **both deletions succeed**
    (no `uq_source_dedup_org` violation, no `restrict_violation`
    from the immutability trigger), that each deleted hive's source
    row survives as an orphan with `hive_id = NULL` and unchanged
    `origin = 'hive'`, and that the two NULL-`hive_id` orphans
    coexist (Postgres treats their NULL `hive_id` as distinct).
  - **Orphans never enter the org partition:** after the deletions
    above, insert a genuine org-wide source (`origin = 'org'`,
    `hive_id = NULL`) with the *same* `(organization_id,
    content_sha256, kind)` as the two orphans. Assert it inserts
    successfully — i.e. the orphaned `origin = 'hive'` rows are
    **absent** from `uq_source_dedup_org`, so they neither block the
    org row nor get deduped against it.
  - **Org-wide dedupe still holds:** inserting a *second* org-wide
    source (`origin = 'org'`) with a `(organization_id,
    content_sha256, kind)` already held by an existing `origin =
    'org'` row is rejected as a duplicate by `uq_source_dedup_org`.
  - **`origin` is immutable:** a direct `UPDATE` of `origin` on a
    stored source is rejected by the §6.7 trigger
    (`restrict_violation`), so a row can never jump dedupe
    partitions.
  - **`origin = 'org'` rows can never hold a `hive_id`:** inserting
    or updating an `origin = 'org'` row with a non-NULL `hive_id` is
    rejected by `chk_source_origin_org`.

- `MigrateLegacyKnowledgeEntriesTest.php` — proves the Phase C
  migration is an **in-place backfill** that preserves
  `knowledge_entries.id` and never orphans a dependent (§9.3,
  §9.6, §1851-region prose). These tests are a **hard gate** on
  `MigrateLegacyKnowledgeEntries`:
  - **Kept rows keep their id (in-place update, no copy):** seed
    a kept legacy `value`-only entry, record its
    `knowledge_entries.id`, run the migration, and assert the
    **same id** still exists with the backfilled
    `slug`/`type`/`body`/`frontmatter`/`tags`/`source_ids` — the
    row is *updated in place*, not copied to a new id and the old
    row deleted.
  - **Dependent references stay valid:** seed a kept entry that is
    referenced by a `knowledge_link` (`source_id`/`target_id`), a
    `workflow_step_knowledge.knowledge_entry_id`, a
    `tasks.knowledge_entry_id`, and a
    `knowledge_read_events.knowledge_entry_id`. After the
    migration, assert **every one of those foreign references
    still resolves to the same (now-backfilled) row** — no remap,
    no dangling reference, no orphan.
  - **Only nuked rows are deleted:** seed entries that match the
    "nuked" rules (`_index:*`, `_health:*`, empty `value`,
    stale/unreferenced, operational TTL) and assert that **only**
    those rows are deleted, while every kept row survives with its
    original id.
  - **Idempotent re-run:** running the migration a second time is
    a no-op on already-backfilled kept rows (no duplicate rows, no
    id churn) and leaves all dependent references valid.
  - **Constraint tightening succeeds with kept AND non-kept rows
    present (the deletion-timing contract the review flagged):**
    seed a mix of *kept* legacy `value`-only rows (matching the
    §9.6 keep rules) and *non-kept* legacy rows (matching the §9.6
    "nuked" rules — `_index:*`, `_health:*`, empty `value`, stale/
    unreferenced, operational TTL), all with NULL `slug`/`type`/
    `body`. Run the full Phase C migration (in-place backfill of
    kept rows → delete of non-kept rows → constraint-tightening
    `ALTER COLUMN … SET NOT NULL` + drop of the legacy `key`
    indexes). Assert that:
    - the migration **completes without error** — the `SET NOT
      NULL` does **not** abort, because every non-kept (still-NULL)
      row was deleted *before* the tightening step, leaving no row
      with a NULL typed field;
    - after it runs, **no** `knowledge_entries` row has a NULL
      `type`/`slug`/`body`, the non-kept rows are gone, and the
      kept rows are backfilled and retain their original ids;
    - the legacy `key` unique indexes have been dropped and the
      partial `slug`/`type` indexes are now the sole uniqueness
      authority (a duplicate converted slug is rejected).
    This pins the single deletion-timing contract (delete non-kept
    rows in Phase C *before* tightening, §9.3/§9.6) and guards
    against the regression where non-kept rows survive with NULL
    typed fields and break the `SET NOT NULL` migration.

**SDK (`superpos-agent-core`):**

- `tests/test_superpos_client_knowledge_typed.py` — covers
  every new method with happy paths, validation failures
  (missing `type`, malformed frontmatter), and scope errors
  (writing org-scoped from a hive-scoped agent).
- `tests/test_get_source_visibility.py` — asserts the SDK
  surface of §6.8: `get_source` / `list_sources` raise / return
  empty for a source attached only to another agent's private
  page (the SDK-level mirror of `SourceVisibilityTest`). It also
  mirrors the two new gating cases: (1) `create_page` /
  `update_page` from agent B citing agent A's `agent:{A}`-private
  source raises (403) and leaves the source un-widened — still
  unreadable to B; and (2) a source cited only by an expired
  (`ttl`-elapsed) page makes `get_source` raise / `list_sources`
  return empty, the same as an expired entry.
- `tests/test_wiki_link_parser.py` — pure-Python unit tests
  for the `[[…]]` parser (Obsidian-flavoured rules, alias
  syntax, `source:` / `task:` / `agent:` namespaces,
  unresolved-link handling). Must assert the routing contract
  from §6.5: only bare page refs (`[[slug]]`, `[[slug|alias]]`)
  yield `wiki_links`; `[[source:…]]` routes to `source_ids`;
  `[[task:…]]` / `[[agent:…]]` route to `knowledge_links`, and
  **none** of those three ever produce a `wiki_links` row.
- `tests/test_aggressive_knowledge_legacy_shim.py` — proves
  that legacy `create_knowledge(value=…)` calls still work
  in Phase A–C and return a 422 in Phase D.

---

## 9. Phased migration plan

Five phases. A, B, C are additive and reversible. D drops
the legacy column. E removes the dead code.

### 9.1 Phase A — additive landing (no removals)

**Scope:**

- Migration: add `type`, `slug`, `title`, `body`, `frontmatter`,
  `summary`, `tags` (array), `source_ids` (array),
  `last_linted_at`, `lint_state` to `knowledge_entries`.
  Add `knowledge_sources` and `wiki_links` tables. Add the
  `search_vector` regeneration.
  - **The new typed columns are added nullable / defaulted, NOT
    `NOT NULL` (§6.1.1).** `knowledge_entries` is live and full
    of existing `value`-only rows, and Phase A is additive and
    reversible — so this `ALTER` must succeed against a populated
    table without forcing placeholder values. Concretely:
    `type`, `slug`, `title`, `body` are added **nullable**;
    `frontmatter`, `tags`, `source_ids` are added with a default
    of `'{}'` (empty object / empty array) so existing rows are
    immediately valid. `title` is added nullable here purely as a
    compatibility column so the `search_vector` regeneration (which
    references `title`) is valid on the live table; it is backfilled
    from `frontmatter.title` by the Phase C backfill and can be
    tightened to `NOT NULL` afterwards alongside `slug`/`type`/`body`
    (§6.1.1, §9.3). `tags` and `source_ids` are declared as native
    PostgreSQL arrays (`text[]`), **not** `jsonb`, so the array
    operators (`@>`, `= ANY(...)`) and GIN array indexes in §6.6 and
    the contracts apply directly.
    No backfill happens here — existing rows keep `value` and
    carry `NULL` `slug`/`type` until the Phase C migration
    converts the kept ones.

    ```php
    Schema::table('knowledge_entries', function (Blueprint $table) {
        $table->string('type', 20)->nullable();          // backfilled + NOT NULL in/after Phase C
        $table->string('slug', 255)->nullable();          // backfilled + NOT NULL in/after Phase C
        $table->string('title', 255)->nullable();         // backfilled in Phase C; can be tightened to NOT NULL alongside slug/type/body
        $table->text('body')->nullable();                 // backfilled + NOT NULL in/after Phase C
        $table->jsonb('frontmatter')->default('{}');
        $table->text('summary')->nullable();
    });

    // tags / source_ids are first-class PostgreSQL arrays (§6.1, §6.6),
    // so they are declared with raw array DDL rather than the jsonb()
    // builder. Both default to the empty array '{}' so every existing
    // value-only row is immediately valid, and the GIN array indexes +
    // `@>` / `= ANY(...)` operators in the contracts stay applicable.
    DB::statement("ALTER TABLE knowledge_entries ADD COLUMN tags text[] NOT NULL DEFAULT '{}'");
    DB::statement("ALTER TABLE knowledge_entries ADD COLUMN source_ids text[] NOT NULL DEFAULT '{}'");  // ULID strings, refs knowledge_sources.id

    Schema::table('knowledge_entries', function (Blueprint $table) {
        $table->timestampTz('last_linted_at')->nullable();
        $table->string('lint_state', 20)->nullable();
    });
    ```
  - **The new typed-page unique indexes are created PARTIAL and
    ADDED ALONGSIDE the pre-existing legacy `key` indexes — the
    legacy indexes are NOT dropped or re-keyed in Phase A** (§6.6).
    The new partial indexes are predicated `WHERE slug IS NOT NULL
    AND type IS NOT NULL` (in addition to the existing `hive_id` /
    `scope` predicates). Because the legacy rows have `NULL`
    `slug`/`type` in Phase A, they are absent from these new
    indexes and cannot collide with one another or with
    later-converted rows. This is why Phase A can land the
    uniqueness machinery *before* the Phase C backfill without
    breaking on existing data.

    **Crucially, the legacy `key` unique indexes stay in place
    through Phases A–C** so that legacy rows — which are outside the
    new partial indexes — keep their duplicate-key guard. A Phase A
    legacy `POST` for an already-present `key` therefore still hits
    the legacy unique index and returns the current **409**
    conflict that `KnowledgeController::store` relies on. Dropping
    them in Phase A would leave such a row guarded by neither index
    and let a duplicate be inserted as a typed row. The legacy
    indexes are dropped only in Phase C, after the backfill+delete
    (§9.3), when no NULL-`slug`/`type` rows remain.

    ```sql
    -- New partial typed-page indexes (added; do NOT collide with the
    -- pre-existing legacy key indexes, which are retained here).
    CREATE UNIQUE INDEX idx_knowledge_hive_slug_scope
      ON knowledge_entries (organization_id, hive_id, slug, type, scope)
      WHERE slug IS NOT NULL AND type IS NOT NULL
        AND hive_id IS NOT NULL AND scope NOT IN ('organization','apiary');

    CREATE UNIQUE INDEX idx_knowledge_organization_slug_scope
      ON knowledge_entries (organization_id, slug, type, scope)
      WHERE slug IS NOT NULL AND type IS NOT NULL
        AND scope IN ('organization','apiary');

    -- Legacy indexes idx_knowledge_hive_key_scope /
    -- idx_knowledge_organization_key_scope are LEFT IN PLACE here.
    -- They are dropped in the Phase C constraint-tightening migration
    -- (§9.3) once the backfill+delete leaves no NULL-slug/type rows.
    ```
  - **The `NOT NULL` / full typed-page constraints are NOT
    enforced in Phase A.** They are tightened only **after** the
    Phase C backfill has populated `slug`/`type`/`body`/
    `frontmatter` on every kept legacy row (a small
    constraint-tightening migration at the tail of Phase C —
    `ALTER COLUMN type SET NOT NULL`, `slug SET NOT NULL`, `body
    SET NOT NULL` — gated on a check that no kept row still has a
    NULL typed field). The same migration also **deletes the
    non-kept legacy rows first** and then **drops the now-redundant
    legacy `key` unique indexes** (§9.3, §9.6). The partial-index
    predicates remain in place afterwards (harmless once the columns
    are `NOT NULL`, and they document intent). See §6.1.1 and §9.3.
- **Migration: enable the `pg_trgm` extension** in its own
  PostgreSQL-guarded migration that *precedes* the index
  migration. The `idx_knowledge_slug_trgm` GIN index (§6.6)
  depends on the `gin_trgm_ops` operator class, which lives in
  `pg_trgm`; without this step the index creation aborts with
  `operator class "gin_trgm_ops" does not exist` on a DB that
  has `vector` but not `pg_trgm`. The migration mirrors the
  existing pgvector enabler
  (`2026_04_15_100000_enable_pgvector_extension.php`) verbatim
  in shape — driver-guarded to `pgsql`, `CREATE EXTENSION IF
  NOT EXISTS` wrapped in a `try/catch` so non-PostgreSQL drivers
  (and PostgreSQL builds without `pg_trgm` available) skip
  gracefully, with the trigram index treated as optional at
  index-build time:

  ```php
  // database/migrations/2026_xx_xx_enable_pg_trgm_extension.php
  // Ordered BEFORE the knowledge index migration.
  public function up(): void
  {
      if (DB::getDriverName() !== 'pgsql') {
          return; // SQLite / MySQL — fuzzy slug search degrades to exact/ILIKE.
      }

      try {
          DB::statement('CREATE EXTENSION IF NOT EXISTS pg_trgm');
      } catch (\Throwable $e) {
          // Extension not available — skip gracefully.
          // The migration that builds idx_knowledge_slug_trgm checks for
          // pg_trgm first and skips the trigram index when it is absent;
          // fuzzy slug lookup falls back to exact / ILIKE matching.
      }
  }

  public function down(): void
  {
      if (DB::getDriverName() !== 'pgsql') {
          return;
      }

      DB::statement('DROP EXTENSION IF EXISTS pg_trgm');
  }
  ```

  The index migration that creates `idx_knowledge_slug_trgm`
  guards the statement on `pg_trgm` being present (e.g.
  `SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'`) and
  skips the trigram index when the extension could not be
  enabled, so a stock PostgreSQL without `pg_trgm` still
  migrates cleanly.
- Model: `KnowledgeEntry` gains new fillable / cast entries
  for the new columns. The old `value` stays fillable.
- Controller: `KnowledgeController::store` and `update`
  accept the *new* shape; the legacy shape is *also*
  accepted and converted. `formatEntry()` returns both.
- SDK: new methods added; old methods kept.
- UI: `Show.jsx` gets a *new* panel above the existing
  JSON dump: "Body" (markdown-rendered), "Frontmatter"
  (key/value list), "Sources" (list of source ULIDs with
  links), "Backlinks" (computed). The JSON dump stays
  visible in Phase A as a sanity check.

**Reversibility:** any time before Phase D, `git revert` the
merge. The legacy `value` column is still there and the
legacy code path is still active.

**Bake:** one full agent cycle (the existing
`apiary:run-knowledge-curator` and `apiary:knowledge-fillin`
commands run on a populated hive, produce some new-shape
pages, the dashboard renders them, no regressions in
`search_knowledge` or `list_knowledge`).

### 9.2 Phase B — bookkeeper rewrite

**Scope:**

- `KnowledgeFillinService` prompt is rewritten to ask for
  typed `WikiWrite` operations. The exemplars are updated
  to typed pages.
- `RunKnowledgeCurator` produces typed pages instead of
  JSON blobs. The `_health:latest` JSON entry is replaced
  by a `procedure:health-check` page.
- `KnowledgeIndexService` is rewritten to write the in-wiki
  `slug=index` and `slug=log` pages instead of the
  `_index:*` JSON entries. The old method names are kept
  as thin wrappers that call the new ones.
- `AGENTS.md` is written and shipped in the SDK.
- `ProcessKnowledgeWriteBack` produces typed pages.

**Reversibility:** `git revert` the merge. The legacy
`value` column is still there; the writer-side just
*also* writes typed pages.

**Bake:** two full curator / fillin cycles on the populated
hive. Verify the new `slug=index` page renders, the
fillin agent's prompt no longer asks for `{title, summary,
content}`, and the dashboard's "Drill into raw sources"
panel shows ingested sources.

### 9.3 Phase C — raw layer wiring

**Scope:**

- `knowledge_sources` table is populated by the write-back
  job and the URL-ingest tool. New endpoints and SDK methods
  are wired (`ingest_source`, `get_source`, `list_sources`).
  The source read endpoints (`get_source`, `list_sources`)
  **must** enforce the §6.8 derived-visibility ACL from the
  moment they ship — a source is readable only through a page
  the caller can see under `checkReadAccess` — and the
  `SourceVisibilityTest` gating tests (§8.6) land in this phase.
- The "Sources" panel in `Show.jsx` becomes functional.
- `wiki_links` are populated on every body write. The
  "Backlinks" panel becomes functional.
- A one-time migration script
  (`app/Console/Commands/MigrateLegacyKnowledgeEntries.php`)
  is run on existing hives. It does **not** migrate every
  entry; it migrates only the small set the proposal
  identifies as actively used (see §9.5). The script:
  - Reads each kept entry's `value`.
  - Heuristically assigns a `type` (e.g. `key` starts with
    `decisions:` → `topic`; `key` starts with `patterns:` →
    `procedure`; default `topic`).
  - Generates a `body` from the JSON value
    (`# {title}\n\n{summary}\n\n{content}`).
  - Extracts `tags` from `value.tags`.
  - Sets `frontmatter` to a sane default per type.
  - Generates a `slug` from the existing `key`.
  - Inserts a `knowledge_sources` row only for entries that
    reference a `value.source` URL we can fetch; otherwise
    leaves `source_ids` empty.
  - **Deletes every non-kept legacy row** (the §9.6 "nuked" set)
    in the *same* Phase C run, immediately after the kept rows are
    backfilled and **before** the constraint-tightening migration
    below. This is the single, canonical place the non-kept rows
    are removed (§9.6) — they are *not* carried forward to a later
    phase with NULL typed fields. Doing the deletion here is what
    leaves the table with **no** NULL-`slug`/`type` rows by the
    time constraints tighten.

- **Constraint tightening (post-backfill, post-delete).** Once the
  migration script above has populated `slug`/`type`/`body`/
  `frontmatter` on every *kept* legacy row **and deleted every
  non-kept legacy row** (§9.6), a follow-on migration tightens the
  typed-page invariants that Phase A deliberately left loose
  (§6.1.1, §9.1): `ALTER COLUMN type SET NOT NULL`, `slug SET NOT
  NULL`, `body SET NOT NULL`. This migration first asserts that no
  row at all still carries a NULL typed field (a guard query; it
  aborts loudly rather than silently corrupting). Because the
  non-kept rows were already deleted and the kept rows were
  backfilled, this guard passes — there is no surviving legacy row
  to fail the `SET NOT NULL`. The same migration then **drops the
  retained legacy `key` unique indexes** (§6.6): with no
  NULL-`slug`/`type` rows left, they no longer guard anything, and
  the partial `slug`/`type` indexes become the sole uniqueness
  authority. Those partial indexes stay as-is — their `WHERE slug
  IS NOT NULL AND type IS NOT NULL` predicate is now satisfied by
  every row, so they behave as full typed-page uniqueness from here
  on. (If a deployment prefers a single-pass Phase A instead, the
  alternative — backfilling every existing row, deleting the
  non-kept ones, and adding the `NOT NULL`/unique constraints all
  inside the same Phase A migration — is contractually equivalent;
  the proposal picks nullable-then-tighten because it keeps Phase A
  additive and reversible per §9.)

- **Task write-back contract — dual-shape acceptance.**
  `CompleteTaskRequest` currently *requires*
  `knowledge_entries.*.value` (`required` validation rule), so
  an old agent that posts the legacy `{title, summary, content,
  tags}` shape — and a new agent that posts the typed `{type,
  body, frontmatter, ...}` shape — cannot both succeed: one of
  them 422s before `TaskController::processKnowledgeWriteBack`
  ever runs. Phase C makes the request accept **both** shapes:
  - Relax/deprecate the `knowledge_entries.*.value` rule from
    `required` to `sometimes|nullable`, and add the new
    `knowledge_entries.*.{type,body,frontmatter,slug}` rules as
    `sometimes`. A `withValidator` closure requires that *one
    of* `value` or `body` is present (so an empty entry still
    422s).
  - `TaskController::processKnowledgeWriteBack` dispatches to
    `ProcessKnowledgeWriteBack` with whichever shape arrived;
    the job's adapter (§7.4 step 1) maps a legacy `value`
    payload to a typed page and passes a typed payload through
    unchanged. Both shapes converge on a stored `body` +
    `frontmatter` page.
  - This is the conversion shim. It is intentionally still
    present at the end of Phase C — it is what lets old agents
    keep completing tasks while the fleet rolls forward. It is
    **not** removed until Phase D, and only after the
    legacy-write scan (§9.4) returns zero.
  - **Tests added in Phase C** (these gate the phase): a
    `CompleteTaskRequest` test asserting it accepts the legacy
    `value` shape; one asserting it accepts the new `body`
    shape; one asserting an entry with *neither* `value` nor
    `body` is rejected 422; and a `ProcessKnowledgeWriteBack`
    test asserting both shapes produce an equivalent stored
    typed page (same `body`/`frontmatter`, same `derived_from`
    link). The future implementation must ship these
    dual-shape acceptance tests.

**Reversibility:** same as Phase B.

**Bake:** confirm the migrated entries show up in the
dashboard with the new shape, that the wiki `slug=index`
lists them, that search still finds them, and that task
completion succeeds for *both* a legacy-shape and a
typed-shape `knowledge_entries` payload.

### 9.4 Phase D — drop the legacy column

**Scope:**

- The legacy `value` column is dropped in a single
  migration. The `JSON.stringify(entry.value, null, 2)` panel
  in `Show.jsx` is removed.
- The legacy `value`-only Form Request validation in
  `CreateKnowledgeRequest` is removed; the new shape is
  required. `UpdateKnowledgeRequest` is updated to match.
- The Form Request returns 422 on legacy `value=…` payloads.
- The `KnowledgeController::store` and `update` legacy
  conversion path is removed.
- The SDK's `create_knowledge(value=…)` and
  `update_knowledge(value=…)` shims return a 422 with a
  pointer to the new `create_page` method.
- The `getValueTitleAttribute` / `getValueSummaryAttribute` /
  `getValueContentAttribute` / `getValueSourceAttribute` /
  `getValueConfidenceAttribute` / `getValueTagsAttribute` /
  `getValueFormatAttribute` accessors on `KnowledgeEntry` are
  removed.
- The task write-back conversion shim is **removed**. The
  dual-shape acceptance landed in Phase C (legacy
  `{title, summary, content, tags}` *and* typed payloads both
  accepted via the `ProcessKnowledgeWriteBack` adapter); Phase D
  retires the legacy half of it. `CompleteTaskRequest` drops the
  deprecated `knowledge_entries.*.value` rule entirely (the
  typed `body`/`frontmatter` shape becomes required), and the
  adapter's legacy-`value` branch is deleted. This is gated on
  the zero-result legacy-write scan below, so by the time the
  shim is removed no live agent is still emitting the legacy
  shape — the dual-shape window in Phase C is exactly what makes
  this safe. After this phase a legacy `value=…` write-back
  payload 422s.

**Reversibility:** the `value` column is gone, so this is
**irreversible** (data loss for any un-migrated entries).
The bake in Phase C must confirm that no caller is still
writing `value=…`. The pre-merge check: `grep -r
"'value'\s*=>" /workspace/repos/superpos-app/app` should
return only the conversion shim, which is removed in this
phase. (The Phase C dual-shape window keeps old agents working
right up until this scan reads zero; removing the shim here
does not contradict it — it is the planned end of that
window.)

**Bake:** before the column drop, a read-only `PreDropValueScanCommand`
artisan command (`php artisan knowledge:scan-legacy-writes`)
runs in dry-run mode and lists every code path that still
writes `value=…`. The PR can only merge when the scan
returns zero results.

### 9.5 Phase E — dead code removal

**Scope:**

- The `value`-keyed GIN index in migration
  `0001_01_01_000016_create_knowledge_entries_table.php` is
  dropped.
- The `value::text ILIKE` and `value->'tags' @> ?::jsonb`
  branches in `KnowledgeController::index` (L92-110) and
  `KnowledgeController::search` (L774-805) are dropped.
- The `_index:*` reservation is removed (no startup check).
  The legacy `_index:topics` / `_index:decisions` /
  `_index:agent:*` *rows* were already deleted in Phase C as
  part of the §9.6 "nuked" set (alongside every other non-kept
  legacy row); Phase E only retires the in-code reservation
  check, it does **not** delete any rows.
- The `formatSearchResult` fallback that builds a snippet
  from `value.title` / `value.content` / `value.summary`
  is replaced with a snippet builder that reads `body` and
  the matched `search_vector` lexeme.
- The `*RegistryPrimaryTest.php`-style legacy-mode tests
  for the JSONB value paths are deleted (mirroring the
  registry b2 §7 pattern).

**Reversibility:** irreversible in any practical sense
(the dead `value` accessors and reservation checks are gone,
and the legacy `_index:*` rows they referenced were already
removed back in Phase C). The bake in Phase D must confirm that
no agent is still asking for them via `knowledge_topics()` or
`knowledge_decisions()`.

### 9.6 Which entries get migrated, which get nuked

Phase C's migration script runs against a snapshot of the
current `knowledge_entries` table. The user has been
explicit: "drop all that we don't need." The bar for "kept"
is high.

**Kept (one-time migration):**

- Any entry that has been *read* more than 5 times in the
  last 90 days. These are entries the agents are actually
  consulting. They get migrated to typed pages, with `type`
  inferred from the key prefix.
- Any entry whose `value.frontmatter.decision` is true or
  whose key starts with `decisions:`. Decisions are the
  things the wiki is supposed to *preserve*; if there are
  decisions in the current store, the curator will rewrite
  them as `procedure:` pages on its next pass.
- Any entry referenced by an existing `knowledge_link`
  (auto-detected or confirmed) — its dependents point at
  it, and dropping it would orphan those links.
- Any entry that is the target of a `derived_from` knowledge
  link produced by `ProcessKnowledgeWriteBack` — i.e. a
  knowledge entry a task explicitly wrote back to memory. The
  keep rule uses the write-back's `derived_from` link
  provenance, **not** `created_by`: `KnowledgeEntry.created_by`
  is an *agent* ULID (the author), not a task/result reference,
  so it cannot tell us which entries originated from a task
  write-back. The `derived_from` link (created in §7.4 step 1)
  is the concrete task-origin signal. (If we later want a
  cheaper lookup than a link join, add an explicit
  task-origin column — e.g. `origin_task_id` — before relying
  on it; until then, `derived_from` is the source of truth.)

**Nuked (deleted in Phase C):**

- Entries that match the `_index:*` reservation (the
  new-shape index will replace them).
- Entries that match the `_health:*` reservation (the
  curator will rewrite them as `procedure:` pages).
- Entries whose `value` is empty (`{}`) or contains only
  null fields. A "stub" entry is worse than no entry.
- Entries that have not been read or written in 365 days
  AND are not referenced by any `knowledge_link` AND
  are not in the "kept" set above.
- Entries whose `value` is clearly *operational* rather
  than *durable* (e.g. `value.expires_at` < now+30d, or
  the entry has `ttl` set and the ttl is short). These
  are session-scoped notes that should never have been
  wiki material in the first place.

**Open question (see §13):** is the read-count threshold
right? My read is yes — entries with > 5 reads in 90 days
are "the agent uses these" and the rest are noise. But
this is configurable.

The migration is an **in-place backfill** (matching §9.3):
it **updates the rows it keeps in place** — populating
`slug`/`type`/`body`/`frontmatter`/`tags`/`source_ids` on the
*same* row, preserving each `knowledge_entries.id` — and
**deletes only the nuked (discarded) rows**. Kept rows are
never copied to a new id and the old row is never deleted, so
every existing reference to a kept entry stays valid:
`knowledge_links.source_id`/`target_id`,
`workflow_step_knowledge.knowledge_entry_id`,
`tasks.knowledge_entry_id`, `knowledge_read_events.knowledge_entry_id`,
and any serialized task/context references all continue to
resolve without a remap. (This is why a kept entry referenced
by a `knowledge_link` is never orphaned — see the keep rule
above.) The work runs in a transaction and is idempotent: if
the script crashes mid-run, the kept rows that were already
backfilled stay backfilled (re-running them is a no-op) and the
unprocessed rows are untouched, so a re-run resumes from where
the prior run left off.

A pre-migration report command
(`php artisan knowledge:migration-report`) prints the
list of entries that will be *deleted* before the
migration runs, so the operator can sanity-check.

---

## 10. UI redesign

`resources/js/Pages/Knowledge/Show.jsx` is the main surface
that needs rebuilding. The current rendering order is:
metadata grid → tags → confidence → ttl → summary card →
content card → "Value (JSON)" card (the bad one) → graph →
links. The new order is:

1. **Header**: title (from `entry.title` or first H1 of
   `entry.body`), `type` badge, `slug`, scope/visibility
   badges, version, lint state.
2. **Summary** (from `entry.summary` or first paragraph of
   body if summary is null).
3. **Body** — markdown-rendered. Uses `react-markdown`
   with `remark-gfm` for tables/strikethrough and a
   `[[wikilink]]` plugin that resolves to a router push
   on click.
4. **Frontmatter** — a small key/value table for
   transparency. Operators want to see what
   `last_refreshed` and `confidence` are.
5. **Sources** — list of `entry.sources`, each with a
   "view raw" link to the source detail page
   (`/knowledge/sources/{id}`).
6. **Backlinks** — list of `entry.wiki_links.incoming` —
   *authored* references from other pages. Each backlink
   shows the source page title, the slug, and a snippet
   of the surrounding text (from `wiki_links.source_span`).
7. **Graph** — same as today. Now shows `wiki_links`
   (authored) and `knowledge_links` (auto-detected) with
   different styling.
8. **Links** — same as today. Auto-detected links.
9. **Edit history** — the activity log entries for this
   page, filtered to `knowledge.created`,
   `knowledge.updated`, `knowledge.deleted`,
   `knowledge.lint_changed`. Two-line entries: timestamp,
   author (if any), what changed.

The `JSON.stringify(entry.value, null, 2)` panel is gone
in Phase D. Before then it sits at the bottom under a
collapse-titled "Legacy payload (will be removed in v{N+1})".

### 10.1 Per-type render templates

Each `type` gets a small template that decides which
panels are emphasised and what additional widgets show:

- **`entity`** — a "Aliases" chip row (from
  `frontmatter.aliases`), a "Related entities" section
  (from `frontmatter.related_entity_slugs`), a "Owners"
  row (from `frontmatter.owners` — agent ULIDs rendered
  as names).
- **`topic`** — a "Related topics" section, a
  "Superseded by" banner (from `frontmatter.superseded_by`)
  if non-null, and a "Sources" panel that lists
  *which sources the topic synthesised from* (this is the
  `source_ids` array, surfaced as the high-signal widget
  for topic pages: "this topic was synthesised from
  these 4 sources, last refreshed YYYY-MM-DD").
- **`trend`** — a "Timeline" widget: each H3 in the body
  is a dated observation; the widget renders them as a
  vertical timeline with a date column.
- **`source`** — a "Source document" panel that shows
  the raw excerpt and a "Captured at" / "Captured by"
  badge.
- **`log`** — a compact monospaced list; no decorations.
- **`procedure`** — a "Steps" widget that renders ordered
  list items as a numbered card stack; a "Review by"
  banner if `frontmatter.review_after_days` is set and
  past due.

### 10.2 The wiki index page

A new dashboard page at `/knowledge/wiki` (org-scoped) and
`/knowledge/wiki` (hive-scoped) renders the in-wiki
`slug=index` page as a navigable tree. It is the agent's
*catalog view* and the operator's "what does the agent
know?" view. The page reuses the body renderer; the index
body is just markdown with `[[wikilink]]`s.

### 10.3 The graph view

`Graph.jsx` (443 lines) renders `wiki_links` and
`knowledge_links` as two edge colours. Authored links are
solid; auto-detected links are dashed. Node colour is by
type (entity = blue, topic = green, trend = amber, source
= grey, log = purple, procedure = pink). The user can
filter by `?link_source=authored|auto|both` and by type.

The graph now also offers a "type cluster" view: nodes are
grouped by type into concentric rings. The agent can see
"all the entity pages this hive knows about" in one ring,
"all the topic pages" in the next, etc.

---

## 11. What's gone by the end

Listed exhaustively because the user said "drop all we don't
need" and we should be thorough.

**Code:**

- `app/Models/KnowledgeEntry.php` — drops all the
  `getValueTitleAttribute` / `getValueSummaryAttribute` /
  `getValueContentAttribute` / `getValueSourceAttribute` /
  `getValueConfidenceAttribute` / `getValueTagsAttribute` /
  `getValueFormatAttribute` accessors. The `value`
  cast is removed. The `value` field is removed from
  `$fillable`. The `scopeValueLike` scope is removed.
- `app/Http/Controllers/Api/KnowledgeController.php` — the
  `valueToString`, `buildFallbackSnippet`, and
  `formatSearchResult` helpers that read `value.title` /
  `value.content` / `value.summary` are removed. The
  hybrid RRF ranker's `value::text ILIKE` branch
  (L1051-1053) is removed. The `visibleLinkCount` /
  `formatEntry` JSON shaping is rewritten to project
  from `body + frontmatter + type + source_ids + tags`.
- `app/Http/Controllers/Api/AgentKnowledgeFillinController.php`
  — the controller's response shape changes (no
  `details.knowledge_created_count` heuristic; the new
  shape carries `pages_written`, `pages_updated`,
  `pages_linted`).
- `app/Http/Controllers/Api/KnowledgeLinkController.php` —
  unchanged on the auto-detected link side. No removal
  here.
- `app/Http/Controllers/Dashboard/KnowledgeDashboardController.php`
  — the list view's columns change: instead of
  `entry.value.title` it projects `entry.title` (or the
  first H1 of `entry.body` for legacy-shaped rows that
  didn't get a denormalised title in migration).
- `app/Http/Controllers/Dashboard/WorkflowStepKnowledgeController.php`
  — unchanged.
- `app/Http/Requests/CreateKnowledgeRequest.php` and
  `UpdateKnowledgeRequest.php` — the legacy `value.*`
  rules are removed; the new `type`, `slug`, `body`,
  `frontmatter`, `tags`, `source_ids` rules are added.
- `app/Services/KnowledgeFillinService.php` — the prompt
  template and the EXEMPLARS are rewritten. The
  hardcoded exemplar list is replaced with a call to
  `wiki_get_typed_exemplars(hive, type)` that pulls the
  best 4 existing pages of the target type from the
  hive's wiki and uses them as anchors. (This is a real
  improvement: the exemplars stay in sync with what the
  hive actually has good pages of.)
- `app/Services/KnowledgeIndexService.php` — the three
  "update the JSON blob" methods are replaced with the
  three "write the typed index page" methods. The
  `_index:*` reservation is removed.
- `app/Services/KnowledgeHealthService.php` — the
  service still computes a health score, but the score
  is now projected onto the `procedure:health-check`
  page instead of into a `_health:latest` JSON entry.
- `app/Console/Commands/RunKnowledgeCurator.php` —
  rewritten to walk typed pages, not JSON blobs.
- `app/Console/Commands/RunKnowledgeFillin.php` —
  unchanged at the command level; the service it calls
  is rewritten.
- `app/Jobs/DetectKnowledgeLinks.php` — unchanged
  (auto-detection is still valuable and the new
  `body` field is a richer input than `value`).
- `app/Jobs/ProcessKnowledgeWriteBack.php` — adapter
  for legacy `{title, summary, content}` payloads; the
  job itself still creates the `derived_from` /
  `authored_by` links, but the `knowledge_entries`
  row is now a typed page.
- `app/Jobs/RecordKnowledgeRead.php` — unchanged.
- `app/Models/KnowledgeLink.php` — unchanged.
- `app/Models/KnowledgeReadEvent.php` — unchanged.
- `app/Listeners/RecordKnowledgeFillinCompletion.php` —
  rewritten to log the new fillin shape
  (`pages_written`, `pages_updated`, `pages_linted`).
- `app/Models/WorkflowStepKnowledge.php` — unchanged.

**Migrations:**

- `0001_01_01_000016_create_knowledge_entries_table.php`
  — the GIN index on `value` is dropped in Phase E. The
  table itself is unchanged.
- `2026_04_04_100000_add_search_vector_to_knowledge_entries.php`
  — superseded; the `search_vector` column is regenerated
  in the new migration.
- `2026_04_04_200000_add_tags_gin_index_to_knowledge_entries.php`
  — the GIN index is renamed to `idx_knowledge_tags_gin`
  and moved onto the new `tags` array column.
- `2026_04_04_300000_add_read_stats_to_knowledge_entries.php`
  — unchanged.
- `2026_04_04_400000_create_knowledge_links_table.php`
  — unchanged.
- `2026_04_04_500000_create_knowledge_read_events_table.php`
  — unchanged.
- `2026_04_05_*` — unchanged.
- `2026_04_15_200000_add_embedding_to_knowledge_entries.php`
  — the `ComputeEmbedding` job is updated to embed
  `body` instead of `value`.
- `2026_05_26_000001_rename_knowledge_scope_apiary_to_organization.php`
  — unchanged.

**New migrations:**

- `2026_xx_xx_knowledge_wiki_phase_a_add_columns.php` —
  the additive column adds.
- `2026_xx_xx_create_knowledge_sources_table.php`.
- `2026_xx_xx_create_wiki_links_table.php`.
- `2026_xx_xx_knowledge_wiki_phase_c_backfill_and_tighten.php`
  — the one-time Phase C migration: backfills
  `type` / `slug` / `body` / `frontmatter` on every kept
  legacy row, then **deletes every non-kept legacy row** (the
  §9.6 "nuked" set, including all `_index:*` rows) before
  tightening the typed-page `NOT NULL` / uniqueness invariants
  and dropping the retained legacy `key` indexes. This is the
  single, canonical deletion point for legacy rows (§9.3, §9.6).
- `2026_xx_xx_knowledge_wiki_phase_d_drop_value_column.php`
  — drops `value` and the legacy `search_vector` generated
  column (which also removes the indexes dependent on `value`).
- `2026_xx_xx_knowledge_wiki_phase_e_drop_value_gin_index.php`
  — Phase E schema cleanup: drops the dead JSONB
  `value`-keyed GIN index declared in
  `0001_01_01_000016_create_knowledge_entries_table.php`
  (§9.5, matching the migration note at the top of this list).
  It does **not** delete the `_index:*` rows — those were
  already removed by the Phase C migration above. Phase E's
  remaining work (retiring the in-code `_index:*` reservation
  check and dead `value` code paths) is not a migration.

**Tests:**

- All `*KnowledgeEntryTest.php` and similar tests that
  exercise the JSONB value path are updated in place or
  replaced.
- New tests:
  - `tests/Feature/KnowledgePageCreateTest.php` — new
    write shape. Must include: a `source` / `log` page with
    **empty frontmatter** writes successfully (HTTP 201) and
    lands `lint_state = 'needs_attention'`; the same page with
    its `lint_required` keys present lands `lint_state = 'ok'`
    (covers §6.4 fix #3).
  - `tests/Feature/KnowledgePageUpdateTest.php` —
    partial body / frontmatter updates.
  - `tests/Feature/KnowledgeSourcesTest.php` — raw layer.
    Must include the immutability-trigger matrix (§6.7 fix #1):
    deleting a `hive` (and an `agent`) that owns source rows
    succeeds and nulls `hive_id` / `captured_by` via the
    `ON DELETE SET NULL` cascade (no `restrict_violation`);
    a direct UPDATE to `raw_excerpt` / `content_sha256` / `uri`
    / `metadata` still raises `restrict_violation`; deleting the
    owning `organization` cascades the source rows away.
  - `tests/Feature/WikiLinksTest.php` — author and
    back-link resolution. Must assert the §6.5 routing contract
    (fix #2): a body with `[[slug]]` creates a `wiki_links` row;
    `[[source:…]]` appends to `source_ids` only; `[[task:…]]` /
    `[[agent:…]]` create `knowledge_links` only; no `wiki_links`
    row is ever created with a non-`knowledge_entries` target.
  - `tests/Feature/KnowledgeMigrationTest.php` — the
    one-time migration script.
- Deleted tests:
  - All tests that exercise the JSONB value path and
    are not migrated to the new shape.

**SDK (`/workspace/repos/superpos-agent-core`):**

- `superpos_client.py` — the legacy
  `create_knowledge` / `update_knowledge` methods
  become shims; the new methods are in
  `knowledge.py`.
- New `tests/test_superpos_client_knowledge_typed.py`.
- New `src/superpos_agent_core/wiki/AGENTS.md`.
- New `src/superpos_agent_core/wiki/__init__.py`
  exposing the wiki constants (type taxonomy, slug
  conventions).

**UI (`/workspace/repos/superpos-app/resources/js`):**

- `Pages/Knowledge/Show.jsx` — rewritten.
- `Pages/Knowledge/Graph.jsx` — updated to render
  authored vs auto edges.
- New `Pages/Knowledge/Wiki.jsx` — the index / catalog
  view.
- New `Pages/Knowledge/Sources/Index.jsx` and
  `Pages/Knowledge/Sources/Show.jsx` — the raw layer
  dashboard.
- New `Components/Knowledge/WikiBody.jsx` —
  markdown renderer with the `[[wikilink]]` plugin.
- New `Components/Knowledge/TypeBadge.jsx`,
  `TypeTemplate.jsx`, `Backlinks.jsx`, `Sources.jsx`,
  `EditHistory.jsx`, `TrendTimeline.jsx`,
  `ProcedureSteps.jsx`.
- Adds `react-markdown` and `remark-gfm` to
  `package.json`.

**Configuration:**

- `config/platform.php` — `knowledge.fillin.enabled`,
  `knowledge.index.enabled`, `knowledge.auto_link.*`,
  `knowledge.embeddings.*`, `knowledge.ranking.*` stay
  (they're the right level of abstraction). Adds
  `knowledge.wiki.types` (the type taxonomy) and
  `knowledge.wiki.curator_interval_minutes`.

**Docs:**

- New `docs/wiki/AGENTS.md` (mirrors the SDK file).
- New `docs/wiki/page-templates.md` — worked examples
  of every page type with the expected frontmatter
  shape, body template, and `[[wikilink]]` usage.
- `docs/PRODUCT.md` — adds a "Knowledge Wiki" section
  summarising the model.
- `docs/proposals/registry.md` (1745 lines) — unchanged.
  The knowledge redesign is *orthogonal* to the registry
  cutover.

---

## 12. Risk callouts

1. **Migration of the existing `value` payload is lossy.**
   The JSON entries don't all map cleanly to a typed
   page. The migration script's heuristic for assigning
   `type` is best-effort. A human (or the curator agent,
   on a subsequent pass) will need to look at the
   migrated pages and re-type the ones that got it wrong.
   This is unavoidable: the current data has no type
   information and we have to invent some.
2. **Search ranking will shift.** The hybrid RRF ranker
   currently uses `value::text`. The new
   `search_vector` is generated from `body` (markdown is
   noisier — code blocks, link syntax, list bullets).
   The RRF weights in `KnowledgeRankingConfig` may need
   to be re-tuned. Plan for a "ranker sanity check" run
   in Phase B that compares top-10 results before and
   after on a fixed query set.
3. **The fillin agent's prompt is the load-bearing piece.**
   If the agent doesn't follow the new prompt and
   continues to emit `{title, summary, content}` JSON,
   the new code path will see those as legacy payloads
   and the adapter in `ProcessKnowledgeWriteBack` will
   silently convert them. That means the agent will
   *appear* to work but will produce low-quality pages.
   Bake the prompt change with a real fillin run, then
   audit the resulting pages for typedness.
4. **The wiki link parser must be safe against malformed
   `[[…]]` syntax.** A bad regex can either (a) match
   inside code blocks (false positives) or (b) miss
   legitimate references (false negatives). The parser
   is a 200-line test target; bake the parser with a
   corpus of real bodies before it ships.
5. **The "nuke the rest" threshold is opinionated.** If
   the user's read of the data is different from the
   proposal's, the migration script's `kept` set could
   lose entries that the user values. The
   `knowledge:migration-report` command (Phase C) lists
   the would-be-deleted entries so the user can
   veto before the migration runs.
6. **The "backlinks" UX is novel for the dashboard.**
   There is no "backlinks" widget anywhere in the
   current codebase. The proposal invents it. A
   separate small proposal may be warranted for the
   widget design alone; in this proposal we describe
   the *data* shape and leave the *visual* design to
   follow-up design work.
7. **Two link tables is a small smell.** A future
   proposal may collapse `wiki_links` and
   `knowledge_links` into a single table with a
   `link_source` column. The proposal does *not* do
   that collapse because the two have different shapes
   and different lifecycles (authored vs auto-detected)
   and the cost of merging them is high. We accept the
   two-table shape as the right level of separation for
   now.
8. **`knowledge_sources` needs object storage to scale.**
   The proposal puts a 50KB excerpt in Postgres. Real
   source documents (Slack threads, GitHub PRs, blog
   posts) are much larger. The migration should NOT
   put more than 50KB in the row; the metadata `raw_uri`
   field should point to object storage (S3, R2) for
   the full content. This is *not* in scope for this
   proposal — it is flagged for a follow-up. The
   current shape is fine for the small sources (URLs,
   short transcripts) the system is likely to ingest
   in the first 90 days.

---

## 13. Open questions for sign-off

1. **Type taxonomy.** Is six types (`entity`, `topic`,
   `trend`, `source`, `log`, `procedure`) the right
   number? Karpathy's article describes five; we added
   `source` for the raw-layer summaries and kept `log`
   as a distinct type for the episodic layer. The user
   may prefer a smaller set (merge `log` into
   `procedure`, merge `source` into `topic`).
2. **Slug format.** Is `type:slug-body` (e.g.
   `entity:redis-cluster-prod`) the right format, or
   do we want flat slugs with the type in a separate
   column? The compound format makes URLs pretty
   (`/knowledge/entity:redis-cluster-prod`) but may
   confuse URL encoders.
3. **Read-count threshold for the "kept" set in the
   migration script.** Is `> 5 reads in 90 days` right,
   or do you want a different threshold?
4. **`knowledge.write_organization` permission gate.**
   Today, organisation-scoped entries require a special
   permission. With the wiki, the question is whether
   cross-hive wiki pages should require the same
   permission (preserves current behaviour) or whether
   the wiki should treat organisation scope as
   first-class (no special permission). My read is
   preserve current behaviour.
5. **The `AGENTS.md` file location.** I propose shipping
   it in the SDK at
   `sdk/src/superpos_agent_core/wiki/AGENTS.md`. An
   alternative is a repo-relative path that the agent
   reads at runtime. The SDK-shipped version is more
   portable (works for any install of the agent) but
   means edits require an SDK release. Which do you
   prefer?
6. **The raw-excerpt size cap.** 50KB is the proposal's
   number. Real sources are larger. Is 50KB acceptable
   for the first cut, with object storage as a
   follow-up?
7. **Backlinks widget design.** The data shape is in
   §10. The visual design (cards? inline list? hover
   preview?) is open. Should the proposal sketch a
   design or leave it to follow-up?
8. **Phase A's dual write shape.** The proposal
   accepts both new and legacy shapes on POST/PUT
   through Phase C, with the conversion happening
   server-side. This is the conservative call. The
   alternative is to break the legacy shape immediately
   in Phase A and force every caller to migrate at
   once. My read is dual-shape is right for the SDK
   (clients update at their own pace) but the
   dashboard should switch to the new shape in Phase A
   (it's our code, we control the release).
9. **The `_index:*` reservation in Phase A–C.** We
   reserve the prefix so the old curator doesn't write
   new rows, but the existing rows stay readable. Is
   that right, or should the existing rows be hidden
   in Phase A so the dashboard doesn't show stale data?
10. **Migration report command scope.** Should
    `knowledge:migration-report` also list the
    `knowledge_links` rows that would be orphaned by
    entry deletion, so the operator can see the blast
    radius?

---

## 14. Estimated size

- ~1500 lines added (new migrations, models, services,
  SDK methods, dashboard components, tests).
- ~800 lines removed (JSONB value paths, the
  `*ValueAttribute` accessors, the
  `value::text ILIKE` branches, the `*IndexService` blob
  methods, the `JSON.stringify` panel, the legacy
  form-request rules).
- ~400 lines modified (the curator, the fillin service,
  the controller's `formatEntry`, the model
  `$fillable`).
- 6 new migrations, 1 modified migration.
- 12+ files modified, 4 new test files, 2 new SDK test
  files, 1 new SDK file (`wiki/AGENTS.md`).
- 1 new artisan command (`knowledge:migration-report`).
- 1 new artisan command (`knowledge:scan-legacy-writes`,
  the pre-merge check in Phase D).

Net: the system gains more functionality (typed pages,
backlinks, raw layer) and loses more complexity (the
JSONB value path, the `_index:*` reservation, the
`scopeValueLike` shim) than it adds. The `Show.jsx`
rewrite is the biggest single line-count change.

---

## 15. Out of scope

- **Object storage for full source content.** The
  `knowledge_sources` row carries a bounded excerpt; the
  full text is left to a follow-up.
- **A web-based markdown editor.** The dashboard
  edit surface is a `<textarea>` for body and a
  structured form for frontmatter.
- **Cross-hive wiki federation.** Pages can be
  `scope=organization` (visible across hives), but
  editing is per-hive. A future proposal may add
  org-level wikis.
- **A wiki search UI distinct from the current
  `search_knowledge`.** The current hybrid FTS/vector
  search is the right primitive; the wiki adds typed
  browse, not a separate search.
- **Real-time collaborative editing.** Single-writer
  per page; concurrent writes create a version
  conflict that the next curator pass resolves by
  "merging" (concatenating new sections, flagging
  duplicates).
- **(c) from the registry b2 cutover.** Knowledge is
  orthogonal to the registry; no cross-proposal
  coordination required.
- **The `decisions` UI redesign.** The current
  `knowledge_decisions()` SDK method and
  `_index:decisions` JSON entry are replaced by
  `list_by_type('topic', tag='decision')` and the
  in-wiki index page. The *dashboard* UI for
  decisions is unchanged; the *agent* UI is
  rewritten.

---

## 16. Phased delivery checklist

A summary of the phases, in order, with the irreversible
step clearly called out.

| Phase | Scope | Reversible? | Bake |
|---|---|---|---|
| A | Additive: new columns, new tables, dual-shape writes, new SDK methods, new dashboard panels | yes | one full agent cycle |
| B | Bookkeeper rewrite: curator + fillin + write-back produce typed pages | yes | two curator cycles |
| C | Raw layer wiring + one-time migration script | yes | confirm dashboard renders migrated entries |
| D | Drop the legacy `value` column + legacy accessors + legacy form-request rules | **NO** | zero legacy writes in `PreDropValueScanCommand` |
| E | Remove dead code: JSONB GIN index, `_index:*` reservation check, hybrid RRF `value::text` branch | **NO** (dead-code/index removal; the `_index:*` rows were already deleted in Phase C) | confirm no agent still asks for `_index:*` |

After Phase D, the system has *one* write shape and the
old code is gone. After Phase E, the dashboard is the
only place anyone sees the wiki; the JSONB era is
over.

Once signed off, the implementation is substantial but
mechanical. The risk is in the migration script's
heuristics (§9.5) and the fillin prompt rewrite
(§7.2); both are well-bounded by the bake plans. No
surprises expected beyond what's listed in §12.
