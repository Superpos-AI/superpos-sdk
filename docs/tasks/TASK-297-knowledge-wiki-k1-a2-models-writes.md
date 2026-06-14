# TASK-297: Knowledge Wiki — Phase A2 Models + Write Path

**Status:** pending
**Branch:** `task/297-knowledge-wiki-a2-models-writes`
**PR:** —
**Depends on:** TASK-296 (✅ merged as PR #792)
**Blocks:** TASK-298, TASK-299

> **Provenance.** This plan was written after PR #792 was reviewed
> and merged. The A1 review surfaced five follow-up commits:
> search_vector was rebuilt with the IMMUTABLE
> `knowledge_entries_tags_fts_text()` wrapper for the `tags` array
> (e0c4c34), `key` + legacy `value->>'…'` JSON fields are folded
> back into the generated column so legacy rows keep an FTS index
> (6f11e0b), and the immutability trigger on `knowledge_sources`
> also blocks `id` rewrites (5583b22). A2 builds on the resulting
> schema, not the pre-review draft.

## Objective

Land the **dual-shape write path** for the knowledge wiki:

- `KnowledgeEntry` model gains fillable/cast entries for the
  typed columns landed in A1 (`type`, `slug`, `title`, `body`,
  `frontmatter`, `summary`, `tags`, `source_ids`, `last_linted_at`,
  `lint_state`). The legacy `key` + `value` stay fillable so
  legacy writes still succeed in Phases A–C.
- New `KnowledgeSource` model with an **app-level immutability
  hook** (in addition to the A1 DB trigger). The hook is the
  second line of defence the A1 trigger design explicitly
  deferred to: Eloquent `saving` / `deleting` events throw
  before any `update()` / `delete()` reaches the DB.
- New `WikiLink` model.
- New `app/Knowledge/FrontmatterSchema` registry (§6.4).
  `validate()` rejects unknown keys + hard `required` omissions
  (write-time 422). `lintMissing()` returns missing
  `lint_required` keys for the curator to set `lint_state =
  'needs_attention'`. **Empty frontmatter is a valid write for
  every type** — the agent can write a pure-body page and have
  the curator backfill metadata later.
- New `app/Knowledge/WikiLinkParser` (§6.5). Obsidian-flavored
  rules. Resolves every `[[…]]` in the same transaction as the
  body write, routes refs to the right store
  (`wiki_links` / `source_ids` / `knowledge_links`), and
  collects unresolved refs into `frontmatter.broken_links`.
- New `app/Services/KnowledgeService` with the dual-shape write
  path + the **§6.8 attach-time authorization** (clauses
  (a) / (b) / (c)). Rejects widening writes (403, rollback).
  Inline `sources=[…]` is ingested-and-attached in the same
  transaction so a single call satisfies (a) directly.
- Updated `CreateKnowledgeRequest` / `UpdateKnowledgeRequest`
  to accept **one of** legacy `key`+`value` **or** new
  `type`+`slug`+`body` (not both, not neither — 422).
- Updated `KnowledgeController::store` / `update` to delegate
  the write to `KnowledgeService`; `formatEntry()` returns both
  new and old fields. Legacy `value` is converted to a
  synthetic `body` markdown rendering on write so legacy clients
  see a one-version "upgrade" rather than a refusal (§8.2).
- New `KnowledgeSourceController::store` (write side of
  `POST /knowledge/sources`) so an agent can ingest a source
  ahead of attaching it. The orphan source is then attachable
  under §6.8 clause (c) by its own originator.
- New `LegacyValueDeprecationContractTest` pinning the
  Phase A–C dual-write contract and the Phase D 422 (§8.6).

The **read endpoints** (`GET /knowledge/sources` /
`/sources/{id}` with the §6.8 read ACL,
`GET /knowledge/{entry}/backlinks`,
`GET /knowledge/types/{type}/list`,
`POST /knowledge/synthesize-topic`, route ordering, and the
Python SDK) are **out of scope for A2** — they land in TASK-298.
The **dashboard UI** is out of scope — TASK-299.

## Functional Requirements

### FR-1 — `KnowledgeEntry` model surface

Add to `$fillable`: `type`, `slug`, `title`, `body`, `frontmatter`,
`summary`, `tags`, `source_ids`, `last_linted_at`, `lint_state`.
Keep all existing fillable (`key`, `value`, `scope`, …).

Add to `$casts`:
- `frontmatter` → `array`
- `last_linted_at` → `datetime`
- `lint_state` → `string` (default cast covers it; explicit
  for clarity)

`tags` and `source_ids` are pgsql `text[]` columns. Eloquent
returns the driver-native representation (PG array literal
string on pgsql; JSON string on sqlite). The
`KnowledgeService` write path normalises input arrays to that
representation; the read formatter normalises output for the
JSON envelope (array on both drivers — see FR-11).

Add a `type()` scope helper (filter to a single type):
`scopeOfType(Builder $q, string $type): Builder`.

### FR-2 — `KnowledgeSource` model + app-level immutability

`app/Models/KnowledgeSource.php`. Eloquent model with
`$fillable` for the A1 columns, `$casts` for `metadata` →
`array` and `captured_at` → `datetime`, and the
`BelongsToOrganization` trait (matches `KnowledgeEntry`'s
choice — `hive_id` is nullable, organization is the always-set
tenant).

**App-level immutability hook.** In `boot()` (or via
`static::updating` / `static::deleting` event listeners),
throw `LogicException` with the same message the DB trigger
uses:

```php
static::updating(function (KnowledgeSource $src): void {
    throw new \LogicException(
        'knowledge_sources rows are immutable and cannot be updated'
    );
});
static::deleting(function (KnowledgeSource $src): void {
    throw new \LogicException(
        'knowledge_sources rows are immutable and cannot be deleted'
    );
});
```

This is the second line of defence the A1 trigger design
explicitly defers to for SQLite (no `pg_trigger_depth()`), and
covers the pgsql-direct-statement case as well. The DB trigger
still fires for raw SQL and for cascade SET NULL; the model
hook covers app-level `update()` / `delete()`.

A `creating` event stamps `captured_by = agent.id` and
`captured_at = now()` if the caller didn't supply them, so the
ingest endpoint is one-line.

Relationships: `hive()`, `capturedByAgent()`,
`organization()` (via `BelongsToOrganization`).

### FR-3 — `WikiLink` model

`app/Models/WikiLink.php`. Eloquent model with `$fillable` for
`source_entry_id`, `target_entry_id`, `link_type`, `source_span`
and `$casts` for `created_at` → `datetime`. BelongsTo
`source` (KnowledgeEntry) and `target` (KnowledgeEntry).
`updated_at` disabled (wiki links are append-only — generated
by the parser on every body change, never mutated by hand).

### FR-4 — `app/Knowledge/FrontmatterSchema` (§6.4)

`final class FrontmatterSchema` with the six per-type
constant arrays verbatim from the proposal §6.4:

- `ENTITY`, `TOPIC`, `TREND`, `SOURCE_PAGE`, `LOG`, `PROCEDURE`
  — each a `['required' => […], 'lint_required' => […], 'optional' => […]]`
  map.
- `SYSTEM = ['broken_links', 'kind', 'lint_notes']` — the
  reserved system/curator-managed keys. The proposal says
  these are "allowed on *every* type, independent of the
  per-type `optional` whitelist", and `validate()` always
  permits them.

Public API:
- `public static function validate(string $type, array $frontmatter): array`
  — returns `['errors' => […]]`. Empty if all keys are
  permitted and required keys are present.
- `public static function lintMissing(string $type, array $frontmatter): array`
  — returns the array of missing `lint_required` keys
  (possibly empty). Never throws.

**Type → schema lookup table** maps `'entity' → ENTITY`,
`'topic' → TOPIC`, etc. Unknown `type` → 422 (not silently
permissive — the agent should know its type is wrong).

### FR-5 — `app/Knowledge/WikiLinkParser` (§6.5)

Regex-driven parser. Returns a structured
`ParseResult` value object with three lists:

```php
final readonly class ParseResult {
    /** @param list<array{slug:string, alias:?string}> $pageRefs */
    /** @param list<string> $sourceIds (ULIDs from [[source:…]]) */
    /** @param list<array{type:string, ref:string}> $entityRefs ([[task:…]] / [[agent:…]]) */
    /** @param list<string> $unresolved (collected raw slugs) */
    public function __construct(
        public array $pageRefs,
        public array $sourceIds,
        public array $entityRefs,
        public array $unresolved,
    ) {}
}
```

Regex (single pass, non-overlapping):

```
\[\[
   (?:(source|task|agent):([A-Za-z0-9]+))   # typed ref
   |  ([^\]\|]+?)                            # page slug
       (?:\|([^\]]+))?                       # optional |alias
 \]
```

`KnowledgeService` calls the parser, then resolves `pageRefs`
against `knowledge_entries` within the same hive (or org-scoped
pages for org-scoped pages), upserts `wiki_links` rows,
appends `sourceIds` to the page's `source_ids` array,
upserts `knowledge_links` rows for `entityRefs`, and appends
`unresolved` slugs to `frontmatter.broken_links` (creating
the key if absent — `broken_links` is a reserved SYSTEM key so
the write is allowed on any type).

All of the above happens **inside the same transaction** as the
body write, so a body change + link rewrite is atomic.

### FR-6 — `app/Services/KnowledgeService` (dual-shape + §6.8)

The new business logic for writes. Two entry points:

```php
public function createPage(Agent $agent, Hive $hive, array $input): KnowledgeEntry
public function updatePage(Agent $agent, KnowledgeEntry $entry, array $input): KnowledgeEntry
public function ingestSource(Agent $agent, ?Hive $hive, array $input): KnowledgeSource
```

**Dual-shape conversion (§8.1 / §8.2 / §9.1).** A
`CreateKnowledgeRequest`-shaped input may carry either
`key`+`value` (legacy) or `type`+`slug`+`body` (new). The
service:

- If legacy, **synthesise** a typed page: `type = 'entity'`
  (the proposal's default for legacy convert), `slug` derived
  from the legacy `key` (`facts:redis-cluster-prod` →
  `entity:redis-cluster-prod`), `title` from
  `value['title']`, `body` from a markdown rendering of
  `value['title'] + value['content']`, `summary` from
  `value['summary']`, `frontmatter` from the remaining
  `value` sub-keys (`source`, `confidence`, `format`,
  non-empty `tags`). The legacy `value` column is also
  written so pre-Phase-D reads and the existing FTS regression
  test keep working (the search_vector folds both).
- If new, pass through with the typed columns; legacy `key`/
  `value` are derived (key = `slug`, value = a JSON
  representation of the typed page — same shape
  `formatEntry()` returns to keep the search-vector folding
  working).

**§6.8 attach-time authorization.** Run inside the same
`DB::transaction` as the page write, **before** the page row
is persisted. For every `source_id` in the request (or in
`source_ids` derived from inline `sources=[…]`):

- (a) **Newly ingested in this transaction** — if the source
  was just created by `ingestSource()` in the same call, the
  caller is the originator; allow.
- (b) **Already readable by the caller** — run the §6.8
  visibility join (caller can read a page whose
  `source_ids` contains this id, with the same not-expired
  ttl predicate). Allow.
- (c) **Orphan source the caller itself ingested** — caller
  is `captured_by` and the source has zero citing pages.
  Allow.

Any other case → **403**, transaction rolls back, no
widening.

The `sources=[…]` inline array path (§8.1): each descriptor
is passed through `ingestSource()` first (which dedupes on
`(organization_id, content_sha256, kind, origin)` per A1's
partial unique indexes, returning the existing source if a
dedupe hit), then immediately appended to the page's
`source_ids` *in the same transaction* — so the attach
satisfies (a) directly. This is the single-call alternative
to the two-step `ingestSource()` → `createPage()` flow.

After the page row is persisted, `WikiLinkParser::parse()`
walks `body`, and the resulting `wiki_links` / `source_ids` /
`knowledge_links` writes happen in the same transaction.

### FR-7 — Updated `CreateKnowledgeRequest` / `UpdateKnowledgeRequest`

Both accept **one of** two shapes:

- **Legacy** — `key` (string, max 500, required on create) +
  `value` (array, required). Existing per-sub-key rules
  retained for backward compatibility.
- **New** — `type` (in `entity|topic|trend|source_page|log|procedure`),
  `slug` (string, max 255, required on create), `body` (string,
  sometimes nullable), `title` (string, max 255, sometimes),
  `summary` (text, sometimes), `frontmatter` (array, sometimes,
  validated by `FrontmatterSchema::validate()`), `tags`
  (array, max 20, each string max 100), `source_ids` (array
  of ULID strings, sometimes), `sources` (array of source
  descriptors, sometimes — the inline ingest-and-attach
  path).

Rule: `required_without: key` for the new-shape top-level
fields + `required_without: value` for the legacy `value`,
plus a manual `withValidator` rule that **422s if both shapes
are present** in the same request (the proposal §8.1: "422s
if both are present or neither is").

`scope`, `visibility`, `ttl` work as today (cross-shape).

### FR-8 — `KnowledgeController` updates

`store()` delegates to `KnowledgeService::createPage()` inside
`DB::transaction`. `update()` delegates to
`updatePage()`. `formatEntry()` is rewritten to return both
new and legacy fields:

```php
return [
    // Identity / lineage
    'id' => $entry->id,
    'organization_id' => $entry->organization_id,
    'hive_id' => $entry->hive_id,
    'version' => $entry->version,
    'created_at' => …, 'updated_at' => …,

    // Legacy (kept through Phase D for backward compat)
    'key' => $entry->key,
    'value' => $entry->value,

    // New typed fields
    'type' => $entry->type,
    'slug' => $entry->slug,
    'title' => $entry->title,
    'body' => $entry->body,
    'summary' => $entry->summary,
    'frontmatter' => $entry->frontmatter,
    'tags' => $this->normaliseArrayForJson($entry->tags),
    'source_ids' => $this->normaliseArrayForJson($entry->source_ids),
    'lint_state' => $entry->lint_state,
    'last_linted_at' => $entry->last_linted_at?->toIso8601String(),

    // Unchanged
    'scope' => $entry->scope,
    'visibility' => $entry->visibility,
    'ttl' => $entry->ttl?->toIso8601String(),
    'stats' => $entry->stats,
    'link_count' => …,
];
```

`tags` / `source_ids` normalisation: on pgsql the raw
column comes back as a `"{a,b,c}"` array literal; the
formatter unwraps to a plain `['a','b','c']` so the JSON
envelope is driver-stable. SQLite returns JSON strings —
`json_decode` to an array.

The existing index / show / search / graph / destroy methods
are **unchanged** — they read both fields, and `formatEntry`
gains the new keys without removing any old ones.

### FR-9 — `KnowledgeSourceController::store`

New controller, write side only. `POST /knowledge/sources`:

```php
public function store(KnowledgeSourceRequest $request, string $hive): JsonResponse
```

The controller delegates to `KnowledgeService::ingestSource()`,
which:
- Resolves `origin` from the request hive context
  (hive-scoped → `origin='hive'`, org-scoped → `origin='org'`).
- Sets `captured_by = $agent->id` (so clause (c) holds later
  if the source stays an orphan).
- Calls `KnowledgeSource::create([...])`. The A1 partial
  unique indexes `(origin='hive' | origin='org',
  organization_id, content_sha256, kind, …)` dedupe — a hit
  returns the existing source (200) rather than 409, so
  re-ingest is idempotent.

**Read-side** (`GET /knowledge/sources`, `GET /knowledge/
sources/{id}`) is **out of scope for A2** — TASK-298.

### FR-10 — Backward-compat safety net

`KnowledgeService` and the request rules MUST preserve every
behaviour the current test suite exercises for legacy writes:

- A `POST /knowledge` with `key` + `value` (no typed fields)
  must continue to return 201, the row is created with the
  same `key` and `version = 1`, and the response includes
  the new typed fields (defaulted / null per A1's nullable
  contract).
- A duplicate legacy `key` continues to 409 via the A1-retained
  legacy `key` unique index.
- A `_index:` legacy write continues to be 403 (the existing
  reserved-prefix check).
- The `CompleteTaskRequest` write-back path with
  `knowledge_entries.*.value` is **not changed in A2** — that
  is part of the Phase B bookkeeper rewrite. The new
  `KnowledgeService::createPage()` only handles the
  controller-facing `POST /knowledge` path.

### FR-11 — Driver-portable array I/O

`tags`, `source_ids` are pgsql `text[]`. To keep the JSON
envelope driver-stable:

- **Write side:** the request validator accepts an array
  (`['foo', 'bar']`). `KnowledgeService` casts to the driver
  representation before insert: on pgsql a PG array literal
  via `DB::raw` binding (so the array is passed to PG as a
  proper `text[]`); on sqlite a JSON-encoded string.
- **Read side:** `formatEntry` decodes pgsql literals to PHP
  arrays; sqlite values come back as JSON strings and decode
  to arrays. The JSON envelope is always a plain PHP array.

A `tests/Feature/Knowledge/PhaseAWritePathTest.php` case
exercises both drivers.

## Non-Functional Requirements

- **NFR-1 (no schema drift).** No new migrations in A2 — the
  A1 schema is the contract. A2 only adds PHP code that uses
  the A1 columns.
- **NFR-2 (no breaking changes to legacy clients).** Every
  existing test that hits `POST/PUT /knowledge` with a legacy
  `key`+`value` payload must continue to pass without
  modification. Verified by the full `php artisan test` suite
  in the test plan.
- **NFR-3 (cross-driver parity).** All A2 features work on
  both pgsql and sqlite, with the same test outcomes. Where
  a feature is pgsql-only (e.g. partial unique indexes), the
  test is gated.
- **NFR-4 (atomicity).** A page write + `wiki_links` rewrite +
  inline `sources` ingest is **one transaction**. A failure at
  any step rolls back the whole write. No half-state is
  observable.
- **NFR-5 (no early deprecation).** Legacy `value` writes
  continue to succeed through Phases A–C. The 422 is a
  Phase D contract, pinned by
  `LegacyValueDeprecationContractTest`.

## Files to Create / Modify

### New files

- `app/Models/KnowledgeSource.php`
- `app/Models/WikiLink.php`
- `app/Knowledge/FrontmatterSchema.php`
- `app/Knowledge/WikiLinkParser.php`
- `app/Services/KnowledgeService.php`
- `app/Http/Controllers/Api/KnowledgeSourceController.php`
  (write side only — read side is A3)
- `app/Http/Requests/KnowledgeSourceRequest.php`
- `tests/Feature/Knowledge/LegacyValueDeprecationContractTest.php`
- `tests/Feature/Knowledge/PhaseAWritePathTest.php`

### Modified files

- `app/Models/KnowledgeEntry.php` — fillable / casts / scope
- `app/Http/Controllers/Api/KnowledgeController.php` —
  `store` / `update` delegate; `formatEntry` returns both
  shapes
- `app/Http/Requests/CreateKnowledgeRequest.php` — dual-shape
  validation
- `app/Http/Requests/UpdateKnowledgeRequest.php` — dual-shape
  validation
- `routes/api.php` — register `POST /knowledge/sources` (the
  literal route, registered **before** the `{entry}` wildcard
  per §8.4 — TASK-298 will add the rest)

## Test Plan

- `LegacyValueDeprecationContractTest.php` (§8.6) — the
  pinned contract test. **Phase A–C dual-write accepted:**
  `POST` / `PUT /knowledge` with legacy `value=…` returns
  2xx and the row is stored with synthesised typed fields;
  `POST` / `PUT` with the new `body` shape also returns 2xx
  and is stored as a typed page; both shapes coexist.
  **422 only in Phase D:** the test is gated on a `phase`
  config flag (default `A–C`); Phase D will flip the flag in
  TASK-301 and re-run.
- `PhaseAWritePathTest.php` — the wiring test.
  - `KnowledgeEntry::$fillable` includes all 8 new typed
    columns; `$casts` includes `frontmatter` (array) and
    `last_linted_at` (datetime).
  - `KnowledgeSource::create()` succeeds and the model
    enforces the immutability hook
    (`updating` → `LogicException`,
     `deleting` → `LogicException`).
  - `WikiLink::create()` succeeds and is append-only
    (`updated_at` disabled).
  - `FrontmatterSchema::validate('entity', [])` is empty
    errors; `validate('source_page', [])` is empty errors
    (empty frontmatter is always valid). `validate('entity',
    ['nonsense' => 1])` returns an error. `validate('source_page',
    [])` followed by `lintMissing('source_page', [])` returns
    `['source_sha256']`.
  - `WikiLinkParser::parse('# Hi [[redis-cluster-prod]]
    and [[source:01HX…]] and [[task:tsk_01HX…]]')` returns
    the expected `ParseResult`.
  - `POST /knowledge` with `key=foo&value=…` returns 201 and
    the row is stored with synthesised `type=entity`,
    `slug=entity:foo`, `title` from `value.title`, `body`
    derived from `value.content`, plus the legacy `key` and
    `value` populated. (Cross-driver: runs on sqlite by
    default; pgsql assertions are gated.)
  - `POST /knowledge` with `type=entity&slug=…&body=…` returns
    201 and the row is stored typed (legacy `key=slug`,
    `value` is the JSON-serialised typed page).
  - `POST /knowledge` with **both** shapes returns 422 with
    a clear "use one shape" error.
  - `POST /knowledge` with `type=invalid` returns 422 (the
    `type` rule).
  - `POST /knowledge` with `type=entity&frontmatter={nonsense: 1}`
    returns 422 (`FrontmatterSchema::validate` rejects
    unknown keys).
  - `POST /knowledge/sources` ingests a source and returns
    201 with the row; a second `POST` with the same
    `(content_sha256, kind, origin, organization_id)` returns
    the existing row (idempotent).
  - `POST /knowledge/sources` then `POST /knowledge` with
    `source_ids=[…]` by the **same** agent succeeds (§6.8
    clause (c) — orphan source, caller is originator).
  - `POST /knowledge` with `source_ids=[orphan_owned_by_other_agent]`
    by a different agent returns 403 (§6.8 widening blocked).
  - `POST /knowledge` with inline `sources=[…]` ingests
    each and attaches it in one transaction (§6.8 clause
    (a)).

- Full `php artisan test` — no regression. The existing
  `KnowledgeFtsTest` and `KnowledgeHybridSearchTest` must
  still pass (the A1 review-fixed `search_vector` folding of
  legacy `key` + `value` fields is the contract they depend
  on, and A2 must not undo it).

## Out of Scope (deferred to A3 / A4 / Phase C / D / E)

- **Read-side source endpoints** (`GET /knowledge/sources`,
  `GET /knowledge/sources/{id}` with the §6.8 read ACL).
- **`listByType`, `backlinks`, `synthesizeTopic`** actions.
- **Route ordering test** (`KnowledgeRouteOrderingTest`) —
  TASK-298 owns it; the read-side routes are what trip the
  wildcard conflict.
- **Python SDK** — `create_page`, `update_page`,
  `ingest_source`, etc. land in TASK-298.
- **Dashboard UI** — markdown render, frontmatter / sources /
  backlinks panels, wiki index page — TASK-299.
- **`CompleteTaskRequest` write-back path** with
  `knowledge_entries.*.value` — Phase B bookkeeper rewrite
  (TASK-300).
- **Phase C** constraint tightening (`SET NOT NULL`,
  `key`-index drop, `_index:*` deletion).
- **Phase D** (drop `value` column) and **Phase E** (dead
  code removal).
