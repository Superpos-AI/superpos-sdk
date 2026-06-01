# Agent Authentication

Superpos uses [Laravel Sanctum](https://laravel.com/docs/sanctum) to authenticate
agents via API tokens. Every agent registers with a **secret**, receives a
**bearer token**, and includes that token in subsequent API requests. This page
covers the full auth lifecycle, endpoint reference, security model, and
troubleshooting tips.

## Architecture Overview

```text
Agent (external process)              Superpos Platform
─────────────────────────             ──────────────────
                                      ┌──────────────────┐
  1. POST /register ───────────────►  │ AgentAuthController│
     { name, hive_id, secret }        │   register()      │
                                      │                   │
  ◄─── 201 { agent, token } ────────  │  • bcrypt secret  │
                                      │  • Sanctum token  │
  2. GET /me ──────────────────────►  │   me()            │
     Authorization: Bearer <token>    │  • guard: sanctum │
                                      │  • resolve agent  │
  ◄─── 200 { agent data } ──────────  └──────────────────┘
                                               │
  3. Poll /tasks?status=pending ──►            │
     Authorization: Bearer <token>        (hive-scoped)
```

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| Sanctum bearer tokens | Laravel-native, auditable, hashed storage, ability-based scoping |
| Bcrypt for agent secrets | One-way hash; secret never stored in plaintext |
| SHA-256 for bearer tokens | Sanctum default; token in `personal_access_tokens` is a hash |
| No token expiration by default | Agents poll continuously; tokens are revocable on demand |
| Separate `sanctum-agent` guard | Isolates agent auth from dashboard (session) auth |

### Two Layers of Hashing

Superpos stores **three** hashed credentials per agent:

1. **`agents.api_token_hash`** — bcrypt hash of the agent's registration
   **secret**. Used during `/login` to verify identity.
2. **`agents.refresh_token_hash`** — bcrypt hash of the rotating refresh token.
   Used by `/token/refresh` for secret-less token renewal.
3. **`personal_access_tokens.token`** — SHA-256 hash of the Sanctum bearer
   **token**. Used on every authenticated request to resolve the agent.

Neither the secret nor the issued tokens are stored in plaintext.

## Endpoints

All endpoints live under the `/api/v1/agents` prefix.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/register` | None | Create agent and receive access + refresh tokens |
| `POST` | `/login` | None | Authenticate and receive a new access + refresh pair |
| `POST` | `/token/refresh` | None (throttled) | Rotate access token using agent refresh token |
| `POST` | `/logout` | Bearer | Revoke current access token |
| `GET`  | `/me` | Bearer | Return authenticated agent info |

### POST /api/v1/agents/register

Create a new agent in a hive and receive a Sanctum bearer token.

**Request:**

```json
{
  "name": "DeployBot",
  "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
  "secret": "my-secret-at-least-16-chars",
  "type": "deployment",
  "capabilities": ["deploy", "rollback"],
  "metadata": { "version": "1.0" }
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | Yes | max 255 characters |
| `hive_id` | string | Yes | 26-character ULID, must exist in `hives` |
| `secret` | string | Yes | 16–255 characters |
| `type` | string | No | max 100 characters (default: `custom`) |
| `capabilities` | string[] | No | array of strings, each max 255 chars |
| `metadata` | object | No | arbitrary key-value pairs |

**Response — 201 Created:**

```json
{
  "data": {
    "agent": {
      "id": "01JFZ123ABC456DEF789GHI012",
      "name": "DeployBot",
      "type": "deployment",
      "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
      "superpos_id": "01JFQABC01JFQABC01JFQABC01",
      "status": "offline",
      "capabilities": ["deploy", "rollback"]
    },
    "token": "1|abc123def456ghi789...",
    "refresh_token": "rt_..."
  },
  "meta": {},
  "errors": null
}
```

::: tip
Store both `token` and `refresh_token` immediately — each is shown only once.
Superpos stores only hashed values internally.
:::

### POST /api/v1/agents/login

Authenticate with `agent_id` + `secret` and receive a **new** bearer token.
Each login creates an additional token; previous tokens remain valid until
explicitly revoked.

**Request:**

```json
{
  "agent_id": "01JFZ123ABC456DEF789GHI012",
  "secret": "my-secret-at-least-16-chars"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `agent_id` | string | Yes | 26-character ULID |
| `secret` | string | Yes | string |

**Response — 200 OK:**

```json
{
  "data": {
    "agent": {
      "id": "01JFZ123ABC456DEF789GHI012",
      "name": "DeployBot",
      "type": "deployment",
      "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
      "superpos_id": "01JFQABC01JFQABC01JFQABC01",
      "status": "offline"
    },
    "token": "2|xyz789uvw012...",
    "refresh_token": "rt_..."
  },
  "meta": {},
  "errors": null
}
```

**Error — 401 Unauthorized** (bad credentials):

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "Invalid credentials.",
      "code": "auth_failed"
    }
  ]
}
```

### POST /api/v1/agents/token/refresh

Rotate credentials without the shared secret using `agent_id` + `refresh_token`.
Use this path for UI-managed agents where only token credentials are provided.

**Request:**

```json
{
  "agent_id": "01JFZ123ABC456DEF789GHI012",
  "refresh_token": "rt_..."
}
```

**Response — 200 OK:**

```json
{
  "data": {
    "agent": {
      "id": "01JFZ123ABC456DEF789GHI012",
      "name": "DeployBot",
      "type": "deployment",
      "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
      "superpos_id": "01JFQABC01JFQABC01JFQABC01",
      "status": "offline"
    },
    "token": "3|new-access-token...",
    "refresh_token": "rt_new..."
  },
  "meta": {},
  "errors": null
}
```

### GET /api/v1/agents/me

Return profile data for the currently authenticated agent.

**Request:**

```http
GET /api/v1/agents/me
Authorization: Bearer 1|abc123def456ghi789...
```

**Response — 200 OK:**

```json
{
  "data": {
    "id": "01JFZ123ABC456DEF789GHI012",
    "name": "DeployBot",
    "type": "deployment",
    "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
    "superpos_id": "01JFQABC01JFQABC01JFQABC01",
    "status": "offline",
    "capabilities": ["deploy", "rollback"],
    "metadata": { "version": "1.0" },
    "last_heartbeat": "2026-02-24T00:48:22Z"
  },
  "meta": {},
  "errors": null
}
```

### POST /api/v1/agents/logout

Revoke the token used in the current request. Other tokens for the same agent
remain valid.

**Request:**

```http
POST /api/v1/agents/logout
Authorization: Bearer 1|abc123def456ghi789...
```

**Response — 204 No Content** (empty body)

After logout, the revoked token returns `401` on any subsequent request.

## Auth Flow for Polling Agents

Superpos agents **never receive inbound connections** — they poll outbound.
A typical agent lifecycle looks like this:

```text
1. Agent starts up
2. Validate current bearer token (`GET /api/v1/agents/me`)
3. If invalid:
   - `POST /api/v1/agents/token/refresh` (preferred UI-managed path)
   - or `POST /api/v1/agents/login` / `POST /api/v1/agents/register` (secret fallback)
4. Store rotated `token` + `refresh_token`
5. Loop:
     GET  /api/v1/agents/me         (health check / heartbeat)
     GET  /api/v1/tasks?status=pending  (claim work)
     POST /api/v1/tasks/{id}/claim
     ... perform work ...
     PUT  /api/v1/tasks/{id}/result
6. POST /api/v1/agents/logout      (graceful shutdown)
```

### Example: Python Agent Bootstrap

```python
import requests

BASE = "https://superpos.example.com/api/v1/agents"

# First run — register
resp = requests.post(f"{BASE}/register", json={
    "name": "my-agent",
    "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
    "secret": "a-very-strong-secret-here",
})
token = resp.json()["data"]["token"]

# Subsequent requests — use bearer token
headers = {"Authorization": f"Bearer {token}"}
me = requests.get(f"{BASE}/me", headers=headers)
print(me.json()["data"]["name"])  # "my-agent"
```

### Example: cURL

```bash
# Register
curl -X POST https://superpos.example.com/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "shell-agent",
    "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
    "secret": "minimum-sixteen-chars"
  }'

# Use the returned token
TOKEN="1|abc123..."

# Check identity
curl https://superpos.example.com/api/v1/agents/me \
  -H "Authorization: Bearer $TOKEN"

# Logout
curl -X POST https://superpos.example.com/api/v1/agents/logout \
  -H "Authorization: Bearer $TOKEN"
```

## Token Lifecycle

### Creation

Credential pairs (`token` + `refresh_token`) are issued during **register**,
**login**, and **token refresh**. Access tokens can be multiple/parallel;
refresh token is rotated on each issuance and only the latest one remains valid.

### Storage

| What | Where | Hash |
|------|-------|------|
| Agent secret | `agents.api_token_hash` | bcrypt |
| Refresh token | `agents.refresh_token_hash` | bcrypt |
| Bearer token | `personal_access_tokens.token` | SHA-256 |

Plaintext access/refresh tokens are returned exactly once in auth responses.
Superpos never stores or logs them.

### Revocation

- **Single token:** `POST /logout` revokes the token used in the request.
- **All tokens:** Admins can revoke all tokens for an agent via the dashboard or
  by deleting rows from `personal_access_tokens` where `tokenable_id` matches
  the agent's ULID.
- **Immediate effect:** Revoked tokens return `401` on the next request — there
  is no grace period or cache.

### Expiration

By default, Sanctum tokens **do not expire**. This is intentional: agents are
long-running processes that poll continuously. Token validity is managed through
explicit revocation rather than time-based expiry.

To enable expiration, set `expiration` in `config/sanctum.php`:

```php
// Expire tokens after 24 hours (value in minutes)
'expiration' => 1440,
```

## Guard and Provider Configuration

Superpos defines a dedicated Sanctum guard for agents, separate from the
dashboard's session-based web guard.

**config/auth.php:**

```php
'guards' => [
    'web' => [
        'driver' => 'session',
        'provider' => 'users',
    ],
    'sanctum-agent' => [
        'driver' => 'sanctum',
        'provider' => 'agents',
    ],
],

'providers' => [
    'users' => [
        'driver' => 'eloquent',
        'model' => App\Models\User::class,
    ],
    'agents' => [
        'driver' => 'eloquent',
        'model' => App\Models\Agent::class,
    ],
],
```

Protected agent routes use the `auth:sanctum-agent` middleware:

```php
Route::prefix('v1/agents')
    ->middleware('auth:sanctum-agent')
    ->group(function () {
        Route::post('/logout', [AgentAuthController::class, 'logout']);
        Route::get('/me', [AgentAuthController::class, 'me']);
    });
```

The `Agent` model implements `Authenticatable` and uses the `HasApiTokens`
trait from Sanctum, enabling it to create and manage its own tokens.

## CE vs Cloud Behavior

| Aspect | Community Edition | Cloud Edition |
|--------|-------------------|---------------|
| Superpos | Single `default` apiary | Multi-tenant, per-org apiaries |
| Hive scoping | All agents in `default` hive (or explicitly created hives) | Agents scoped to tenant's hives |
| Token isolation | Tokens belong to one agent | Same — tokens belong to one agent |
| Registration | Open (no invite required) | May require org-level invitation (future) |
| Dashboard auth | Session-based (web guard) | Session-based (web guard) |
| Agent auth | Sanctum bearer tokens | Sanctum bearer tokens |

The agent authentication API is **identical** in both editions. The only
difference is the organizational context: CE resolves to a single default
apiary, while Cloud scopes agents to the tenant's apiary.

## Activity Logging

Every authentication event is recorded in the
activity log:

| Action | Logged On | Details |
|--------|-----------|---------|
| `agent.registered` | Register | `{ token_name: "agent-api" }` |
| `agent.login` | Login | `{ token_name: "agent-api" }` |
| `agent.logout` | Logout | `{ token_id: <int> }` |

All entries include `superpos_id`, `hive_id`, and `agent_id` context for
audit filtering.

## Common Pitfalls and Troubleshooting

### 401 Unauthorized on /me or /logout

| Cause | Fix |
|-------|-----|
| Missing `Authorization` header | Add `Authorization: Bearer <token>` to every request |
| Malformed header | Ensure format is exactly `Bearer <token>` (capital B, single space) |
| Token was revoked (logout) | Call `/login` again to obtain a new token |
| Token does not exist in DB | Re-register or re-login; the token may have been manually deleted |
| Wrong guard middleware | Ensure route uses `auth:sanctum-agent`, not `auth:sanctum` |

### 401 on /login — "Invalid credentials"

| Cause | Fix |
|-------|-----|
| Wrong `agent_id` | Verify the ULID is exactly 26 characters and matches the registered agent |
| Wrong `secret` | The secret must match what was provided at registration (case-sensitive) |
| Agent was deleted | Re-register the agent |

### 403 Forbidden

A `403` means the agent authenticated successfully but lacks permission for the
requested action. This is enforced by the policy engine, not by auth. Check:

- Agent permissions in the dashboard
- Hive-scoping — the agent may be in a different hive than the resource
- Cross-hive permissions if accessing resources outside the agent's home hive

### 422 Validation Errors

Registration returns `422` when request data fails validation:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    { "message": "The name field is required.", "code": "validation_error", "field": "name" },
    { "message": "The secret field must be at least 16 characters.", "code": "validation_error", "field": "secret" }
  ]
}
```

Common validation issues:

| Field | Rule | Common Mistake |
|-------|------|----------------|
| `name` | required, max 255 | Empty or missing |
| `hive_id` | 26-char ULID, must exist | Wrong length, non-existent hive |
| `secret` | min 16 characters | Too short — use a strong passphrase or generated key |

### Tokens Shown Only Once

Plaintext `token` and `refresh_token` values are returned **only** in auth
responses. If lost, call `/login` (or re-connect via dashboard) to mint a new
pair. Previous access tokens remain valid until revoked.

### Multiple Access Tokens per Agent

Each `/login` call creates a **new** access token without revoking previous
ones. This allows parallel agent instances to hold independent access tokens.
To clean up stale tokens, revoke them via `/logout` or the admin dashboard.

Refresh tokens are different: only the latest refresh token is valid for an
agent, and it rotates whenever a new auth pair is issued.

## Testing and Validation

The test suite for agent authentication is in
`tests/Feature/AgentAuthTest.php`. It covers:

- **Registration flow** — agent creation, auth pair issuance, hashed storage
- **Login flow** — credential verification, new auth pair per login
- **Refresh flow** — token renewal with `agent_id` + `refresh_token`
- **Protected endpoints** — 401 without token, 401 with invalid token
- **Logout and revocation** — token invalidation, isolation between tokens
- **Activity logging** — correct action strings and metadata
- **Response format** — API envelope structure (`{ data, meta, errors }`)
- **Security** — secret bcrypt-hashed in DB, token SHA-256-hashed in DB

Run the auth tests:

```bash
php artisan test --filter=AgentAuthTest
```

Run the full test suite:

```bash
php artisan test
```

### Writing Tests for Authenticated Agent Requests

When writing feature tests that require an authenticated agent, use Sanctum's
`actingAs` helper:

```php
use Laravel\Sanctum\Sanctum;

// Create and authenticate an agent
$agent = Agent::factory()->create();
Sanctum::actingAs($agent, ['*'], 'sanctum-agent');

// Now make authenticated requests
$response = $this->getJson('/api/v1/agents/me');
$response->assertOk();
```

Alternatively, register an agent via the API and use the returned token:

```php
$response = $this->postJson('/api/v1/agents/register', [
    'name' => 'TestBot',
    'hive_id' => $hive->id,
    'secret' => 'test-secret-minimum-16',
]);

$token = $response->json('data.token');

$this->getJson('/api/v1/agents/me', [
    'Authorization' => "Bearer {$token}",
])->assertOk();
```
