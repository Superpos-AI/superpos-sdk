# TASK-254: Admin-configurable hosted agent presets (DB-backed)

**Status:** done (all 5 steps merged)
**Branch:** `task/254-admin-hosted-agent-presets`
**PR:** merged (5 PRs — steps 1–5)
**Depends on:** TASK-253, TASK-241
**Blocks:** —
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §3

## Objective

Replace the `config/apiary.php` preset array with a DB-backed table plus
admin CRUD UI so operators can add / edit / deprecate presets without a
code deploy. Preserves the MVP API shape — callers of
`HostedAgentPresetRegistry` are untouched.

## Requirements

### Functional

- [x] FR-1: Migration creates `hosted_agent_presets` with the same fields
  as the MVP value object (key, label, description, image JSONB,
  command, replicas JSONB, restart_policy, models JSONB, model_env_key,
  user_env JSONB, is_enabled, created_at, updated_at).
- [x] FR-2: `HostedAgentPresetRegistry` reads from DB, cached for 5 min
  in Redis. Cache bust on write.
- [x] FR-3: Config-backed presets continue to work as a fallback for dev
  environments — registry merges DB + config with DB taking precedence
  on key collision. A one-off seeder imports the config presets into DB
  on first cloud deploy.
- [x] FR-4: Admin-only routes under `/admin/hosted-agent-presets` (not
  hive-scoped) — protected by the existing `admin` gate.
    - `GET` list, `POST` create, `PATCH /{key}`, `DELETE /{key}`,
      `POST /{key}/enable`, `POST /{key}/disable`.
- [x] FR-5: Validation: `image.name` must match the GHCR prefix
  `ghcr.io/apiary-ai/` (configurable allowlist). Protects against an
  admin pointing a preset at an untrusted image.
- [x] FR-6: Admin UI pages under `resources/js/Pages/Cloud/Admin/
  HostedAgentPresets/` for list + create/edit forms.
- [x] FR-7: Disabling a preset is soft — existing hosted agents keep
  running. Wizard hides disabled presets from the catalogue.

### Non-Functional

- [x] NFR-1: Activity log on preset mutations.
- [x] NFR-2: No plaintext `user_env.help` longer than 500 chars.
- [x] NFR-3: Image pull allowlist stored in
  `config('apiary.hosted_agents.image_allowlist')` — enforced server
  side regardless of what the admin UI accepts.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/cloud/YYYY_create_hosted_agent_presets_table.php` | Table |
| Create | `database/seeders/HostedAgentPresetsConfigSeeder.php` | Import from config on first boot |
| Modify | `app/Cloud/Services/HostedAgentPresetRegistry.php` | DB-first, config-fallback |
| Modify | `app/Cloud/Models/HostedAgentPreset.php` | Becomes an Eloquent model |
| Create | `app/Cloud/Http/Controllers/Admin/HostedAgentPresetController.php` | CRUD |
| Create | `app/Cloud/Http/Requests/CreateHostedAgentPresetRequest.php` | Validation |
| Create | `app/Cloud/Http/Requests/UpdateHostedAgentPresetRequest.php` | Validation |
| Create | `resources/js/Pages/Cloud/Admin/HostedAgentPresets/Index.jsx` | List UI |
| Create | `resources/js/Pages/Cloud/Admin/HostedAgentPresets/Form.jsx` | Create/edit UI |

### Key Design Decisions

- **Registry contract does not change.** Making `HostedAgentPreset` an
  Eloquent model while keeping the `->key`, `->image`, etc. accessors
  means every call site from MVP continues to work.
- **Allowlist is configuration, not DB.** Admins can edit presets but
  cannot change the set of trusted image prefixes — that's ops territory.
- **Config seed, then DB wins.** Existing cloud deploys keep their
  presets without manual import; future edits happen in DB.

## Test Plan

- [x] Seeder imports MVP config presets into DB.
- [x] DB override of a config key takes precedence.
- [x] Image allowlist rejects foreign registry.
- [x] Disabling a preset hides it from `sanitizedCatalogue`.
- [x] Admin UI requires admin gate.
- [x] Activity log on create/update/delete.

## Validation Checklist

- [x] All tests pass
- [x] Registry contract unchanged for existing callers
- [x] Image allowlist enforced server-side
- [x] Admin-only routes
