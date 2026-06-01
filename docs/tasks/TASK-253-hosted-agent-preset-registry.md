# TASK-253: Hosted agent preset registry (seeded config)

**Status:** pending
**Branch:** `task/253-hosted-agent-preset-registry`
**PR:** —
**Depends on:** TASK-227
**Blocks:** TASK-228, TASK-230, TASK-231, TASK-254
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §3

## Objective

Introduce the preset catalogue that the CRUD API, wizard, and deploy job
consume. MVP reads from `config/platform.php` — the shape is designed to
migrate cleanly to a DB-backed admin CRUD (TASK-254) later.

## Requirements

### Functional

- [ ] FR-1: `App\Cloud\Services\HostedAgentPresetRegistry` exposes:
    - `all(): array<HostedAgentPreset>` — ordered by config key.
    - `find(string $key): ?HostedAgentPreset`
    - `requireFind(string $key): HostedAgentPreset` — throws
      `HostedAgentPresetNotFoundException`.
- [ ] FR-2: `App\Cloud\Models\HostedAgentPreset` value object carries:
  `key`, `label`, `description`, `image` (name+tag), `command`,
  `replicas` (size+count), `restart_policy`, `models[]`, `model_env_key`,
  `user_env` (schema map).
- [ ] FR-3: Registry is instantiated from
  `config('platform.hosted_agents.presets')` and validates each entry at
  boot — misconfigured preset raises `HostedAgentPresetConfigException`
  before HTTP requests start, not when a user tries to use it.
- [ ] FR-4: Seed the two MVP presets in `config/platform.php`:
    - `claude-sdk` → `ghcr.io/superpos-ai/superpos-claude-agent`
      with models `[claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5-20251001]`
      and required env `ANTHROPIC_API_KEY`.
    - `codex-sdk` → `ghcr.io/superpos-ai/superpos-codex-agent`
      with models `[gpt-5.4, gpt-5.4-mini, gpt-5.3-codex, gpt-5.2]` and required env
      `OPENAI_API_KEY`.
- [ ] FR-5: Tag override via env per preset:
  `SUPERPOS_HOSTED_CLAUDE_TAG`, `SUPERPOS_HOSTED_CODEX_TAG` — defaults to
  `latest`.
- [ ] FR-6: `sanitizedCatalogue(): array` method produces the shape the
  dashboard wizard consumes — omits `image.name`, `command`,
  `registry_credential_id`.

### Non-Functional

- [ ] NFR-1: Registry is a singleton bound in the container.
- [ ] NFR-2: The `HostedAgentPreset` class is the **only** producer of
  the novps payload section for image + command + replicas. Deploy job
  (TASK-230) asks the preset, never reads config directly.
- [ ] NFR-3: No DB reads — the MVP path is pure config so CE can parse
  config without a migration.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Cloud/Services/HostedAgentPresetRegistry.php` | Lookup API |
| Create | `app/Cloud/Models/HostedAgentPreset.php` | Value object |
| Create | `app/Cloud/Exceptions/HostedAgentPresetNotFoundException.php` | Typed error |
| Create | `app/Cloud/Exceptions/HostedAgentPresetConfigException.php` | Typed error |
| Modify | `config/platform.php` | Seed the two presets + `enabled` + `app_name_prefix` |

### Key Design Decisions

- **Value object, not Eloquent model.** Preset is immutable and
  config-sourced in MVP. When TASK-254 lands, `HostedAgentPreset` becomes
  the model-layer API; the caller contract stays the same.
- **Sanitized catalogue is a separate method**, not a view layer concern.
  Centralises the "what can the user see" decision so any consumer (API,
  dashboard, SDK) gets the same filtered data.

## Test Plan

### Unit Tests

- [ ] `find` returns null for unknown key.
- [ ] `requireFind` throws typed exception.
- [ ] Malformed preset (missing required field) throws
  `HostedAgentPresetConfigException` on registry boot.
- [ ] `sanitizedCatalogue` strips image.name + command + credential id.
- [ ] Env override (`SUPERPOS_HOSTED_CLAUDE_TAG`) is picked up.

### Feature Tests

- [ ] Container resolves a registry singleton.
- [ ] Registry visible only under cloud edition.

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant
- [ ] No DB dependency for MVP
- [ ] Preset shape is forward-compatible with TASK-254 DB schema
