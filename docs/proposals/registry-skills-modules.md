# Registry: Skills + Modules Onboarding (Beat 0)

Status: Plan for sign-off
Owner: registry track
Scope: Design doc that ratifies the plan to bring the registry's `skill`
and `module` kinds live, mirroring the completed `subagent` migration.
This is **Beat 0** — the design that must be signed off before any
import/serving code lands.

Precedent: the original registry proposal [#714](https://github.com/Superpos-AI/superpos-app/pull/714)
("Registry: Subagents, Skills, Modules") introduced the three sibling
kinds and the shared attachment model. The `subagent` kind is now fully
migrated — registry-native writes, reads, claim-time resolution, and the
legacy `sub_agent_definitions` table dropped (see
[`docs/proposals/registry-b2-cutover.md`](registry-b2-cutover.md) and the
phase-c work that removed the dual-write gates, recorded in
[`config/platform.php`](../../config/platform.php) lines 903–910). This
proposal does for `skill` and `module` what those beats did for
`subagent`.

---

## 1. Why now

`skill` and `module` are already declared as valid kinds on the registry
schema — see `RegistryItem::KINDS` in
[`app/Models/RegistryItem.php`](../../app/Models/RegistryItem.php) line 16:

```php
public const KINDS = ['subagent', 'skill', 'module'];
```

But nothing **imports, resolves, or serves** them. The registry write
path (`RegistryService::createItem` /
[`app/Services/RegistryService.php`](../../app/Services/RegistryService.php))
accepts any of the three kinds, and the `/registry/resolved` endpoint
([`app/Http/Controllers/Api/RegistryApiController.php`](../../app/Http/Controllers/Api/RegistryApiController.php)
line 407, `RegistryService::resolve` line 447) already groups its output
by `(kind, slug)` — so a `skill` or `module` item, if one existed and
were attached, would *already* flow through resolution untouched. The
gap is entirely on the **producer** (importer) and **consumer**
(agent-core runtime) ends: no code creates skill/module items, and no
agent reads them.

Today both kinds are **baked into the agent image**:

- **Modules** ship as `module.yaml + scripts/ + SKILL.md` directories
  inside the `superpos-agent-core` Python package. They are discovered at
  startup by `module_loader.discover_modules()` and installed by
  `module_setup.run_setup()`, which symlinks each module's scripts onto
  `PATH`, renders a documentation block into `CLAUDE.md`, and runs any
  per-module setup step for workspace modules. There are **4 real
  `module.yaml` modules**: `superpos-github`, `superpos-issues`,
  `superpos-knowledge`, `superpos-workflows`.
- **Skills** are thinner — plain markdown baked into the image workspace
  at `.claude/skills/*.md`, surfaced via the `Skill` tool / `/skill-name`.

Baking these in means every skill/module change requires a container
rebuild and redeploy, and a hive cannot share, audit, or task-override
them. Completing this track lets us ship **lean agent images** with no
baked-in skills or modules — everything pulled from the registry at
claim time.

## 2. Current registry schema (grounding)

Everything below reuses the schema the `subagent` kind already runs on.
No new tables.

### 2.1 Tables

| Table | Migration | Notes |
|---|---|---|
| `registry_items` | [`2026_06_01_100000_create_registry_items_table.php`](../../database/migrations/2026_06_01_100000_create_registry_items_table.php) | The envelope: `id` (ULID `string(26)`), `organization_id`, `hive_id`, `kind` (`string(20)`), `slug` (`string(100)`), `name`, `description`, `visibility` (default `hive`), `owner_agent_id`, `payload` (jsonb), `latest_revision_id`, `is_active`, `deleted_at`. Partial unique index `idx_registry_items_live_slug` on `(hive_id, kind, slug)` WHERE `deleted_at IS NULL`. |
| `registry_item_revisions` | [`2026_06_01_100001_create_registry_item_revisions_table.php`](../../database/migrations/2026_06_01_100001_create_registry_item_revisions_table.php) | `id` (ULID), `item_id`, `version` (unsigned int), `payload` (jsonb), `message`, `author_agent_id`. Unique `(item_id, version)`. |
| `registry_attachments` | [`2026_06_01_100002_create_registry_attachments_table.php`](../../database/migrations/2026_06_01_100002_create_registry_attachments_table.php) | Binds an item (optionally a pinned `revision_id`) to a `scope` (`hive` / `agent` / `task`) + `scope_id`, optional `role`. |
| `registry_items.latest_revision_id` | [`2026_06_06_100000_add_latest_revision_id_to_registry_items.php`](../../database/migrations/2026_06_06_100000_add_latest_revision_id_to_registry_items.php) | Back-pointer to the revision the item currently names (the source of truth for "active revision"; see `RegistryItem::activeRevision()`). |

The `kind` column is just a `string(20)` discriminator — it carries no
per-kind constraints. All per-kind shape lives in the `payload` JSON,
exactly as it does for `subagent` today.

### 2.2 How `subagent` shapes its payload (the model we copy)

`SubAgentDefinitionService::buildRegistryPayload()`
([`app/Services/SubAgentDefinitionService.php`](../../app/Services/SubAgentDefinitionService.php)
lines 312–342) is the template. It writes a payload of this shape into
both `RegistryItem.payload` (the "latest" snapshot) and a new
`RegistryItemRevision.payload` (the immutable history entry):

```php
return [
    'frontmatter' => [
        'name' => $record->name,
        'description' => $record->description,
        'tools' => $record->allowedTools,
        'model' => $record->model,
    ],
    'body' => $this->assemble($record),   // rendered markdown
    'documents' => $record->documents,
    'config' => $record->config,
];
```

On update, an `authoring` sub-key is appended
(`SubAgentDefinitionService.php` lines 382 / 473) for provenance. Every
write creates a new revision and re-points `latest_revision_id` so the
back-pointer always names the active revision
(`RegistryItem::activeRevision()` in
[`app/Models/RegistryItem.php`](../../app/Models/RegistryItem.php)).

### 2.3 How resolution serves it

`RegistryService::resolve($agentId, $taskId)`
([`app/Services/RegistryService.php`](../../app/Services/RegistryService.php)
lines 447–525) collects every attachment in scope (`hive` for the
agent's hive, `agent` for the agent, `task` for the claimed task),
de-duplicates by `(kind, slug)` with scope precedence
`task (3) > agent (2) > hive (1)`, and emits one row per winner:

```php
$items[] = [
    'kind' => $item->kind,
    'slug' => $item->slug,
    'name' => $item->name,
    'revision_id' => $revisionId,
    'payload' => $payload,            // pinned revision payload, else item payload
    'resolved_from_scope' => $attachment->scope,
    'resolved_from_attachment_id' => $attachment->id,
    'deleted_at' => $item->deleted_at?->toIso8601String(),
];
```

This loop is **kind-agnostic** — it already passes `skill` and `module`
payloads through verbatim. The endpoint wrapper adds an `agent_context`
block (`agent_memory`, `persona_version`) and returns under `items`
(`RegistryApiController::resolved`, line 409). The runtime-bundle adapter
on the agent side consumes this `items` array; today it only knows how to
materialize `subagent` entries. The work in this track is to teach it the
other two kinds (§6).

## 3. Payload shapes

These build directly on the §2.2 template and the sketch in the original
proposal ([`docs/proposals/registry.md`](registry.md) lines 273–283),
made concrete and consistent with what `subagent` actually stores.

### 3.1 `kind=skill`

A skill is a single `SKILL.md` body plus optional helper files. One line:
**`{ frontmatter: { name, description }, instructions: <SKILL.md markdown>, files: [{ path, content, mode }] }`**.

The `SKILL.md` body lives under `instructions` (not `body`) so the payload
matches the contract the live `superpos-agent-core` sync already implements:
`registry_sync._install_skill` writes `payload["instructions"]` to
`SKILL.md`. Using `body` here would round-trip into an **empty** `SKILL.md`.

```jsonc
// registry_item_revisions.payload for kind=skill
{
  "frontmatter": {
    "name": "deep-research",            // display name; mirrors RegistryItem.name
    "description": "Deep research harness — fan-out web searches..."
  },
  "instructions": "# Deep research...\n...",  // the full SKILL.md markdown (consumed by registry_sync._install_skill)
  "files": [                            // optional; empty for markdown-only skills
    { "path": "scripts/fetch.py", "content": "...", "mode": "+x" }  // "+x" or an int; string-octal ("0644") NOT honored
  ]
}
```

Rationale for reusing `frontmatter` + a single body field: it keeps skills
structurally close to subagents, so the agent-side overlay logic stays a
near-copy of the existing subagent overlay. Note the one deliberate naming
difference: the live core stores the subagent body under `body`
(`_install_subagent`) but the skill body under `instructions`
(`_install_skill`, which writes it to `SKILL.md` and lays helper `files[]`
down alongside it). This proposal follows the field name each live
installer already consumes rather than forcing a single name, so a seeded
skill round-trips into a non-empty `SKILL.md` with no core change. `files`
uses the same `[{ path, content, mode }]` shape modules use to serve their
scripts (§3.2), so the served-artifact contract is identical across both
kinds; it is empty for the current baked-in skills, which are
markdown-only (`.claude/skills/*.md`). Both kinds' `files[]` paths are subject to the same path-safety rule — normalized, relative, and confined to the item dir (§3.2, enforced at §6.1/§6.2).

**`files[].mode` contract.** `mode` is optional and follows exactly what
the live installer already honors — no core change. `registry_sync._install_skill`
applies a mode only in two cases: when `mode` is a JSON **integer** (it runs
`target.chmod(mode & 0o777)`) or when `mode` is the literal string **`"+x"`**
(it ORs the execute bits onto the file's current mode). Any other value —
including a **string-octal** form like `"0644"` or `"0755"` — matches neither
branch and is **silently ignored**, leaving the file at the default umask
permissions with no executable bit. The contract here therefore admits only
those two shapes: omit `mode` (or use an integer) for regular content files,
and use `"+x"` for files that must be executable. The importer (§5) is
responsible for emitting one of these shapes — never a string-octal value —
so a seeded executable helper actually lands executable.

### 3.2 `kind=module`

A module is a bundled package: a manifest, an idempotent install recipe,
the served script files themselves, declared (non-secret) env-var
**names**, and an optional bundled `SKILL.md`. One line:
**`{ manifest: { name, version, env_keys[], scripts[], requires_service? }, files: [{ path, content, mode }], install: { steps[] }, skill: <SKILL.md> | null, source: { fixture, synced_from } }`**.

```jsonc
// registry_item_revisions.payload for kind=module
{
  "manifest": {
    "name": "superpos-github",
    "version": "1.0.0",
    "env_keys": ["SUPERPOS_BASE_URL", "SUPERPOS_HIVE_ID",
                 "SUPERPOS_AGENT_ID", "SUPERPOS_API_TOKEN"],  // NAMES ONLY
    "scripts": ["superpos-github"],          // which served files become PATH entries
    "requires_service": "github"             // optional, non-blocking dashboard hint
  },
  "files": [                                 // the served script artifacts; mirrors skills' files[]
    { "path": "scripts/superpos-github",     // path relative to the module dir
      "content": "#!/usr/bin/env bash\n...", // the actual script body
      "mode": "+x" }                         // "+x" (or an int); scripts must be executable
  ],
  "install": {
    "steps": [                               // idempotent recipe (today's module setup)
      { "type": "symlink_scripts" },
      { "type": "render_claude_md" },
      { "type": "run_setup", "when": "workspace" }
    ]
  },
  "skill": "# superpos-github\n...",          // bundled SKILL.md, or null
  "source": {
    "fixture": "modules/superpos-github",     // path under the seed-fixture tree
    "synced_from": "superpos-agent-core@<sha>"
  }
}
```

`files[]` carries the **actual content** of the module's scripts (and any
other bundled files), mirroring the skill payload's `files: [{ path,
content, mode }]` (§3.1). It is the served artifact mechanism that lets a
registry-served module install on a lean Beat-4 image with nothing
pre-baked: the runtime writes each `files[]` entry to disk at its declared
`path` and `mode` before symlinking. `manifest.scripts[]` and `files[]`
have a strict relationship — `scripts[]` names **which** served files
become `PATH` entries, and `files[]` carries **their content**; every name
in `scripts[]` must have a backing `files[]` entry (enforced write-time,
§6.1). `mode` matters because scripts must be executable — emitted as `"+x"`
(or an integer mode), the only shapes the live installer honors (see §3.1).

Each `manifest.scripts[]` entry must be a **safe basename** — no path
separators (`/` or `\`), no absolute path, and no `.`/`..` segment — that
names an executable resolving to a backing `files[]` entry. Because the
`scripts[]` values become the symlink names and targets created on `PATH`
at install (§6.2), a value that is not a bare safe basename could escape
the module/bin roots; the registry write-time validator therefore rejects
any `scripts[]` value that is not a bare safe basename (§6.1), the sibling
of the `files[]` path-safety guard below.

Every `files[]` `path` — in **both** kinds — must be a **normalized relative
path confined to the item's own directory**. An absolute path or any `..`
segment that would escape the skill/module dir (e.g.
`{"path": "../../.ssh/authorized_keys"}`) is **rejected**, not written. This
is not merely a documented convention: it is enforced at every layer that
writes registry-authored bytes to disk — the importer that embeds `files[]`
(§4.1), the write-time validator on the server (§6.1), and the runtime
materializer before any file write or symlink (§6.2) — mirroring the
path-safety check the skill installer already applies before laying down
helper `files[]`.

`env_keys` is the security-critical field — see §5. The `install.steps`
shape mirrors what `module_setup.run_setup()` already does for a baked-in
module today (write scripts → symlink scripts → render CLAUDE.md doc block
→ per-module setup); encoding it as data, alongside the served `files[]`,
lets the agent run the same recipe from a registry payload instead of from
files baked into the image.

## 4. Importer (Beat 1)

Two idempotent, hive-attached artisan commands, following the registry
service's existing create path (`RegistryService::createItem`, which
already creates the `RegistryItem` + initial `RegistryItemRevision` in one
transaction — [`app/Services/RegistryService.php`](../../app/Services/RegistryService.php)
lines 23–115):

```
php artisan registry:import-skills  [--hive=<id>|--all-hives] [--dry-run]
php artisan registry:import-modules [--hive=<id>|--all-hives] [--dry-run]
```

### 4.1 Source: CI-synced seed fixtures (locked)

The importer reads **seed fixtures checked into superpos-app**, not the
live `superpos-agent-core` package. The fixtures are the authoritative
source the importer materializes:

```
database/registry-fixtures/
  skills/<slug>.md
  modules/<slug>/module.yaml
  modules/<slug>/SKILL.md
  modules/<slug>/scripts/*
```

The module importer reads each fixture's `scripts/*` files and **embeds
their content into the module payload's `files[]`** — one `{ path,
content, mode }` entry per script file (`path` relative to the module dir,
e.g. `scripts/superpos-github`; `mode` derived from the fixture's
permission bits — emitted as `"+x"` when the fixture file carries an
execute bit, omitted otherwise — so the served script stays executable
under the live installer's `int`/`"+x"` contract (§3.1), never as an
ignored string-octal value). This closes the round-trip end to end:
**fixture `scripts/` → importer embeds as `files[]` → registry serves the
payload → runtime writes the files + symlinks `scripts[]`** (§6.2). Nothing
is left on disk for the runtime to find — the payload is self-contained.
The skill importer does the same for any helper files alongside a skill's
markdown.

A CI job keeps these fixtures synced from `superpos-agent-core` (it diffs
the upstream module/skill sources and opens a PR when they drift). The
importer has **no runtime coupling to the core repo** — at import time it
only ever touches local files.

**Why fixtures over a live manifest pull (rationale).** The original
proposal left this as a fork in the road: import from a live manifest
served by `superpos-agent-core`, or snapshot the sources into superpos-app.
We choose **fixtures**. A live-manifest pull was considered and rejected:
it would make the app's import path depend on the core service being
reachable and version-matched at import time, reintroducing exactly the
runtime cross-repo coupling the registry exists to remove. Fixtures make
the import deterministic and reviewable (the diff shows up in a PR), keep
superpos-app self-contained for tests and CI, and move the
cross-repo concern to a single, observable CI sync job rather than the hot
path. The cost — fixtures can lag upstream until the sync PR merges — is
acceptable and visible.

### 4.2 Idempotency

- **Idempotency key** = `(hive_id, kind, slug)` — the same partial unique
  index (`idx_registry_items_live_slug`) the subagent path already relies
  on. The importer looks up a live item by that key; if absent it creates,
  if present it compares the incoming payload against
  `latest_revision_id`'s payload and appends a new revision **only on
  change** (no-op re-import creates no revisions).
- Re-running either command is safe and produces no churn when fixtures
  are unchanged. `--dry-run` reports what would be created/updated.

### 4.3 Hive attachment

After create/update, the importer attaches each item at `scope=hive`
(matching how built-in subagents are seeded and how the original proposal
specifies skills/modules import "as hive-scoped items, attached to the
hive by default so behavior is unchanged" —
[`docs/proposals/registry.md`](registry.md) lines 926–930). Hive
attachment uses the existing attachment path; modules are **never**
attached at `scope=task` (`RegistryService` already rejects task-scoped
modules — see [`app/Services/RegistryService.php`](../../app/Services/RegistryService.php)
line 365).

### 4.4 v1 module set (locked)

The import covers the **4 `module.yaml` modules**: `superpos-github`,
`superpos-issues`, `superpos-knowledge`, `superpos-workflows`.
`superpos-sdk` is **excluded** — it is a pip dependency that happens to
ship scripts, not a `module.yaml` module directory, so it has no manifest
to import and is explicitly carved out of v1. (Note: the original
proposal said "six bundled modules"; the real, current `module.yaml`
count is four. This proposal supersedes that number.)

## 5. Module secret-binding (locked: declaration-only)

Modules declare the **names** of the env vars their scripts need; they
never carry values. This preserves the platform invariant **"agents never
see credentials."**

- The registry stores `manifest.env_keys` as a list of NAMES only. A
  write-time validator (added to the module write path / a rule on
  `StoreRegistryItemRequest` —
  [`app/Http/Requests/StoreRegistryItemRequest.php`](../../app/Http/Requests/StoreRegistryItemRequest.php))
  **rejects any `KEY=value` form** — any entry containing `=` is a
  validation error. This makes it structurally impossible to smuggle a
  secret value into a module payload.
- Binding stays at the **credential proxy**. Third-party credentials never
  enter the agent environment; module scripts call the existing credential
  proxy, which injects them server-side keyed by agent identity + the
  hive's `service_connections`. This is the same mechanism the current
  baked-in modules already use (e.g. `superpos-github` scripts call the
  proxy rather than reading a token from env).
- `manifest.requires_service` is an **optional, non-blocking** dashboard
  hint (e.g. "this module wants a `github` service connection"). It never
  gates install or resolution.
- **No new secret store** is introduced.

## 6. Serving + runtime adapter (Beats 2–3)

### 6.1 Server side

No `/registry/resolved` changes are required for correctness — the
resolution loop (§2.3) is already kind-agnostic and will emit
`skill`/`module` winners as soon as items exist and are attached. The only
server work is (a) the write-time `env_keys` validator (§5) and a sibling
rule that **rejects any module whose `manifest.scripts[]` names a script
without a corresponding `files[]` entry** (a module must not claim a
`PATH` script it does not actually serve — otherwise resolution would emit
a module the runtime cannot install) — and, in addition to that
backing-entry check, a sibling rule that **rejects any module whose
`manifest.scripts[]` contains an absolute path, any `/` or `\` separator,
or a `..`/`.` segment** (so a `scripts[]` value can only ever name a bare
safe basename, never a path that would escape the module/bin roots when
symlinked onto `PATH`, §6.2) — and a sibling rule that **rejects any
`files[]` entry whose `path` is absolute or contains a `..` segment** (so
registry-authored bytes can never be written outside the item's own
directory), and (b) ensuring list/detail
formatters (`RegistryApiController::formatItemFull` etc.) surface the new
kinds, which they already do generically.

### 6.2 Agent-core side

This is the substantive consumer work, in `superpos-agent-core`:

- **Skills**: extend the runtime-bundle adapter that today materializes
  `subagent` entries from `/registry/resolved` so it also writes
  `kind=skill` entries to `.claude/skills/<slug>/SKILL.md` (`SKILL.md`
  body = payload `instructions`; any `files[]` written relative to the
  skill dir). This is the skill-overlay analogue of the existing
  subagent overlay. **Status: already landed** —
  `registry_sync._install_skill` implements exactly this, and
  `tests/test_registry_sync.py::test_installs_new_desired_items` is the
  contract test that proves a seeded skill (payload `instructions` +
  helper `files[]`) round-trips into a **non-empty** `SKILL.md`. Beat 2
  must add one further contract test alongside it — a seeded helper file
  carrying `mode: "+x"` materializes **with its execute bit set** — to
  pin the `files[].mode` contract (§3.1) against `_install_skill`'s
  `int`/`"+x"` mode handling and guard against a regression to the
  silently-ignored string-octal shape. Beat 2 then wires the adapter into
  the live resolve loop.
- **Modules**: `module_loader.discover_modules()` and
  `module_setup.run_setup()` learn a **registry source** in addition to
  the packaged-directory source. Instead of discovering `module.yaml`
  dirs inside the package, they consume `kind=module` entries from
  `/registry/resolved`, then run the same install recipe they run today,
  driven by `install.steps` rather than on-disk files. Because the lean
  Beat-4 image has **no baked-in module files to symlink**, the adapter
  must materialize the served artifacts first: it (1) **validates and writes
  each `payload.files[]` entry to disk** at its declared `path` relative to the
  module dir, with its declared `mode` (`"+x"` or an integer — the shapes
  the live installer honors, §3.1 — so scripts land executable) —
  **normalizing the path and rejecting any absolute path or `..`
  segment that would escape the module dir before writing** — then (2) **symlinks the `manifest.scripts[]` names onto `PATH`**
  — each name now resolving to a file the adapter just wrote. Before
  creating each symlink the adapter **resolves both the materialized source
  file and the intended link path and confirms BOTH stay confined within
  the module root (source) and the managed bin root (link)**, rejecting any
  entry whose resolved source or link escapes those roots and recording a
  `registry.module_install_failed` activity-log entry (the same
  install-failure mode as §6.3). This runtime confinement is the backstop
  even though the write-time validator (§6.1) should already have rejected
  any unsafe `scripts[]` name — then (3)
  renders the module doc block (from `payload.skill`) into `CLAUDE.md`, and
  (4) runs per-module setup for workspace modules. Nothing is assumed
  pre-baked; the payload is the sole source of the script bodies.
- **Required contract tests** (sibling to the `files[]` path-safety
  coverage). Just as `tests/test_registry_sync.py` proves the `files[]`
  guard rejects a `../`/absolute `path`, the contract test suite must
  cover a malicious `manifest.scripts[]` value — both an absolute path and
  a `../` escape — being rejected at **both** layers: the write-time
  validator (§6.1) rejecting the non-basename `scripts[]` value, and the
  runtime adapter (§6.2) rejecting (and logging
  `registry.module_install_failed` for) an entry whose resolved source or
  link path escapes the module/bin roots.

### 6.3 Install-failure mode (locked: degraded + one retry + log)

If a module fails to install at startup:

1. **Retry once** with backoff.
2. On second failure, **skip the module** — no script symlink, no doc
   injection.
3. Record an activity-log event `registry.module_install_failed` (module
   slug, revision, error).
4. **Keep polling.** The agent does not refuse to start.

Rationale: refusing to start would brick a polling agent over one flaky
module install; a silent skip is undiagnosable. Degraded mode with a
bounded retry and a logged record is the only option that keeps the agent
alive **and** observable.

## 7. Rollout (4-beat, mirrors the subagent migration)

1. **Import / backfill** — ship `registry:import-skills` /
   `registry:import-modules` (idempotent, hive-attached, §4). Items exist
   in the registry but are not yet consumed; baked-in artifacts still
   drive behavior. Reversible.
2. **Dual-source** — the agent overlays registry-resolved skills/modules
   on top of the baked-in artifacts, flag-gated (a
   `config('platform.registry.*')` style flag, sibling to the gates that
   lived at [`config/platform.php`](../../config/platform.php) line 903).
   Instant rollback by flipping the flag.
3. **Registry-primary serving** — agents fetch skills/modules via
   `/registry/resolved` as the source of truth; baked-in artifacts become
   a fallback only.
4. **Drop baked-in artifacts** — remove `.claude/skills/*.md` and the
   packaged `module.yaml` dirs from the image; ship the lean image. This
   is a **coordinated superpos-app + agent-repo release** (the app must be
   serving registry-primary before the image drops its fallback).

This is the same reversible-then-irreversible cadence the subagent
migration used (b1 reversible, b2 irreversible — see
[`docs/proposals/registry-b2-cutover.md`](registry-b2-cutover.md) §3).

## 8. Risks & rollback

| Risk | Mitigation |
|---|---|
| Fixtures drift from upstream `superpos-agent-core`. | CI sync job opens a PR on drift; drift is visible in review. Import is a no-op when fixtures are unchanged. |
| A module install fails at agent startup. | Degraded mode: one retry, then skip + `registry.module_install_failed` log. Agent keeps polling (§6.3). |
| A secret value is smuggled into a module payload. | Write-time validator rejects any `KEY=value` form in `env_keys`; values only ever come from the credential proxy (§5). |
| A registry-served module installs as docs/metadata only on the lean image (no script bodies to symlink). | The module payload carries the script bodies in `files: [{ path, content, mode }]` (§3.2); the runtime writes them before symlinking (§6.2), and a write-time rule rejects any `scripts[]` name without a backing `files[]` entry (§6.1). |
| A malicious or buggy `files[]` `path` (`../…` or absolute) writes outside the item dir on disk. | `path` must be a normalized relative path confined to the skill/module dir; rejected at write-time validation (§6.1) and again by the runtime materializer before any write or symlink (§6.2), mirroring the path-safety check the skill installer already applies. |
| A malicious or buggy `manifest.scripts[]` value (`../…` or absolute) escapes the module/bin roots when symlinked onto `PATH`. | Each `scripts[]` entry must be a bare safe basename; rejected at write-time validation (§6.1) and again by the runtime adapter, which resolves the source file and link path and confirms both stay confined to the module root and the managed bin root before symlinking (§6.2), mirroring the `files[]` path-safety guard. |
| Beat-4 image drop races ahead of registry-primary serving. | Beat 4 is gated on Beat 3 being live in prod; it is an explicitly coordinated cross-repo release. Until then the baked-in artifacts remain as fallback. |
| Resolution regression for `subagent`. | The resolution loop is unchanged; skill/module are additive. Existing subagent tests guard the shared path. |

**Rollback per beat:** Beats 1–3 are flag- or fixture-reversible (disable
the import, flip the dual-source flag, or revert to baked-in fallback).
Beat 4 is the only irreversible step and is therefore the only one
requiring a coordinated release + bake period — exactly as in the
subagent cutover.

## 9. Non-goals

Deferred to separate proposals:

- **subagent ↔ skill unification.** Subagents increasingly look
  skill-like, but merging the two kinds is out of scope here.
- **task-scoped modules.** v1 keeps the existing rejection of
  `scope=task` for `kind=module` (modules have shared-state side effects —
  PATH mutation, installs, env injection — that are unsafe under
  task-level file sandboxing). Skills and subagents remain task-scopable.

## 10. Open questions for reviewers

These are genuinely still open (the four locked decisions — v1 module set,
fixture sync ownership, declaration-only secret binding, and degraded
install-failure mode — are settled and written above as decided):

1. **CI sync mechanism details.** What exactly triggers the
   superpos-agent-core → superpos-app fixture sync (push to core `main`?
   tagged release? nightly?), and how is a sync PR reviewed/auto-merged?
   The ownership is decided (CI-synced fixtures in superpos-app); the
   plumbing is not.
2. **Beat-4 cross-repo release coordination.** What is the concrete
   handshake that guarantees the app is serving registry-primary in prod
   before the agent image drops its baked-in fallback — a version gate, a
   health check, a manual sign-off, or a feature-flag both sides read?
3. **Fixture format for `install.steps`.** §3.2 sketches a step list
   (`symlink_scripts` / `render_claude_md` / `run_setup`). Should the
   importer derive these steps from each `module.yaml` automatically, or
   should the step list be authored explicitly per module in the fixture?
