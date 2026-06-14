# Agent Registration API

The agent registration endpoint (`POST /api/v1/agents/register`) is the entry
point for every agent joining an Superpos hive. It validates the payload, enforces
hive and apiary scoping, creates the agent record, and returns a one-time bearer
token. This page covers the full registration contract — request/response
schemas, scope safety, duplicate handling, migration notes, and security model.

For the broader auth lifecycle (login, logout, token management), see the
[Agent Authentication](./agent-authentication.md) guide.

## Overview

```text
Agent (external)                      Superpos Platform
────────────────                      ────────────────
  POST /api/v1/agents/register ──►    AgentAuthController::register()
  {                                     │
    name, hive_id, secret,              ├─ Validate payload (AgentRegisterRequest)
    registration_token,                   ├─ Verify registration_token (hive-scoped)
    superpos_id?, type?,                  ├─ Resolve hive
    capabilities?, metadata?            ├─ Scope safety check (superpos_id ↔ hive)
  }                                     ├─ Create agent (bcrypt secret)
                                        ├─ Grant token / hive default permissions
                                        ├─ Create Sanctum token
                                        ├─ Log activity (agent.registered)
  ◄── 201 { agent, token }             └─ Return one-time token
```

**Key guarantees:**

- Agent names are unique per hive (validated + DB-enforced)
- The bearer token is returned exactly once — store it immediately
- The agent secret is bcrypt-hashed — never stored or returned in plaintext
- Every registration is recorded in the activity log
- Scope mismatches are rejected before any data is written

## Request Schema

```http
POST /api/v1/agents/register
Content-Type: application/json
```

```json
{
  "name": "DeployBot",
  "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
  "secret": "my-secret-at-least-16-chars",
  "registration_token": "srt_aBcD1234...",
  "superpos_id": "01JFQABC01JFQABC01JFQABC01",
  "type": "deployment",
  "capabilities": ["deploy", "rollback"],
  "metadata": { "version": "2.1" }
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | **Yes** | Max 255 characters. Must be unique within the target hive. |
| `hive_id` | string | **Yes** | 26-character ULID. Must reference an existing hive. |
| `secret` | string | **Yes** | 16–255 characters. Hashed with bcrypt before storage. |
| `registration_token` | string | **Yes\*** | One-time `srt_…` plaintext minted by a hive operator. Required by default (`platform.agent_registration.require_token`, default on). Validated against the target hive — see [Registration Tokens](#registration-tokens) for the `422` rejection reasons. Becomes optional only when `require_token` is disabled. |
| `superpos_id` | string | No | 26-character ULID. If provided, must match the hive's owning apiary. |
| `type` | string | No | Max 100 characters. Defaults to `custom`. |
| `capabilities` | string[] | No | Array of strings, each max 255 characters. |
| `metadata` | object | No | Arbitrary key-value pairs stored as JSONB. |

\* `registration_token` is required whenever the hive gates registration with a
token, which is the **default**. See [Registration Tokens](#registration-tokens).

## Registration Tokens

By default the platform gates open registration: every `register` call must
carry a valid `registration_token` for the target hive
(`platform.agent_registration.require_token`, default **on**). This lets
operators decide exactly which agents may join a hive and what permissions they
start with.

### How operators mint tokens

Operators mint registration tokens from the dashboard using the web-session
endpoints (admin/member "manage" access required):

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agents-registration-tokens` | Mint a token. Returns the token row **plus** the one-time plaintext `token` (`srt_…`). |
| `GET`  | `/agents-registration-tokens` | List tokens (the plaintext is never re-exposed). |
| `DELETE` | `/agents-registration-tokens/{id}` | Revoke a token. |

The mint endpoint accepts the following optional body fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Human-readable label for the token. |
| `max_uses` | int (1–1000) | `1` | How many agents may register with this token. |
| `expires_in_days` | int (1–365) | config `token_ttl_days` (default 7) | Lifetime before the token expires. |
| `permissions` | string[] | hive defaults | Subset of the permission catalog to grant agents that register with this token. Omit to grant the hive's default permission set. |

The plaintext `srt_…` value is shown **exactly once** at mint time — store it
immediately and hand it to the agent operator. Superpos keeps only a hash.

### Permissions granted on registration

When `require_token` is on (the default), an agent that registers with a valid
token is **immediately usable**: it is granted either the token's explicit
`permissions` list (an empty list grants nothing; an unset list falls back to
the hive defaults) or, when the token carries no list, the hive's
`default_permissions`. The default set is configured at
`platform.agent_registration.default_permissions` and currently grants:

```text
tasks:claim, tasks:read, tasks:update, tasks:create,
knowledge:read, knowledge:write,
events:publish, events:poll,
issues:read, issues:manage,
workflows:read, workflows:run,
agents:read, schedules:read
```

An admin can adjust an agent's permissions afterward via the dashboard.

When `require_token` is **disabled** (legacy open-registration mode), the
`registration_token` field is optional and **no** permissions are auto-granted —
an administrator must grant them before the agent can use privileged endpoints.

### 422 — Invalid Registration Token

When `require_token` is on and the supplied token cannot be used, the endpoint
returns a field-level `422` on `registration_token`. The message identifies the
reason:

| Reason | Message |
|--------|---------|
| Unknown / malformed token | `The registration token is invalid.` |
| Token belongs to a different hive | `The registration token is not valid for this hive.` |
| Token revoked, expired, or exhausted (`max_uses` reached) | Reported as an invalid registration token for the hive. |

## Response Schema

### 201 Created — Success

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
      "capabilities": ["deploy", "rollback"],
      "metadata": { "version": "2.1" }
    },
    "token": "1|GkevWP2jV3XxwLe9Zm5nQrStUvWxYzAbCdEfGhIjKlMnOpQr"
  },
  "meta": {},
  "errors": null
}
```

::: tip
The `token` value is shown **only once**. Store it immediately in your agent's
configuration. Superpos stores only a SHA-256 hash internally. If you lose the
token, call `/login` with the agent's `id` and `secret` to obtain a new one.
:::

The `superpos_id` in the response is always derived from the hive — you do not
need to supply it. It is included so agents know their full organizational
context.

### 422 Unprocessable Entity — Validation Error

All validation failures return the standard API envelope with field-level errors:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "The name field is required.",
      "code": "validation_error",
      "field": "name"
    },
    {
      "message": "The secret field must be at least 16 characters.",
      "code": "validation_error",
      "field": "secret"
    }
  ]
}
```

Each error includes:

| Key | Description |
|-----|-------------|
| `message` | Human-readable description of the failure |
| `code` | Machine-readable error code (always `validation_error` for field errors) |
| `field` | The request field that failed validation (omitted for non-field errors) |

### 422 — Scope Mismatch

If `superpos_id` is provided but does not match the hive's owning apiary:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "The provided superpos_id does not match the hive's apiary.",
      "code": "scope_mismatch"
    }
  ]
}
```

This is a scope safety check, not a field validation error, so the `field` key
is absent.

### 422 — Duplicate Name

If an agent with the same name already exists in the target hive:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "An agent with this name already exists in the specified hive.",
      "code": "validation_error",
      "field": "name"
    }
  ]
}
```

This error is returned regardless of whether the duplicate was caught by form
validation or the database unique constraint (see
[Duplicate Handling](#duplicate-handling) below).

## Scope Safety

Superpos enforces a strict two-level hierarchy: **Superpos** (organization) →
**Hive** (project). Every agent belongs to exactly one hive, and every hive
belongs to exactly one apiary. The registration endpoint enforces this at
multiple levels.

### How `hive_id` Works

The `hive_id` field is **required**. The endpoint resolves the hive and
automatically derives the `superpos_id` from it:

```text
Agent sends: { hive_id: "01ABC..." }
Platform:    hive = Hive::find("01ABC...")
             agent.superpos_id = hive.superpos_id   ← auto-derived
```

You never need to send `superpos_id` for correct scoping — the hive already
implies it.

### Optional `superpos_id` — Explicit Verification

The optional `superpos_id` field exists for **safety verification**. If your agent
knows which apiary it belongs to, include it to catch configuration errors
(e.g., a hive ID that points to a different organization):

```text
Agent sends: { hive_id: "01ABC...", superpos_id: "01XYZ..." }
Platform:    hive = Hive::find("01ABC...")
             if hive.superpos_id ≠ "01XYZ..."  →  422 scope_mismatch
```

If `superpos_id` is omitted, no mismatch check is performed — the hive's apiary
is accepted as-is.

### CE vs Cloud Scoping

| Aspect | Community Edition | Cloud Edition |
|--------|-------------------|---------------|
| Apiaries | Single `default` apiary | Multiple apiaries (one per org) |
| Hives | User-created hives within `default` apiary | Hives scoped to tenant's apiary |
| `superpos_id` param | Optional but always matches `default` | Useful for multi-org safety checks |
| Global scopes | No runtime filtering (single tenant) | `BelongsToHive` trait adds hive-level filtering |
| Registration API | Identical contract | Identical contract |

The registration endpoint behaves identically in both editions. The only
difference is the organizational context the hive resolves to.

## Duplicate Handling

Agent name uniqueness is enforced per hive through **two layers**:

### Layer 1 — Form Validation

The `AgentRegisterRequest` form request checks for existing agents with the same
`(hive_id, name)` pair before the controller runs:

```php
'name' => [
    'required', 'string', 'max:255',
    Rule::unique('agents')->where('hive_id', $this->hive_id),
],
```

If a duplicate is found, the request is rejected with a `422` validation error
before any database write occurs.

### Layer 2 — Database Unique Constraint

A composite unique index on `(hive_id, name)` in the `agents` table acts as
the ultimate safety net:

```sql
CREATE UNIQUE INDEX agents_hive_id_name_unique
    ON agents (hive_id, name);
```

If two concurrent registration requests pass form validation simultaneously
(a race condition), the second `INSERT` hits the unique constraint. The
controller catches this `UniqueConstraintViolationException` and returns the
same `422` error as form validation — the client sees identical behavior
regardless of which layer caught the duplicate:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    {
      "message": "An agent with this name already exists in the specified hive.",
      "code": "validation_error",
      "field": "name"
    }
  ]
}
```

### Cross-Hive Names

Agent names only need to be unique **within a hive**. The same name can exist in
different hives:

```text
Hive A: "DeployBot" ✓
Hive B: "DeployBot" ✓     ← different hive, no conflict
Hive A: "DeployBot" ✗     ← same hive, duplicate rejected
```

## Migration Safety

The unique constraint was added in migration
`2026_02_24_010000_add_unique_agent_name_per_hive`. This migration safely
handles pre-existing data that may violate the new constraint.

### Deduplication Strategy

Before adding the unique index, the migration scans for duplicate
`(hive_id, name)` pairs and renames collisions:

1. **Group** agents by `(hive_id, name)` where `count > 1`
2. **Keep** the oldest agent (lowest ULID) with its original name
3. **Rename** subsequent agents to `{name}-dup-{N}` (e.g., `DeployBot-dup-1`)
4. **Increment** the suffix if the generated name is already taken

### Collision-Safe Suffixing

The suffix generator checks for existing names to avoid creating new collisions:

```text
Original:  "DeployBot", "DeployBot"  (duplicates)
Step 1:    Keep first "DeployBot"
Step 2:    Rename second → "DeployBot-dup-1"
           If "DeployBot-dup-1" exists → try "DeployBot-dup-2"
           Continue until an unused suffix is found
```

### UTF-8-Safe Truncation

Agent names have a 255-character limit. When a long name needs a `-dup-{N}`
suffix, the migration uses `mb_substr()` for UTF-8-safe truncation:

```text
Name:      "あいうえお..." (253 multibyte characters)
Suffix:    "-dup-1" (6 characters)
Truncated: mb_substr(name, 0, 249) . "-dup-1"  ← stays within 255 limit
```

This ensures multibyte characters are never split mid-codepoint.

### Rollback

The migration's `down()` method drops the unique index, restoring the previous
schema. Dedup renames are **not** reversed — the renamed agents keep their new
names. This is intentional: re-introducing duplicates would violate the
application's uniqueness assumptions.

## Security and Logging

### One-Time Secrets

Two values are hashed and never returned after creation:

| Value | Storage | Hash Algorithm | Returned |
|-------|---------|---------------|----------|
| Agent secret | `agents.api_token_hash` | bcrypt | Never (only sent once at registration) |
| Bearer token | `personal_access_tokens.token` | SHA-256 | Once in the `201` response |

The plaintext secret is provided by the agent at registration time and is
**never echoed back** in any response. The bearer token is returned exactly once
in the registration response.

### Activity Logging

Every registration writes an entry to the activity log:

| Action | Details |
|--------|---------|
| `agent.registered` | `{ token_name: "agent-api", agent_name: "DeployBot", agent_type: "deployment" }` |

The log entry includes full context: `superpos_id`, `hive_id`, and `agent_id`.
This provides a complete audit trail of which agents were registered, when, and
in which organizational scope.

### What Is Never Logged

- The agent's plaintext secret
- The bearer token value
- Request bodies containing secrets

## CE vs Cloud Notes

| Behavior | Community Edition | Cloud Edition |
|----------|-------------------|---------------|
| Superpos context | Always `default` | Resolved from tenant org |
| Hive isolation | Application-level scoping | DB-level global scopes via `BelongsToHive` trait |
| `superpos_id` verification | Works but trivial (single apiary) | Guards against cross-org misconfiguration |
| Agent name uniqueness | Per hive | Per hive (same constraint) |
| Registration endpoint | `/api/v1/agents/register` | `/api/v1/agents/register` (identical) |
| Token issuance | Sanctum bearer token | Sanctum bearer token (identical) |

The registration API contract is **fully portable** between editions. Agents
built for CE work on Cloud without modification. The only difference is
organizational context — CE has a single default apiary, Cloud resolves the
apiary from the tenant's organization.

## Troubleshooting

### Common Registration Errors

| HTTP Status | Error Code | Cause | Fix |
|-------------|------------|-------|-----|
| 422 | `validation_error` (field: `name`) | Name missing or duplicate in hive | Choose a unique name within the target hive |
| 422 | `validation_error` (field: `hive_id`) | Invalid ULID or hive does not exist | Verify the hive ID is a valid 26-character ULID and exists |
| 422 | `validation_error` (field: `secret`) | Secret shorter than 16 characters | Use a strong passphrase or generated key (16+ chars) |
| 422 | `validation_error` (field: `registration_token`) | Token missing, invalid, wrong hive, revoked, expired, or exhausted | Mint a fresh token for the target hive (see [Registration Tokens](#registration-tokens)); disable `require_token` only for open registration |
| 422 | `scope_mismatch` | `superpos_id` does not match hive's apiary | Omit `superpos_id` or correct it to match the hive's owning apiary |
| 422 | `validation_error` (field: `name`) | Race condition duplicate | Retry with a different name or handle the error gracefully |

### Debugging Scope Issues

If you receive a `scope_mismatch` error:

1. Fetch the hive details to confirm its `superpos_id`
2. Compare with the `superpos_id` you are sending
3. Either correct the `superpos_id` or omit it entirely

```bash
# Check which apiary owns a hive (requires admin access)
curl https://superpos.example.com/api/v1/hives/01JFWXYZ01JFWXYZ01JFWXYZ01 \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Duplicate Name After Migration

If your agent's name was changed during the dedup migration (e.g.,
`DeployBot` → `DeployBot-dup-1`), you can:

1. **Login** with the agent's `id` and original `secret` — the secret is
   unchanged
2. **Rename** the agent via the dashboard
3. **Re-register** with a new unique name if preferred

## Testing

The registration API is covered by comprehensive tests in
`tests/Feature/AgentRegistrationTest.php`. Key test areas:

- **Happy path** — successful registration returns `201` with agent and token
- **Optional fields** — `type`, `capabilities`, `metadata` are correctly stored
- **Superpos derivation** — `superpos_id` is auto-derived from hive
- **Scope enforcement** — `superpos_id` mismatch returns `422` with `scope_mismatch`
- **Duplicate detection** — same name in same hive returns `422`
- **Cross-hive isolation** — same name in different hive succeeds
- **Race conditions** — DB constraint catches concurrent duplicates
- **Error consistency** — form validation and DB constraint return identical errors
- **Migration dedup** — oldest agent keeps name, duplicates get `-dup-{N}` suffix
- **UTF-8 safety** — multibyte names are truncated correctly during dedup
- **Long names** — names at 255-character limit with dedup suffixes

Run the registration tests:

```bash
php artisan test --filter=AgentRegistrationTest
```

Run the full test suite:

```bash
php artisan test
```

### Writing Integration Tests

To test registration in your own agent code, use the API directly:

```python
import os
import requests

BASE = "https://superpos.example.com/api/v1/agents"

resp = requests.post(f"{BASE}/register", json={
    "name": "test-agent",
    "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
    "secret": "test-secret-minimum-16",
    "registration_token": os.environ["SUPERPOS_REGISTRATION_TOKEN"],  # srt_…
    "type": "testing",
    "capabilities": ["self_test"],
})

assert resp.status_code == 201
data = resp.json()
assert data["data"]["agent"]["name"] == "test-agent"
assert data["data"]["token"] is not None
assert data["errors"] is None

# Token is now available for authenticated requests
token = data["data"]["token"]
```

Test duplicate rejection:

```python
# Same name + same hive → 422
dup = requests.post(f"{BASE}/register", json={
    "name": "test-agent",
    "hive_id": "01JFWXYZ01JFWXYZ01JFWXYZ01",
    "secret": "another-secret-16-plus",
    "registration_token": os.environ["SUPERPOS_REGISTRATION_TOKEN"],  # srt_…
})

assert dup.status_code == 422
assert dup.json()["errors"][0]["field"] == "name"
```
