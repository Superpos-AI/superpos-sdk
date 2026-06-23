# GitLab Cloud Integration (OAuth-app style)

Let a Superpos org connect **GitLab (gitlab.com / GitLab Cloud)** the way it
connects GitHub — agents act on GitLab repos (issues, merge requests,
pipelines) through the existing proxy + webhook pipeline, with **no agent ever
holding a token**.

Unlike the GitHub App (a per-agent *installation token broker*, see
[`github-app-integration.md`](./github-app-integration.md)), GitLab is connected
through a **standard OAuth2 application**: the platform holds one OAuth client,
and each `service_connection` stores its own per-user access/refresh token pair.

## Phase breakdown (issues)

| Phase | Issue | Scope |
| ----- | ----- | ----- |
| GL-1  | #167  | Register the OAuth app + `config/gitlab.php` plumbing (**this doc**) |
| GL-2  | #168  | `auth_type=gitlab_oauth` threaded through compatibility surfaces |
| GL-3  | #169  | OAuth connect flow + `TokenRefresher` GitLab branch (refresh rotation) |
| GL-4  | #170  | `GitLabConnector` + webhook routing + hook setup |
| GL-5  | —     | Dashboard "Connect GitLab" button + callback |
| GL-6  | —     | `superpos-gitlab` agent module + `glab`/`GITLAB_TOKEN` helper |

---

## GL-1: Registering the GitLab OAuth application

GitLab OAuth apps can be created at three scopes. Use the narrowest that fits
the deployment:

- **User-owned** (`User Settings → Applications`) — fine for a single-operator
  CE install.
- **Group-owned** (`Group → Settings → Applications`) — recommended for an org
  so the app survives an individual leaving.
- **Instance-wide** (admin area, self-managed only).

### Steps (gitlab.com)

1. Go to **User Settings → Applications** (`https://gitlab.com/-/user_settings/applications`)
   or the group/instance equivalent.
2. **Name**: `Superpos` (or `Superpos – <org>`).
3. **Redirect URI**: must match `config('gitlab.oauth.redirect')` **exactly**.
   Default is `<APP_URL>/auth/gitlab/callback`. Register every environment's URL
   (e.g. `https://app.superpos.io/auth/gitlab/callback` and any staging host) —
   GitLab does strict redirect-URI matching.
4. **Confidential**: ✅ Yes (the server holds the secret; required for refresh
   tokens).
5. **Scopes**: tick
   - `api` — full read/write repo, MR, and pipeline access (the proxy uses this).
   - `read_user` — for the Test-Connection `GET /user` probe (GL-2).

   Add `read_repository` / `write_repository` only if you want to scope down
   from full `api`; for the MVP `api` + `read_user` is the documented default
   (`GITLAB_OAUTH_SCOPES=api,read_user`).
6. Click **Save application**. Copy the **Application ID** and **Secret** — the
   secret is shown only once.

### Wiring it up

Paste the credentials into the environment (CE: `.env`; Cloud: platform secret
store). **Never store these in the database.**

```dotenv
GITLAB_OAUTH_CLIENT_ID=<Application ID>
GITLAB_OAUTH_CLIENT_SECRET=<Secret>
GITLAB_OAUTH_REDIRECT_URI=https://app.example/auth/gitlab/callback   # optional; defaults to APP_URL/auth/gitlab/callback
GITLAB_OAUTH_SCOPES=api,read_user
GITLAB_API_BASE_URL=https://gitlab.com/api/v4
GITLAB_ALLOWED_HOSTS=gitlab.com
GITLAB_WEBHOOK_SECRET=                                               # optional app-wide fallback; per-connection secrets preferred
```

All of these are read through `config('gitlab.*')` (see `config/gitlab.php`).

### `allowed_hosts` (self-managed safety)

`GITLAB_ALLOWED_HOSTS` is an allowlist of GitLab hosts that connections may
authenticate against. A tenant can set a connection `base_url`, so without an
allowlist a malicious `base_url` could point the OAuth/refresh exchange (which
carries the platform client secret) at an attacker-controlled host. Any
`base_url` whose host is **not** in this list is rejected before any token is
exchanged or proxied. Defaults to `gitlab.com`; add self-managed hosts
explicitly (e.g. `gitlab.com,gitlab.acme.internal`). The host of
`GITLAB_API_BASE_URL` must also appear here.

### Refresh tokens

GitLab **rotates the refresh token on every use**. GL-3 handles this with a
row-locked refresh in `TokenRefresher`; confidential apps get refresh tokens
without an explicit `offline_access` scope.
