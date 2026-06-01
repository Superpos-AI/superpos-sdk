# TASK-063 — Hive Resolution Middleware

> **Status:** In Progress
> **Depends On:** TASK-062 (Hive management API)
> **Branch:** `task/063-hive-resolution-middleware`

## Objective

Create a middleware that resolves the target hive from the `{hive}` URL parameter,
validates tenant isolation, and stores the resolved Hive model on the request for
controller access — eliminating duplicated `resolveHive()` methods across controllers.

## Requirements

1. **Hive resolution** — Extract `{hive}` from route parameters and find the Hive model.
2. **Fail-closed** — Return 404 if hive doesn't exist; 403 if it belongs to another apiary.
3. **Request attribute** — Store the resolved Hive model on `$request->attributes->set('hive', $hive)`
   so controllers can access it without re-querying.
4. **No container binding override** — Does NOT set `apiary.current_hive_id` because
   cross-hive operations need the agent's hive context for activity logging and
   model creation hooks. Controllers continue using `withoutGlobalScopes()`.
5. **API error envelope** — All error responses use the standard `{ data, meta, errors }` format.
6. **Controller refactoring** — Remove duplicated `resolveHive()` methods from TaskController,
   EventController, and KnowledgeController; use middleware-resolved hive instead.
7. **Middleware registration** — Register as alias `'hive'` and apply to the `hives/{hive}` route group.

## Design

### Middleware: `ResolveHive`

```
Route::prefix('hives/{hive}')
    ->middleware(['auth:sanctum-agent', 'hive'])
    ->group(function () { ... });
```

The middleware:
1. Gets the authenticated agent via `$request->user('sanctum-agent')`
2. Extracts `{hive}` from route parameters
3. Finds hive: `Hive::withoutGlobalScopes()->find($hiveParam)`
4. Validates hive exists → 404
5. Validates `$hive->superpos_id === $agent->superpos_id` → 403
6. Sets `$request->attributes->set('hive', $hive)`
7. Passes to next middleware

### Controller changes

Controllers switch from:
```php
$targetHive = Hive::withoutGlobalScopes()->find($hive);
if (! $targetHive) { return $this->notFound('Hive not found.'); }
if ($targetHive->superpos_id !== $agent->superpos_id) { ... }
```

To:
```php
$targetHive = $request->attributes->get('hive');
```

Controller-specific business logic (cross-hive permission checks) remains in controllers.

## Files

| Action | File |
|--------|------|
| Create | `app/Http/Middleware/ResolveHive.php` |
| Modify | `bootstrap/app.php` (register alias) |
| Modify | `routes/api.php` (apply to route group) |
| Modify | `app/Http/Controllers/Api/TaskController.php` |
| Modify | `app/Http/Controllers/Api/EventController.php` |
| Modify | `app/Http/Controllers/Api/KnowledgeController.php` |
| Create | `tests/Feature/HiveResolutionMiddlewareTest.php` |

## Test Plan

- Middleware returns 401 when no agent is authenticated
- Middleware returns 404 for non-existent hive ID
- Middleware returns 403 for hive belonging to different apiary
- Middleware resolves valid hive and stores on request attributes
- Resolved Hive model is available on `$request->attributes->get('hive')`
- Error responses use standard API envelope format
- Inactive hive is still resolvable (policy decision)
- Cross-hive access within same apiary is allowed (middleware-level)
- Integration tests with real API routes

## Validation Checklist

- [ ] All tests pass
- [ ] PSR-12 compliant (Pint)
- [ ] Standard API error envelope
- [ ] Fail-closed behavior
- [ ] No credentials or secrets in logs
