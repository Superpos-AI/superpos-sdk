# TASK-233: Hosted agent lifecycle API (start / stop / restart / scale / destroy)

> **Post-merge correction (2026-04-19):** references to `SUPERPOS_TOKEN`
> in this doc should be read as `SUPERPOS_API_TOKEN`; the env var was
> unified post-merge to match the Python SDK's `from_env()` contract
> (see TASK-256).

**Status:** pending
**Branch:** `task/233-hosted-agent-lifecycle-api`
**PR:** —
**Depends on:** TASK-228, TASK-229, TASK-230, TASK-231
**Blocks:** TASK-241
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §7, §10.2

## Objective

Expose explicit lifecycle endpoints and the backing jobs for stop / start /
restart / scale / destroy. Each endpoint is a thin controller action that
enqueues the matching job; the jobs do the novps round-trips and reconcile
`hosted_agents.status`.

## Requirements

### Functional

- [ ] FR-1: `POST .../hosted-agents/{id}/start` — allowed only from
  `stopped` or `error`. Enqueues `DeployHostedAgentJob` (same path as
  create). Immediate status → `deploying`.
- [ ] FR-2: `POST .../hosted-agents/{id}/stop` — allowed from `running`,
  `deploying`, or `error`. Enqueues `StopHostedAgentJob` which calls
  `NovpsClient::deleteResource($resourceId)`, clears
  `hosted_agents.novps_resource_id`, and sets `hosted_agents.status = stopped`.
  A 404 from NoVPS is treated as success (resource already gone). The
  resource is recreated by `applyApp()` on the next start.
- [ ] FR-3: `POST .../hosted-agents/{id}/restart` — allowed from
  `running`. Enqueues `DeployHostedAgentJob` with `restart=true` flag
  which calls `NovpsClient::redeploy($appId)` instead of re-applying.
- [ ] FR-4: `POST .../hosted-agents/{id}/scale` — accepts
  `{ replicas: { size, count } }`. Persists to DB and enqueues a scale
  job that calls `NovpsClient::scaleResource`.
- [ ] FR-5: `DELETE .../hosted-agents/{id}` (from TASK-228) routes through
  `DestroyHostedAgentJob` here. Job: calls
  `NovpsClient::deleteApp($appId)`, on success soft-deletes the
  `hosted_agents` row by setting `status = deleted` and nulling
  `novps_*` handles, revokes the agent's `SUPERPOS_API_TOKEN`, and archives
  the underlying `Agent` record (`is_archived = true`).
- [ ] FR-6: All endpoints return 202 with the updated resource + the
  queued job's name. Dashboard polls `GET /status` (TASK-228) for
  convergence.
- [ ] FR-7: State transitions guarded by an `assertTransitionAllowed()`
  helper — invalid transitions (e.g. start from `running`) return 409
  Conflict with a machine-readable `reason`.
- [ ] FR-8: Every lifecycle op writes an `activity_log` entry:
  `hosted_agent.{started|stopped|restarted|scaled|destroyed}`.

### Non-Functional

- [ ] NFR-1: All jobs are idempotent — running twice must not cause double
  destroys / double scales. Use the existing novps state as the
  convergence target, not the transition verb.
- [ ] NFR-2: On `deleteApp` 404 (already gone remotely), treat as
  successful destroy and converge DB state regardless.
- [ ] NFR-3: No lifecycle op may leak `SUPERPOS_API_TOKEN` or `user_env` through
  logs / activity_log / API response.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Cloud/Http/Controllers/Api/HostedAgentController.php` | Add lifecycle actions |
| Create | `app/Cloud/Jobs/StopHostedAgentJob.php` | DELETE resource |
| Create | `app/Cloud/Jobs/ScaleHostedAgentJob.php` | PATCH resource |
| Create | `app/Cloud/Jobs/DestroyHostedAgentJob.php` | delete app + cleanup |
| Create | `app/Cloud/Services/HostedAgentStateMachine.php` | Transition guard |
| Create | `app/Cloud/Http/Requests/ScaleHostedAgentRequest.php` | Validation |
| Modify | `routes/api.php` | Register lifecycle routes |

### Key Design Decisions

- **One job per verb.** `DeployHostedAgentJob` already handles start +
  restart; stop/scale/destroy are small enough that separate classes are
  clearer than a command pattern.
- **Destroy is terminal, not reversible.** Once `status = deleted` the
  same name can't be reused — dashboard enforces that by hiding deleted
  rows from the list endpoint.
- **`restart` uses `redeploy`, not `apply`.** `redeploy` on novps creates
  a new deployment without re-reading the app spec — faster + the spec is
  unchanged. `apply` is used only when the payload has changed.

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/v1/hives/{hive}/hosted-agents/{id}/start` | Start stopped agent |
| POST   | `/api/v1/hives/{hive}/hosted-agents/{id}/stop` | Scale to zero |
| POST   | `/api/v1/hives/{hive}/hosted-agents/{id}/restart` | Redeploy |
| POST   | `/api/v1/hives/{hive}/hosted-agents/{id}/scale` | Change replicas |
| DELETE | `/api/v1/hives/{hive}/hosted-agents/{id}` | Destroy (wired via TASK-228 controller) |

## Test Plan

### Unit Tests

- [ ] State machine: valid/invalid transitions matrix.
- [ ] Stop job calls `deleteResource($resourceId)` and clears `novps_resource_id`.
- [ ] Stop job treats a 404 from NoVPS as success (resource already gone).
- [ ] Scale job calls `updateResource` with new replicas payload.
- [ ] Destroy job calls `deleteApp`, revokes token, archives agent.
- [ ] Destroy on remote-404 still converges DB.

### Feature Tests

- [ ] Start from `stopped` → `deploying` → `running` end-to-end with
  `Http::fake()`.
- [ ] Stop while `running` → `stopped`, resource deleted on novps and `novps_resource_id` cleared.
- [ ] Restart while `running` uses `redeploy`, not `apply`.
- [ ] Scale with `{size:'sm', count:3}` persists + dispatches job.
- [ ] Invalid transition returns 409 with `reason`.
- [ ] Destroy cascades: agent archived, token revoked, novps app deleted.

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant
- [ ] Activity logging on each transition
- [ ] API envelope consistent
- [ ] Form Requests validate scale payloads
- [ ] Jobs idempotent
