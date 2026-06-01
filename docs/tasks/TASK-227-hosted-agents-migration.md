# TASK-227: Hosted agents migration + models

**Status:** pending
**Branch:** `task/227-hosted-agents-migration`
**PR:** —
**Depends on:** TASK-007
**Blocks:** TASK-228, TASK-229, TASK-230, TASK-231, TASK-233, TASK-236, TASK-240, TASK-244, TASK-253
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §9

## Objective

Create the database schema and Eloquent models that back Hosted Agents on
novps.io: one row per deployed agent (`hosted_agents`) plus a deployment
history log (`hosted_agent_deployments`).

## Requirements

### Functional

- [ ] FR-1: `hosted_agents` table matching §9 of the feature doc — agent FK,
  preset_key, model, encrypted user_env, novps handles (app name/id,
  resource_id, latest deployment_id), status enum, replica size+count.
- [ ] FR-2: `hosted_agent_deployments` table — per-deployment row with
  novps deployment id, status, triggered_by, image_tag, duration, log excerpt.
- [ ] FR-2a: `hosted_agents.image_tag_override` column (nullable string,
  default null). When set, the deploy job (TASK-230) uses this tag
  instead of the preset's default tag. Rollback (TASK-240) writes to
  this column so subsequent deploys stay pinned until the user
  explicitly clears or overwrites it.
- [ ] FR-3: `App\Cloud\Models\HostedAgent` Eloquent model with relationships
  to `Agent`, `Hive`, `Superpos`, and `deployments()` hasMany.
- [ ] FR-4: `App\Cloud\Models\HostedAgentDeployment` with belongsTo
  `HostedAgent`.
- [ ] FR-5: `user_env` encrypted at rest using Laravel Crypt cast
  (`encrypted:array`).
- [ ] FR-6: Status enum values: `pending`, `deploying`, `running`,
  `stopped`, `error`, `deleted`. `deleted` is a terminal state reached
  via the destroy flow (TASK-233) — the row is kept for historical
  deployment lookups but novps handles are nulled.
- [ ] FR-7: Indexes: partial index on `status` where
  status ∈ (deploying, running, error); index on `hosted_agent_deployments
  (hosted_agent_id, created_at DESC)`.
- [ ] FR-8: Unique index on `hosted_agents.novps_app_name` (null-safe —
  names are only assigned once the deploy job acquires one).
- [ ] FR-9: Factories for both models under `database/factories/cloud/`.

### Non-Functional

- [ ] NFR-1: Migration file lives under `database/migrations/cloud/` —
  only runs when `apiary.edition === 'cloud'` (align with existing cloud
  migration pattern).
- [ ] NFR-2: ULIDs for primary keys on both tables.
- [ ] NFR-3: `BelongsToApiary` + `BelongsToHive` traits applied so scoping
  works identically to other core models.
- [ ] NFR-4: No plaintext secret ever written to `activity_log` — the
  `HostedAgent` `toArray()` / API resource must mask `user_env` keys only
  (values never exposed).

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/cloud/YYYY_MM_DD_create_hosted_agents_table.php` | Schema for `hosted_agents` |
| Create | `database/migrations/cloud/YYYY_MM_DD_create_hosted_agent_deployments_table.php` | Schema for `hosted_agent_deployments` |
| Create | `app/Cloud/Models/HostedAgent.php` | Eloquent model |
| Create | `app/Cloud/Models/HostedAgentDeployment.php` | Eloquent model |
| Create | `database/factories/cloud/HostedAgentFactory.php` | Factory |
| Create | `database/factories/cloud/HostedAgentDeploymentFactory.php` | Factory |
| Modify | `config/apiary.php` | Add `hosted_agents.presets` stub + `enabled` flag |
| Modify | `config/services.php` | Add `novps` section |

### Key Design Decisions

- **One table, not three** (versus the retired K8s design's `managed_agents
  + managed_agent_builds + managed_agent_events`). We never build, so a
  build log is dead weight; lifecycle events land in the existing
  `activity_log` table.
- **`user_env` as JSON-in-encrypted-text**, not a linked secrets table.
  The payload is a small flat map (usually one key), and decrypting always
  requires the whole set. A join adds cost with zero benefit.
- **Soft delete by status, not Laravel SoftDeletes.** Destroy flips status
  to `deleted` and nulls novps handles after the remote DELETE succeeds —
  that way the row stays available for historical `deployments` lookups.

## Database Changes

See §9 of FEATURE_HOSTED_AGENTS.md for full SQL.

## Test Plan

### Unit Tests

- [ ] HostedAgent casts `user_env` via `encrypted:array` (round-trips).
- [ ] Factory produces a valid model with a minimal preset.

### Feature Tests

- [ ] Migration runs only under cloud edition; skipped on CE.
- [ ] `HostedAgent::forApiary()` / `forHive()` scope queries correctly.
- [ ] Deployment `hasMany` relation orders by `created_at DESC`.

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] ULIDs for primary keys
- [ ] BelongsToApiary/BelongsToHive applied
- [ ] `user_env` never serialized in plaintext to JSON
