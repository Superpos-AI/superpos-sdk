# Proposal: GitHub App integration (per-agent installation token broker)

Status: Draft for review
Owner: Platform
Scope: Replaces long-lived GitHub PATs in agent containers with short-lived installation access tokens (IATs) minted on demand by Superpos, fronted by a single platform-owned GitHub App. Keeps PATs as an explicit fallback. Reuses `service_connections`, `auth:sanctum-agent`, the existing webhook receiver, and `PersonaController` platform context. No breaking changes for existing PAT-backed connections.

---

## 1. Problem

Today every agent ships with a long-lived GitHub credential — either an env-injected `GITHUB_TOKEN` or a PAT decrypted from `service_connections.auth_config` and forwarded via `ServiceProxy`. That violates the "agents never see credentials" principle in the CLAUDE.md spirit (PATs are *seen* even if they originate server-side), and it has a stack of secondary problems:

- **Identity is a human user.** Every commit, comment, and review the agent makes is attributed to whoever owns the PAT. Audit attribution is weak; the user has to own the bot's actions.
- **Webhook loop prevention is fragile.** The current rule ("skip if the comment author matches my own GitHub user") is a runtime string match — change the PAT, change the rule, miss the rule, infinite loop.
- **Rate limits are shared.** A noisy task can starve the whole hive.
- **Scope is broad.** PATs are typically `repo` (full read/write) on every repo the user can see. Revocation is all-or-nothing.
- **No per-agent traceability at GitHub.** GitHub sees one identity; we cannot tell from the GitHub side which Superpos agent did what.

GitHub Apps solve all of these — but only if the App's private key stays on the server. Agents need a way to obtain a short-lived, scoped token without ever touching the key.

## 2. Goals / Non-goals

**Goals**
- One Superpos GitHub App (single bot identity, `superpos-agent[bot]`). Private key + webhook secret stored only in superpos-app config (env-injected, never in DB).
- Per-agent, per-request IAT minting: an agent that needs GitHub access calls `POST /api/v1/github/installation-token`, gets a ~1h token scoped to the installation backing its target `service_connection`, uses it, throws it away.
- Reuse `service_connections` (an **organization-scoped** resource — see `app/Models/ServiceConnection.php:14-20` and TASK-036) as the binding between an org and a GitHub installation. Add `auth_type='github_app'` + `auth_config.installation_id`. One service-connection row per installation; an org may have several (multiple installations, or mixed App + PAT rows). **This is not a "schema only" change**: the existing platform hardcodes GitHub `auth_type` to `token` in several places (`app/Models/ServiceConnection.php:17`, `app/Http/Controllers/Dashboard/ServiceConnectionDashboardController.php:533`, `app/Cloud/Services/HiveTemplateApplyEngine.php:93-95,128-130`, and the GitHub-token-only assertion at `tests/Unit/Cloud/HiveTemplateApplyEngineTest.php:2264-2293`). The new `auth_type` value must be threaded through all of these compatibility surfaces — see Phase 4.5 in §11 for the full enumeration.
- Agent access to a GitHub connection is gated by the **existing** `services:{connection_id}` / `services:*` permission contract (`app/Http/Controllers/Api/ProxyController.php:32-48`, `app/Http/Requests/UpdateAgentPermissionsRequest.php:16-69`). No new permission key is introduced.
- Keep PAT path as an **explicit fallback** for repos where installing the App is not possible or wanted (personal scratch repos, transient experiments). Same broker endpoint serves both; agent code does not branch.
- Replace fragile string-match webhook-loop prevention with a deterministic match against the App's bot login, surfaced through the persona.
- Per-agent audit: every IAT issuance is an `activity_log` row with `agent_id`, `service_connection_id`, `installation_id`, `expires_at`, and a token hash prefix (never the token).

**Non-goals (V1)**
- Multiple Apps (separate identities per role — e.g. "review bot" vs "coding bot"). Single bot identity for V1.
- OAuth user-to-server flow. The App acts on its own behalf only.
- Marketplace listing.
- Narrowed installation tokens (GitHub supports per-call `repository_ids` + `permissions` subset). V1 returns the full-installation IAT; see §12.
- Auto-discovery / auto-install of repos. The hive admin installs the App on whichever repos they want, via the standard GitHub flow. Superpos only reads the resulting installation.
- New permission keys for GitHub. The broker reuses the existing `services:{connection_id}` / `services:*` permission contract (same as `ProxyController`). No `github.*` permission family is introduced.

## 3. Concepts

**GitHub App** — A single Superpos-owned App. Holds `app_id`, RSA private key, webhook secret. Lives in platform config; not per-org, not per-hive. (CE deployments register their own App during setup; Cloud uses the Superpos-owned App and installations bind per customer org.)

**Installation** — A GitHub org or user that has installed the App on a selected set of repos. Has a numeric `installation_id`. A Superpos `service_connection` with `auth_type='github_app'` carries exactly one `installation_id`. Because `service_connections` are **organization-scoped** (`BelongsToOrganization`, see `app/Models/ServiceConnection.php`), the row is shared across all hives in the org — the same installation can back GitHub work in multiple hives, gated per-agent by `services:{connection_id}`.

**Installation Access Token (IAT)** — Short-lived (max 1h) token issued by GitHub for a single installation. Acts as `superpos-agent[bot]`. Scoped to the App's permissions and the installation's repo selection. **Disposable** — agents fetch fresh ones on demand and never persist them.

**App JWT** — A 10-minute JWT signed with the App's private key, used at GitHub to exchange for IATs. Minted in-process by superpos-app, cached server-side, never sent to agents.

**Token Broker** — The new `POST /api/v1/github/installation-token` endpoint. Authenticates agents via `auth:sanctum-agent`, resolves the requested `service_connection` (org-scoped, `services:{connection_id}` permission required), mints or returns a cached IAT for the backing `installation_id`, and logs the issuance.

**Credential Helper** — The agent-side script (`superpos-gh-token`) that calls the broker and wires the result into `git` (via `credential.helper`) and `gh` (via `GH_TOKEN`). Caches on tmpfs only.

## 4. Architecture

```
Agent container                          superpos-app                       GitHub
────────────────                         ──────────────                     ───────
gh / git ──► superpos-gh-token ──HTTPS──► POST /api/v1/github/installation-token
                  (auth: SUPERPOS_API_TOKEN)        │
                                                     │ 1. resolve agent → hive
                                                     │ 2. load service_connection
                                                     │    (auth_type, installation_id)
                                                     │ 3. if cached IAT valid → return
                                                     │ 4. else mint App JWT (cached 9m)
                                                     │ 5. POST /app/installations/{id}/access_tokens ──► api.github.com
                                                     │ 6. cache IAT (Redis, TTL = exp - 5m)
                                                     │ 7. activity_log row
                                                     ▼
                                          { token, expires_at, permissions, bot_login, ... }
                  ◄──────────────────────────────────
gh / git uses token directly ───────────────────────────────────────────────► api.github.com
                                                                              github.com (clone/push)

Webhooks (push, PR, issue_comment, ...)
github.com ──► POST /api/v1/webhooks/github-app   (single, literal App webhook URL)
                       │
                       ▼
               GitHubAppWebhookController (new, registered BEFORE the catch-all)
                 1. Read installation.id from JSON payload
                 2. Look up service_connection_id via github_app_installations
                    table (indexed by installation_id — see §5.3)
                 3. Dispatch into WebhookController::receive with resolved id
                       │
                       ▼
               WebhookController::receive (routes/api.php:111, lines 35-64)
                 1. Lookup ServiceConnection by id
                 2. Resolve connector
                 3. GitHubConnector::validateWebhook (reads webhook secret from platform config for github_app connections)
                 4. Dispatch ProcessWebhook job
                       │
                       ▼
               WebhookRouteEvaluator (existing routing infra, keyed on the same id)
```

**Key alignment point.** Every box on the server side reuses existing primitives — Sanctum guard, `service_connections`, `Crypt`, `activity_log`, Redis cache, `WebhookController`, `GitHubConnector`. The new surface area is: one broker endpoint (`POST /api/v1/github/installation-token`), one shim webhook route (`POST /api/v1/webhooks/github-app`) registered ahead of the existing catch-all, one new `auth_type` value, one `github_app_installations` mapping table for queryable webhook routing (§5.3), one Redis key family, one platform-config block, one localized change to `GitHubConnector::resolveWebhookSecret` (§9), and one small agent-side script.

## 5. Data model

### 5.1 `service_connections` additions

```text
service_connections
  + auth_type (string, indexed)                  # extend GitHub-valid set: 'token' | 'github_app'
  + auth_config (jsonb, already exists)          # shape extended
```

The platform's existing GitHub `auth_type` is `'token'` — see `ServiceConnection::AUTH_TYPES` (`app/Models/ServiceConnection.php:17`) and the GitHub row of `HiveTemplateApplyEngine::SERVICE_TYPE_ALLOWED_AUTH_TYPES` (`app/Cloud/Services/HiveTemplateApplyEngine.php:128-135`). The proposal introduces `'github_app'` as a **second valid auth_type for GitHub connections** alongside the existing `'token'`. The "`pat`" label used informally elsewhere in this doc refers to the existing `'token'` rows; no rename happens. Each of the surfaces listed in §11 Phase 4.5 must be updated to accept `github_app` for `type='github'` rows before the new value can be written safely.

For `auth_type='token'` (status quo), `auth_config` keeps its current shape: `{ "token": "<encrypted>" }`.

For `auth_type='github_app'`:

```json
{
  "installation_id": 12345678,
  "target_type": "Organization",      // or "User"
  "target_login": "Superpos-AI",
  "installed_at": "2026-05-23T10:00:00Z",
  "repository_selection": "selected"  // or "all" — informational only
}
```

No encrypted secret here — the secret material (private key) lives in platform config, not per-connection. The connection row is the binding "this organization's GitHub work for this installation goes through this row." Because `ServiceConnection` uses `BelongsToOrganization` (`app/Models/ServiceConnection.php:14`), the row is visible to every hive in the org, and per-agent access is gated by the standard `services:{connection_id}` permission.

### 5.2 Platform config

```text
config/services.php (or config/github.php)
  github.app.app_id          (int, from env GITHUB_APP_ID)
  github.app.private_key     (string, PEM, from env GITHUB_APP_PRIVATE_KEY — base64 acceptable)
  github.app.webhook_secret  (string, from env GITHUB_APP_WEBHOOK_SECRET)
  github.app.bot_login       (string, e.g. 'superpos-agent[bot]', from env)
  github.app.client_id       (string, optional, only needed for future OAuth)
  github.app.install_url     (string, e.g. 'https://github.com/apps/superpos-agent/installations/new', from env GITHUB_APP_INSTALL_URL)
  github.app.rate_limit      (array, e.g. ['hourly_mints' => 60], from env GITHUB_APP_RATE_LIMIT_HOURLY_MINTS et al.)
```

**Canonical config surface.** All GitHub App configuration lives under the single `github.app.*` namespace — `app_id`, `private_key`, `webhook_secret`, `bot_login`, `client_id`, `install_url`, and `rate_limit`. The data model (§5.3), broker (§6), persona payload (§8), and webhook shim (§9) all read from this surface; there is **no** parallel `services.github_app.*` block. Reviewers will spot earlier drafts of this proposal that referenced `config('services.github_app.webhook_secret')` — that path is dropped in favor of `config('github.app.webhook_secret')` for consistency with §5.2.

The private key is **never** persisted to the database. CE installers paste it into `.env` once; Cloud reads it from the platform secret store.

### 5.3 `github_app_installations` mapping table

Because `auth_config` is cast as `encrypted` in `ServiceConnection` (`app/Models/ServiceConnection.php:43`) and stored as opaque ciphertext in a `text` column (`database/migrations/0001_01_01_000017_create_service_connections_table.php:21`), **JSON operators like `auth_config->>'installation_id'` cannot be used in SQL queries** — the DB engine sees only ciphertext, not a JSON document. The webhook shim (§9) needs to resolve a `service_connection` from a numeric `installation_id` arriving in the GitHub payload, so a queryable lookup path is required.

**Solution: a dedicated mapping table.**

```sql
github_app_installations
  id                     string(26) PK   -- ULID
  installation_id        bigint NOT NULL  -- GitHub's numeric installation id
  service_connection_id  string(26) NOT NULL  -- FK → service_connections.id
  organization_id        string(26) NOT NULL  -- denormalized for scoping
  created_at             timestamp
  updated_at             timestamp

  UNIQUE(installation_id)
  INDEX(service_connection_id)
  FOREIGN KEY(service_connection_id) REFERENCES service_connections(id) ON DELETE CASCADE
```

This table is written once when the dashboard creates a `github_app` service connection (Phase 5) and deleted on cascade when the connection is removed. The webhook shim queries `github_app_installations` by `installation_id` (a plain indexed integer column) to resolve the `service_connection_id`, completely sidestepping the encrypted `auth_config` column. The `installation_id` also remains inside `auth_config` for display purposes and for the broker to read after decryption — the mapping table is purely for queryable webhook routing.

### 5.4 Token issuance logging

Issuance is logged via the existing `activity_log` table with `activity_type='github_app.token_issued'` and metadata `{ agent_id, service_connection_id, installation_id, expires_at, token_hash_prefix }`. If usage analytics later need a dedicated table, it can be added without breaking the broker contract.

## 6. Token broker endpoint

### 6.1 Request

```http
POST /api/v1/github/installation-token
Authorization: Bearer <SUPERPOS_API_TOKEN>
Content-Type: application/json

{
  "service_connection_id": "01HQ...",   // required — identifies the org-scoped GitHub connection
  "repo": "Superpos-AI/superpos-app"    // optional; reserved for future narrowed-token support (§12)
}
```

### 6.2 Resolution

1. `auth:sanctum-agent` resolves `Agent`; `BindAgentTokenHiveContext` resolves hive context (for `activity_log` attribution only — the connection itself is org-scoped).
2. Load `service_connection` by the request body's `service_connection_id`, restricted to the agent's `organization_id` (mirrors `ProxyController::forward` at `app/Http/Controllers/Api/ProxyController.php:32-40`). 404 if not found or inactive.
3. Authorize: agent must hold `services:{connection_id}` **or** `services:*` (same check used by `ProxyController` at `app/Http/Controllers/Api/ProxyController.php:46-48`). 403 otherwise. No new permission key.
4. Verify `connection.type === 'github'`. 400 otherwise.
5. Branch on `auth_type`:
   - `token` (the existing PAT path) → decrypt `auth_config.token` in-process, return `{ token, token_type: 'pat', expires_at: null, bot_login: null, actor_login: <pat_owner_login> }`. The `actor_login` is the PAT owner's GitHub username, resolved by the broker once at connection creation/rotation via `GET /user` with the PAT (cached in `auth_config.actor_login` after encryption — never re-queried per request). `bot_login` stays `null` on this path so callers can distinguish App-backed connections from PAT-backed ones. Identical wire shape otherwise so the agent helper does not branch.
   - `github_app` → §6.3.

**Why `service_connection_id` is required (not optional).** `service_connections` are organization-scoped, not hive-bound. An org may have multiple GitHub connections (multiple installations, or a mix of App and PAT rows), and any of them may be visible across multiple hives. There is no safe "the one GitHub connection for this hive" fallback at the broker level — the agent (or its persona) must name the connection it wants, and the existing `services:{connection_id}` permission then gates access. This matches how `ProxyController` already handles ambiguity: callers always name a connection.

### 6.3 IAT minting (App path)

1. Cache lookup: `redis.get("github:iat:{organization_id}:{service_connection_id}")`. If present and `expires_at > now + 5min`, return cached.
2. Cache miss: ensure a fresh App JWT (cache key `github:app_jwt:{app_id}`, TTL 9 min). Sign with the platform private key via `firebase/php-jwt` or `lcobucci/jwt` (Laravel already ships the latter transitively).
3. `POST https://api.github.com/app/installations/{installation_id}/access_tokens` with the JWT as Bearer.
4. Cache the response in Redis until `expires_at - 5min` under `github:iat:{organization_id}:{service_connection_id}`. The org + connection-id scoping prevents a misconfigured lookup from returning another org's token (see §10).
5. Write `activity_log` row (`github_app.token_issued`).
6. Return:

```json
{
  "token": "ghs_...",
  "token_type": "github_app_installation",
  "expires_at": "2026-05-23T11:00:00Z",
  "permissions": { "contents": "write", "pull_requests": "write", ... },
  "repository_selection": "selected",
  "bot_login": "superpos-agent[bot]",
  "actor_login": "superpos-agent[bot]"
}
```

`actor_login` is returned on both branches (`token` and `github_app`) so the agent helper and the persona-level loop-prevention rule (§8) can use a single field name regardless of the underlying credential type. For App connections it equals `bot_login`; for PAT connections it equals the PAT owner's login. Callers that specifically need to know whether the credential is bot-backed should check `token_type` (or `bot_login !== null`), not `actor_login`.

### 6.4 Errors

- `403 github_app_not_installed` — `auth_type='github_app'` but installation has been uninstalled at GitHub (broker detects via 404 on the access-tokens call). Response carries an `install_url` so the dashboard can prompt the user.
- `403 permission_denied` — agent lacks `services:{connection_id}` and `services:*`.
- `404 service_connection_not_found` — id does not match an active connection in the agent's organization.
- `400 not_a_github_connection` — connection exists but `type !== 'github'`.
- `429 rate_limited` — per-agent rate limit. V1 default: **60 mints/hour/agent**. Cache hits do not count.

### 6.5 Rate limits and abuse control

- Per-agent hourly cap on **mint** operations (cache hits are free), bucket keyed `github:iat:mint:{agent_id}`.
- Per-installation cap on App-JWT-to-IAT exchanges to stay within GitHub's own limits (App has 5000 req/hour shared).
- Both implemented via the existing rate-limit middleware (`throttle:github-token`), defined in a new limiter in `app/Providers/RouteServiceProvider.php` (or wherever current limiters live).

## 7. Agent-side credential helper

A small script `superpos-gh-token` shipped in the agent container image (`superpos-agent-core` module path).

**Surface:**

```bash
superpos-gh-token                       # prints fresh token to stdout for the selected connection
superpos-gh-token --git-credential      # speaks the git-credential protocol
superpos-gh-token --bot-login           # prints the connection's actor login (bot or PAT owner)
superpos-gh-token --refresh             # force re-mint, bypass local cache
superpos-gh-token --connection <id>     # override connection selection for this call
superpos-gh-token --list-connections    # prints the agent's permitted GitHub connections (debug)
```

**Connection selection contract.** Because `service_connections` are org-scoped and a single agent may have access to several GitHub connections (multiple App installations, or a mix of App + PAT rows — see `persona.github.connections[]` in §8), the helper must know *which* connection to mint a token for before it can call the broker. Resolution order, first match wins:

1. `--connection <service_connection_id>` CLI flag (explicit, highest priority — used by tooling that knows exactly which connection it wants).
2. `GH_CONNECTION_ID` environment variable (per-process override, set by callers like a CI step or a wrapper script targeting a specific repo).
3. A repo-local config file: `.superpos/github.toml` at the repository root, schema `connection_id = "01HQ..."`. Walked upward from the current working directory the same way `git` discovers `.git`, so the file lives with the repo and survives `git clone` into the agent's workspace.
4. The agent persona's default: `persona.github.default_connection_id` (new field, see §8). Set by the dashboard when the agent is granted access to exactly one GitHub connection, or explicitly chosen by the operator when there are several.
5. If still ambiguous (multiple permitted connections, no default, no override), the helper exits non-zero with a message listing the candidates and the precedence rules above. It never silently picks one.

The helper passes the resolved id to the broker as the `service_connection_id` body parameter (§6.1), which is already required by the endpoint — this section just defines how the agent-side surface arrives at that id.

**Behaviour:**

1. Reads `SUPERPOS_BASE_URL` + `SUPERPOS_API_TOKEN` from env (already present).
2. Resolves the target `service_connection_id` per the selection contract above.
3. Local cache on tmpfs, **keyed per connection**: `${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/superpos-gh-token-<service_connection_id>.json`. Holds `{ token, expires_at, actor_login, auth_type }`. Mode `0600`, never persisted to disk-backed volumes. Per-connection keying ensures that a token minted for connection A is never reused when the helper is called for connection B (e.g., when an agent works against two installations in sequence).
4. If cache is fresh (`expires_at > now + 60s`) **for the resolved connection id**, reuse. Otherwise call the broker.
5. On 403 `github_app_not_installed`: print install URL to stderr and exit non-zero so the agent surfaces it.

**Wiring:**

- `git`: a startup hook in the agent shell sets `git config --global credential.helper '!superpos-gh-token --git-credential'`. The helper resolves the connection from `.superpos/github.toml` discovered relative to the git working tree (step 3 of the selection contract), which is how `git` plumbing naturally targets the right credential for a repo.
- `gh`: a wrapper or shell function exports `GH_TOKEN=$(superpos-gh-token)` before each invocation. Callers targeting a specific repo set `GH_CONNECTION_ID` (or rely on `.superpos/github.toml`) so the wrapper mints against the correct connection. (`GH_TOKEN` itself is per-process, so refresh-on-demand is trivial.)
- The static `GITHUB_TOKEN` env var is **removed** from the agent container — its presence today is what makes the helper feel optional. Once removed, every code path naturally goes through the helper. Removal is not just a Dockerfile edit; see Phase 6 in §11 for the full enumeration of runtime surfaces that currently read `GITHUB_TOKEN` and must migrate alongside the container change.

## 8. System prompt + persona context

`PersonaController::show` (`app/Http/Controllers/Api/PersonaController.php:36-43`) returns `platform_context` as the **raw markdown content string** read from `PlatformContextService::getActiveContext(...)?->content`, not a structured JSON object. The seeded content (`resources/platform-context/sdk-knowledge.md`) is a markdown document. So the proposal cannot just "add a `github` key" to `platform_context` — that field is a string by contract.

**Chosen approach: a new top-level persona field `persona.github`.** `PersonaController::show` already composes the persona payload (`formatPersona($persona)` plus the `platform_context` / `platform_context_version` keys). We add one more top-level key that the controller assembles from the agent's available GitHub connections:

```json
{
  "data": {
    "name": "...",
    "system_prompt": "...",
    "platform_context": "# Superpos Platform — SDK Reference\n\n...",
    "platform_context_version": 12,
    "github": {
      "bot_login": "superpos-agent[bot]",
      "install_url": "https://github.com/apps/superpos-agent/installations/new",
      "rate_limit": { "hourly_mints": 60 },
      "default_connection_id": "01HQ...",
      "connections": [
        {
          "service_connection_id": "01HQ...",
          "auth_type": "github_app",
          "target_type": "Organization",
          "target_login": "Superpos-AI",
          "repository_selection": "selected",
          "actor_login": "superpos-agent[bot]"
        },
        {
          "service_connection_id": "01HR...",
          "auth_type": "token",
          "target_type": "User",
          "target_login": "dinashbotdev",
          "actor_login": "dinashbotdev"
        }
      ]
    }
  }
}
```

Properties of this shape:

- **It is a structured field**, not a substring of `platform_context`. The markdown content document is unchanged.
- The `connections` array is filtered by the agent's `services:{connection_id}` / `services:*` permission — agents only see the GitHub connections they are authorized to broker against.
- `bot_login`, `install_url`, and `rate_limit` come from `config('github.app.*')` and are constant across the org.
- `connections[].service_connection_id` is the exact id the agent passes to `POST /api/v1/github/installation-token` (§6.1).
- `connections[].actor_login` is the GitHub login that appears as the **API-call actor** (the `sender` / `user` on issues, PR comments, reviews, review comments, and the **pusher** on push events) for actions taken with the connection's token. For `auth_type='github_app'` rows it equals the App's bot login (`superpos-agent[bot]`); for `auth_type='token'` (PAT) rows it equals the PAT owner's GitHub username (resolved by the broker once at connection creation via `GET /user` with the PAT, cached on the connection row — never re-queried on every persona fetch). This is the field the persona-level webhook-loop-prevention rule compares against; see the `actor_login` discussion below. **Important caveat: `actor_login` is not the commit author or committer.** Commit author/committer are taken from local Git metadata (`git config user.name`/`user.email` or an explicit `--author`/`--committer`), independent of which token authenticates the `git push`. The token only determines who pushed the ref and who appears as the API actor on subsequent events — see the "commit identity" note below for how to make commits appear under the bot identity when that is desired.
- `default_connection_id` is the connection the helper picks when no other selection signal is present (see the §7 selection contract). Optional — present only when the agent has been configured with a default (or has exactly one permitted connection).

**Why not the other two options.**

- *(b) Render GitHub metadata into the existing markdown document via `PlatformContextService`.* Would force `PlatformContextService` to grow template parameters for org-specific runtime data (bot login is constant, but the `connections` array is per-org and per-agent). The service today is content + version with org-level caching; adding per-agent rendering breaks its cache model. Rejected.
- *(c) Separate endpoint `GET /api/v1/agents/{agent}/github-context`.* Forces every SDK to make a second call, and the SDK already does a single persona fetch. The data is small and stable enough to ride along on the persona payload. Held in reserve if `persona.github` ever becomes too heavy.

**Persona content updates (markdown, not schema).** The `AgentPersona.content` text — the bot's CLAUDE.md-equivalent — is updated to:

- Drop the "string-match your own GitHub username" rule for webhook-loop prevention. Replace with a **connection-aware identity check**: when an event arrives, look up the `service_connection_id` it was dispatched against and find that entry in `persona.github.connections[]`. Skip the event when `sender.login == connection.actor_login` (also covers `comment.user.login`, `review.user.login`). For `github_app` connections `actor_login` is the bot login; for `token` (PAT) connections it is the PAT owner's GitHub username — so the rule works on the App path **and** the fallback path with the same code. This is deterministic and survives identity changes (the broker recomputes `actor_login` whenever the underlying credential is rotated).
  - If the broker has not yet populated `actor_login` for a PAT connection (e.g., legacy rows that pre-date this field), the persona falls back to the legacy string-match rule for that connection only, and the dashboard surfaces a one-time prompt to re-save the PAT so the broker can resolve and cache the owner login. This is the only place the legacy rule survives, and it is bounded by the migration playbook in Phase 8.
- Document that `gh` / `git` operations are attributed to whichever identity backs the selected connection **at the API / push-actor layer only**: `superpos-agent[bot]` for App connections, the PAT owner for `token` connections. That identity appears as the `sender`/`user` on issues, PRs, comments, and reviews, and as the `pusher` on push events — i.e., everywhere GitHub records "who made this API call." **Commit author and committer are a separate concern**: they are written by `git commit` itself from local Git config (`git config user.name`/`user.email`) or an explicit `--author`/`--committer`, and the installation token has no influence on them. To make commits also appear under the bot identity, the agent must explicitly set the identity before committing:

  ```bash
  # For App connections (set per-repo or per-process before `git commit`):
  git config user.name 'superpos-agent[bot]'
  git config user.email '<APP_ID>+superpos-agent[bot]@users.noreply.github.com'
  # ...or equivalently, pass GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL / GIT_COMMITTER_NAME /
  # GIT_COMMITTER_EMAIL in the commit's environment, or `git commit --author "..."`.
  ```

  The `<APP_ID>+superpos-agent[bot]@users.noreply.github.com` form is the GitHub-recommended noreply address for App-authored commits and is what links the commit to the bot account in the GitHub UI. The `superpos-gh-token` helper does **not** set these by default — agents (or the dashboard's per-repo bootstrap) opt in explicitly, because some tasks (e.g., applying a user's patch) intentionally want to preserve the original `--author`.
- Document the fallback: if `gh` returns `Not Found` on a repo, the App is not installed there; surface `install_url` to the user, or fall back to a `token` connection if one is permitted.

No schema change to `AgentPersona` is required — the runtime metadata is composed into the response by `PersonaController`, parallel to (but distinct from) `platform_context`.

### 8.1 Versioning and invalidation for `persona.github`

The existing `PersonaController::version()` (`app/Http/Controllers/Api/PersonaController.php:85-94`) reports three version values — `version` (persona document), `platform_context_version`, and `environment_version` — that SDK clients poll to detect staleness. The proposed `persona.github` field is not covered by any of these:

- `version` tracks persona document changes, not runtime connection metadata.
- `platform_context_version` tracks the platform context markdown document.
- `environment_version` is a content-hash computed by `EnvironmentRendererService`, which renders ALL active org services when the agent has `services.read` (`app/Services/EnvironmentRendererService.php:272-295`) — it does not respect per-connection permission grants (`services:{id}`), so it cannot reflect the per-agent `persona.github.connections` view.

**The gap**: granting or revoking a `services:<id>` permission on an agent changes which GitHub connections appear in `persona.github.connections`, but none of the three existing version values change. An SDK client polling `/api/v1/persona/version` would continue to see `changed: false` and keep serving stale `persona.github` data.

**Solution: add `github_version` to the version response.**

`PersonaController::version()` will return a fourth field:

```json
{
  "version": 12,
  "platform_context_version": 3,
  "environment_version": "a1b2c3...",
  "github_version": "d4e5f6..."
}
```

`github_version` is a hex content-hash (same format as `environment_version`) computed over the sorted, deterministic serialization of the `persona.github` payload for the requesting agent. The computation:

1. Resolve the agent's permitted GitHub connections (same query used to build `persona.github.connections` in §8 — org-scoped `service_connections` where `type='github'`, filtered by the agent's `services:{connection_id}` / `services:*` permissions).
2. Build the canonical `persona.github` structure (bot_login, install_url, rate_limit, `default_connection_id`, and the connections array sorted by `service_connection_id` with each entry including its `actor_login`).
3. `hash('sha256', json_encode($canonicalPayload))` — truncated to the first 16 hex chars for compactness.

The version endpoint accepts an optional `known_github_version` query parameter (same pattern as the existing `known_environment_version`). When present, the `changed` flag in the response incorporates it:

```
changed = personaChanged || platformChanged || environmentChanged || githubChanged
```

**What triggers a `github_version` change:**

- A `github_app` or `token` service connection is created, updated, or deleted in the agent's organization.
- A `services:<id>` permission is granted or revoked for the agent, changing which connections it can see.
- A connection's `actor_login` is (re)resolved — for `token` rows this happens on PAT save/rotation, for `github_app` rows it tracks the App-wide bot login.
- The agent's `default_connection_id` is changed.
- The platform-level `config('github.app.bot_login')` or `config('github.app.rate_limit')` changes (rare — typically only on App re-registration).

**Why not bump `environment_version` instead.** `EnvironmentRendererService::renderServices()` renders all active org services visible to agents with `services.read` — it is not scoped by per-connection permissions (`services:{id}`). Changing its hash computation to factor in per-agent connection grants would break its current contract (the hash is agent-independent within an org) and force per-agent cache invalidation across all environment renders, not just GitHub. A dedicated `github_version` is narrower and does not perturb existing cache/invalidation behavior.

**Implementation note (Phase 7).** The `github_version` computation should be extracted into a small service method (e.g., `GitHubPersonaService::getVersion(Agent $agent): ?string`) that both `PersonaController::version()` and `PersonaController::show()` can call. The field returns `null` (and is omitted from the version response) **only when the agent's `persona.github` payload itself would be empty** — i.e., when the agent has no permitted GitHub connections *and* no platform-level GitHub metadata to surface (no `github.app.bot_login`, no `install_url`, no `rate_limit`). In every other case `github_version` is computed and returned, including:

- **PAT-only orgs** (no `github.app.app_id` configured, only `auth_type='token'` rows). These orgs still build `persona.github.connections[]` from PAT rows, still rely on `default_connection_id` for helper selection (§7), and still depend on per-connection `actor_login` for the webhook-loop-prevention rule (§8). A PAT rotation, a `services:<id>` grant/revoke, or a default-connection change must invalidate the persona on these orgs — which means `github_version` must be live on the PAT-only path, not gated on App configuration.
- **Mixed App + PAT orgs**, where some connections are `github_app` and others are `token`. Same rationale.
- **App-configured orgs with zero installations yet**, where `persona.github` still carries `bot_login` / `install_url` / `rate_limit` for the dashboard prompt — a later install must invalidate.

Concretely: `GitHubPersonaService::getVersion(Agent $agent)` keys off the **presence of GitHub connection metadata in the assembled `persona.github` payload**, not off `config('github.app.app_id')`. Pseudocode:

```php
$payload = $this->buildPersonaGithub($agent);   // same builder used by PersonaController::show
if ($payload === null || $payload === []) {
    return null;        // no connections AND no platform-level GitHub block — omit field
}
return substr(hash('sha256', json_encode($payload)), 0, 16);
```

This keeps the field backward-compatible (still omitted for agents/orgs with no GitHub footprint at all, so existing SDK clients that do not send `known_github_version` are unaffected) while ensuring PAT-only and mixed paths get the same invalidation guarantees as the App path.

## 9. Webhooks

The live ingress is `POST /api/v1/webhooks/{service}` (`routes/api.php:111`), where `{service}` is **already the concrete `service_connection_id`** — `WebhookController::receive` (`app/Http/Controllers/Api/WebhookController.php:35-64`) looks up the `ServiceConnection` by that id first, *then* resolves the connector and runs `validateWebhook`. Downstream dedupe and `WebhookRouteEvaluator` matching are keyed on that same id. The connector validation step never sees the request until the `ServiceConnection` has already been resolved.

**The constraint this imposes on a GitHub App.** A GitHub App has exactly one webhook URL, configured at App registration time, that receives events for *every* installation of the App. There is no per-installation webhook URL on a GitHub App, and the URL is a literal string — it cannot contain a placeholder like `{service_connection_id}` that GitHub would somehow expand per installation. So we cannot reuse the existing `/api/v1/webhooks/{service_connection_id}` ingress directly: GitHub will only ever POST to one fixed URL, and that URL must do the per-installation resolution itself before delegating into the standard pipeline.

**V1 ingress: a dedicated shim route in front of the existing catch-all.**

- The GitHub App is configured with a single, literal webhook URL: `POST /api/v1/webhooks/github-app`. No templating, no per-installation overrides, no calls to GitHub's hook-config API.
- A new `GitHubAppWebhookController` handles that route. It reads `installation.id` from the JSON payload and looks up the corresponding `service_connection_id` via the `github_app_installations` mapping table (§5.3) — a simple indexed query on a plain `bigint` column, with no dependency on decrypting `auth_config`. It then **dispatches into the standard webhook pipeline** with the resolved `service_connection_id`. In practice it is a thin wrapper that calls `WebhookController::receive($request, $resolvedConnectionId)` (or an equivalent shared service extracted from that method) so signature validation, dedupe, and `WebhookRouteEvaluator` routing all reuse the existing code path verbatim.
- **Route-order requirement (load-bearing).** The shim route must be registered *before* the catch-all `Route::post('/webhooks/{service}', ...)` at `routes/api.php:111`. Laravel matches routes in declaration order, and `{service}` is a string parameter that would otherwise capture the literal `github-app` segment and dispatch it into `WebhookController::receive` with `$service='github-app'` — which would then 404 because no `ServiceConnection` has that id. The Phase 4 work (§11) must therefore both add the new route *and* place it above the existing catch-all in the file.
- **Webhook secret handling.** Consistent with §2 and §5, the App-wide webhook secret lives only in platform config (`config('github.app.webhook_secret')` — the canonical config surface defined in §5.2) and is **not** stored on any `service_connection` row — neither in `auth_config` nor in the `webhook_secret` column. This means `GitHubConnector::validateWebhook` (`app/Connectors/GitHubConnector.php:36-54`) **will need modification** for `github_app` connections: its `resolveWebhookSecret` method (`app/Connectors/GitHubConnector.php:60-69`) currently reads the secret from `auth_config` or the `webhook_secret` column, but for `github_app` rows both are empty. The updated path must detect `auth_type='github_app'` on the resolved `ServiceConnection` and read the secret from `config('github.app.webhook_secret')` instead. For `auth_type='token'` (PAT) rows, the existing resolution path is unchanged. This is a small, localized change to `resolveWebhookSecret` — no reordering of the validation flow is required.

**Why not the alternatives.**

- *Per-installation webhook URL via the GitHub Apps API.* GitHub does not currently expose per-installation webhook URL configuration. Even if it did, threading freshly minted `service_connection_id`s into per-installation URLs at install time adds an extra coupled write to the install flow without removing any code from the shim. Rejected for V1.
- *Resolving `installation_id` inside `GitHubConnector::validateWebhook`.* `WebhookController::receive` resolves the `ServiceConnection` *before* the connector is invoked (`app/Http/Controllers/Api/WebhookController.php:35-64`); by the time `validateWebhook` runs there is already a single concrete connection in hand. Moving installation-id resolution into the connector would either require reordering that flow (which is intentionally fail-closed and used by every connector, not just GitHub) or re-fetching the connection inside the connector — both worse than a dedicated shim route. Rejected.

**Properties of the shim.**

- Signature validation order is unchanged: shim resolves connection → `WebhookController::receive` loads ServiceConnection → resolve connector → `validateWebhook` → dispatch. The shim itself does not validate the signature; it only resolves the id.
- If `installation.id` does not match any row in `github_app_installations`, the shim returns `404 service_connection_not_found` *without* invoking the connector. This is the same status `WebhookController::receive` would return for an unknown `{service}`, so external callers (including GitHub's redelivery UI) see consistent behavior.
- No change to `WebhookRouteEvaluator` or downstream routing is required — they continue to operate on the same `service_connection_id` they always have. Only the front-door resolution step is new.

## 10. Security

- **Private key handling.** Loaded from env at boot, kept as a string in `config('github.app.private_key')`. Never written to logs, never serialized to JSON, never returned by any API. CI must include a lint check that no `dd($config)` / `Log::info($config)` paths touch `github.app.*`.
- **IATs.** Logged with token hash prefix only (`hash('sha256', $token)` → first 12 chars). Never full token in `activity_log`, `proxy_log`, or stdout. Cache stored in Redis; Redis access is already platform-trusted.
- **Cache scoping.** Cache key includes `organization_id` and `service_connection_id` so a code-path bug that resolved the wrong connection cannot pull another org's token (`github:iat:{organization_id}:{service_connection_id}`). The `installation_id` alone is not used as the key — it is technically global at GitHub, but the broker's authority unit is the org-scoped `service_connection` row.
- **PAT fallback.** Allowed only on connections explicitly created with `auth_type='token'` (the existing GitHub auth_type). Default for new connections is `github_app` once an App is configured. `token` connections decrypt in-process exactly as today — no new risk introduced.
- **Rate limits.** Per-agent and per-installation; documented in §6.5.
- **Audit.** `activity_log` row for every mint. Dashboard surfaces "Recent GitHub token issuances" per hive.

## 11. Rollout

| Phase | Effort | Decision gate |
|---|---|---|
| 1. Register the GitHub App (manifest flow), capture `app_id` + private key + webhook secret. CE: produce a setup wizard step. Cloud: provision the App once, owned by Superpos. | XS | None |
| 2. Migration: ensure `service_connections.auth_type` accepts the new value (no column add — the column already exists; the change is to the allowed-value set, see Phase 4.5), ship config plumbing for `config('github.app.*')`. | S | Phase 1 |
| 3. Implement `POST /api/v1/github/installation-token` (broker), including App JWT minting, IAT cache, rate limits, `activity_log`. | M | Phase 2 |
| 4. Webhook shim: add `GitHubAppWebhookController` and register `POST /api/v1/webhooks/github-app` in `routes/api.php` **above** the existing `Route::post('/webhooks/{service}', ...)` catch-all (`routes/api.php:111`). The controller resolves `service_connection` from `installation.id` via the `github_app_installations` mapping table (§5.3), then dispatches into the existing `WebhookController::receive` pipeline (`app/Http/Controllers/Api/WebhookController.php:35-64`). Also includes: migration to create the `github_app_installations` table, and updating `GitHubConnector::resolveWebhookSecret` to read the secret from `config('github.app.webhook_secret')` for `github_app` connections (see §9). | S | Phase 1 |
| 4.5. **`github_app` auth_type compatibility surfaces.** Update every place that currently hardcodes GitHub auth_type to `token`, so `github_app` rows are accepted and routed through correctly. Concretely: extend `ServiceConnection::AUTH_TYPES` to include `'github_app'` (`app/Models/ServiceConnection.php:17`); extend the dashboard validator's auth_type rule for GitHub connections in `ServiceConnectionDashboardController::validateServiceRequest` (`app/Http/Controllers/Dashboard/ServiceConnectionDashboardController.php:533`) and the dashboard React form so the new value can be set/displayed; extend `HiveTemplateApplyEngine::SERVICE_TYPE_ALLOWED_AUTH_TYPES` and (where applicable) `SERVICE_TYPE_DEFAULTS` to allow `github_app` for `github` (`app/Cloud/Services/HiveTemplateApplyEngine.php:93-95, 128-135`); update the GitHub-token-only assertion at `tests/Unit/Cloud/HiveTemplateApplyEngineTest.php:2264-2293` to also cover a `github_app` credential path; update `GitHubConnector::configurationRules()` to make the `token` field conditionally required — currently `token` is unconditionally `['required', 'string']` (`app/Connectors/GitHubConnector.php:107-113`) and `webhookSecretField()` models webhook auth as `webhook_secret` on the connection (`app/Connectors/GitHubConnector.php:120-122`), so `HiveTemplateApplyEngine` (which iterates `configurationRules()` to discover required fields and promotes the `webhookSecretField` to required when a webhook ref is present — `app/Cloud/Services/HiveTemplateApplyEngine.php:931-950`) would reject the tokenless `github_app` shape. Fix: either make `configurationRules()` auth_type-aware (accept a context parameter or resolve from the `ServiceConnection` in scope) so that `github_app` rows require `installation_id` instead of `token` and return `null` from `webhookSecretField()` (since the App-wide webhook secret lives in platform config, not on the connection), or split into a separate `GitHubAppConnector` with its own rule set; update `ServiceConnectionDashboardController::buildAuthHeaders()` to add a `'github_app'` branch — currently the `match` only handles `token|oauth2|basic|api_key|none` and falls through to empty headers for any unrecognized auth_type (`app/Http/Controllers/Dashboard/ServiceConnectionDashboardController.php:503-518`), so the dashboard "Test Connection" flow for a GitHub App-backed connection would send an unauthenticated request. The `github_app` branch should mint or retrieve an IAT via the same broker logic used by the agent-facing endpoint (§6) and set `Authorization: Bearer <IAT>`. **Probe endpoint must also change for `github_app` connections.** The current probe is `GET https://api.github.com/user` (`app/Http/Controllers/Dashboard/ServiceConnectionDashboardController.php:493-500`), which per GitHub's docs ([REST: Get the authenticated user](https://docs.github.com/en/rest/users/users#get-the-authenticated-user)) accepts **App user-access tokens** but **not installation access tokens** — calling `/user` with an IAT returns `403 Resource not accessible by integration`, making every "Test Connection" click for a GitHub App row fail even when the IAT is valid. Swap the probe to `GET https://api.github.com/installation/repositories` when `auth_type='github_app'`: it accepts the IAT directly, returns the repos the installation can see (which doubles as a useful confirmation in the dashboard UI), and does not require a JWT. Alternatives considered and rejected: `GET /app/installations/{installation_id}` works but requires the App JWT rather than the IAT (couples the probe to a different credential, doesn't exercise the same code path the agent will use); `GET /rate_limit` accepts an IAT but tells us nothing useful about whether the installation is functional. Keep `GET /user` for `auth_type='token'` (PAT) rows — that path is unchanged. **Rollback note**: if any of these surfaces are not updated when Phase 5 / 8 starts writing `auth_type='github_app'` rows, the dashboard validator will 422 on edit, hive-template apply will reject the credential, the dashboard test button will send unauthenticated requests, and existing tests will fail — so Phase 4.5 is a hard prerequisite for Phase 5 and Phase 8, not just an "also nice to have." | S | Phase 2 |
| 5. Dashboard: "Connect via Superpos GitHub App" button (renders App install URL), post-install handler that creates the `service_connection` row from the GitHub redirect. | M | Phase 3, 4.5 |
| 6. **Helper rollout + `GITHUB_TOKEN` decommission across all runtime surfaces.** Build `superpos-gh-token` helper, wire `git` credential helper + `gh` `GH_TOKEN` plumbing, and remove static `GITHUB_TOKEN` from the agent container image. **`GITHUB_TOKEN` is not just a container env var — several other surfaces read it today and all of them must migrate in lockstep with the container change**, otherwise the variable's removal silently breaks them. Concretely: (a) **Python worker** — `sdk/python/src/superpos_sdk/workers/github.py:1-84` reads `GITHUB_TOKEN` directly from the process environment to authenticate its HTTP client; migrate it to call `superpos-gh-token` (preferred — same code path as `gh`/`git`) **or** call the broker endpoint itself, resolving the target connection via `GH_CONNECTION_ID` per the §7 selection contract. The worker must also stop assuming a single global token across its lifetime: every outbound call should mint/refresh against the connection bound to the task it is executing. (b) **Hosted-agent env schema** — `config/platform.php:373-377` exposes `GITHUB_TOKEN` in the hosted-agent env allowlist; remove the entry, and replace it with a hosted-agent-side install of the `superpos-gh-token` helper plus `GH_CONNECTION_ID` (or persona-default-driven) selection. The dashboard "agent credentials" view that currently surfaces `GITHUB_TOKEN` as a copyable env line must be updated to show the helper invocation instead (the bulk-copy view shipped in #645 should drop the `GITHUB_TOKEN` row for github connections). (c) **Tests that assert `GITHUB_TOKEN` is present** — `tests/Feature/Cloud/HostedAgentDashboardTest.php:280-307` and `tests/Unit/Cloud/HostedAgentPresetRegistryTest.php:427-440` both assert that the hosted-agent env block includes `GITHUB_TOKEN`; update them to assert the new helper-based shape (e.g., the absence of `GITHUB_TOKEN` and the presence of whatever selection signal replaces it — `GH_CONNECTION_ID` for hosted agents that target a specific connection, or no GitHub env at all when the persona default is used). (d) **CE shell SDK / agent images** — any `superpos-agent-core` image layer that exports `GITHUB_TOKEN` from the connection at boot must be removed; the helper now does this on demand. **Ordering**: do (a)/(b)/(c) before flipping the Dockerfile to drop the env var, so the container removal lands only after every reader has been migrated. Phase 6 is not complete until `rg "GITHUB_TOKEN" --type py --type php` returns only references in code that has been intentionally retained for legacy detection (e.g., a startup check that fails fast with a clear migration message if an operator still sets it on a hosted-agent env). | M | Phase 3 |
| 7. Persona update: new top-level `persona.github` field in `PersonaController::show` (including per-connection `actor_login` and the optional `default_connection_id`); add `github_version` content-hash to `PersonaController::version` response with `known_github_version` polling support (§8.1); extract `GitHubPersonaService` for shared version computation; rewrite the persona's webhook-loop rule to compare `sender.login` against the resolved connection's `actor_login` (works for both `github_app` and `token` paths — see §8). | S | Phase 6 |
| 8. Migration playbook for existing `token` (PAT) connections: dashboard banner offering to upgrade. Existing rows remain valid; no forced cutover. | S | Phase 5, 6 |

Each phase ships independently. The system is correct after each: until Phase 6 lands, agents keep using whatever credential their connection produces (`token`/PAT or App-via-broker); from Phase 6 onward the helper is the only path. Phase 4.5 is a tightly-coupled prerequisite for the user-visible upgrade flow in Phase 5/8 — without it, generic dashboard and template paths will reject or mis-handle the new rows.

## 12. Open questions

- **Narrowed tokens.** GitHub supports per-call `repository_ids` + `permissions` subset on the access-tokens endpoint. V1 returns the full-installation IAT for simplicity. If we see incidents where one bad task burns the bot's reputation on unrelated repos, revisit and accept the `repo` body param introduced in §6.1 as a real input.
- **Per-agent rate limit value.** 60 mints/hour assumes one mint per task plus occasional refresh. Long-running multi-PR sessions might hit it. Worth instrumenting before fixing the number.
- **Cross-hive operations.** If an agent in hive A creates a task in hive B that touches GitHub, the executing agent in B uses B's installation. Confirmed direction; documented here for posterity.
- **CE setup ergonomics.** Manual App registration is a friction point for self-hosters. Investigate GitHub's [App Manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest) so CE setup can one-click create the App against the admin's chosen org.
- **Bot commit signing.** GitHub Apps can sign commits via the `/repos/.../contents` API but not via plain `git push`. V1 accepts unsigned bot commits; signed commits is a separate feature.
- **What happens when the App is uninstalled mid-task?** Broker returns `403 github_app_not_installed`. The agent should surface this to the user rather than silently failing — covered by the helper's exit-non-zero behaviour in §7, but the persona prompt should explicitly call it out.
