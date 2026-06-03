# Proposal: Admin-configurable hosted-agent presets (DB-backed)

**Task:** TASK-254
**Authoritative spec:** [`docs/tasks/TASK-254-admin-hosted-agent-presets.md`](../tasks/TASK-254-admin-hosted-agent-presets.md)
**Status:** complete (all 5 steps merged)
**Edition:** cloud-only

> **Completion note (TASK-254 step 5/5):** All five implementation steps
> are complete. The `config('platform.hosted_agents.presets')` block in
> `config/platform.php` is now used only as a seed source / dev fallback.
> The `hosted_agent_presets` database table is the runtime source of truth.
> Presets are managed via the admin UI at `/admin/hosted-agent-presets`.
> The `HostedAgentPresetSeeder` is additive only (`firstOrCreate`) — it
> creates missing presets but never updates existing rows.

This proposal documented the design for TASK-254 during implementation.
All five steps have been merged. Where the task file pinned a decision
(FR-1 .. FR-7, NFR-1 .. NFR-3), this proposal **reused** it verbatim and
only filled gaps.

---

## Part A — Current state recap

Today the catalogue of hosted-agent presets is hard-coded in
[`config/platform.php`](../../config/platform.php) lines 246–326 under
`hosted_agents.presets`. Two presets ship: `claude-sdk` and `codex-sdk`.
The values are hydrated into immutable
[`App\Cloud\Models\HostedAgentPreset`](../../app/Cloud/Models/HostedAgentPreset.php)
value objects through `HostedAgentPreset::fromConfig()` (see lines 77–254 —
the validator that owns the schema contract today). The
[`HostedAgentPresetRegistry`](../../app/Cloud/Services/HostedAgentPresetRegistry.php)
takes the raw config array in its constructor (lines 31–41) and is bound
**once at boot** as a singleton in
[`AppServiceProvider`](../../app/Providers/AppServiceProvider.php) lines
50–55, gated on `config('platform.edition') === 'cloud'`. The
[`HostedAgent`](../../app/Cloud/Models/HostedAgent.php) row stores the
preset identifier as a plain `string('preset_key', 64)` column
(`database/migrations/cloud/2026_04_16_000010_create_hosted_agents_table.php`
line 26) — there is no FK; the registry is the source of truth at
runtime, and a missing key currently raises
`HostedAgentPresetNotFoundException`.

Adding a new LLM backend, a non-LLM language runtime (PHP/JS/Java/Go), or
a custom user image therefore requires a code change, a redeploy, and a
restart to pick up the new singleton — operators have no way to ship a
preset without engineering involvement, which is the gap TASK-254 closes.

## Part B — Schema

### Migration: `create_hosted_agent_presets_table`

Path: `database/migrations/cloud/YYYY_MM_DD_create_hosted_agent_presets_table.php`
(cloud-only — the table belongs in `database/migrations/cloud/`, the same
folder that holds `create_hosted_agents_table.php`).

| Column | Type | Notes |
|---|---|---|
| `id` | `ulid` (string 26, PK) | `Str::ulid()`, matches the ULID convention used across the codebase. |
| `key` | `string(64)`, **unique** | Slug (`claude-sdk`, `php-worker`). Same shape consumed today by `HostedAgent.preset_key`. |
| `label` | `string(120)` | Human-readable name. |
| `description` | `text` | Surfaced in the wizard. |
| `image` | `jsonb`, **NOT NULL** | `{name: string, tag: string}` — matches the MVP `ImageSpec` type alias (`HostedAgentPreset.php` line 16). E.g. `{"name": "ghcr.io/superpos-ai/superpos-claude-agent", "tag": "latest"}`. Keeping the structured shape avoids a lossy flatten and lets `fromConfig()` / Eloquent hydrate with zero mapping. |
| `command` | `string(255)`, **nullable** | Null = use Docker `CMD`; matches the comment block at config/platform.php:271–280. |
| `models` | `jsonb`, **NOT NULL** | List of allowed model strings. Must be a non-empty array — this matches the existing `fromConfig()` validation (line 114–118), the `CreateHostedAgentRequest` `model` rule (line 84, required), and `Wizard.jsx` which accesses `selectedPreset.models` without a null guard (line 225). Non-LLM presets are deferred (Open Question 4); if they land, the migration path must first add null-handling to `HostedAgentEnvResolver` (line 64), `CreateHostedAgentRequest::modelRule()` (lines 127–138), and `Wizard.jsx` (lines 119, 225–227) before relaxing the column constraint. |
| `model_env_key` | `string(64)`, **NOT NULL** | e.g. `CLAUDE_MODEL`, `OPENAI_MODEL`. Required because `HostedAgentEnvResolver` unconditionally indexes into it at line 64 (`$merged[$preset->modelEnvKey] = $agent->model`). Same migration-first rule as `models` above. |
| `replicas` | `jsonb`, **NOT NULL**, default `'{"size":"xs","count":1}'` | `{size: string, count: int}` — matches the MVP `ReplicasSpec` type alias (`HostedAgentPreset.php` line 17). Keeps the structured shape consistent with `image` and avoids splitting a value object across two flat columns. |
| `restart_policy` | `string(16)`, default `'always'` | Mirrors `data['restart_policy']` validation in fromConfig() line 228. |
| `user_env` | `jsonb` | Associative map keyed by env-var name (`array<string, {required?, secret?, help?, default?}>`), matching the existing `UserEnvSchema` type alias (`HostedAgentPreset.php` line 18). E.g. `{"ANTHROPIC_API_KEY": {"required": true, "secret": true, "help": "Your API key"}}`. The keys of the map are the environment variable names — there is no separate `key` field inside each entry. Validated by the same rules as `HostedAgentPreset::ALLOWED_USER_ENV_KEYS` (line 36) and `RESERVED_USER_ENV_PREFIX` (line 47). The `help` field must be plaintext, max 500 characters (NFR-2). |
| `is_enabled` | `boolean`, default `true` | Soft-disable toggle (FR-7). Disabled presets disappear from the wizard but existing agents continue. Named `is_enabled` to match the task spec (TASK-254 FR-1 line 25). |
| `is_seeded` | `boolean`, default `false` | True for built-in rows imported from config. Prevents the seeder from clobbering admin edits on subsequent deploys. |
| `created_by_user_id` | `ulid`, nullable | FK to `users.id`. Null for seeded rows. |
| `created_at`, `updated_at` | `timestamps` | |

Indexes: unique on `key`; partial on `is_enabled` for wizard listing.

### Handling the existing two presets

The seeder (`HostedAgentPresetsConfigSeeder`, listed in the task file's
"Files to Create / Modify" table) backfills `claude-sdk` and `codex-sdk`
from the current config block as `is_seeded: true` rows on first deploy.
The seeder is **idempotent and additive only**: on subsequent deploys it
inserts missing seeded keys but never updates existing rows. This means
admin edits always win — config drift after backfill is intentional, not
a bug.

**DB + config merge fallback (FR-3).** The registry merges the config
array from `config('platform.hosted_agents.presets')` into the result
**only when the DB table is empty** (zero rows). This is required by
TASK-254 FR-3 ("Config-backed presets continue to work as a fallback for
dev environments") and is essential for local dev where the migration or
seeder may not have run. The merge lives in
`HostedAgentPresetRegistry::all()` and is exercised by tests (see Part C,
step 3). Once the seeder has populated the table the config block is
inert — the DB is the sole source of truth. This means admin deletions
are real: deleting a seeded row removes it from the catalogue without the
config fallback reintroducing it on the next read.

## Part C — Registry refactor

The existing contract — `find()`, `requireFind()`, `all()`,
`sanitizedCatalogue()` returning `HostedAgentPreset` value objects — must
not change (TASK-254 design decision: "Registry contract does not change").
Every caller verified:

- `HostedAgentEnvResolver` (constructor injection at line 42)
- `HostedAgentDeployer` (line 86)
- `CreateHostedAgentRequest::preset()` (line 108)
- `UpdateHostedAgentRequest::preset()` (line 65)
- `HostedAgentDashboardController` (lines 82, 200)
- `Api\HostedAgentPresetController`

Refactor outline:

1. `HostedAgentPreset` becomes an **Eloquent model** in addition to its
   current value-object accessors. The `->key`, `->image`, `->command`,
   `->models`, `->modelEnvKey`, `->userEnv`, `->replicas`, `->label`,
   `->description` accessors stay (some via Eloquent attribute casts,
   some via accessors). `fromConfig()` is preserved for the seeder and
   for tests that build presets without hitting the DB; it becomes a
   factory that returns an unsaved Eloquent instance.
2. `HostedAgentPresetRegistry` no longer takes a config array. It depends
   on the model and on the cache repository:
   ```php
   public function __construct(private CacheRepository $cache, private array $configFallback) {}
   ```
   `all()` reads `Cache::remember('hosted_agent_presets:all', 300, fn() => HostedAgentPreset::query()->orderBy('key')->get()->keyBy('key')->all())` (FR-2: 5-min Redis TTL). The `orderBy('key')` and trailing `->all()` preserve the current contract: a plain `array<string, HostedAgentPreset>` sorted alphabetically by key (matching the existing `ksort()` behaviour and the assertions in `HostedAgentPresetRegistryTest`).
3. **Fallback for empty DB.** When the DB table has zero rows (migration
   landed but seeder hasn't run yet, or running locally without a seed),
   the registry falls back to `$configFallback` from
   `config('platform.hosted_agents.presets')` (FR-3). Once at least one
   row exists the config block is ignored entirely, so admin deletions
   are permanent and the DB is the sole source of truth.
4. **Cache busting.** A model observer (`HostedAgentPreset::saved` /
   `::deleted`) calls `Cache::forget('hosted_agent_presets:all')` so admin
   CRUD takes effect on the next request.
5. The singleton binding in `AppServiceProvider` lines 50–55 is replaced
   by a request-scoped `bind()` (or kept as singleton with a manual
   `flush()` method invoked by the observer).

Boot-time validation moves to model save: a `saving` hook re-runs the
existing `HostedAgentPreset::fromConfig()` validation rules against the
attribute payload so a malformed admin save is rejected with the same
exception type used today, keeping seeder/runtime validation symmetric.

**`user_env.*.help` length cap (NFR-2).** The existing `fromConfig()`
validator (line 181) only checks that `help` is a string — it does not
enforce a length limit. TASK-254 NFR-2 requires `user_env.help` to stay
within 500 plaintext characters. This rule must be added in two places:

1. **`fromConfig()`** — add a `mb_strlen($envSpec['help']) > 500` check
   immediately after the existing `is_string` check (line 181–184) so
   that config-sourced and seeder-sourced presets are also constrained.
2. **Admin form requests** (`CreateHostedAgentPresetRequest` /
   `UpdateHostedAgentPresetRequest`) — add a Laravel `max:500` rule on
   `user_env.*.help` so the admin UI surfaces a proper validation error.

A dedicated test should verify that both `fromConfig()` and the form
request reject `help` values exceeding 500 characters.

## Part D — Admin CRUD

Routes — added to the existing `if (config('platform.is_cloud', false))`
admin group in [`routes/web.php`](../../routes/web.php) lines 352–392
(under `EnsurePlatformAdmin` via the `platform-admin` middleware alias):

| Verb | Path | Controller method |
|---|---|---|
| GET | `/admin/hosted-agent-presets` | `index` |
| GET | `/admin/hosted-agent-presets/create` | `create` |
| POST | `/admin/hosted-agent-presets` | `store` |
| GET | `/admin/hosted-agent-presets/{preset}` | `show` |
| GET | `/admin/hosted-agent-presets/{preset}/edit` | `edit` |
| PATCH | `/admin/hosted-agent-presets/{preset}` | `update` |
| DELETE | `/admin/hosted-agent-presets/{preset}` | `destroy` |
| POST | `/admin/hosted-agent-presets/{preset}/enable` | `enable` |
| POST | `/admin/hosted-agent-presets/{preset}/disable` | `disable` |

The enable/disable verbs satisfy FR-4 (the task spec calls these out
explicitly) and avoid an awkward PATCH-with-only-`is_enabled` payload.

Controller: `app/Cloud/Http/Controllers/Admin/HostedAgentPresetController.php`
following the conventions of `AdminOrganizationController` and
`AdminHiveController` — thin, returns Inertia responses, delegates to
form requests for validation. Mutations write to `activity_log` (NFR-1)
matching the `logActivity()` calls in `Api\HostedAgentController`.

Form requests:
- `app/Cloud/Http/Requests/CreateHostedAgentPresetRequest.php`
- `app/Cloud/Http/Requests/UpdateHostedAgentPresetRequest.php`

Both reuse the validation primitives in `HostedAgentPreset::fromConfig()`
so a single source of truth governs schema rules. Note that `fromConfig()`
validates the `user_env` shape as an associative map keyed by env-var name
(see `UserEnvSchema` at `HostedAgentPreset.php` line 18) — the form
requests must preserve this shape, not flatten it into a list of objects.
In addition to the checks already in `fromConfig()`, the form requests
add the 500-character length cap on `user_env.*.help` required by NFR-2
(see Part C for details). Key-uniqueness is enforced via Laravel's
`unique:hosted_agent_presets,key` rule.

Inertia pages under `resources/js/Pages/Cloud/Admin/HostedAgentPresets/`:

- `Index.jsx` — table of presets with `is_enabled`, `is_seeded`, in-use
  count, and row actions (edit, enable/disable, delete).
- `Form.jsx` — shared create/edit form. Fields:
  - `label`, `key` (slug-validated, immutable on edit), `description`
  - `image.name`, `image.tag` (structured JSONB — matches the MVP `ImageSpec`)
  - `command` (optional, with the explanatory tooltip from
    config/platform.php:271–280)
  - `models` — multi-input list (required), plus `model_env_key` text input (required)
  - `replicas.size` dropdown (`xs|s|m|l`) + `replicas.count` (structured JSONB — matches the MVP `ReplicasSpec`)
  - `restart_policy`
  - `user_env` — repeater table where each row has an env-var name (the
    map key) plus `{required, secret, help, default}` fields (matching
    the `UserEnvSchema` associative-map shape). `help` is capped at 500
    plaintext characters (NFR-2)
  - `is_enabled` toggle

Frontend mirrors `resources/js/Pages/Cloud/Admin/Organizations/` shape so
review effort is minimal.

## Part E — User-facing changes

The existing dashboard create flow at
[`Wizard.jsx`](../../resources/js/Pages/Cloud/HostedAgents/Wizard.jsx)
already consumes a `presets` prop hydrated by
`HostedAgentDashboardController` line 85
(`'presets' => $registry->sanitizedCatalogue()`). After the registry
refactor (Part C) the same call-site reads from DB transparently — no
React change required.

`is_enabled = false` rows are filtered out of `sanitizedCatalogue()` so
the wizard only offers live presets (FR-7). Existing
`HostedAgent.preset_key` references to disabled or even deleted presets
keep resolving as long as the row still exists in the DB; the show page
at `HostedAgentDashboardController:201` calls `$registry->find()` which
returns null gracefully.

**Deletion safety.** Hard-deleting a preset that has live agents would
break their show pages and break re-deploys. Two options:

1. **Block deletion** when `HostedAgent::where('preset_key', $key)->exists()`
   — surface a 409 with a count of dependent agents. Forces the admin to
   migrate or stop those agents first.
2. **Soft-delete** with `deleted_at`. Show pages still resolve via
   `withTrashed()`; new wizard hides them.

Recommendation: **block** (option 1) for the first cut. Soft-delete is
strictly more code and the admin can always disable instead. Revisit
after we have telemetry on how often admins want to remove a preset.

## Part F — Migration plan

1. **PR 1 (S):** migration `create_hosted_agent_presets_table` +
   Eloquent model + `HostedAgentPresetsConfigSeeder` that backfills the
   two existing presets as `is_seeded=true` rows. No behavioural change
   yet — registry still reads from config.
2. **PR 2 (M):** registry refactor (Part C). Caller contract preserved;
   DB-first, config-fallback. Cache observer + tests.
3. **PR 3 (M):** admin CRUD backend — controller, form requests, routes,
   policies, activity log entries. **Also wires the `is_enabled` filter
   into `sanitizedCatalogue()`** so the wizard hides disabled presets as
   soon as the disable toggle ships (FR-7). Shipping the filter in a
   later PR would create an intermediate release where an admin disables
   a preset but the wizard still shows it.
4. **PR 4 (M):** admin CRUD frontend — Inertia Index + Form pages.
5. **PR 5 (S):** cleanup — config block stays, but documented as a seed
   source / dev fallback only. Long-term we can move the env-driven
   image tags out of config entirely.

Test coverage (per FR-1 .. FR-7 + NFR-1 .. NFR-3):

- Seeder produces a `HostedAgentPreset` whose `toSanitizedArray()` matches
  the pre-migration output byte-for-byte (regression guard).
- Registry caches results and busts on save/delete.
- Image allowlist (Part H) rejects foreign GHCR repositories.
- Disabling hides the preset from the wizard but does not break show
  pages of existing agents.
- Admin gate: non-admin users get a 404 (consistent with
  `EnsurePlatformAdmin`).
- `HostedAgent` create flow still succeeds end-to-end after migration.
- Activity log gains `hosted_agent_preset.created/updated/deleted/enabled/disabled` entries.

## Part G — Incremental delivery (sizing summary)

| # | Size | Scope | Risk |
|---|---|---|---|
| 1 | S | Migration + model + seeder | Low — additive table, no caller change |
| 2 | M | Registry refactor (DB-first, config-fallback) | Med — touches every preset consumer |
| 3 | M | Admin CRUD backend + `sanitizedCatalogue()` filter | Low — orthogonal to runtime; filter is a one-line `where` |
| 4 | M | Admin CRUD frontend | Low — pure Inertia |
| 5 | S | Config cleanup / docs | Trivial |

PRs 3 & 4 can land in parallel after PR 2.

## Part H — Security and safety

- **Image allowlist (FR-5, NFR-3).** Validate `image.name` server-side
  against `config('platform.hosted_agents.image_allowlist')`. Default
  list: `['ghcr.io/superpos-ai/', 'ghcr.io/apiary-ai/']`. Admins can
  edit the preset row but cannot bypass the allowlist — that's an ops
  setting in env / config. A malicious admin who got past the
  `EnsurePlatformAdmin` gate still cannot exfiltrate via a hostile
  image because the allowlist blocks the deploy.
- **`user_env` schema is metadata only.** The preset declares which
  keys the wizard accepts; per-tenant secret values are written into
  `HostedAgent.user_env` (encrypted via the model's
  `encrypted:array` cast, see HostedAgent.php line 70). The preset row
  must never carry plaintext secrets. Form-request validation rejects
  `user_env[*].default` on entries with `secret: true`, mirroring the
  existing rule at HostedAgentPreset.php:194.
- **`PLATFORM_` reserved prefix.** Re-enforce
  `HostedAgentPreset::usesReservedUserEnvPrefix()` (line 267) inside
  the form request so an admin cannot smuggle in a key that shadows
  platform-injected env vars.
- **Deletion guard.** `destroy()` returns 409 if any HostedAgent
  references the key; admins must disable + migrate first.
- **Seeded rows.** Even though admins can edit seeded rows (the
  in-DB row is fully mutable), the `is_seeded` flag is preserved so we
  can detect drift later if needed. Deleting a seeded row is allowed
  (admins who don't want Codex shouldn't be forced to keep the row),
  with the deletion guard from Part E.
- **`activity_log` entries** on every mutation (NFR-1) carry the actor
  user ID and a diff of changed columns.

## Part I — Open questions for the user

Five decisions that block code:

1. **Scope: org-scoped vs. global.** TASK-254 says "admin-only routes —
   not hive-scoped" (FR-4) which strongly implies global. Confirm: one
   catalogue across all tenants, only platform admins can edit?
2. **Categories / tags.** With ≥5 future presets (LLM backends + language
   runtimes + tools) the wizard needs filtering. Add `category` enum
   (`llm`, `runtime`, `tool`) now or defer until ≥5 presets exist?
3. **Image allowlist scope.** The task file pins
   `ghcr.io/apiary-ai/` as the example prefix. Should we ship with both
   `superpos-ai` and `apiary-ai` GHCR orgs, allow any GHCR repo, or
   accept arbitrary registries? My recommendation: ship with the two
   superpos/apiary GHCR prefixes, configurable via env.
4. **`models` for non-LLM presets.** A PHP-runtime preset has no model.
   Both `models` and `model_env_key` are NOT NULL in this proposal
   because the current runtime assumes they are always present (see
   schema notes). If non-LLM presets land, a preparatory PR must first
   add null-handling to `HostedAgentEnvResolver` (line 64),
   `CreateHostedAgentRequest::modelRule()` (lines 127–138), and
   `Wizard.jsx` (lines 119, 225–227) before a follow-up migration
   relaxes the column constraint to nullable. Alternatively, generalize
   to a `parameters` jsonb — but that is a bigger refactor. Defer.
5. **Tag versioning.** When an admin changes a preset's
   `image.tag` from `:v1` to `:v2`, do existing
   `HostedAgent`s redeploy onto `:v2` automatically (current behaviour:
   `image_tag_override` on `HostedAgent` lets a user pin), or do they
   stay on `:v1` until manually triggered? Recommendation: existing
   agents pick up the new default on next redeploy unless their
   `image_tag_override` is set, matching how the column is named.

---

**Sign-off:** complete. All five implementation steps merged.
