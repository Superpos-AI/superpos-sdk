# TASK-229: novps.io public-api HTTP client

> **NOTE (post-merge):** the legacy S2S surface this task originally
> targeted (`/public-api/*` paths, `x-novps-token` header,
> `private-api.novps.io` host) was retired in favour of the public API.
> The shipped client now talks to `https://api.novps.io` with an
> `Authorization: <nvps_...>` PAT and uses `/apps/*` / `/resources/*`
> paths. The contract requirements below are kept for historical
> context; the runtime now matches the public API. See the NoVPS PAT
> setup runbook for current operator config.

**Status:** pending
**Branch:** `task/229-novps-client-service`
**PR:** —
**Depends on:** TASK-227
**Blocks:** TASK-230, TASK-231, TASK-233, TASK-236, TASK-240, TASK-244
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §5, §7, §8

## Objective

Provide a thin, typed Laravel service that wraps the subset of the novps.io
`/public-api/*` endpoints we consume. All HTTP mechanics (auth header,
base URL, timeout, retry, secret redaction) live here; callers work with
PHP arrays/DTOs only.

## Requirements

### Functional

- [ ] FR-1: `App\Cloud\Services\Novps\NovpsClient` with methods covering
  the operations in the feature doc:
    - `applyApp(string $appName, array $payload): array` →
      `PUT /public-api/apps/{app_name}/apply`
    - `getApp(string $appId): array` →
      `GET /public-api/apps/{app_id}/resources` (+ metadata via `listApps`)
    - `listApps(): array` → `GET /public-api/apps`
    - `exportApp(string $appName, bool $includeSecrets = false): array`
    - `redeploy(string $appId): array` →
      `POST /public-api/apps/{app_id}/deployment`
    - `getDeployment(string $appId, string $deploymentId): array`
    - `deleteApp(string $appId): array`
    - `updateResource(string $resourceId, array $payload): array`
    - `scaleResource(string $resourceId, string $size, int $count): array`
      (convenience over `updateResource`)
    - `deleteResource(string $resourceId): array`
    - `getResourceLogs(string $resourceId, array $query): array` →
      `GET /public-api/resources/{resource_id}/logs`
- [ ] FR-2: Auth via `x-novps-token` header pulled from
  `config('services.novps.api_token')`.
- [ ] FR-3: Base URL from `config('services.novps.base_url')`; timeout from
  `config('services.novps.request_timeout')`.
- [ ] FR-4: Throws `NovpsApiException` (new) on non-2xx with the HTTP
  status, the `detail` field from the body, and the request path. Never
  includes request headers or the api token in the exception message.
- [ ] FR-5: Retries idempotent GET/PUT/DELETE up to 2 times on 5xx and
  on `ConnectionException` with exponential backoff (250ms, 1000ms).
  POST is not retried unless the endpoint is declarative (
  `/apps/{name}/apply` is safe; `/apps/{id}/deployment` is not).
- [ ] FR-6: HTTP client configured with a redacting logging middleware
  that strips `x-novps-token` and any `envs[*].value` before logs are
  emitted.
- [ ] FR-7: Resource-log response is passed through untouched so callers
  can stream Loki-format ranges; the client only validates the envelope.

### Non-Functional

- [ ] NFR-1: Built on Laravel `Http` facade with a named client
  `Http::withOptions(...)->baseUrl(...)` macro registered in
  `NovpsServiceProvider`.
- [ ] NFR-2: No I/O in the constructor; client is a simple pure-config
  singleton bound in the container.
- [ ] NFR-3: `NovpsClient::sanitizeForLog()` is the single authoritative
  sanitization contract — every novps log line (including those emitted
  by the request-pipeline middleware) is routed through it before being
  written. The middleware takes the closure as a required constructor
  argument and both entry-points (`Http::novps()` macro and
  `NovpsClient::pending()`) pass `$client->sanitizeForLog(...)`, so any
  future masking change made in `sanitizeForLog()` applies everywhere.
- [ ] NFR-4: Exceptions do not leak `Authorization` / `x-novps-token`
  headers. Verified by a dedicated test.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Cloud/Services/Novps/NovpsClient.php` | The client |
| Create | `app/Cloud/Services/Novps/NovpsApiException.php` | Typed error |
| Create | `app/Cloud/Services/Novps/Support/SecretRedactor.php` | Log-scrubber |
| Create | `app/Cloud/Providers/NovpsServiceProvider.php` | Binds client, registers macro |
| Modify | `bootstrap/providers.php` | Register provider (cloud only) |
| Modify | `config/services.php` | Add the `novps` block |

### Key Design Decisions

- **Thin wrapper, not a full SDK.** We only call ~10 endpoints. Method names
  mirror the OpenAPI `summary` fields so upgrades are a search-and-replace.
- **Retry policy is per-method.** `apply` (PUT) is declarative → retry.
  `redeploy` (POST) is not → caller must be idempotent at a higher level
  (e.g. dedupe by `novps_deployment_id` captured from the first try).
- **No DTOs for responses.** novps responses are loosely typed and
  upstream-shape changes are more common than field additions — callers
  dereference with `array_get` against documented keys.

## Implementation Plan

1. Add `config/services.php` `novps` block (matches FEATURE doc §4.1).
2. Write `NovpsClient` with the method list above. Each method builds a
   `Http::withHeaders` request and calls `retry()` per the policy in FR-5.
3. Write `SecretRedactor::redact(array $body): array` — deep walks and
   masks any key named `value` under `envs`/`secret_env_vars` paths.
4. Register `NovpsServiceProvider` conditional on
   `apiary.edition === 'cloud'`.
5. Unit-test every method with `Http::fake()`.

## Test Plan

### Unit Tests

- [ ] `applyApp` PUTs to the correct URL with `x-novps-token` header.
- [ ] Non-2xx raises `NovpsApiException` with path + status + detail.
- [ ] Token + env values are absent from exception messages.
- [ ] `SecretRedactor` masks nested env values and top-level secrets.
- [ ] Retry policy: 500 → retried; 400 → not retried.
- [ ] `getResourceLogs` passes through query params verbatim.

### Feature Tests

- [ ] Provider only registers under cloud edition.

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant
- [ ] No credentials logged in plaintext
- [ ] All outbound calls timeout at `config.novps.request_timeout`
