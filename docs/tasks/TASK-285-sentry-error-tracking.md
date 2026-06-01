---
name: TASK-285 Sentry error tracking
description: Wire sentry-laravel + @sentry/react for backend and frontend error capture. Cloud-only, env-gated, with secret scrubbing.
type: project
---

# TASK-285: Sentry error tracking

**Status:** pending
**Branch:** `task/285-sentry-error-tracking`
**PR:** —
**Depends on:** —
**Blocks:** Cloud production launch
**Edition:** cloud-only (CE self-hosters don't want their errors shipped to our Sentry)
**Feature doc:** this task.

## Objective

Production Cloud without an error pipe is flying blind. Wire Sentry (backend + frontend), scrub secrets, tag with org/hive/user so errors are actionable. Gate the whole thing behind `SENTRY_DSN` — if the env var is absent, Sentry is fully disabled (no runtime cost — the `@sentry/react` bundle is never loaded or parsed, no failed sends).

## Requirements

### Functional

- [ ] FR-1: Install `sentry/sentry-laravel` (backend) and `@sentry/react` + `@sentry/vite-plugin` (frontend).
- [ ] FR-2: Env-gated — `SENTRY_DSN` empty ⇒ Sentry is not initialized, no client, no middleware overhead. Both backend and frontend honor this.
- [ ] FR-3: Cloud-only — when `config('platform.is_cloud') === false`, Sentry is also disabled regardless of DSN. CE operators may opt in later by flipping the flag themselves.
- [ ] FR-4: Secret scrubbing — beforeSend hook strips:
  - Any key matching `/token|key|secret|password|authorization|bearer|api_key|stripe/i` from request body, query string, cookies, and event extra/contexts.
  - The raw `Stripe-Signature` header from webhook events.
  - Full webhook request bodies for `/stripe/webhook` (Stripe payloads contain customer PII by design — don't relay to Sentry).
  - Any env vars in stack frame vars (Sentry by default includes them; suppress).
- [ ] FR-5: Tagging — every captured event includes:
  - `organization_id` (from `platform.current_org_id` binding if set)
  - `hive_id` (from `platform.current_hive_id`)
  - `user_id` + `user_email` if authenticated
  - `cloud_tenant_id` on Cloud
  - `edition` = `ce|cloud`
  - `release` = the app version / git SHA
- [ ] FR-6: Frontend — `@sentry/react` dynamically imported in `app.jsx` only when DSN present AND `VITE_PLATFORM_EDITION=cloud`. When disabled, the module is never loaded or parsed (no runtime cost). `AppErrorBoundary` wraps the Inertia app with an `onError` callback — Sentry-aware when enabled, no-op when disabled. The boundary itself does NOT import `@sentry/react`.
- [ ] FR-7: Source maps — `@sentry/vite-plugin` uploads source maps at build time (gated on `SENTRY_AUTH_TOKEN` presence; build succeeds without the token, just without sourcemap upload — useful in CI).
- [ ] FR-8: Sample rates — `SENTRY_TRACES_SAMPLE_RATE` default `0.1`, `SENTRY_PROFILES_SAMPLE_RATE` default `0.0`. Errors always captured (`sample_rate = 1.0`).
- [ ] FR-9: Performance — no tracing on webhook endpoints (`/stripe/webhook`, any incoming webhooks route) — they're high-volume and low-value for traces.
- [ ] FR-10: Out-of-box, health-check endpoints are not traced (`/up`, `/health`, `/horizon/*`).

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Loading Sentry client adds <15ms to request latency with DSN set (measure during implementation).
- [ ] NFR-3: Failed Sentry sends never break the application request. Timeouts and errors on the Sentry client are logged-and-swallowed, not thrown.
- [ ] NFR-4: No new PHP tests required beyond "Sentry disabled when DSN missing" smoke test. Heavy integration coverage is pointless — we're just wiring a library.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `composer.json` | Add `sentry/sentry-laravel` |
| Modify | `package.json` | Add `@sentry/react`, `@sentry/vite-plugin` |
| Create | `config/sentry.php` | Standard Sentry config scoped + trimmed |
| Modify | `bootstrap/app.php` or `app/Exceptions/Handler.php` | Register Sentry reportable |
| Create | `app/Sentry/EventScrubber.php` | beforeSend hook |
| Modify | `app/Http/Middleware/SetSentryContext.php` | Tag events with org/hive/user |
| Modify | `resources/js/app.jsx` | Init `@sentry/react` if DSN present |
| Modify | `resources/js/Components/AppErrorBoundary.jsx` | Wrap root, report to Sentry |
| Modify | `vite.config.js` | `@sentry/vite-plugin` gated on env |
| Modify | `.env.example` | Document `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `SENTRY_TRACES_SAMPLE_RATE` |
| Create | `tests/Cloud/Feature/SentryIntegrationTest.php` | DSN absent ⇒ no init; DSN present ⇒ tags applied |
| Create | `docs/ops/sentry-setup.md` | Setup runbook |

### Key Design Decisions

- **DSN-gated everything.** Avoids a second flag. Operator sets DSN ⇒ Sentry on; unsets ⇒ off.
- **Cloud-only.** CE self-hosters shouldn't ship their errors to our central account. They can add their own DSN if they want Sentry.
- **Scrub at the source.** A beforeSend hook that actually strips keys is more reliable than Sentry's server-side inbound filters.
- **No request bodies from webhook routes.** Stripe payloads contain PII. The request URL is enough context; the body isn't worth the exposure.
- **Frontend ErrorBoundary.** React errors that don't reach `window.onerror` are still reported via the boundary.
- **Source map upload is optional.** `SENTRY_AUTH_TOKEN` present ⇒ upload during build. Absent (e.g. in CI) ⇒ skip silently. Don't fail the build on missing token.

## Implementation Plan

1. Composer + npm install. Commit `composer.lock` and `package-lock.json` updates.
2. `config/sentry.php` with DSN + sample-rate env reads, Cloud+DSN gate.
3. Backend: register Sentry in `bootstrap/app.php`, build `EventScrubber` + `SetSentryContext` middleware, wire into the global middleware stack.
4. Frontend: initialize in `app.jsx` before mounting Inertia; wrap with ErrorBoundary; wire vite-plugin for sourcemaps.
5. Write the setup runbook at `docs/ops/sentry-setup.md` (DSN creation, auth token creation, expected error categories, log-link).
6. Smoke test: throw a deliberate exception from an admin-only debug route (gated in local/staging), confirm it arrives in Sentry with all tags and NO secrets.

## Test Plan

- [ ] Unit/Feature: with DSN empty, Sentry client is not initialized; no network calls attempted.
- [ ] Unit/Feature: with DSN set, EventScrubber removes a known secret key from a synthetic event.
- [ ] Unit/Feature: SetSentryContext middleware tags events with org/hive/user when authenticated.
- [ ] Manual: trigger a real 500 in staging, confirm it lands in Sentry with tags and scrubbed payload.

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] `SENTRY_DSN=""` ⇒ everything still works, no errors in logs
- [ ] Source maps uploaded on builds with `SENTRY_AUTH_TOKEN`
- [ ] Webhook payloads NOT visible in Sentry (manual verification in staging)
- [ ] Runbook committed at `docs/ops/sentry-setup.md`

## Notes for Implementer

- `sentry/sentry-laravel` auto-registers an exception handler in Laravel 12. Confirm it doesn't double-report when we also call `report()` manually.
- The `EventScrubber` should be a pure function given the event. Test it with a fixture event.
- `@sentry/vite-plugin` requires `org` and `project` config, not just an auth token. Add those as env keys too (`SENTRY_ORG`, `SENTRY_PROJECT`).
- Profiling (CPU profiles) default off — profiling has measurable overhead. Leave it to the operator to enable via env.
- If the Sentry SDK auto-instruments Laravel queries, DB spans can explode. Cap with `sentry.breadcrumbs.sql_queries = false` unless the operator opts in.
