# Superpos — Feature: Hosted Agents (novps.io Runtime)

## Addendum to PRODUCT.md v4.0

> **Naming note.** This feature was previously called *Managed Agents* in
> earlier drafts. That name was retired because `App\Cloud\Services\ManagedAgentRuntime`
> already denotes the in-process zero-code LLM runtime (see TASKS #147–148).
> *Hosted Agents* refers specifically to agent **processes** that Superpos
> builds, deploys, and manages on an external container platform.

---

## 1. Problem

BYOA (Bring Your Own Agent) works but blocks onboarding: a user needs their
own infrastructure before they can try Superpos. That creates four pain points:

- Infra dependency: VPS, Docker host, or container platform required.
- No lifecycle management: agents run somewhere Superpos can't see.
- Scaling is DIY: more capacity means "go deploy another container."
- Security surface: user's box has the LLM key *and* network access to the
  rest of their stack.

The platform manages the orchestra but not the musicians. Hosted Agents fills
that gap for Cloud tenants.

## 2. Solution: Hosted Agents on novps.io

Superpos deploys preset agent images onto **novps.io** — a PaaS with a
declarative public API for apps, resources, logs, and deployments. Each
hosted agent is a single `worker` resource (container) inside a novps app.

```
┌───────────────────────────────────────────────────────────────────────┐
│                       Superpos Platform                                 │
│                                                                       │
│   ┌───────────────┐     ┌────────────────────────────────────────┐    │
│   │  Superpos Core  │     │  HostedAgentDeploymentService (Laravel)│    │
│   │  (Laravel)    │◂───▸│  · issues SUPERPOS_API_TOKEN             │    │
│   │               │     │  · builds novps PUT /apps/{name}/apply │    │
│   │  agents       │     │  · polls deployment status             │    │
│   │  hosted_agents│     │  · mirrors status → hosted_agents      │    │
│   └───────┬───────┘     └─────────────────┬──────────────────────┘    │
│           │                                │                          │
│           │ normal REST polling            │ HTTPS                    │
│           │                                │ Authorization: nvps_...  │
│           │              ┌─────────────────▼──────────────────┐       │
│           │              │        novps.io public API         │       │
│           │              │       /apps, /resources            │       │
│           │              └──────────────┬─────────────────────┘       │
│           │                             │ runs                        │
│           │              ┌──────────────▼─────────────────────┐       │
│           └────── poll ──│   Worker Pod: superpos-*-agent     │       │
│                          │   (Claude or Codex SDK image)      │       │
│                          │   ENV: SUPERPOS_API_TOKEN,           │       │
│                          │        ANTHROPIC_API_KEY / OPENAI  │       │
│                          └────────────────────────────────────┘       │
└───────────────────────────────────────────────────────────────────────┘
```

Key differences from the retired K8s design:

| Retired (K8s design)                      | Hosted Agents (novps.io)                |
|-------------------------------------------|-----------------------------------------|
| Superpos runs its own control plane         | novps.io runs the control plane         |
| Kaniko in-cluster build                   | No build — prebuilt images on GHCR      |
| NetworkPolicy + ResourceQuota authored    | novps enforces isolation + quotas       |
| Autoscaler service polling queue depth    | Fixed replicas (admin picks size)       |
| Git + inline-code sources                 | Docker image only (preset catalogue)    |
| Operator-owned K8s cluster                | HTTPS call to novps public API          |

---

## 3. Presets

Agents are deployed from a **catalogue of admin-defined presets**, not from
arbitrary user-provided images. A preset bundles:

- a container image (on private GHCR),
- a default command,
- the list of models the user may choose from,
- the env-var schema (which values the user must provide, which are secret).

MVP ships with two presets defined in `config/platform.php`. The agent
images themselves are **built and published by their own dedicated public
repos** — there is no Dockerfile or build workflow inside `superpos-app`:

- `claude-sdk` — image built by [Superpos-AI/superpos-claude-agent](https://github.com/Superpos-AI/superpos-claude-agent),
  published to `ghcr.io/superpos-ai/superpos-claude-agent` (override via
  `PLATFORM_HOSTED_CLAUDE_IMAGE`)
- `codex-sdk` — image built by [Superpos-AI/superpos-codex-agent](https://github.com/Superpos-AI/superpos-codex-agent),
  published to `ghcr.io/superpos-ai/superpos-codex-agent` (override via
  `PLATFORM_HOSTED_CODEX_IMAGE`)

The command (NoVPS `config.command` — Kubernetes semantics: it OVERRIDES
the image's ENTRYPOINT, it does not just supply args / CMD) is preset-
specific. Including `entrypoint.sh` explicitly is required so the image's
auth.json setup runs before the python agent starts; without it
codex/claude auth fails and the container restart-loops. The default can
be overridden per preset:

- `claude-sdk` — `PLATFORM_HOSTED_CLAUDE_COMMAND` (default `/app/entrypoint.sh python3 -m src.main`)
- `codex-sdk` — `PLATFORM_HOSTED_CODEX_COMMAND` (default `/app/entrypoint.sh python3 -m superpos_agent_codex`)

Admin-editable presets (DB-backed CRUD) are tracked as a follow-up
(TASK-254). Shape of the DB row is intentionally identical to the config
array so the migration path is a straight import.

### 3.1 Preset Config Shape

```php
// config/platform.php — under 'hosted_agents.presets'
'claude-sdk' => [
    'label' => 'Claude SDK Agent',
    'description' => 'Claude-powered agent using the Superpos hosted-agent image.',
    'image' => [
        'name' => env('PLATFORM_HOSTED_CLAUDE_IMAGE', 'ghcr.io/superpos-ai/superpos-claude-agent'),
        'tag'  => env('PLATFORM_HOSTED_CLAUDE_TAG', 'latest'),
    ],
    'command' => env('PLATFORM_HOSTED_CLAUDE_COMMAND', '/app/entrypoint.sh python3 -m src.main'),
    'replicas' => ['size' => 'xs', 'count' => 1],
    'restart_policy' => 'always',
    'models' => ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'],
    'model_env_key' => 'CLAUDE_MODEL',
    'user_env' => [
        'ANTHROPIC_API_KEY' => [
            'required' => true,
            'secret' => true,
            'help' => 'Anthropic API key (sk-ant-...).',
        ],
    ],
],
```

---

## 4. Operator Configuration

### 4.1 `config/services.php`

```php
'novps' => [
    'base_url' => env('NOVPS_BASE_URL', 'https://api.novps.io'),
    'api_token' => env('NOVPS_API_TOKEN'),
    'project_id' => env('NOVPS_PROJECT_ID'),
    'request_timeout' => env('NOVPS_HTTP_TIMEOUT', 30),
    'image_credentials' => env('NOVPS_IMAGE_CREDENTIALS'),
    'registry_credential_id' => env('NOVPS_REGISTRY_CREDENTIAL_ID'),  // deprecated fallback
],
```

Authentication is via a NoVPS personal access token (prefixed `nvps_`)
sent in the `Authorization` header (raw, no `Bearer` prefix). The
hosted-agent presets default to **public** GHCR images but operators
can override the image names via `PLATFORM_HOSTED_CLAUDE_IMAGE` and
`PLATFORM_HOSTED_CODEX_IMAGE` env vars before publishing their own.
The container command (NoVPS `config.command`, which OVERRIDES the image's
ENTRYPOINT — Kubernetes semantics) is also overridable via
`PLATFORM_HOSTED_CLAUDE_COMMAND` (default `/app/entrypoint.sh python3 -m src.main`)
and `PLATFORM_HOSTED_CODEX_COMMAND` (default `/app/entrypoint.sh python3 -m superpos_agent_codex`),
so the image's auth-init step runs before the python agent starts.
If a preset references a private image, set `NOVPS_IMAGE_CREDENTIALS`
to an inline `username:token` string (for GHCR: `<github_username>:<classic PAT with read:packages>`)
— the value is sent per-payload via `source.credentials`.
The deprecated `NOVPS_REGISTRY_CREDENTIAL_ID` env var is still read as a
fallback when `NOVPS_IMAGE_CREDENTIALS` is not configured (null), but new
deploys should use `NOVPS_IMAGE_CREDENTIALS`. Set it to an empty string
for anonymous pulls (public packages only).
See the [NoVPS PAT setup runbook](../../runbooks/novps-pat-setup.md)
for full PAT provisioning, env-var configuration, and rotation steps.

### 4.2 `config/platform.php`

```php
'hosted_agents' => [
    'enabled' => (bool) env('PLATFORM_HOSTED_AGENTS_ENABLED', env('APIARY_HOSTED_AGENTS_ENABLED', false)),
    'apiary_base_url' => env('PLATFORM_HOSTED_AGENTS_BASE_URL', env('APIARY_HOSTED_AGENTS_BASE_URL')),
    'app_name_prefix' => env('PLATFORM_HOSTED_AGENTS_APP_PREFIX', env('APIARY_HOSTED_AGENTS_APP_PREFIX', 'apiary-hosted')),
    'deploy_poll_interval' => (int) env('PLATFORM_HOSTED_AGENTS_POLL_INTERVAL', env('APIARY_HOSTED_AGENTS_POLL_INTERVAL', 5)),
    'deploy_timeout' => (int) env('PLATFORM_HOSTED_AGENTS_DEPLOY_TIMEOUT', env('APIARY_HOSTED_AGENTS_DEPLOY_TIMEOUT', 600)),
    'presets' => [ /* see §3.1 */ ],
],
```

Each `PLATFORM_HOSTED_AGENTS_*` env var falls back to its `APIARY_HOSTED_AGENTS_*`
counterpart for backward compatibility. New deploys should use the `PLATFORM_*` prefix.

CE hard-hides the feature: when `hosted_agents.enabled === false`, the
dashboard route is removed and API routes 404.

### 4.3 Auto-Injected Environment

Written into the resource `envs[]` by the deploy job:

| Env                 | Source                                               |
|---------------------|------------------------------------------------------|
| `SUPERPOS_BASE_URL`   | Cluster-internal Superpos URL                          |
| `SUPERPOS_API_TOKEN`  | Freshly issued agent token (hashed in `agents`)      |
| `SUPERPOS_HIVE_ID`    | From owning hive                                     |
| `SUPERPOS_AGENT_ID`   | From created agent record                            |

**Reserved prefix.** The `SUPERPOS_*` name prefix is reserved by the
platform. Neither the preset `user_env` schema nor a user's
`user_env` payload may declare a key beginning with `SUPERPOS_`.
Validation rejects such keys with a 422 in both the create/update API
(TASK-228) and the admin preset CRUD (TASK-254), so admins cannot
shadow reserved names by editing a preset.

**Env merge order (last write wins).** The deploy job builds the
final `envs[]` array in this order, so the auto-injected `SUPERPOS_*`
values are always the final write:

1. Preset-defined non-secret defaults (from `user_env` schema defaults).
2. **Preset model env** — the preset's `model_env_key` is written with
   the agent's selected model value (e.g. `CLAUDE_MODEL=claude-sonnet-4-6`
   or `CODEX_MODEL=gpt-5.4`). This sits between the preset
   defaults and user-supplied values so that the model selection is
   always present, even when the user supplies no `user_env` at all.
3. User-supplied `user_env` (the values entered in the wizard / PATCH).
   **Note:** the resolver strips any `user_env` key that matches the
   preset's `model_env_key` before merging, so a user cannot shadow
   the model selection via `user_env` even if validation was bypassed.
4. **Auto-injected `SUPERPOS_*` envs** (this layer is last and wins
   unconditionally over anything earlier).

Because the reserved-prefix check happens at validation time, layers
1–3 cannot legally contain `SUPERPOS_*` keys; the final-write
ordering is a defence-in-depth backstop.

---

## 5. Create / Deploy Flow

```
┌────────── User ──────────┐   ┌─────── Superpos ───────┐   ┌── novps.io ──┐
│                          │   │                      │   │              │
│ 1. Dashboard: +Add       │                              │              │
│    → pick preset         │                              │              │
│    → pick model          │                              │              │
│    → paste API_KEY       │                              │              │
│    → name it             │                              │              │
│    → Deploy ───────────▸ │ 2. POST /api/.../hosted-     │              │
│                          │    agents                    │              │
│                          │    · Validate preset+model   │              │
│                          │    · Create `agents` row     │              │
│                          │    · Issue SUPERPOS_API_TOKEN  │              │
│                          │    · Create `hosted_agents`  │              │
│                          │      row (status=deploying)  │              │
│                          │    · Enqueue DeployJob       │              │
│                          │                              │              │
│                          │ 3. DeployHostedAgentJob      │              │
│                          │    · Build apply payload     │              │
│                          │    · PUT /apps/{name}/apply  │───────────▸  │
│                          │                              │              │
│                          │                              │ 4. Provision │
│                          │                              │    worker    │
│                          │                              │    (docker)  │
│                          │ 5. GET /apps/{id}/           │◂──────────── │
│                          │    deployments/{id} (poll)   │              │
│                          │                              │              │
│                          │ 6. On success:               │              │
│                          │    hosted_agents.status =    │              │
│                          │      'running'               │              │
│                          │                              │              │
│                          │                              │ 7. Container │
│                          │                              │    starts,   │
│                          │ 8. GET /tasks (polling) ◂── │    polls      │
│                          │                             │    Superpos     │
└──────────────────────────┘                             └──────────────┘
```

### 5.1 Idempotency

`PUT /apps/{app_name}/apply` is declarative — running it twice
with identical payload is a no-op. The deploy job is safe to retry.

### 5.2 App-Name Allocation

One novps app per hosted agent. Name is:

```
{app_name_prefix}-{short_hive_slug}-{agent_slug}
```

e.g. `apiary-hosted-backend-code-reviewer`. novps constraints: 3–40 chars,
`^[a-z0-9-]+$` (lowercase alphanumerics + hyphen, standard hostname
charset). Collision handled by appending `-{random4}` on retry, where
`{random4}` is 4 lowercase hex chars (`[0-9a-f]{4}`) so the suffix stays
inside the allowed charset.

**Length enforcement (deterministic).** After assembling the candidate
name, if it exceeds 40 chars the allocator truncates the
`{short_hive_slug}-{agent_slug}` portion and appends `-` plus the first
6 hex chars of `sha256(prefix + "-" + slug(hive) + "-" + slug(agent))`
so uniqueness is preserved deterministically. Both the 6-char hex hash
and the 4-char retry suffix fit inside `^[a-z0-9-]+$`. The assembled
final name must match novps's allowed character set (`^[a-z0-9-]+$`)
and length constraints (3–40 chars) **before** the deploy job calls
`applyApp` — see TASK-230 FR-2.

---

## 6. Runtime Env Contract

The Slim Agent images already expect a specific env shape — we honour it so
images need zero modification.

### 6.1 Claude SDK image

| Env                  | Provider     | Notes                                |
|----------------------|--------------|--------------------------------------|
| `SUPERPOS_BASE_URL`    | Superpos       | Auto-injected                        |
| `SUPERPOS_API_TOKEN`   | Superpos       | Auto-injected, per-agent             |
| `SUPERPOS_HIVE_ID`     | Superpos       | Auto-injected                        |
| `SUPERPOS_AGENT_ID`    | Superpos       | Auto-injected                        |
| `ANTHROPIC_API_KEY`  | User         | Required, secret                     |
| `TELEGRAM_BOT_TOKEN` | User         | Optional, secret                     |
| `CLAUDE_MODEL`       | User→Superpos  | Value from preset's `models` list    |

### 6.2 Codex SDK image

| Env              | Provider     | Notes                                    |
|------------------|--------------|------------------------------------------|
| `SUPERPOS_*`       | Superpos       | Auto-injected (same as Claude)           |
| `OPENAI_API_KEY` | User         | Required, secret                         |
| `CODEX_MODEL`    | User→Superpos  | Value from preset's `models` list        |

---

## 7. Lifecycle

All operations proxy to novps.io:

| Operation | novps call                                                | Superpos side-effect                                   |
|-----------|-----------------------------------------------------------|------------------------------------------------------|
| Start     | `POST /apps/{id}/deployment` (redeploy)                   | Rotate `SUPERPOS_API_TOKEN`; status → `deploying`      |
| Stop      | `DELETE /resources/{id}` (recreated on next start)        | Status → `stopped`; `novps_resource_id` cleared      |
| Restart   | `POST /apps/{id}/deployment`                              | Status → `deploying`                                 |
| Destroy   | `DELETE /apps/{id}`                                       | Soft-delete `hosted_agents`; deactivate agent token  |

Manual scaling (`PATCH .../resources/{id}` with a new `replicas.count`) is
exposed through the same lifecycle endpoint as a `replicas` override.
Autoscale is deferred — novps does not expose a scale-on-queue hook.

---

## 8. Logs

```
GET /api/v1/hives/{hive}/hosted-agents/{id}/logs?start&end&pod&search&limit
```

Thin proxy to `GET /resources/{resource_id}/logs` — novps returns
a Loki-style ranged response, Superpos forwards it plus a `meta.source=novps`
marker. No log retention on the Superpos side.

Dashboard renders a live-follow viewer with optional pod/search filters.

---

## 9. Database Schema

```sql
-- Replaces the retired managed_agents / managed_agent_builds tables.

CREATE TABLE hosted_agents (
    id                   VARCHAR(26) PRIMARY KEY,
    agent_id             VARCHAR(26) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    superpos_id            VARCHAR(26) NOT NULL,
    hive_id              VARCHAR(26) NOT NULL,

    -- Preset + user selections
    preset_key           VARCHAR(64) NOT NULL,     -- 'claude-sdk' etc.
    model                VARCHAR(128) NOT NULL,    -- picked from preset.models
    user_env             TEXT,                     -- encrypted JSON: { ANTHROPIC_API_KEY: '...' }
    replicas_size        VARCHAR(4) NOT NULL DEFAULT 'xs',
    replicas_count       SMALLINT  NOT NULL DEFAULT 1,

    -- novps handles
    novps_app_name       VARCHAR(64),              -- prefix + slug
    novps_app_id         VARCHAR(36),              -- uuid from novps
    novps_resource_id    VARCHAR(36),
    novps_deployment_id  VARCHAR(36),              -- latest deployment

    -- Rollback / tag pinning
    image_tag_override   VARCHAR(128),             -- nullable; when set, deploy job uses this
                                                   -- instead of the preset's default tag.
                                                   -- Written by the rollback endpoint (TASK-240);
                                                   -- cleared or overwritten by the user explicitly.

    -- State
    status               VARCHAR(20) NOT NULL DEFAULT 'deploying',
         -- create → deploying → running → stopped | error
         -- (the initial create API always writes `deploying`; `pending`
         --  is retained in the enum only for future pre-deploy states
         --  and is NOT a state the create flow ever produces)
         -- terminal: deleted (via destroy flow — row retained, novps_* handles nulled)
    status_message       TEXT,
    last_deployed_at     TIMESTAMP,

    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW(),

    UNIQUE (novps_app_name)
);

CREATE INDEX idx_hosted_agents_status
    ON hosted_agents (status)
    WHERE status IN ('deploying','running','error');

CREATE TABLE hosted_agent_deployments (
    id                   VARCHAR(26) PRIMARY KEY,
    hosted_agent_id      VARCHAR(26) NOT NULL REFERENCES hosted_agents(id) ON DELETE CASCADE,

    novps_deployment_id  VARCHAR(36),
    status               VARCHAR(20) NOT NULL,     -- pending|building|running|success|failed|cancelled
    triggered_by         VARCHAR(50),              -- user:{id} | system:start | system:restart
    image_tag            VARCHAR(128),             -- tag captured at deploy time
    duration_seconds     INTEGER,
    log_excerpt          TEXT,

    created_at           TIMESTAMP DEFAULT NOW(),
    completed_at         TIMESTAMP
);

CREATE INDEX idx_hosted_agent_deployments_hosted
    ON hosted_agent_deployments (hosted_agent_id, created_at DESC);
```

Build/rollout history in one table — no separate builds table, because we
never build. Rollback = redeploy with a specific image tag override.

Activity-log records continue to use the existing `activity_log` table.

---

## 10. API

### 10.1 CRUD

```
GET    /api/v1/hives/{hive}/hosted-agents
POST   /api/v1/hives/{hive}/hosted-agents
GET    /api/v1/hives/{hive}/hosted-agents/{id}
PATCH  /api/v1/hives/{hive}/hosted-agents/{id}     (model/env/replicas — triggers redeploy)
DELETE /api/v1/hives/{hive}/hosted-agents/{id}     (destroys novps app)
```

### 10.2 Lifecycle

```
POST   /api/v1/hives/{hive}/hosted-agents/{id}/start
POST   /api/v1/hives/{hive}/hosted-agents/{id}/stop
POST   /api/v1/hives/{hive}/hosted-agents/{id}/restart
POST   /api/v1/hives/{hive}/hosted-agents/{id}/scale   (replicas override)
```

### 10.3 Observability

```
GET    /api/v1/hives/{hive}/hosted-agents/{id}/logs
GET    /api/v1/hives/{hive}/hosted-agents/{id}/deployments
GET    /api/v1/hives/{hive}/hosted-agents/{id}/status   (live novps status)
```

### 10.4 Presets (read-only)

```
GET    /api/v1/hosted-agent-presets
```

Returns the sanitized preset catalogue for the dashboard wizard — no image
credentials, no `env` defaults, just labels / models / required env keys.

### 10.5 Create Example

```json
POST /api/v1/hives/backend/hosted-agents
{
  "name": "code-reviewer",
  "preset_key": "claude-sdk",
  "model": "claude-sonnet-4-6",
  "user_env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  },
  "replicas": { "size": "xs", "count": 1 }
}
```

Response:

```json
{
  "data": {
    "id": "hag_01J...",
    "agent_id": "agt_01J...",
    "name": "code-reviewer",
    "preset_key": "claude-sdk",
    "model": "claude-sonnet-4-6",
    "status": "deploying",
    "novps_app_name": "apiary-hosted-backend-code-reviewer",
    "latest_deployment": {
      "id": "had_01J...",
      "status": "pending",
      "started_at": "2026-04-16T10:00:00Z"
    }
  }
}
```

---

## 11. Dashboard

Hosted Agents live under **Agents → Hosted** in the hive sidebar. Hidden
entirely when `platform.hosted_agents.enabled` is false.

### 11.1 Deploy Wizard

```
Step 1: "Pick a preset"
   ◉ Claude SDK Agent
   ○ OpenAI Codex SDK Agent

Step 2: "Pick a model"
   [claude-sonnet-4-6 ▾]

Step 3: "Provide credentials"
   ANTHROPIC_API_KEY  [••••••••••••••••]  (required, secret)

Step 4: "Name & size"
   Name:     [code-reviewer]
   Size:     [xs ▾]   Replicas: [1]

[Deploy] → Status: deploying → running ✅
```

### 11.2 Agent Detail (Hosted view)

Tabs beyond the standard agent view:

- **Deployments** — table of `hosted_agent_deployments` with redeploy/rollback
- **Logs** — live viewer with follow toggle (§8)
- **Env** — edit user-supplied env (secrets masked, save triggers redeploy)

---

## 12. Security

### 12.1 Trust boundaries

```
Layer 1: novps.io tenancy
  └── Each Superpos Cloud tenant lives in a novps project we control

Layer 2: novps network isolation
  └── Worker pods can reach the public internet but not intra-tenant
      resources in the Superpos project. No NetworkPolicy authored by us.

Layer 3: Superpos auth
  └── Per-agent SUPERPOS_API_TOKEN, same permission model as BYOA.
      Token rotated on every redeploy.

Layer 4: Secret handling
  └── user_env stored encrypted at rest (Laravel Crypt).
      Plaintext only in-memory during deploy job.
      Never written to logs, activity_log, or API responses.
      Masked in the dashboard (only key names shown).
```

### 12.2 What novps sees

novps sees the full env payload at deploy time (image, SUPERPOS_API_TOKEN,
user-supplied API keys). That is the same trust model as any PaaS —
documented explicitly in `docs/SECURITY.md` for this feature.

### 12.3 What Superpos never logs

- `NOVPS_API_TOKEN`
- Any value in `hosted_agents.user_env`
- Anything in the resolved env payload sent to novps

HTTP client is configured with a redacting middleware to enforce this.

---

## 13. Edition Gating

Cloud-only. CE users do not see Hosted Agents at all — not a "greyed-out"
button, the UI section is absent. Enforcement:

| Layer       | Check                                                               |
|-------------|---------------------------------------------------------------------|
| Routes      | `Route::middleware('apiary.hosted.enabled')` wraps API + web routes |
| Controllers | Abort 404 if `config('platform.hosted_agents.enabled') === false`   |
| Inertia     | Dashboard nav entry omitted via `HandleInertiaRequests` shared prop |
| Code path   | All classes under `app/Cloud/` namespace                            |

The ops toggle is `PLATFORM_HOSTED_AGENTS_ENABLED=true` in `.env`
(`APIARY_HOSTED_AGENTS_ENABLED` is accepted as a fallback).

---

## 14. Observability & Usage

Per-agent novps usage (compute-seconds, replica-count history) is polled
on a scheduler and written into the existing cloud billing tables.
Detail lives in TASK-244.

---

## 15. Implementation Priority

| Priority | Feature                                         | Task                              |
|----------|-------------------------------------------------|-----------------------------------|
| P0       | hosted_agents migration + models                | TASK-227                          |
| P0       | Seeded preset config + `HostedAgentPresetRegistry` | TASK-253                       |
| P0       | novps public API HTTP client                    | TASK-229                          |
| P0       | Hosted agents CRUD API                          | TASK-228                          |
| P0       | Deploy job (apply + poll)                       | TASK-230                          |
| P0       | Auto-injected + user env                        | TASK-231                          |
| P0       | Lifecycle API (start/stop/restart/scale/destroy)| TASK-233                          |
| P1       | Log streaming proxy                             | TASK-236                          |
| P1       | Deployment history + rollback                   | TASK-240                          |
| P1       | Dashboard: wizard + list + detail               | TASK-241                          |
| P2       | Usage data collection                           | TASK-244                          |
| P2       | Admin-configurable presets (DB-backed)          | TASK-254                          |
| Runbook  | Novps registry credential setup                 | TASK-255                          |

P0 set = usable MVP. Estimate ~3 weeks. P1 adds operator polish.

### 15.1 What was retired from the K8s plan

These tasks are **deleted**, not deferred — they do not map onto novps:

- TASK-232 Network policy isolation (novps enforces)
- TASK-234 Git source + Kaniko build (we use prebuilt images)
- TASK-235 Always-on / on-demand launch modes (novps replicas are explicit)
- TASK-237 Auto-deploy on git push (no build pipeline)
- TASK-238 Autoscale engine (no scale-on-queue hook on novps)
- TASK-239 Inline code + buildpack (prebuilt-only)
- TASK-242 Dashboard inline editor (no inline source)

---

## 16. Ops Prerequisites

Before hosted-agent deploys will work in any environment, the following
must be in place:

1. **GHCR image publishing.** The two preset images are built and pushed
   automatically by the publish workflow inside each agent's own public
   repo (NOT inside `superpos-app` — there is no `docker/agents/`
   directory or build workflow here). Default names (overridable via
   `PLATFORM_HOSTED_CLAUDE_IMAGE` / `PLATFORM_HOSTED_CODEX_IMAGE`):
   - `ghcr.io/superpos-ai/superpos-claude-agent` — published from
     [Superpos-AI/superpos-claude-agent](https://github.com/Superpos-AI/superpos-claude-agent)
   - `ghcr.io/superpos-ai/superpos-codex-agent` — published from
     [Superpos-AI/superpos-codex-agent](https://github.com/Superpos-AI/superpos-codex-agent)

   The packages must be readable by NoVPS (public, or with registry
   credentials provided inline via the `NOVPS_IMAGE_CREDENTIALS` env
   var — see §4.1). The old
   `ghcr.io/apiary-ai/apiary-slim-agent-*` images are retired and no
   longer published.

   See the [NoVPS PAT setup runbook §3](../../runbooks/novps-pat-setup.md#3-container-image-publishing-prerequisite)
   for full details.

2. **NoVPS PAT.** A personal access token with app/resource management
   scope, configured via `NOVPS_API_TOKEN` and `NOVPS_PROJECT_ID`.
   See the [NoVPS PAT setup runbook](../../runbooks/novps-pat-setup.md).

3. **Feature flag.** `PLATFORM_HOSTED_AGENTS_ENABLED=true` in the
   deployment environment.

---

*Feature version: 2.0 (novps.io rewrite)*
*Supersedes: FEATURE_MANAGED_AGENTS.md v1.0 (K8s design, retired)*
*Depends on: PRODUCT.md v4.0 (agents, hives), FEATURE_PLATFORM_ENHANCEMENTS.md (drain mode)*
*Infrastructure dependency: novps.io project + GHCR image publishing (see §16)*
