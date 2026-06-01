# TASK-121 — Sentry Connector

**Status:** Pending
**Branch:** `task/121-sentry-connector`
**PR:** —
**Depends On:** TASK-038 (Connector Interface + Base Class)
**Blocks:** —
**Edition Scope:** `shared`

---

## Objective

Implement a concrete `SentryConnector` class that extends `BaseConnector`, providing Sentry webhook signature validation (HMAC-SHA256 with secret), webhook parsing for Sentry issue/event alerts, and `auth_config` validation rules for Sentry service connections. This enables Superpos hives to receive Sentry alerts as tasks and route error events to agents for automated triage, alerting, or remediation.

## Architecture Fit

### How It Fits the Existing Platform

Sentry follows the same connector pattern established by GitHub (TASK-039), Slack (TASK-040), and Gmail connectors:

1. **Connector class** — `SentryConnector` extends `BaseConnector` (implements `ConnectorInterface`)
2. **Webhook receiver** — Reuses existing `WebhookReceiverController` (TASK-057) for inbound delivery
3. **Webhook routes** — Existing `webhook_routes` table + `WebhookRouteEvaluator` (TASK-058) maps Sentry events → tasks
4. **Service connections** — Stored in `service_connections` table with encrypted `auth_config`
5. **Policy engine** — Existing `PolicyEngine` (TASK-044) governs what agents can do with Sentry data
6. **Seeder registration** — Registered in `connectors` table via seeder, same as GitHub/Slack

No new tables, controllers, or middleware required. The connector plugs directly into the existing webhook + service proxy infrastructure.

### Connector Hierarchy

```
ConnectorInterface
  └── BaseConnector (abstract)
        ├── GitHubConnector   ✅ (TASK-039)
        ├── SlackConnector    ✅ (TASK-040)
        ├── CustomConnector   ✅ (TASK-041)
        ├── GmailConnector    ✅
        └── SentryConnector   ← NEW (TASK-121)
```

## API Surface Proposal

### 1. SentryConnector (`app/Connectors/SentryConnector.php`)

- Extends `BaseConnector`
- `type()` returns `'sentry'`
- `name()` returns `'Sentry'`
- `supportsWebhooks()` inherits default `true` from `BaseConnector`

### 2. Webhook Validation (`validateWebhook`)

Sentry signs webhook payloads using HMAC-SHA256.

- Validates `sentry-hook-signature` header using HMAC-SHA256
- Secret sourced from `ServiceConnection->auth_config['client_secret']`
- Constant-time comparison via `hash_equals()`
- Returns `false` when:
  - `sentry-hook-signature` header is missing
  - `client_secret` is missing from `auth_config`
  - Signature mismatch

**Reference:** Sentry webhook signature verification uses `HMAC-SHA256(client_secret, request_body)` and sends the hex digest in the `sentry-hook-signature` header.

### 3. Webhook Parsing (`parseWebhook`)

Sentry sends different webhook resource types (issue, event, metric_alert, comment, etc.) via the `sentry-hook-resource` header, with the action in `sentry-hook-action`.

- Reads `sentry-hook-resource` header for resource type (e.g., `issue`, `event`, `metric_alert`)
- Reads `sentry-hook-action` header for action (e.g., `created`, `resolved`, `assigned`)
- Normalizes into dot-notation: `{resource}.{action}` (e.g., `issue.created`, `metric_alert.critical`)
- Returns `['event' => string, 'payload' => array]` per interface contract
- Extracts common fields into payload:
  - `project` — project slug/name from body
  - `level` — severity level (fatal, error, warning, info)
  - `title` — issue/event title
  - `url` — link back to Sentry issue
  - `culprit` — the originating code location (if present)
  - `environment` — environment tag (production, staging, etc.)
- Falls back gracefully when optional fields are missing
- Defaults to `event => 'unknown'` when resource header is absent

### 4. Configuration Rules (`configurationRules`)

- `configurationRules()` returns Laravel validation rules for:
  - `client_secret` — required string (Sentry integration client secret, for webhook signature verification)
  - `dsn` — nullable string (Sentry DSN for outbound error reporting, if proxy use is needed)
  - `auth_token` — nullable string (Sentry API token for outbound API calls via proxy)
  - `organization_slug` — nullable string (Sentry org slug for API calls)

### 5. Seeder Registration

- Register `SentryConnector` as a built-in connector in the `connectors` table seeder
- Type: `sentry`, name: `Sentry`, built-in: `true`, class: `App\Connectors\SentryConnector`

## Auth / Policy / Security Model

### Authentication Flow

1. **Inbound webhooks:** Validated via HMAC-SHA256 signature using the `client_secret` stored in `auth_config`. No bearer tokens or API keys exposed to agents.
2. **Outbound proxy:** If agents need to call Sentry API (e.g., resolve an issue), the `auth_token` in `auth_config` is used by the service proxy (`ServiceProxyController`, TASK-042). Agents never see the token directly.
3. **Credentials storage:** All `auth_config` fields encrypted at rest via Laravel `Crypt` (existing `CredentialVault` from TASK-037).

### Policy Enforcement

Existing `ActionPolicy` rules (TASK-043/044) apply:

- Policies can restrict which agents may receive Sentry webhook tasks
- Policies can restrict which Sentry API endpoints agents may call via proxy
- `require_approval` policy can gate destructive actions (e.g., `resolve`, `delete`, `merge` operations)
- Example policy rules:
  - `allow` — agent `sentry-triage` can `POST /api/0/issues/{id}/` (to assign/resolve)
  - `deny` — agent `sentry-triage` cannot `DELETE /api/0/issues/{id}/`
  - `require_approval` — agent can merge issues only with human approval

### Security Considerations

- **Replay attacks:** Sentry does not include a timestamp header like Slack. Mitigation: rely on idempotency keys (TASK-076) at the webhook route level to prevent duplicate processing. Consider adding a configurable max-age window if Sentry adds timestamp support in the future.
- **Secret rotation:** Rotating `client_secret` requires updating the `auth_config` on the service connection. During rotation, the old secret should be removed promptly. (No grace period mechanism — Sentry regenerates the secret atomically.)
- **IP allowlist:** Not enforced at connector level. Can be layered via Inbox security (TASK-089) once available, or via infrastructure-level firewall rules.
- **Payload size:** Sentry event payloads can be large (stack traces, breadcrumbs). The webhook receiver already handles this via Laravel's request size limits. No connector-level changes needed.

## Requirements

### Functional

- [ ] FR-1: `SentryConnector` extends `BaseConnector` with type `sentry` and name `Sentry`
- [ ] FR-2: `validateWebhook` verifies HMAC-SHA256 signature from `sentry-hook-signature` header
- [ ] FR-3: `parseWebhook` normalizes `sentry-hook-resource` + `sentry-hook-action` into dot-notation event string
- [ ] FR-4: `parseWebhook` extracts `project`, `level`, `title`, `url`, `culprit`, `environment` into payload
- [ ] FR-5: `configurationRules` validates `client_secret` (required), `dsn`, `auth_token`, `organization_slug` (nullable)
- [ ] FR-6: Seeder registers Sentry as a built-in connector

### Non-Functional

- [ ] NFR-1: Constant-time signature comparison (`hash_equals`)
- [ ] NFR-2: No credentials logged in plaintext
- [ ] NFR-3: Graceful fallback on missing optional headers/fields
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Connectors/SentryConnector.php` | Connector implementation |
| Create | `tests/Unit/SentryConnectorTest.php` | Unit tests |
| Modify | `database/seeders/ConnectorSeeder.php` | Register built-in Sentry connector |

### Key Design Decisions

- **Same pattern as GitHub/Slack** — No architectural novelty. Follows established connector contract exactly.
- **No custom middleware** — Sentry webhooks are handled by the existing `WebhookReceiverController`.
- **Client secret for HMAC** — Sentry uses the integration's `client_secret` (not a separate webhook secret), so the field name reflects Sentry's terminology.
- **Dot-notation events** — `issue.created`, `event.created`, `metric_alert.critical` etc. align with the webhook route filter system.
- **No timestamp replay protection** — Unlike Slack, Sentry doesn't provide a request timestamp header. Mitigated by idempotency keys at the webhook route layer.

## Implementation Plan

1. Create `SentryConnector` class extending `BaseConnector`
2. Implement `type()`, `name()` methods
3. Implement `validateWebhook()` with HMAC-SHA256 verification
4. Implement `parseWebhook()` with resource/action normalization and field extraction
5. Implement `configurationRules()` with validation rules
6. Update `ConnectorSeeder` to register Sentry connector
7. Write comprehensive unit tests
8. Verify full test suite passes

## Test Plan

### Unit Tests (`tests/Unit/SentryConnectorTest.php`)

- [ ] `type()` returns `'sentry'`
- [ ] `name()` returns `'Sentry'`
- [ ] `supportsWebhooks()` returns `true`
- [ ] `configurationRules()` returns expected validation shape (client_secret required, dsn/auth_token/organization_slug nullable)
- [ ] Webhook validation: valid HMAC-SHA256 signature → `true`
- [ ] Webhook validation: invalid signature → `false`
- [ ] Webhook validation: missing `sentry-hook-signature` header → `false`
- [ ] Webhook validation: missing `client_secret` in auth_config → `false`
- [ ] Webhook parsing: `issue.created` event with full payload
- [ ] Webhook parsing: `event.created` event with error data
- [ ] Webhook parsing: `metric_alert.critical` event
- [ ] Webhook parsing: missing resource header defaults to `'unknown'`
- [ ] Webhook parsing: missing action header → resource-only event string
- [ ] Webhook parsing: extracts project, level, title, url, culprit, environment
- [ ] Webhook parsing: missing optional fields handled gracefully (no exceptions)
- [ ] Webhook parsing: preserves full body in payload

### Feature / Integration Tests

- [ ] Sentry webhook delivered via `WebhookReceiverController` → task created (end-to-end with webhook route)
- [ ] Policy engine denies agent access to Sentry proxy endpoint → 403

## Risks & Open Questions

### Risks

1. **Sentry webhook format changes** — Sentry occasionally updates their webhook payload structure. Mitigation: parse defensively with optional field fallbacks; pin to current documented format.
2. **Large payloads** — Sentry error events can include full stack traces and breadcrumb trails. Mitigation: existing Laravel request size limits apply; no connector-level truncation needed unless performance issues arise.
3. **No replay protection** — Sentry lacks a timestamp header. Mitigation: idempotency keys (TASK-076) prevent duplicate task creation. Acceptable trade-off given Sentry's delivery model.

### Open Questions

1. **Sentry integration type** — Should this target Sentry's Internal Integration (org-level) or Public Integration (installable app)? Internal is simpler and sufficient for self-hosted Superpos; Public would be needed for a marketplace listing. **Recommendation:** Start with Internal Integration support; Public can be added later.
2. **Metric alert payload structure** — Sentry metric alerts have a different payload shape than issue alerts. Should both be supported from day one, or should metric alerts be a follow-up? **Recommendation:** Support both; the parsing is straightforward with header-based routing.
3. **Outbound Sentry API scope** — Which Sentry API operations should agents be able to call via proxy? (e.g., resolve issue, assign issue, add comment). **Recommendation:** No restrictions at connector level — let action policies govern what's allowed per agent.
4. **Installation guide** — Should the task include a docs page for setting up the Sentry integration in Superpos? **Recommendation:** Defer to a separate documentation task.

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on state changes (N/A — connector is stateless)
- [ ] API responses use `{ data, meta, errors }` envelope (N/A — no new endpoints)
- [ ] Form Request validation on all inputs (N/A — no new endpoints)
- [ ] ULIDs for primary keys (N/A — no new tables)
- [ ] BelongsToApiary/BelongsToHive traits applied where needed (N/A)
- [ ] No credentials logged in plaintext
