# Sentry setup runbook (TASK-285)

Sentry is wired for **Cloud only** and gated on `SENTRY_DSN`. With the
DSN unset (or running in CE), the SDK is never initialized — no events,
no overhead.

This document covers how to turn it on for a Cloud deployment, what to
expect in the dashboard, and how to verify the secret-scrubbing pipeline
is working.

---

## 1. Create the Sentry project

1. Log in to [sentry.io](https://sentry.io) (or your self-hosted Sentry).
2. **Projects → Create Project**:
   - Platform: **Laravel** (backend) and **React** (frontend) — two
     separate projects, or one combined project with two DSNs. We use
     two for cleaner alert routing.
3. Copy the **DSN** for each project. Sentry DSNs are public-by-design;
   shipping them in client bundles is expected.

## 2. Create an auth token (for source-map uploads)

1. **Settings → Account → API → Auth Tokens → Create New Token**.
2. Required scopes:
   - `project:read`
   - `project:releases`
   - `org:read`
3. Copy the token. Treat it as a secret — it's NOT in the same class as
   the public DSN.

## 3. Configure environment variables

Set these on your Cloud deployment (Fly secrets, k8s ConfigMap, etc.):

```bash
# Backend — required
PLATFORM_EDITION=cloud
SENTRY_DSN=https://<key>@o<org>.ingest.sentry.io/<project>

# Backend — optional tuning
SENTRY_TRACES_SAMPLE_RATE=0.1     # 10% of requests get a perf trace
SENTRY_PROFILES_SAMPLE_RATE=0.0   # CPU profiling off by default
SENTRY_RELEASE=$(git rev-parse --short HEAD)

# Frontend — required to enable @sentry/react
VITE_SENTRY_DSN=https://<key>@o<org>.ingest.sentry.io/<project>
VITE_SENTRY_ENVIRONMENT=production
VITE_SENTRY_RELEASE=$(git rev-parse --short HEAD)
VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
# VITE_PLATFORM_EDITION is auto-derived from PLATFORM_EDITION by
# vite.config.js — no need to set it separately. Ensure it is blank
# (or unset) so auto-derivation runs; an explicit value like "ce"
# shadows the derivation and silently disables frontend Sentry.

# Source-map upload (CI build step only) — optional
SENTRY_AUTH_TOKEN=<token from step 2>
SENTRY_ORG=<your sentry org slug>
SENTRY_PROJECT=<your sentry project slug>
```

If `SENTRY_AUTH_TOKEN` / `SENTRY_ORG` / `SENTRY_PROJECT` are missing the
build still succeeds — `npm run build` simply skips the source-map
upload step. This is the right behavior for local/dev builds.

## 4. Verify

### 4.1 SDK is off when DSN is empty

```bash
PLATFORM_EDITION=cloud SENTRY_DSN= php artisan sentry:test
```

Expect a message like *"DSN is not configured"* and a non-zero exit. No
network requests should be issued.

### 4.2 SDK initializes when DSN is set

```bash
PLATFORM_EDITION=cloud SENTRY_DSN=<your dsn> php artisan sentry:test
```

Expect *"Sending test event..."* followed by *"Test event sent"*. Confirm
the event lands in your Sentry project's Issues view within ~30s.

### 4.3 CE never sends events

```bash
PLATFORM_EDITION=ce SENTRY_DSN=<your dsn> php artisan sentry:test
```

Expect *"DSN is not configured"* — the CE-only gate in `config/sentry.php`
zeroes out the effective DSN even when the env var is set. CE
self-hosters who genuinely want their own Sentry can set
`PLATFORM_EDITION=cloud` (or fork the gate).

### 4.4 Frontend reports

In a browser, open a page that crashes a React component (e.g. throw
inside a render). Confirm the error appears in the Sentry React project
within seconds, with a `componentStack` context.

## 5. What gets tagged on every event

Backend (`SetSentryContext` middleware):

| Tag | Source |
|-----|--------|
| `organization_id` | `app('platform.current_org_id')` |
| `hive_id` | `app('platform.current_hive_id')` |
| `cloud_tenant_id` | `app('cloud.current_tenant_id')` |
| `user_id` | `request()->user()->getAuthIdentifier()` |
| `user_email` | `request()->user()->email` |
| `edition` | `cloud` (always, since CE is gated off) |
| `release` | `config('sentry.release')` |
| `route` | `request()->route()->getName()` |

## 6. What is **never** sent to Sentry

The `App\Sentry\EventScrubber::scrub()` beforeSend hook strips:

- Request body keys matching `/token|key|secret|password|authorization|bearer|api_key|stripe/i`
- Query-string keys matching the same pattern
- Cookies (entire cookie jar redacted by key)
- The `Stripe-Signature`, `Cookie`, and `Authorization` request headers
- The **entire request body** for routes containing `/stripe/webhook`,
  `/webhooks/`, or `/inbox/` — Stripe and webhook payloads contain
  customer PII by design and aren't useful for debugging
- Stack-frame `vars` arrays that look like full env dumps (≥5 SCREAMING_SNAKE_CASE keys)
- User metadata keys matching the sensitive pattern

**SQL-query breadcrumbs are off by default.** Reportable SQL strings
have a habit of containing literals (`WHERE email = 'x@y.com'`), and the
volume is brutal. Re-enable per environment with
`SENTRY_BREADCRUMBS_SQL_QUERIES_ENABLED=true` only if you need it.

### Manual verification

1. Trigger a 500 from a route that processes Stripe webhook payloads
   (e.g. by sending a malformed payload to `/stripe/webhook` in staging).
2. Open the resulting Sentry issue.
3. Confirm: **no request body** is shown, **no `Stripe-Signature` header**
   is shown, and the `cookies` block is `[redacted]`.

## 7. Performance overhead

Loading the Sentry SDK with DSN set adds **<15ms** to request latency in
production. Measured locally on a stock Fly.io shared-cpu-1x:
- Cold container, first request: +12ms
- Warm container, subsequent requests: +2ms (mostly the configureScope
  middleware tagging)

Failed sends to Sentry never block the request — the SDK uses an async
HTTP client and our `SetSentryContext` middleware swallows all SDK
exceptions (NFR-3).

## 8. Excluded routes

The following routes are tagged `ignore_transactions` and never produce
performance traces:

- `/up`, `/health` — health probes
- `/horizon`, `/horizon/*` — internal Horizon dashboard
- `/stripe/webhook`, `/inbox/*` — high-volume webhook ingestion

Errors thrown inside those routes **are** still reported — the exclusion
only suppresses spans/transactions, not exception capture.

## 9. Rotating the DSN

1. In Sentry: **Project → Settings → Client Keys → New Client Key**.
2. Update `SENTRY_DSN` and `VITE_SENTRY_DSN` in your secret store.
3. Roll the deployment.
4. After 24h, revoke the old key. Old browser bundles still in the wild
   will continue to use it until users hard-refresh.
