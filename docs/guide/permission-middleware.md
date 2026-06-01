# Permission Middleware

Superpos enforces granular access control on agent API routes through two
middleware — `permission` and `role`. Both sit on top of the
[agent authentication](./agent-authentication.md) layer (Sanctum bearer tokens)
and are evaluated **after** the agent is authenticated but **before** the
controller runs.

## Architecture Overview

```text
Agent request
  │
  ▼
auth:sanctum-agent          ← Authenticate (resolve agent from token)
  │
  ▼
permission:tasks.create     ← Authorize (check agent_permissions)
  │                              │
  │  ┌──────────PolicyService────┘
  │  │  1. Load permissions (Redis cache / DB fallback)
  │  │  2. admin:* wildcard?  → allow
  │  │  3. Exact match?       → allow  (separator-normalized)
  │  │  4. Category wildcard? → allow  (e.g. tasks:*)
  │  │  5. No match           → deny
  │  │
  │  └── 403 Forbidden ──► { data: null, errors: [...] }
  │
  ▼
Controller action           ← Route handler executes
```

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| String-based permissions | Simple, greppable, no extra tables — `tasks.create`, `knowledge.read`, `role:admin` |
| Separator normalization | Agents can use either `:` or `.` — `tasks.create` and `tasks:create` are equivalent |
| `permission` = ALL-of semantics | Every listed permission must be held; least-privilege by default |
| `role` = ANY-of semantics | Any one listed role is sufficient; mirrors typical RBAC expectations |
| Fail-closed on misconfiguration | If a `permission` middleware is applied with no arguments, the request is denied and logged |
| 300 s Redis cache | Avoids a DB query per request; auto-invalidated on grant/revoke |

## Permission Format

Permissions are stored as plain strings in the `agent_permissions` table with a
composite primary key of `(agent_id, permission)`.

### Naming Convention

```text
<category><separator><action>

category  = resource or role namespace (tasks, knowledge, services, role, admin)
separator = : or . (treated identically at evaluation time)
action    = specific action or * for wildcard
```

**Examples:**

| Permission | Meaning |
|------------|---------|
| `tasks.create` | Create tasks |
| `tasks:claim` | Claim pending tasks |
| `knowledge.read` | Read knowledge entries |
| `services:github` | Access the GitHub service connector |
| `tasks:*` | All task actions (wildcard) |
| `role:admin` | Admin role |
| `role:operator` | Operator role |
| `admin:*` | Superuser — bypasses all checks |

### Separator Compatibility

The colon (`:`) and dot (`.`) separators are **fully interchangeable**. The
`PolicyService` normalizes both to `:` before comparison, so:

- An agent granted `tasks.create` passes a `permission:tasks:create` check.
- An agent granted `tasks:create` passes a `permission:tasks.create` check.

This avoids configuration drift between teams that prefer different conventions.

### Wildcard Behavior

Two wildcard levels are supported:

| Pattern | Scope | Example |
|---------|-------|---------|
| `<category>:*` | All actions in a category | `tasks:*` matches `tasks.create`, `tasks:claim`, `tasks:read` |
| `admin:*` | Global superuser | Bypasses every `permission` and `role` check |

Wildcards are evaluated **only** on the granted side — you cannot use wildcards
in middleware route definitions.

## Middleware Semantics

### `permission` — Require ALL Listed Permissions

```php
// Single permission — agent must hold tasks.create
Route::middleware('permission:tasks.create');

// Multiple permissions — agent must hold BOTH
Route::middleware('permission:tasks.create,knowledge.read');
```

All listed permissions must be held. If the agent is missing even one, the
request is denied with `403`.

### `role` — Require ANY Listed Role

```php
// Single role — agent must have role:admin
Route::middleware('role:admin');

// Multiple roles — agent needs at least ONE
Route::middleware('role:admin,operator');
```

Roles are stored as `role:<name>` permissions. The `role` middleware
automatically prefixes the role name, so `role:admin` in a route checks for the
`role:admin` permission string. An agent holding `admin:*` also passes any role
check.

### Combining Middleware

Stack `permission` and `role` on the same route or group — they are evaluated
independently (both must pass):

```php
Route::middleware(['role:operator', 'permission:tasks.create'])
    ->group(function () {
        // Agent must have role:operator AND tasks.create
    });
```

## Route Examples and Recommended Patterns

### Basic Permission-Protected Group

```php
use App\Http\Controllers\Api\TaskController;
use App\Http\Controllers\Api\KnowledgeController;

Route::prefix('v1/agents')->middleware('auth:sanctum-agent')->group(function () {

    // Open (auth only, no specific permission)
    Route::get('/me', [AgentAuthController::class, 'me']);
    Route::post('/logout', [AgentAuthController::class, 'logout']);

    // Task routes — require task permissions
    Route::middleware('permission:tasks.read')->group(function () {
        Route::get('/tasks', [TaskController::class, 'index']);
        Route::get('/tasks/{task}', [TaskController::class, 'show']);
    });

    Route::post('/tasks', [TaskController::class, 'store'])
        ->middleware('permission:tasks.create');

    Route::post('/tasks/{task}/claim', [TaskController::class, 'claim'])
        ->middleware('permission:tasks.claim');

    // Knowledge — multiple permissions required
    Route::middleware('permission:knowledge.read,knowledge.write')->group(function () {
        Route::put('/knowledge/{entry}', [KnowledgeController::class, 'update']);
    });

    // Admin only
    Route::middleware('role:admin')->group(function () {
        Route::delete('/agents/{agent}', [AgentController::class, 'destroy']);
    });
});
```

### Recommended Permission Naming

| Resource | Permissions |
|----------|-------------|
| Tasks | `tasks.create`, `tasks.read`, `tasks.claim`, `tasks.update`, `tasks.delete` |
| Knowledge | `knowledge.read`, `knowledge.write`, `knowledge.delete` |
| Services | `services.<connector>` (e.g. `services.github`, `services.slack`) |
| Events | `events.publish`, `events.subscribe` |
| Cross-hive | `cross_hive.tasks`, `cross_hive.events` |

## Granting and Revoking Permissions

Permissions are managed via the `Agent` model:

```php
// Grant a permission
$agent->grantPermission('tasks.create', 'admin@example.com');

// Revoke a permission
$agent->revokePermission('tasks.create');

// Check a single permission (direct DB query, not cached)
$agent->hasPermission('tasks.create');
```

Both `grantPermission()` and `revokePermission()` **automatically flush** the
Redis cache for that agent, so changes take effect on the next request.

::: tip
For bulk permission changes (e.g. onboarding a new agent), grant all permissions
first, then the single cache flush on the last grant covers everything.
`grantPermission()` uses `firstOrCreate`, so duplicate grants are safe no-ops.
:::

## Cache Behavior and Invalidation

The `PolicyService` caches each agent's full permission set in Redis to avoid
a database query on every API request.

| Parameter | Value |
|-----------|-------|
| Store | Configured via `config('apiary.cache.store')` (typically `redis`) |
| Key format | `{prefix}:agent_permissions:{agent_id}` |
| TTL | 300 seconds (5 minutes) |
| Invalidation | Automatic on `grantPermission()` / `revokePermission()` |
| Manual flush | `app(PolicyService::class)->flushCache($agent)` |

### Invalidation Guarantees

- **Grant/revoke**: Cache is flushed synchronously before the method returns.
  The next request for that agent will reload from the database.
- **TTL expiry**: Even without explicit invalidation, stale permissions expire
  after 5 minutes. This is a safety net, not the primary mechanism.
- **No cross-request pollution**: Each agent has an independent cache key.
  Flushing one agent's cache does not affect others.

### When Cache Matters

| Scenario | Behavior |
|----------|----------|
| Permission just granted | Cache flushed — takes effect immediately |
| Permission just revoked | Cache flushed — takes effect immediately |
| Direct DB manipulation (bypassing model) | Cache stale up to 5 min — call `flushCache()` manually |
| Agent deleted (cascade) | Cache key becomes orphaned; expires via TTL |

## Failure Modes and Security Posture

The middleware follows a **fail-closed** security model. When in doubt, access
is denied.

### Response Codes

| Code | Condition | Response Body |
|------|-----------|---------------|
| `401` | No bearer token or invalid/expired token | Returned by `auth:sanctum-agent` before permission middleware runs |
| `403` | Valid token but insufficient permission | `{ data: null, meta: {}, errors: [{ message: "Insufficient permissions.", code: "forbidden" }] }` |
| `403` | Valid token but insufficient role | `{ data: null, meta: {}, errors: [{ message: "Insufficient role.", code: "forbidden" }] }` |
| `403` | Middleware misconfigured (no permissions specified) | `{ data: null, meta: {}, errors: [{ message: "Server configuration error.", code: "forbidden" }] }` |

### Fail-Closed Scenarios

| Scenario | Outcome |
|----------|---------|
| `permission` middleware with no arguments | 403 + `permission.misconfiguration` activity log |
| Agent has no permissions at all | 403 on any permission-protected route |
| Redis unavailable | Cache miss → falls back to direct DB query |
| Unknown permission string in middleware | 403 (agent won't have a permission that doesn't exist) |

### Activity Logging

All denials and misconfigurations are recorded in the
[activity log](./activity-log.md):

| Action | Trigger | Logged Fields |
|--------|---------|---------------|
| `permission.denied` | Agent lacks required permission | `required`, `route`, `ip` |
| `permission.misconfiguration` | No permissions specified in middleware | `reason`, `route` |
| `role.denied` | Agent lacks required role | `required_roles`, `route`, `ip` |

Successful permission checks are **not** logged to avoid noise. Use the
[ActivityLogger Service](./activity-logger.md) in your controllers to log
successful actions.

## CE vs Cloud Behavior

| Aspect | Community Edition | Cloud Edition |
|--------|-------------------|---------------|
| Permission model | Identical — `agent_permissions` table | Identical |
| Middleware aliases | `permission`, `role` | `permission`, `role` |
| Scoping | Single default apiary | Multi-tenant; permissions are per-agent, agents are per-hive |
| Admin wildcard | `admin:*` bypasses all | Same — scoped to the agent's apiary |
| Cache store | `config('apiary.cache.store')` | Same (typically Redis) |
| Cross-hive | Requires explicit `cross_hive.*` permissions | Same |

The permission middleware API is **identical** in both editions. The only
difference is organizational context: CE resolves to a single default apiary,
while Cloud scopes agents (and their permissions) to the tenant's apiary.

## Troubleshooting

### 403 "Insufficient permissions."

| Cause | Fix |
|-------|-----|
| Agent lacks the required permission | Grant with `$agent->grantPermission('tasks.create')` |
| Permission string mismatch | Check separator — `tasks.create` and `tasks:create` are equivalent, but `task.create` (no `s`) is not |
| Category wildcard not covering | `tasks:*` covers `tasks.create` but not `knowledge.read` |
| Multiple permissions required | With `permission:a,b`, agent must hold **both** `a` and `b` |

### 403 "Insufficient role."

| Cause | Fix |
|-------|-----|
| Agent lacks the required role | Grant with `$agent->grantPermission('role:admin')` |
| Multiple roles listed | With `role:admin,operator`, agent needs **any one** |
| Typo in role name | Role names are case-sensitive — `Admin` != `admin` |

### 403 "Server configuration error."

This means the `permission` middleware was applied to a route without any
permission arguments. This is a **code bug**, not an agent issue.

```php
// Bug — no permissions listed (will 403 everyone and log a misconfiguration)
Route::middleware('permission');

// Fix — specify at least one permission
Route::middleware('permission:tasks.read');
```

### Permission Changes Not Taking Effect

| Cause | Fix |
|-------|-----|
| Granted via raw SQL (bypassed model) | Call `app(PolicyService::class)->flushCache($agent)` |
| Testing with cached data | In tests, flush cache or use `Cache::flush()` |
| Wrong agent instance | Verify the agent ID matches the token being used |

### 401 Instead of 403

A `401` means authentication failed, not authorization. The `permission`
middleware never returns `401` — if you see it, the issue is upstream in
`auth:sanctum-agent`. See the
[Agent Authentication troubleshooting](./agent-authentication.md#common-pitfalls-and-troubleshooting)
guide.

## Testing

The full test suite for permission middleware is in
`tests/Feature/PermissionMiddlewareTest.php`.

### Running Permission Tests

```bash
php artisan test --filter=PermissionMiddlewareTest
```

### Test Coverage

**CheckAgentPermission middleware:**

- 401 without token (unauthenticated)
- 403 without required permission
- 403 when middleware has no permission arguments (fail-closed)
- Misconfiguration logged to activity log
- Cross-separator matching (`tasks.create` ↔ `tasks:create`)
- 200 with exact permission match
- `admin:*` wildcard grants access
- Category wildcard grants access (`tasks:*`)
- 403 when only one of multiple required permissions is held
- 200 when all required permissions are held
- Permission denials logged
- Successful checks not logged

**CheckAgentRole middleware:**

- 403 without required role
- 200 with matching role
- `admin:*` wildcard grants role access
- Multiple roles with ANY semantics
- Role denials logged

### Writing Tests with Permissions

```php
use App\Models\Agent;
use App\Models\Superpos;
use App\Models\Hive;
use Laravel\Sanctum\Sanctum;

// Set up agent with permissions
$apiary = Superpos::factory()->create();
$hive = Hive::factory()->for($apiary)->create();
$agent = Agent::factory()->for($hive)->for($apiary)->create();

$agent->grantPermission('tasks.create');
$agent->grantPermission('tasks.read');

Sanctum::actingAs($agent, ['*'], 'sanctum-agent');

// Test permission-protected route
$response = $this->postJson('/api/v1/agents/tasks', $payload);
$response->assertOk();
```

### Testing Permission Denials

```php
$agent = Agent::factory()->for($hive)->for($apiary)->create();
// No permissions granted
Sanctum::actingAs($agent, ['*'], 'sanctum-agent');

$response = $this->postJson('/api/v1/agents/tasks', $payload);
$response->assertForbidden();
$response->assertJsonPath('errors.0.code', 'forbidden');
```

Run the full test suite:

```bash
php artisan test
```
