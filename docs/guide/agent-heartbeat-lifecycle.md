# Agent Heartbeat & Lifecycle API

The heartbeat and lifecycle endpoints let agents signal liveness and manage
their operational status. The heartbeat (`POST /api/v1/agents/heartbeat`)
updates the agent's last-seen timestamp and optional runtime metadata. The
status endpoint (`PATCH /api/v1/agents/status`) transitions the agent between
lifecycle states. This page covers both endpoint contracts, stale detection,
status transitions, error handling, activity logging, and configuration.

For registration and token management, see the
[Agent Registration API](./agent-registration-api.md) and
[Agent Authentication](./agent-authentication.md) guides.

## Overview

```text
Agent (external)                      Superpos Platform
────────────────                      ────────────────
  POST /api/v1/agents/heartbeat ──►   AgentLifecycleController::heartbeat()
  {                                     │
    metadata?                           ├─ Validate payload (AgentHeartbeatRequest)
  }                                     ├─ Update last_heartbeat timestamp
                                        ├─ Replace metadata (if provided)
                                        ├─ Log activity (agent.heartbeat)
  ◄── 200 { id, status,               └─ Return updated agent state
             last_heartbeat, metadata }

  PATCH /api/v1/agents/status ────►   AgentLifecycleController::updateStatus()
  {                                     │
    status                              ├─ Validate payload (AgentStatusUpdateRequest)
  }                                     ├─ Compare old → new status
                                        ├─ If changed: update status + timestamps
                                        ├─ If changed: log activity (agent.status_changed)
  ◄── 200 { id, status,               └─ Return updated agent state
             status_changed_at,
             last_heartbeat }
```

**Key guarantees:**

- Both endpoints require a valid Sanctum bearer token (`auth:sanctum-agent`)
- An agent can only update its own heartbeat and status — never another agent's
- Heartbeats are idempotent — repeated calls without metadata simply bump the timestamp
- Same-status transitions are no-ops — no activity log entry, no timestamp change
- Every real state change is recorded in the activity log

## Heartbeat Endpoint

### Heartbeat Request

```http
POST /api/v1/agents/heartbeat
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "metadata": {
    "cpu": 42,
    "memory_mb": 1024,
    "current_task": "01JFZ456DEF789GHI012ABC345"
  }
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `metadata` | object | No | Must be an array/object if provided. Replaces existing metadata entirely. |

The request body can be empty (`{}`) for a simple timestamp-only heartbeat.

### Heartbeat Response

#### 200 OK — Success

```json
{
  "data": {
    "id": "01JFZ123ABC456DEF789GHI012",
    "status": "online",
    "last_heartbeat": "2026-02-24T10:30:45+00:00",
    "metadata": {
      "cpu": 42,
      "memory_mb": 1024,
      "current_task": "01JFZ456DEF789GHI012ABC345"
    }
  },
  "meta": {},
  "errors": null
}
```

#### 422 Unprocessable Entity — Validation Error

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "The metadata field must be an array.",
      "code": "validation_error",
      "field": "metadata"
    }
  ]
}
```

#### 401 Unauthorized — Missing or Invalid Token

Returned when the `Authorization` header is missing or the token is invalid.
The response body follows the standard Laravel 401 format.

### Heartbeat Behavior

1. **Timestamp update** — `last_heartbeat` is set to the current time on every
   call, regardless of whether metadata is provided.
2. **Metadata replacement** — When `metadata` is included, it **replaces** the
   agent's existing metadata entirely (no deep merge). This keeps the contract
   simple: the agent always owns the full metadata snapshot.
3. **Metadata preservation** — When `metadata` is omitted, the existing
   metadata is left untouched. Only the timestamp advances.
4. **Idempotent** — Repeated heartbeat calls are safe. There are no
   side effects beyond advancing the timestamp and (optionally) replacing
   metadata.

::: tip
Send heartbeats on a regular interval (e.g., every 10–30 seconds) to avoid
being marked as stale. The default stale threshold is 60 seconds — see
[Stale Detection](#stale-detection) below.
:::

## Status Endpoint

### Status Request

```http
PATCH /api/v1/agents/status
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "status": "online"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `status` | string | **Yes** | Must be one of: `online`, `busy`, `idle`, `offline`, `error` |

### Status Response

#### 200 OK — Status Changed

```json
{
  "data": {
    "id": "01JFZ123ABC456DEF789GHI012",
    "status": "online",
    "status_changed_at": "2026-02-24T10:30:45+00:00",
    "last_heartbeat": "2026-02-24T10:30:45+00:00"
  },
  "meta": {},
  "errors": null
}
```

#### 200 OK — Same Status (No-Op)

When the new status matches the current status, the response is identical in
shape but no database write or activity log entry occurs. The
`status_changed_at` and `last_heartbeat` values reflect the most recent
*actual* transition, not the current request time.

#### 422 Unprocessable Entity — Invalid Status

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "The selected status is invalid.",
      "code": "validation_error",
      "field": "status"
    }
  ]
}
```

### Status Behavior

1. **No-op on same status** — If the agent is already `online` and sends
   `{ "status": "online" }`, no database write occurs, no activity log is
   created, and the response returns the current state unchanged.
2. **Timestamp updates on transition** — When the status actually changes,
   both `status_changed_at` and `last_heartbeat` are set to the current time.
3. **Activity logging** — A `agent.status_changed` entry is created only when
   the status actually changes (see [Activity Logging](#activity-logging)).
4. **No transition restrictions** — Any valid status can transition to any
   other valid status. There is no enforced state machine graph. This is
   intentional: agents know their own operational state best.

## Lifecycle Statuses

Agents have five lifecycle statuses:

| Status | Meaning | Active? | Can Be Stale? |
|--------|---------|---------|---------------|
| `online` | Running and ready for tasks | Yes | Yes |
| `busy` | Running and currently processing a task | Yes | Yes |
| `idle` | Running but waiting for work | Yes | Yes |
| `offline` | Not running | No | No |
| `error` | Encountered an error condition | No | No |

### Active vs Inactive

The `Agent` model provides two constants and helper methods for status
classification:

```php
Agent::STATUSES        // ['online', 'busy', 'idle', 'offline', 'error']
Agent::ACTIVE_STATUSES // ['online', 'busy', 'idle']

$agent->isOnline()     // true when status === 'online'
$agent->isActive()     // true when status is online, busy, or idle
$agent->isStale()      // true when active but heartbeat has expired
```

**Active** statuses (`online`, `busy`, `idle`) indicate the agent process is
running and expected to send heartbeats. **Inactive** statuses (`offline`,
`error`) indicate the agent is not running — heartbeats are not expected, and
the agent cannot be stale.

### Recommended Status Flow

While transitions are not enforced, the typical agent lifecycle follows this
pattern:

```text
                    ┌─────────┐
        register    │ offline │   (initial status after registration)
        ─────────►  └────┬────┘
                         │
                   status: online
                         │
                    ┌────▼────┐
               ┌───►│ online  │◄───┐
               │    └────┬────┘    │
               │         │         │
          status: idle   │    status: online
               │    status: busy   │
               │         │         │
          ┌────▼────┐  ┌─▼──────┐  │
          │  idle   │  │  busy  ├──┘
          └────┬────┘  └────────┘
               │
          status: offline
               │
          ┌────▼────┐
          │ offline │   (graceful shutdown)
          └─────────┘

  Any status ──► error   (on unrecoverable failure)
```

## Stale Detection

An agent is considered **stale** when it claims to be active but has stopped
sending heartbeats. This helps the platform identify agents that may have
crashed without a graceful shutdown.

### How Stale Detection Works

```php
public function isStale(): bool
{
    // Only active agents can be stale
    if (! $this->isActive()) {
        return false;
    }

    // Active with no heartbeat ever recorded = stale
    if ($this->last_heartbeat === null) {
        return true;
    }

    // Check against configured timeout
    $timeout = config('apiary.agent.heartbeat_timeout', 60);

    return $this->last_heartbeat->diffInSeconds(now()) > $timeout;
}
```

### Stale Detection Rules

| Agent Status | Last Heartbeat | Result |
|-------------|----------------|--------|
| `offline` | Any | Not stale (inactive agents are never stale) |
| `error` | Any | Not stale (inactive agents are never stale) |
| `online` | Never sent | **Stale** (active but never heartbeated) |
| `online` | 30 seconds ago | Not stale (within default 60s timeout) |
| `online` | 90 seconds ago | **Stale** (exceeds 60s timeout) |
| `busy` | 90 seconds ago | **Stale** (busy agents are active) |
| `idle` | 90 seconds ago | **Stale** (idle agents are active) |

### Configuration

The stale timeout is configured in `config/apiary.php`:

```php
'agent' => [
    'heartbeat_timeout' => (int) env('SUPERPOS_AGENT_HEARTBEAT_TIMEOUT', 60),
],
```

Set `SUPERPOS_AGENT_HEARTBEAT_TIMEOUT` in your `.env` to adjust the threshold.
A lower value detects stale agents faster but requires more frequent
heartbeats. A higher value is more tolerant of network hiccups.

| Env Variable | Default | Unit | Description |
|-------------|---------|------|-------------|
| `SUPERPOS_AGENT_HEARTBEAT_TIMEOUT` | `60` | seconds | Time after last heartbeat before an active agent is considered stale |

::: tip
As a rule of thumb, set the heartbeat interval to roughly one-third of the
timeout. With the default 60-second timeout, heartbeat every 15–20 seconds.
:::

## Security and Scope Rules

### Authentication

Both endpoints require a valid Sanctum bearer token via the
`auth:sanctum-agent` middleware:

```http
Authorization: Bearer 1|abc123def456ghi789...
```

The authenticated agent is resolved via `$request->user('sanctum-agent')`.
There is no additional permission check — all authenticated agents can send
heartbeats and update their own status.

### Scope Isolation

An agent can only modify **its own** heartbeat and status. The controller
retrieves the agent from the authentication context, not from a URL parameter:

```php
$agent = $request->user('sanctum-agent');
```

There is no endpoint to update another agent's status. This means:

- Agent A cannot send heartbeats on behalf of Agent B
- An agent in Hive A cannot affect agents in Hive B
- Cross-apiary interference is impossible

### What Is Never Logged

- Bearer token values
- Request headers
- Full request bodies

Only structured event metadata (`metadata_updated`, `old_status`,
`new_status`) appears in the activity log.

## Activity Logging

Every real state change creates an entry in the
activity log. No-op operations (same-status updates,
timestamp-only heartbeats without metadata changes) still log for heartbeats
but skip logging for status no-ops.

### Heartbeat Events

| Action | Trigger | Details |
|--------|---------|---------|
| `agent.heartbeat` | Every heartbeat call | `{ metadata_updated: true }` or `{ metadata_updated: false }` |

### Status Change Events

| Action | Trigger | Details |
|--------|---------|---------|
| `agent.status_changed` | Status actually changes | `{ old_status: "offline", new_status: "online" }` |

Same-status updates produce **no** activity log entry.

### Context Fields

All entries automatically include:

| Field | Source |
|-------|--------|
| `superpos_id` | Resolved from agent's hive |
| `hive_id` | Agent's home hive |
| `agent_id` | Authenticated agent |

The `ActivityLogger` service provides the fluent builder API used internally.

## CE vs Cloud Notes

| Behavior | Community Edition | Cloud Edition |
|----------|-------------------|---------------|
| Heartbeat endpoint | `/api/v1/agents/heartbeat` | `/api/v1/agents/heartbeat` (identical) |
| Status endpoint | `/api/v1/agents/status` | `/api/v1/agents/status` (identical) |
| Superpos context | Always `default` apiary | Resolved from tenant organization |
| Hive isolation | Application-level scoping | DB-level global scopes via `BelongsToHive` trait |
| Stale timeout config | `SUPERPOS_AGENT_HEARTBEAT_TIMEOUT` | Same env variable |
| Activity log scoping | Single apiary, single or few hives | Multi-tenant, per-org filtering |
| API contract | Identical | Identical |

The heartbeat and lifecycle API is **fully portable** between editions. Agents
built for CE work on Cloud without modification. The only difference is
organizational context — CE uses a single default apiary, Cloud resolves the
apiary from the tenant's organization.

## Troubleshooting

### Common Heartbeat Errors

| HTTP Status | Error Code | Cause | Fix |
|-------------|------------|-------|-----|
| 401 | — | Missing or invalid `Authorization` header | Include `Authorization: Bearer <token>` in every request |
| 422 | `validation_error` (field: `metadata`) | `metadata` is not an object/array | Pass metadata as a JSON object, not a string or scalar |

### Common Status Errors

| HTTP Status | Error Code | Cause | Fix |
|-------------|------------|-------|-----|
| 401 | — | Missing or invalid `Authorization` header | Include `Authorization: Bearer <token>` in every request |
| 422 | `validation_error` (field: `status`) | Missing `status` field | Include `{ "status": "..." }` in the request body |
| 422 | `validation_error` (field: `status`) | Invalid status value | Use one of: `online`, `busy`, `idle`, `offline`, `error` |
| 422 | `validation_error` (field: `status`) | Non-string status (e.g., numeric) | Status must be a string |

### Agent Shows as Stale

If your agent appears stale in the dashboard:

1. **Check heartbeat interval** — ensure your agent sends heartbeats more
   frequently than the configured timeout (default 60 seconds)
2. **Check network connectivity** — the agent must be able to reach the Superpos
   API endpoint
3. **Check agent status** — only active agents (`online`, `busy`, `idle`) can
   be stale. If the agent set itself to `offline` or `error`, it will not be
   flagged as stale regardless of heartbeat age
4. **Check timeout config** — verify `SUPERPOS_AGENT_HEARTBEAT_TIMEOUT` in your
   `.env` is set appropriately for your network conditions

### Metadata Not Updating

- **Metadata replaces, not merges** — sending `{ "metadata": { "cpu": 42 } }`
  replaces all existing metadata. To preserve fields, include them all in
  every heartbeat
- **Omitting metadata preserves it** — if you send `{}` (empty body), existing
  metadata is left unchanged

### Status Not Changing

- **Same-status is a no-op** — sending the current status back returns `200`
  but does not update timestamps or create an activity log entry
- **Check the response** — the `status_changed_at` field shows when the last
  *actual* transition occurred

## Testing

The heartbeat and lifecycle API is covered by comprehensive tests in
`tests/Feature/AgentHeartbeatTest.php`. Key test areas:

- **Heartbeat timestamp** — `last_heartbeat` updates on every call
- **Metadata replacement** — new metadata replaces old, omitted metadata is preserved
- **Idempotent heartbeats** — repeated calls without metadata are safe
- **Status transitions** — all five valid statuses are accepted
- **Same-status no-op** — no activity log when status unchanged
- **Validation** — invalid status values, non-array metadata rejected with 422
- **Auth enforcement** — 401 without bearer token
- **Scope isolation** — heartbeat/status only affects authenticated agent
- **Cross-apiary safety** — agents in different apiaries are fully isolated
- **Stale detection** — timeout logic, config override, per-status behavior
- **Model helpers** — `isOnline()`, `isActive()`, `isStale()` correctness
- **Envelope format** — consistent `{ data, meta, errors }` structure

Run the heartbeat and lifecycle tests:

```bash
php artisan test --filter=AgentHeartbeatTest
```

Run the full test suite:

```bash
php artisan test
```

### Example: Python Agent with Heartbeat Loop

```python
import requests
import time

BASE = "https://superpos.example.com/api/v1/agents"
TOKEN = "1|abc123def456ghi789..."
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Set status to online
requests.patch(f"{BASE}/status", json={"status": "online"}, headers=HEADERS)

# Heartbeat loop
while running:
    resp = requests.post(f"{BASE}/heartbeat", json={
        "metadata": {"cpu": get_cpu(), "memory_mb": get_memory()},
    }, headers=HEADERS)
    assert resp.status_code == 200
    time.sleep(15)

# Graceful shutdown
requests.patch(f"{BASE}/status", json={"status": "offline"}, headers=HEADERS)
```

### Example: cURL

```bash
TOKEN="1|abc123..."

# Send heartbeat with metadata
curl -X POST https://superpos.example.com/api/v1/agents/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"cpu": 42, "memory_mb": 1024}}'

# Send heartbeat without metadata (timestamp-only)
curl -X POST https://superpos.example.com/api/v1/agents/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'

# Update status
curl -X PATCH https://superpos.example.com/api/v1/agents/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "online"}'
```

### Writing Feature Tests

To test heartbeat and status in your own code, use Sanctum's `actingAs`
helper:

```php
use App\Models\Agent;
use Laravel\Sanctum\Sanctum;

$agent = Agent::factory()->create(['status' => 'offline']);
Sanctum::actingAs($agent, ['*'], 'sanctum-agent');

// Send heartbeat
$this->postJson('/api/v1/agents/heartbeat', [
    'metadata' => ['cpu' => 42],
])->assertOk()
  ->assertJsonPath('data.metadata.cpu', 42);

// Transition to online
$this->patchJson('/api/v1/agents/status', [
    'status' => 'online',
])->assertOk()
  ->assertJsonPath('data.status', 'online');

// Verify stale detection
$agent->refresh();
$this->assertFalse($agent->isStale()); // just heartbeated
```
