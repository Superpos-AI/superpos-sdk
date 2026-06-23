# GitLab Webhooks (GL-4)

How GitLab webhooks flow through the platform, and how to register a project
hook — automatically or manually.

## Pipeline

A GitLab project (or group) webhook is delivered to the existing catch-all
endpoint:

```
POST /api/v1/webhooks/{service}
```

where `{service}` is the **ServiceConnection id** (a ULID). There is **no
installation table** — GitLab uses user-scoped OAuth tokens, so resolution is
keyed on the connection id directly, exactly like the `/webhooks/{service}`
route resolves any other connection.

`WebhookController::receive()` →
1. Resolves the `ServiceConnection` by id and checks it is active.
2. Resolves `GitLabConnector` (registered in `WebhookController::$builtinClassPaths`
   under the key `gitlab`, auto-provisioned on first delivery).
3. `validateWebhook()` — **constant-time** compare of the `X-Gitlab-Token`
   header against the connection's stored secret (`hash_equals`). GitLab echoes
   the secret verbatim; it is *not* an HMAC of the body. No secret resolvable ⇒
   fail closed (401).
4. `parseWebhook()` — normalizes `X-Gitlab-Event` / `object_kind` (+ optional
   `object_attributes.action`) into the platform envelope
   (`{event, payload}`), e.g. `merge_request.open`, `push`, `pipeline`,
   `issue.close`, `note`.
5. Dedups on `X-Gitlab-Event-UUID` and dispatches `ProcessWebhook`, which runs
   `WebhookRoute` evaluation and creates a task — identical to every other
   connector.

## Webhook secret

The secret lives, in preference order:

1. `auth_config['webhook_secret']` on the `ServiceConnection` (preferred);
2. the legacy top-level `webhook_secret` column;
3. the optional app-wide fallback `config('gitlab.webhook.secret')`
   (`GITLAB_WEBHOOK_SECRET`).

`GitLabConnector::resolveWebhookSecret()` is the single source of truth, used
both to verify deliveries and (via `GitLabHookRegistrar`) to configure the hook,
so the value GitLab sends always matches the value we check.

## Registering the project hook

### Why not automatically at OAuth-connect time?

A `gitlab_oauth` `ServiceConnection` is created from a **user-scoped** OAuth
token. At connect time no project has been selected, and GitLab webhooks are
**per-project** (or per-group) — there is nothing to attach a hook to yet.
Registration therefore happens once a project is chosen, not at connect time.

### Automatic (API) — `GitLabHookRegistrar`

When a project is selected, call:

```php
app(\App\Services\GitLabHookRegistrar::class)
    ->registerProjectHook($serviceConnection, $projectId);
```

It `POST`s to `…/projects/:id/hooks` with the connection's bearer token,
setting `url` to this connection's `/api/v1/webhooks/{id}` endpoint and `token`
to the per-connection secret, enabling push / merge-request / pipeline / issue /
note events with SSL verification on. It returns `null` (and logs) on failure —
notably a `403` when the OAuth user lacks Maintainer/Owner on the project, in
which case fall back to the manual path below.

### Manual

In the GitLab project: **Settings → Webhooks → Add new webhook**

- **URL**: `https://<your-superpos-host>/api/v1/webhooks/<connection-id>`
- **Secret token**: the connection's `webhook_secret`
- **Trigger**: Push, Merge request, Pipeline, Issues, Comments (as needed)
- **SSL verification**: enabled
