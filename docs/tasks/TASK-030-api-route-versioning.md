# TASK-030: API route organization & versioning

## Status
Review

## PR
https://github.com/Superpos-AI/superpos-app/pull/37

## Objective
Consolidate all agent-facing API routes under a single `/api/v1` group, apply
a consistent naming convention, and add a public version discovery endpoint.

## Why
The existing routes already used a `v1/` prefix but were spread across
multiple top-level `Route::prefix()` calls with no route names. This made it
hard to generate URLs by name, audit the endpoint surface, and prepare for
future API versions. A discovery endpoint lets agents bootstrap themselves
without hard-coding URIs.

## Dependencies
- TASK-003 API response envelope ✅
- TASK-012 Agent auth (Sanctum) ✅
- TASK-013 Permission middleware ✅

## Scope

### 1. Route consolidation
Rewrite `routes/api.php` to use a single `Route::prefix('v1')` wrapper.
All existing endpoints keep their exact URIs — no breaking changes.

### 2. Route naming convention
Apply `api.v1.{resource}.{action}` names to every endpoint:

| Name | Method | URI |
|------|--------|-----|
| `api.v1.index` | GET | `/api/v1` |
| `api.v1.agents.register` | POST | `/api/v1/agents/register` |
| `api.v1.agents.login` | POST | `/api/v1/agents/login` |
| `api.v1.agents.logout` | POST | `/api/v1/agents/logout` |
| `api.v1.agents.me` | GET | `/api/v1/agents/me` |
| `api.v1.agents.heartbeat` | POST | `/api/v1/agents/heartbeat` |
| `api.v1.agents.updateStatus` | PATCH | `/api/v1/agents/status` |
| `api.v1.tasks.store` | POST | `/api/v1/hives/{hive}/tasks` |
| `api.v1.tasks.poll` | GET | `/api/v1/hives/{hive}/tasks/poll` |
| `api.v1.tasks.claim` | PATCH | `/api/v1/hives/{hive}/tasks/{task}/claim` |
| `api.v1.tasks.progress` | PATCH | `/api/v1/hives/{hive}/tasks/{task}/progress` |
| `api.v1.tasks.complete` | PATCH | `/api/v1/hives/{hive}/tasks/{task}/complete` |
| `api.v1.tasks.fail` | PATCH | `/api/v1/hives/{hive}/tasks/{task}/fail` |
| `api.v1.knowledge.index` | GET | `/api/v1/hives/{hive}/knowledge` |
| `api.v1.knowledge.search` | GET | `/api/v1/hives/{hive}/knowledge/search` |
| `api.v1.knowledge.show` | GET | `/api/v1/hives/{hive}/knowledge/{entry}` |
| `api.v1.knowledge.store` | POST | `/api/v1/hives/{hive}/knowledge` |
| `api.v1.knowledge.update` | PUT | `/api/v1/hives/{hive}/knowledge/{entry}` |
| `api.v1.knowledge.destroy` | DELETE | `/api/v1/hives/{hive}/knowledge/{entry}` |

### 3. Version discovery endpoint
`GET /api/v1` — public, no auth required. Returns the API version and a
catalog of all named endpoints with method and URI.

### 4. Middleware unchanged
Auth and permission middleware assignments are preserved exactly as-is.

### 5. Tests
Feature tests covering route registration, naming convention, version
discovery response, access behavior (public vs authenticated), and URI
stability.

### 6. Documentation
VitePress guide + docs index link.

## Exit Criteria
- All API routes use the `api.v1.*` naming convention.
- `GET /api/v1` returns a version + endpoint catalog.
- No existing URI changes (zero breaking changes).
- Middleware/auth behavior unchanged.
- Full test suite passes (1206+ tests).
- Docs updated.
