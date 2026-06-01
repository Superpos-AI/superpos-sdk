# TASK-081 — API Key Rotation with Grace Period

| Field       | Value                                       |
|-------------|---------------------------------------------|
| Status      | ✅ Done                                     |
| Priority    | High                                        |
| Depends On  | TASK-012 (Agent auth via Sanctum)            |
| Branch      | `task/081-api-key-rotation` (merged)         |
| PR          | [#131](https://github.com/Superpos-AI/superpos-app/pull/131) |

## Objective

Allow agents to rotate their API key (secret) with an optional grace period
during which both the new and old keys are accepted for login. This enables
zero-downtime key rotation in distributed agent deployments.

## Design

### Data Model

Three new columns on the `agents` table:

| Column                        | Type              | Purpose                               |
|-------------------------------|-------------------|---------------------------------------|
| `previous_api_token_hash`     | `varchar` nullable| Hashed copy of the old key            |
| `key_grace_period_expires_at` | `timestamp` nullable| When the old key stops being accepted |
| `key_rotated_at`              | `timestamp` nullable| When the key was last rotated         |

### API Endpoints

All endpoints are authenticated (`auth:sanctum-agent`) and scoped to the calling agent.

| Method | Path                     | Purpose                            |
|--------|--------------------------|-------------------------------------|
| POST   | `/agents/key/rotate`     | Rotate key, set grace period        |
| POST   | `/agents/key/revoke`     | Immediately revoke previous key     |
| GET    | `/agents/key/status`     | Get current key rotation state      |

### Rotate Request Body

```json
{
  "new_secret": "string (min 16 chars, required)",
  "grace_period_minutes": 60
}
```

`grace_period_minutes` is optional (default 0 = no grace window).
Maximum: 10080 (7 days).

### Login Behavior

The login endpoint (`POST /agents/login`) now checks:
1. Primary key (`api_token_hash`) — normal login
2. Previous key (`previous_api_token_hash`) — accepted only if `key_grace_period_expires_at` is in the future

When the grace key is used, the response includes a `warning` field and
`grace_period_expires_at` to nudge the agent to update.

### Grace Key Auto-Cleanup

Expired grace keys are automatically cleaned up:
- On failed login attempts (prevents stale data buildup)
- On `GET /agents/key/status` calls (lazy cleanup)
- The `clearExpiredGraceKey()` model method handles this

## Files Changed

- `database/migrations/2026_03_08_210000_add_key_rotation_to_agents_table.php`
- `app/Models/Agent.php` — new fields, casts, helpers
- `app/Http/Controllers/Api/AgentKeyController.php` — rotate/revoke/status
- `app/Http/Controllers/Api/AgentAuthController.php` — grace-key login logic
- `app/Http/Requests/RotateKeyRequest.php` — validation
- `routes/api.php` — new routes
- `sdk/python/src/superpos_sdk/client.py` — `rotate_key()`, `revoke_previous_key()`, `key_status()`
- `sdk/shell/src/superpos-sdk.sh` — `superpos_rotate_key`, `superpos_revoke_previous_key`, `superpos_key_status`
- `sdk/shell/bin/superpos-cli` — `key-rotate`, `key-revoke`, `key-status` commands
- `tests/Feature/AgentKeyRotationTest.php` — 28 tests

## Test Coverage (28 tests, 187 assertions)

- Key rotation: new token, hash update, grace period, no grace period
- Sanctum token revocation on rotate
- Activity logging for rotate and revoke
- Validation: short secret, negative/excessive grace period, auth required
- Grace period login: old key accepted, new key works, expiry rejection
- Edge timing: boundary at expiry, just-before-expiry
- Immediate revoke: stops grace key acceptance
- Double rotation: only current + previous keys honored (not N-2)
- Scope isolation: rotation scoped to authenticated agent only
- Cross-apiary isolation
- Model helpers: `isInGracePeriod()`, `hasExpiredGraceKey()`, `clearExpiredGraceKey()`
