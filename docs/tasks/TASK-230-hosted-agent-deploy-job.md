# TASK-230: Hosted agent deploy job (apply + poll)

> **Post-merge correction (2026-04-19):** references to `SUPERPOS_TOKEN`
> in this doc should be read as `SUPERPOS_API_TOKEN`; the env var was
> unified post-merge to match the Python SDK's `from_env()` contract
> (see TASK-256).

**Status:** pending
**Branch:** `task/230-hosted-agent-deploy-job`
**PR:** —
**Depends on:** TASK-227, TASK-228, TASK-229, TASK-231, TASK-253, TASK-255
**Blocks:** TASK-233, TASK-240, TASK-241
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §5

## Objective

Implement the queued job that turns a newly-created `hosted_agents` row
(status=`deploying`, per FEATURE §5 / TASK-228 FR-2) into a running
worker on novps.io. The job composes the full `apply` payload, calls
`NovpsClient::applyApp()`, polls the deployment to terminal state, and
reconciles `hosted_agents` status back to the database
(`deploying → running | error`).

## Requirements

### Functional

- [ ] FR-1: `App\Cloud\Jobs\DeployHostedAgentJob` accepts a
  `hosted_agent_id` and is dispatched on the `hosted-agents` queue.
- [ ] FR-2: Job loads the `HostedAgent`, resolves the preset from
  `HostedAgentPresetRegistry` (TASK-253), resolves the full env set
  (TASK-231), and constructs the novps `apply` payload:
    - Allocates a novps app name via
      `apiary.hosted_agents.app_name_prefix + slug(hive) + slug(agent)`,
      retrying once with a 4-char random hex suffix (`[0-9a-f]{4}`) on
      collision.
    - **App-name length enforcement (before `applyApp`):** novps caps
      app names at 40 chars and restricts the character set to
      `^[a-z0-9-]+$` (lowercase alphanumerics + hyphen — standard
      hostname charset). The slugger must lowercase and strip any
      character outside the allowed set. After assembling the candidate
      name (`prefix-slug(hive)-slug(agent)` and any retry suffix), if
      it exceeds 40 chars, truncate the `slug(hive)-slug(agent)`
      portion and append a `-` plus the first 6 hex chars of
      `sha256(prefix + "-" + slug(hive) + "-" + slug(agent))` so
      uniqueness is preserved deterministically. Both the 6-char hex
      hash and the 4-char retry suffix are inside `^[a-z0-9-]+$`. The
      prefix, the truncation, the 6-char hash, and any retry suffix
      must together stay within the 40-char / charset constraints; the
      allocator must assert this before the first `applyApp` call.
    - Builds one resource with `type: worker`, `source_type: docker`,
      `image: { name, tag, credentials }`, `config: { command,
      restartPolicy }`, `replicas: { type, count }`, `envs: […]`.
    - `credentials` references
      `config('services.novps.registry_credential_id')`.
    - **Image tag selection:** if `hosted_agents.image_tag_override` is
      non-null, use it as `image.tag`; otherwise fall back to the
      preset's default tag. Captured on the deployment row as
      `image_tag` either way (TASK-240 FR-4).
- [ ] FR-3: Calls `NovpsClient::applyApp($name, $payload)`.
  Captures `app_id`, `resource_id`, and `deployment_id` from the response,
  persists them to `hosted_agents` + creates a `hosted_agent_deployments`
  row (status=`pending`).
- [ ] FR-4: Polls deployment status every `apiary.hosted_agents.deploy_poll_interval`
  seconds until `success`, `failed`, or `cancelled`, or the
  `deploy_timeout` is reached.
  - Terminal `success` → `hosted_agents.status = running`,
    `last_deployed_at = now()`.
  - Terminal `failed|cancelled|timeout` → `hosted_agents.status = error`,
    `status_message` populated; deployment row captures the failure and
    last 2KB of logs via `NovpsClient::getResourceLogs`.
- [ ] FR-5: Every status transition writes an `activity_log` row
  (`hosted_agent.deploy.{started|succeeded|failed}`) scoped to the hive,
  without leaking env values.
- [ ] FR-6: Job is **idempotent** on retry:
    - If `novps_app_name` already set → re-run `applyApp` (PUT is
      declarative) and continue polling the existing deployment.
    - If `hosted_agent` already in `running` and image/model unchanged →
      no-op, log "already converged", return.
- [ ] FR-7: Fires `HostedAgentStatusChanged` domain event on terminal
  state so Reverb can broadcast to the dashboard.
- [ ] FR-8: Max attempts 3; retries with exponential backoff. On final
  failure, status stays `error` with the last exception message.

### Non-Functional

- [ ] NFR-1: Polling loop must respect Horizon timeout settings — use
  `Bus::chain` or a self-redispatching job (`release()` + re-queue) rather
  than `sleep()` inside `handle()` so worker threads stay free.
- [ ] NFR-2: Logs scrub `SUPERPOS_API_TOKEN` and any `user_env` values.
- [ ] NFR-3: `deploy_timeout` is enforced as a **wall-clock** deadline
  stored on the deployment row (`started_at + timeout`), not a counter —
  job crashes mid-poll must still honour the original deadline.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Cloud/Jobs/DeployHostedAgentJob.php` | Orchestrates apply + poll |
| Create | `app/Cloud/Services/HostedAgentDeployer.php` | Builds apply payload, runs polling (pure / testable) |
| Create | `app/Cloud/Events/HostedAgentStatusChanged.php` | Broadcast event |
| Create | `app/Cloud/Support/HostedAgentAppNameAllocator.php` | Slug + collision retry |
| Modify | `config/queue.php` | Add `hosted-agents` queue alias |

### Key Design Decisions

- **Service + Job split** — `HostedAgentDeployer` holds all pure logic
  (payload assembly, state machine transitions). The job is a thin
  Horizon-native shell. Makes testing trivial.
- **Self-redispatch for polling** — instead of sleeping, the job checks
  status once, updates DB, and if non-terminal schedules a delayed
  self-dispatch `dispatch(...)->delay($pollInterval)`. That keeps worker
  threads hot and gives us free timeout enforcement via queue config.
- **No separate "destroy" or "scale" job here** — those live in TASK-233
  so this task stays narrowly about the create/update happy path.

## Test Plan

### Unit Tests

- [ ] Payload builder produces the exact novps shape for the Claude preset.
- [ ] Payload includes auto-injected `SUPERPOS_*` env vars.
- [ ] App-name allocator retries with a suffix on a `409`-like response.
- [ ] Poll loop transitions to `running` on `success`.
- [ ] Poll loop transitions to `error` on `failed` with last logs attached.
- [ ] Timeout deadline is enforced across redispatches.
- [ ] Retry on an already-running agent is a no-op.

### Feature Tests

- [ ] End-to-end with `Http::fake()`: POST create → job runs → status
  transitions correctly → activity_log has started + succeeded rows.
- [ ] Failed novps deploy marks agent `error`, keeps agent row alive so
  the user can retry.
- [ ] Broadcast event fires on terminal transitions.

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant
- [ ] Activity logging on state changes
- [ ] No env values in logs
- [ ] Idempotent on retry (verified by running the same job twice)
