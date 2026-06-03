# TASK-082 — Per-Agent Rate Limiting

| Field       | Value                                       |
|-------------|---------------------------------------------|
| Status      | ✅ Done                                     |
| Priority    | High                                        |
| Depends On  | TASK-012 (Agent auth via Sanctum)            |
| Branch      | `task/082-per-agent-rate-limiting` (merged)  |
| PR          | [#132](https://github.com/Superpos-AI/superpos-app/pull/132) |
| Edition     | `shared`                                    |

## Objective

Enforce per-agent API rate limiting with configurable limits and sane defaults.
Prevents abusive or runaway agents from overwhelming the platform while allowing
operators to tune limits per agent.

## Design

### Data Model

One new column on the `agents` table:

| Column                  | Type              | Purpose                                    |
|-------------------------|-------------------|--------------------------------------------|
| `rate_limit_per_minute` | `integer` nullable | Per-agent override; null = use system default |

### Configuration (config/apiary.php)

```php
'rate_limit' => [
    'max_per_minute' => env('SUPERPOS_RATE_LIMIT_MAX', 60),
],
```

### Enforcement

Redis-backed fixed-window counter using atomic `INCR` + `EXPIRE`.

Key format: `apiary:rate_limit:{agent_id}:{minute_bucket}`

The middleware `ThrottleAgent` runs after `auth:sanctum-agent` on all
authenticated agent API routes. It:
1. Resolves the agent from the request
2. Determines the effective limit (per-agent override or system default)
3. Atomically increments the Redis counter for the current window
4. If over limit: returns 429 with retry_after metadata
5. Always sets `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers

### API Endpoints

| Method | Path                      | Purpose                          |
|--------|---------------------------|----------------------------------|
| GET    | `/agents/rate-limit`      | Get current rate limit & usage   |
| PUT    | `/agents/rate-limit`      | Update per-agent rate limit      |

### Rate Limit Status Response

```json
{
  "data": {
    "limit": 60,
    "remaining": 45,
    "resets_at": "2026-03-08T12:01:00Z",
    "is_custom": false
  }
}
```

### 429 Error Response

```json
{
  "data": null,
  "meta": {
    "retry_after": 15
  },
  "errors": [{ "message": "Rate limit exceeded.", "code": "rate_limited" }]
}
```

## Files Changed

- `database/migrations/2026_03_08_230000_add_rate_limit_to_agents_table.php`
- `app/Models/Agent.php` — new field, cast, helper
- `app/Services/AgentRateLimitService.php` — Redis-backed rate limit logic
- `app/Http/Middleware/ThrottleAgent.php` — middleware
- `app/Http/Controllers/Api/AgentRateLimitController.php` — status/config API
- `app/Http/Requests/UpdateRateLimitRequest.php` — validation
- `config/apiary.php` — default rate limit config
- `routes/api.php` — new routes + middleware attachment
- `bootstrap/app.php` — register middleware alias
- `sdk/python/src/superpos_sdk/client.py` — `rate_limit_status()`, `update_rate_limit()`
- `sdk/shell/src/superpos-sdk.sh` — `superpos_rate_limit_status`, `superpos_update_rate_limit`
- `sdk/shell/bin/superpos-cli` — `rate-limit-status`, `rate-limit-update` commands
- `tests/Feature/AgentRateLimitTest.php`

## Test Plan

- Within-limit requests pass through normally
- Over-limit requests return 429 with correct envelope and retry_after
- Rate limit headers present on all responses
- Window resets after expiry, requests succeed again
- Per-agent custom limit overrides system default
- Null custom limit falls back to system default
- Hive/apiary scope isolation (agent A's usage doesn't affect agent B)
- Concurrency: parallel requests don't over-admit past the limit
- Rate limit status endpoint returns correct usage
- Rate limit update endpoint validates and persists
- Activity logging on rate limit changes
