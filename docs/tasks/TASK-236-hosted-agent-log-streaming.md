# TASK-236: Hosted agent log streaming (novps proxy)

**Status:** pending
**Branch:** `task/236-hosted-agent-log-streaming`
**PR:** —
**Depends on:** TASK-229, TASK-230
**Blocks:** TASK-241
**Edition:** cloud
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §8

## Objective

Surface `novps.io` worker logs to the Superpos dashboard via a thin proxy
endpoint. No retention — Superpos fetches on demand and forwards. The
dashboard component renders a live-follow viewer on top.

## Requirements

### Functional

- [ ] FR-1: `GET /api/v1/hives/{hive}/hosted-agents/{id}/logs` proxies to
  `NovpsClient::getResourceLogs($resourceId, $query)`.
- [ ] FR-2: Accepts query params: `start` (ISO-8601, required),
  `end` (ISO-8601, required), `limit` (int ≤ 1000, default 500),
  `direction` (`forward`|`backward`, default `backward`), `search`
  (string), `pod` (string).
- [ ] FR-3: Validates the time window: max 24h span, `start < end`, both
  within the last 30 days.
- [ ] FR-4: Forwards the novps response body verbatim under `data`, adds
  `meta.source = "novps"` and `meta.resource_id`.
- [ ] FR-5: Returns 409 with `reason: "not_deployed"` when the hosted
  agent has no `novps_resource_id` yet.
- [ ] FR-6: Returns 503 with `reason: "upstream_unavailable"` on novps
  5xx or connection error — controller does not re-throw.
- [ ] FR-7: Endpoint is **read-only** — no writes, no activity_log entry.
- [ ] FR-8: Dashboard live-follow support: controller handles
  `Accept: text/event-stream` and streams SSE chunks, re-polling novps
  every 2s with `start` advancing on each chunk.
  (Poll-via-SSE, not upstream streaming — novps does not expose a stream
  endpoint.)

### Non-Functional

- [ ] NFR-1: No logging of response bodies (they contain user code output
  which may include sensitive values printed by their agent).
- [ ] NFR-2: Rate-limited at 60 req/min per user per hosted agent to keep
  novps quota healthy.
- [ ] NFR-3: SSE connections auto-terminate after 10 minutes — dashboard
  reconnects with a new `start`.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Cloud/Http/Controllers/Api/HostedAgentLogController.php` | Proxy |
| Create | `app/Cloud/Http/Requests/HostedAgentLogQueryRequest.php` | Validation |
| Create | `app/Cloud/Services/HostedAgentLogStreamer.php` | SSE loop |
| Modify | `routes/api.php` | Register route |

### Key Design Decisions

- **Polling, not true streaming.** novps exposes range queries, not a
  log-tail endpoint. We poll every 2s, server-side, and push SSE frames.
  Dashboard stays client-unaware.
- **Short window validation.** 24h cap prevents accidental mass-pull
  requests that would hammer novps's Loki backend.
- **No database row per query.** Usage tracking for logs lives in the
  rate limiter; log volume is too high to write per-request rows.

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/hives/{hive}/hosted-agents/{id}/logs` | Range query + SSE follow |

## Test Plan

### Unit Tests

- [ ] Query validator rejects >24h span.
- [ ] Query validator rejects reversed `start`/`end`.
- [ ] 409 when `novps_resource_id` is null.
- [ ] 503 on `NovpsApiException`.
- [ ] Response body is passed through unchanged.

### Feature Tests

- [ ] Authenticated dashboard user can fetch logs.
- [ ] Cross-hive access is blocked.
- [ ] SSE returns chunks and closes after timeout.
- [ ] Rate limit: 61st request in a minute returns 429.

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant
- [ ] No log-body content written to Superpos logs
- [ ] API envelope + error `reason` codes
- [ ] Form Request validation
