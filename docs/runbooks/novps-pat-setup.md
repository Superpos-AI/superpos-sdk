# Runbook: NoVPS Personal Access Token (PAT) Setup

> **Audience:** Cloud ops engineer
> **When:** One-time setup per environment (production, staging) and on PAT rotation.
> **Prerequisite:** Admin access to the NoVPS.io project used by Superpos Cloud.

This runbook covers everything Superpos Cloud needs to talk to NoVPS:
generating a personal access token, the env vars the app reads, and a
note on registry credentials for private images.

---

## 1. Generate a NoVPS PAT

The NoVPS public API is authenticated with a **personal access token**
(prefixed `nvps_`). The token is sent in the `Authorization` header as
the **raw value** (no `Bearer` prefix).

### Steps

1. Log in to the NoVPS dashboard.
2. Navigate to **Account → Settings → API Tokens** (the exact label
   may vary; look for "Personal access tokens" or "API tokens").
3. Click **Generate** / **Create new token**.
4. Give it a descriptive name, e.g. `superpos-cloud-production`.
5. Save the returned value — it is shown only once. The value will look
   like:

   ```
   nvps_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
   ```

The token must have permission to manage **apps** and **resources**
inside the project Superpos Cloud deploys to.

---

## 2. Configure the Superpos Cloud Environment

Set the following environment variables on the Cloud Superpos
deployment (`.env`, infra config, or NoVPS app env):

### 2.0 Required base env vars (all environments)

These are required for any Superpos deployment serving traffic over
HTTPS through a reverse proxy. Cloud edition applies sensible defaults
for `TRUSTED_PROXIES` and forces Secure cookies / HTTPS URLs at runtime
(see `app/Providers/AppServiceProvider.php` and `bootstrap/app.php`),
but **explicit settings are still strongly recommended** so the
configuration is visible and survives any future change to the
defaulting logic.

| Var | Required | Notes |
| --- | --- | --- |
| `APP_URL` | yes | Must be `https://<domain>` in production. Drives URL generation, OAuth callback URLs, and the SESSION_SECURE_COOKIE auto-detect. |
| `TRUSTED_PROXIES` | yes (recommended) | `*` to trust all proxies (NoVPS is the trust boundary), or a comma-separated list of IPs/CIDRs. Cloud edition defaults to `*` when unset; setting it explicitly is preferred. **Without this, Laravel sees forwarded HTTPS as plain HTTP** — cookies lose the `Secure` flag, `route()` emits `http://` URLs (mixed-content blocking), and CSRF cookie mismatches produce 419 errors on POST/PATCH/DELETE. |
| `SESSION_SECURE_COOKIE` | yes | `true` in production. Cloud edition force-enables this at runtime, but explicit setting documents the requirement. Required for the session cookie to round-trip on HTTPS browsers. |

### 2.1 NoVPS-specific env vars

| Var | Required | Notes |
| --- | --- | --- |
| `NOVPS_API_TOKEN` | yes | The full `nvps_...` PAT from step 1. |
| `NOVPS_PROJECT_ID` | yes | The NoVPS project ID Superpos deploys hosted agents into. |
| `NOVPS_BASE_URL` | optional | Defaults to `https://api.novps.io`. Override only if pointing at a non-prod region/host. |
| `NOVPS_HTTP_TIMEOUT` | optional | Per-request timeout in seconds, default `30`. |
| `NOVPS_IMAGE_CREDENTIALS` | optional | Inline `username:token` string used by NoVPS to pull private container images. For GHCR: `<github_username>:<classic PAT with read:packages>`. Sent as `source.credentials` in the apply payload. For anonymous pulls (public packages only), set this to an **empty string** (`NOVPS_IMAGE_CREDENTIALS=`); simply leaving it unset will cause the deployer to fall back to the legacy `NOVPS_REGISTRY_CREDENTIAL_ID` if that variable is still present. |
| `NOVPS_REGISTRY_CREDENTIAL_ID` | deprecated | Read as a fallback if `NOVPS_IMAGE_CREDENTIALS` is unset. Despite the historic name, the value is also an inline `username:token` string, **not** a UUID — the original docs were wrong. New deploys should use `NOVPS_IMAGE_CREDENTIALS`. |

Verify the value is picked up by the application:

```bash
php artisan tinker --execute="echo config('services.novps.base_url'); echo PHP_EOL;"
# Expected: https://api.novps.io  (or your override)

php artisan tinker --execute="echo strlen((string) config('services.novps.api_token'));"
# Expected: a non-zero number — never echo the token itself.
```

Restart / redeploy the application after any env change so the new
configuration takes effect.

### Observability env vars (Horizon container)

Hosted-agent deploys run as queued jobs on the **Horizon** worker
container, not on the web container — these are separate processes
with separate environments. For NoVPS errors raised inside a queue
job (deploy, redeploy, usage sampling) to surface in Sentry, **both
`SENTRY_DSN` and `PLATFORM_EDITION` must be set on the Horizon
container as well as the web container**. If only the web container
has them, you will see web-side 502/503s in Sentry but the actual
upstream `NovpsApiException` raised inside `DeployHostedAgentJob`
will be silently swallowed by the queue runner. Verify after every
infra change that Horizon's `printenv | grep -E '^(SENTRY_DSN|PLATFORM_EDITION)='`
returns the same values as the web container.

---

## 3. Container Image Publishing (Prerequisite)

The hosted-agent presets reference two container images that are **built
and published from their own dedicated public repos** — *not* from
`superpos-app`. The `docker/agents/` directory in `superpos-app` does
**not** exist; agent images are not built in this repo.

| Preset | Source Repo | Default Image | Env Override |
| --- | --- | --- | --- |
| `claude-sdk` | [Superpos-AI/superpos-claude-agent](https://github.com/Superpos-AI/superpos-claude-agent) | `ghcr.io/superpos-ai/superpos-claude-agent` | `PLATFORM_HOSTED_CLAUDE_IMAGE` |
| `codex-sdk`  | [Superpos-AI/superpos-codex-agent](https://github.com/Superpos-AI/superpos-codex-agent)   | `ghcr.io/superpos-ai/superpos-codex-agent`  | `PLATFORM_HOSTED_CODEX_IMAGE` |

### What needs to happen

1. **Images are built and pushed by each agent repo's own CI workflow.**
   Both `Superpos-AI/superpos-claude-agent` and
   `Superpos-AI/superpos-codex-agent` carry their own GHCR publish
   workflow that pushes `:latest` (and tagged releases) to the GHCR
   image names listed above. To use a custom registry, override the
   image names via `PLATFORM_HOSTED_CLAUDE_IMAGE` /
   `PLATFORM_HOSTED_CODEX_IMAGE` env vars.
2. **Ensure the packages are readable by NoVPS.** Either:
   - Make the packages **public** (simplest — NoVPS pulls anonymously), or
   - Keep them private and set `NOVPS_IMAGE_CREDENTIALS` to an inline
     `username:token` string on the Superpos Cloud deployment (see §4
     below). The credential is sent in the apply payload under
     `source.credentials` and used by NoVPS server-side for the image
     pull.
3. **Tag policy:** the presets default to the `latest` tag. Pin to a
   specific tag via `PLATFORM_HOSTED_CLAUDE_TAG` /
   `PLATFORM_HOSTED_CODEX_TAG` env vars if you need reproducible
   deploys.

### Migration note

The old images (`ghcr.io/apiary-ai/apiary-slim-agent-claude`,
`ghcr.io/apiary-ai/apiary-slim-agent-codex`) under the retired
`apiary-ai` org are **no longer published** and should not be
referenced. The new `superpos-ai` names above are the intended
long-term target and replace them entirely.

---

## 4. Registry Credentials (Private Images Only)

If the preset images are made **public** on GHCR, no registry
credential is required — NoVPS pulls them anonymously. To ensure
anonymous pulls, set `NOVPS_IMAGE_CREDENTIALS` to an **empty string**
(`NOVPS_IMAGE_CREDENTIALS=`). If you simply leave it unset and the
legacy `NOVPS_REGISTRY_CREDENTIAL_ID` is still present, the deployer
will fall back to the legacy credential instead of pulling anonymously.

### 4.1 Private container registry credentials

When images are kept private (e.g. on GHCR with restricted visibility),
set `NOVPS_IMAGE_CREDENTIALS` on the Cloud Superpos deployment to the
inline `username:token` string NoVPS will use to authenticate the
image pull at deploy time:

```
NOVPS_IMAGE_CREDENTIALS=<github_username>:<classic_PAT_with_read:packages>
```

For GHCR this is your GitHub username and a classic personal access
token with the `read:packages` scope (and only that scope — keep it
minimal). The value is sent in the apply payload under
`source.credentials` and used by NoVPS server-side for `docker pull`.
**It is NOT exposed to the agent container itself.**

The credentials field is masked everywhere it could otherwise leak:

- Outbound HTTP debug logs (the `RedactingHttpLogger` middleware in
  `app/Cloud/Services/Novps/NovpsClient.php` runs the request body
  through `SecretRedactor` before `Log::debug()` ever sees it).
- Exception messages — `NovpsApiException` deliberately never carries
  the request body.
- Activity log — only structured deploy metadata (app name, image tag,
  reason) is written, never the raw apply payload.

### 4.2 Rotation

PATs do not auto-rotate. To rotate the image-pull credential:

1. Generate a new classic PAT in GitHub with `read:packages` scope.
2. Update `NOVPS_IMAGE_CREDENTIALS` on the Superpos Cloud deployment.
3. Redeploy the app so the new env value is read by the worker.
4. Trigger a hosted-agent redeploy (or wait for the next scheduled one)
   to confirm the new credential authenticates the pull.
5. Once confirmed, revoke the old PAT in GitHub.

> **Note:** The old `NOVPS_GHCR_CREDENTIAL_ID` env var is deprecated.
> The `NOVPS_REGISTRY_CREDENTIAL_ID` env var is also deprecated — its
> name implied a UUID, but the field is actually an inline
> `username:token` string. New deploys should use
> `NOVPS_IMAGE_CREDENTIALS`. The deployer reads
> `NOVPS_REGISTRY_CREDENTIAL_ID` only as a fallback when
> `NOVPS_IMAGE_CREDENTIALS` is **unset** (null). If you want anonymous
> pulls and the legacy variable is still present, set
> `NOVPS_IMAGE_CREDENTIALS` to an **empty string** rather than leaving
> it unset — otherwise the deployer will use the legacy credential.

---

## 5. Sanity Check

After the env vars are deployed:

1. Ensure `PLATFORM_HOSTED_AGENTS_ENABLED=true` in the deployment
   environment.

2. Via the dashboard or API, deploy a hosted agent using the
   `claude-sdk` preset into a **test hive**:

   ```bash
   curl -X POST "https://<SUPERPOS_URL>/api/v1/hives/<test-hive-slug>/hosted-agents" \
     -H "Authorization: Bearer <USER_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "pat-smoke-test",
       "preset_key": "claude-sdk",
       "model": "claude-sonnet-4-6",
       "user_env": {
         "ANTHROPIC_API_KEY": "<test-api-key>"
       }
     }'
   ```

3. Poll the status endpoint until the agent reaches `running`:

   ```bash
   curl "https://<SUPERPOS_URL>/api/v1/hives/<test-hive-slug>/hosted-agents/<id>/status" \
     -H "Authorization: Bearer <USER_TOKEN>"
   ```

   Expected (eventually): `"status": "running"`.

4. Clean up:

   ```bash
   curl -X DELETE "https://<SUPERPOS_URL>/api/v1/hives/<test-hive-slug>/hosted-agents/<id>" \
     -H "Authorization: Bearer <USER_TOKEN>"
   ```

If the agent reaches `running`, the PAT works end-to-end.

---

## 6. Rotation

PATs do not auto-rotate. Plan rotation on whatever cadence your security
policy demands (90 days is a reasonable default).

1. Generate a new PAT in the NoVPS dashboard (Section 1).
2. Update `NOVPS_API_TOKEN` on the Superpos Cloud deployment.
3. Restart / redeploy the app.
4. Verify with the sanity check (Section 5).
5. Revoke the old PAT in the NoVPS dashboard once traffic is confirmed
   on the new token.

No hosted-agent redeploy is required — the PAT is only used by the
Superpos control-plane to issue API calls to NoVPS, not by the running
agent containers.

---

## 7. If Something Breaks

### Failure Mode 1: 401 Unauthorized from `/apps/...`

**Symptom:** Hosted agent deploys fail almost immediately. Application
logs show `novps API ... returned 401`.

**Cause:** `NOVPS_API_TOKEN` is missing, malformed, or revoked.

**Fix:**

1. Confirm the env var is set and starts with `nvps_`.
2. Confirm the token is still listed (and not expired/revoked) in the
   NoVPS dashboard.
3. Generate a new PAT and roll the env var.

### Failure Mode 2: 403 / "project not found"

**Symptom:** API calls succeed for some endpoints but `/apps/...`
returns 403 or "project not found".

**Cause:** `NOVPS_PROJECT_ID` does not match the project the PAT can
access, or the PAT does not have project-management scope.

**Fix:**

1. Confirm the project ID matches the project shown in the dashboard.
2. Re-generate the PAT inside that project's account (or grant the
   existing PAT the right scopes if the dashboard supports per-token
   scope editing).

### Failure Mode 3: Image Pull Failure (private image)

**Symptom:** Apply succeeds but the resource never reaches `running`;
NoVPS-side logs show an image-pull error.

**Cause:** The image is private and no valid registry credential is
configured for Superpos to send to NoVPS.

**Fix:** Set `NOVPS_IMAGE_CREDENTIALS` on the Cloud Superpos
deployment to `<github_username>:<classic_PAT_with_read:packages>`,
then redeploy Superpos so the new env value is picked up, then
trigger a hosted-agent redeploy. The value is sent in the apply
payload under `source.credentials`. See §4.1 above.

---

### Verifying admin emails

After setting `PLATFORM_ADMIN_EMAILS` (or rotating which emails are listed), run:

```
php artisan platform:verify-admin-emails
```

This stamps `email_verified_at` for each listed user **whose column is
currently null**, allowing them through Laravel's `verified` middleware.
Users who already have a non-null `email_verified_at` are left unchanged
(the command prints `[already verified]` for each). Idempotent — safe to
run anytime. Use `--dry-run` first if uncertain:

```
php artisan platform:verify-admin-emails --dry-run
```

#### One-time `--force` backfill for existing deployments

On existing deployments being upgraded for the first time, some admins
may already have an `email_verified_at` value set via self-verification,
OAuth, or other legacy flows. The plain run above skips those rows
because it only touches users with a null timestamp. To ensure **every**
admin in the allowlist has a fresh operator-stamped verification (the new
trust root), run the force variant **once** immediately after deploying
the command for the first time:

```
php artisan platform:verify-admin-emails --force --dry-run   # preview first
php artisan platform:verify-admin-emails --force              # apply
```

`--force` re-stamps `email_verified_at = now()` on **all** listed admins,
including those already verified. The command prints `[re-verified]` for
rows that had a prior value and `[verified]` for rows that were null.

#### When to use plain runs vs `--force`

| Scenario | Command |
| --- | --- |
| After adding or rotating `PLATFORM_ADMIN_EMAILS` | `php artisan platform:verify-admin-emails` |
| Routine post-deploy verification (nothing changed) | `php artisan platform:verify-admin-emails` |
| **First deploy** of this command on an existing environment (legacy backfill) | `php artisan platform:verify-admin-emails --force` |
| Suspected drift — want to guarantee all admins are re-verified | `php artisan platform:verify-admin-emails --force` |

After the initial `--force` backfill, day-to-day usage should use the
plain (non-force) variant. The `--force` flag is not harmful to run
repeatedly, but it is unnecessary once all admin rows have been stamped
by the operator command at least once.

The login listener (`App\Cloud\Auth\PromoteAndGateOnLogin`) still
auto-promotes the `is_platform_admin` flag for any user whose address is
on the env list. When a user is **first promoted** (transitions from
non-admin to admin), the listener also **resets `email_verified_at` to
null** — even if the user previously self-verified. This ensures the
artisan command is the sole trust root: a user who verified their email
before being added to the allowlist cannot bypass the operator command.

Without running this command after adding or rotating admin emails,
newly promoted admins whose `email_verified_at` is null will be blocked
by the `verified` middleware when accessing `/admin/*` routes (they can
still log in and reach the dashboard).

> **Note:** OAuth login (GitHub / Google) does **not** auto-verify
> `email_verified_at` for admin-listed emails. The admin panel's
> force-verify endpoint (`/admin/users/{user}/verify`) also rejects
> platform admin emails — they must go through the artisan command.

### Reconciling admin flags after rotating `PLATFORM_ADMIN_EMAILS`

When you add or remove emails from `PLATFORM_ADMIN_EMAILS`, the
`is_platform_admin` DB flag does **not** automatically update for
existing users. The login listener and onboarding service only promote
(add-only), so removed admins keep their access indefinitely.

After rotating the env list, run:

```
php artisan platform:reconcile-admins
```

This command:
- **Promotes** users in the current allowlist who are not yet admins
- **Demotes** users NOT in the current allowlist who currently have
  `is_platform_admin = true`
- Logs all changes via `Log::info` and prints to stdout

Use `--dry-run` first to preview changes:

```
php artisan platform:reconcile-admins --dry-run
```

Idempotent — safe to run anytime. Run this command **and**
`platform:verify-admin-emails` together after every rotation of
`PLATFORM_ADMIN_EMAILS`.

---

*Related: [FEATURE_HOSTED_AGENTS.md §4.1](../features/list-1/FEATURE_HOSTED_AGENTS.md#41-configservicesphp) — NoVPS operator configuration*
