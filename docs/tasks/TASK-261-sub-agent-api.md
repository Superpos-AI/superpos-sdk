# TASK-261: Agent-facing sub-agent API

**Status:** pending
**Branch:** `task/261-sub-agent-api`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/463
**Depends on:** TASK-259, TASK-260
**Blocks:** TASK-267, TASK-268
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §6

## Objective

Create agent-facing REST API endpoints for listing, fetching, and assembling sub-agent definitions. These endpoints are scoped to the agent's hive via sanctum-agent authentication, allowing agents to discover and fetch sub-agent definitions at runtime.

## Requirements

### Functional

- [ ] FR-1: `GET /api/v1/sub-agents` — list all active sub-agent definitions in the authenticated agent's hive. Returns lightweight data: id, slug, name, description, model, version, document_count (integer count of non-empty documents). Standard `{ data }` envelope.
- [ ] FR-2: `GET /api/v1/sub-agents/{slug}` — get a specific active sub-agent definition by slug in the agent's hive. Returns full data including documents, config, allowed_tools. Returns 404 if slug not found or not active.
- [ ] FR-3: `GET /api/v1/sub-agents/{slug}/assembled` — returns the pre-assembled system prompt for the current active version of the given slug. Response: `{ data: { slug, version, prompt, document_count } }`. Uses `SubAgentDefinitionService::assemble()`.
- [ ] FR-4: `GET /api/v1/sub-agents/by-id/{id}` — version-stable fetch by ULID. Returns the exact sub-agent definition row regardless of which version is currently active for the slug. Used when an agent needs to re-fetch a pinned definition from a task. Returns 404 if ID not found. Scoped to agent's hive.
- [ ] FR-5: `GET /api/v1/sub-agents/by-id/{id}/assembled` — version-stable assembled prompt by ULID. Returns assembled prompt for the exact pinned version. Used for re-fetching a previously claimed task's sub-agent prompt.
- [ ] FR-6: All endpoints scoped to the authenticated agent's hive via `auth:sanctum-agent` middleware. Agent can only access sub-agent definitions in their own hive.

### Non-Functional

- [ ] NFR-1: Standard API response envelope `{ data, meta, errors }` — follow existing API patterns
- [ ] NFR-2: PSR-12 compliant
- [ ] NFR-3: No form request validation needed (all endpoints are read-only GETs)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Http/Controllers/Api/SubAgentApiController.php` | Agent-facing API controller |
| Modify | `routes/api.php` | Register sub-agent API routes |
| Create | `tests/Feature/SubAgentApiControllerTest.php` | API endpoint tests |

### Key Design Decisions

- **Slug-based vs ID-based endpoints** — slug-based endpoints (`/sub-agents/{slug}`) always resolve to the current active version, convenient for discovery. ID-based endpoints (`/sub-agents/by-id/{id}`) return the exact pinned version, required for version-stable fetching when a task or workflow has pinned a specific `sub_agent_definition_id`.
- **Lightweight list response** — the list endpoint returns only summary data (no full documents) to keep responses small. Full documents are available via the show endpoint.
- **Hive scoping** — all endpoints are scoped to the agent's hive automatically, consistent with other agent-facing APIs.

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/sub-agents` | List active sub-agent definitions in agent's hive |
| GET | `/api/v1/sub-agents/{slug}` | Get active definition by slug (full documents) |
| GET | `/api/v1/sub-agents/{slug}/assembled` | Get assembled prompt for active version |
| GET | `/api/v1/sub-agents/by-id/{id}` | Get definition by ULID (version-stable) |
| GET | `/api/v1/sub-agents/by-id/{id}/assembled` | Get assembled prompt by ULID (version-stable) |

### Response Examples

**List response (`GET /api/v1/sub-agents`):**
```json
{
  "data": [
    {
      "id": "01ABC...",
      "slug": "coder",
      "name": "Coding Agent",
      "description": "Focused coding agent for implementing features and fixes",
      "model": "claude-opus-4-7",
      "version": 3,
      "document_count": 4
    }
  ]
}
```

**Show response (`GET /api/v1/sub-agents/{slug}`):**
```json
{
  "data": {
    "id": "01ABC...",
    "slug": "coder",
    "name": "Coding Agent",
    "description": "Focused coding agent for implementing features and fixes",
    "model": "claude-opus-4-7",
    "version": 3,
    "documents": {
      "SOUL": "You are a focused coding agent...",
      "AGENT": "When you receive a coding task...",
      "RULES": "NEVER commit directly to main..."
    },
    "config": { "temperature": 0.2, "max_tokens": 8192 },
    "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
  }
}
```

**Assembled response (`GET /api/v1/sub-agents/{slug}/assembled`):**
```json
{
  "data": {
    "slug": "coder",
    "version": 3,
    "prompt": "# SOUL\n\nYou are a focused coding agent...\n\n# AGENT\n\nWhen you receive a coding task...",
    "document_count": 4
  }
}
```

## Implementation Plan

1. Create `SubAgentApiController` with constructor injecting `SubAgentDefinitionService`:
   ```php
   class SubAgentApiController extends ApiController
   {
       public function __construct(
           private SubAgentDefinitionService $service
       ) {}
   }
   ```

2. Implement `index()` method:
   - Get agent's hive_id from authenticated agent
   - Query active definitions via service `list()`
   - Map to lightweight response (slug, name, description, model, version, document_count)
   - Return `$this->success($data)`

3. Implement `show(string $slug)` method:
   - Find active definition: `SubAgentDefinition::where('hive_id', $hiveId)->where('slug', $slug)->active()->first()`
   - Return 404 if not found
   - Return full definition data including documents, config, allowed_tools

4. Implement `assembled(string $slug)` method:
   - Find active definition (same as show)
   - Call `$this->service->assemble($definition)`
   - Return slug, version, prompt, document_count

5. Implement `showById(string $id)` method:
   - Find definition by ID, scoped to agent's hive: `SubAgentDefinition::where('hive_id', $hiveId)->where('id', $id)->first()`
   - Return 404 if not found
   - Return full definition data (same shape as show)

6. Implement `assembledById(string $id)` method:
   - Find definition by ID (same as showById)
   - Return assembled prompt (same shape as assembled)

7. Register routes in `routes/api.php` under `auth:sanctum-agent` middleware:
   ```php
   Route::prefix('sub-agents')->group(function () {
       Route::get('/', [SubAgentApiController::class, 'index']);
       Route::get('/by-id/{id}', [SubAgentApiController::class, 'showById']);
       Route::get('/by-id/{id}/assembled', [SubAgentApiController::class, 'assembledById']);
       Route::get('/{slug}', [SubAgentApiController::class, 'show']);
       Route::get('/{slug}/assembled', [SubAgentApiController::class, 'assembled']);
   });
   ```
   Note: `/by-id/{id}` routes must be registered before `/{slug}` routes to avoid slug matching on "by-id".

8. Write feature tests

## Test Plan

### Feature Tests

- [ ] `GET /api/v1/sub-agents` returns only active definitions in agent's hive
- [ ] `GET /api/v1/sub-agents` does not return definitions from other hives
- [ ] `GET /api/v1/sub-agents` does not return inactive definitions
- [ ] `GET /api/v1/sub-agents` returns correct document_count
- [ ] `GET /api/v1/sub-agents/{slug}` returns full definition with documents
- [ ] `GET /api/v1/sub-agents/{slug}` returns 404 for non-existent slug
- [ ] `GET /api/v1/sub-agents/{slug}` returns 404 for inactive slug
- [ ] `GET /api/v1/sub-agents/{slug}/assembled` returns concatenated prompt
- [ ] `GET /api/v1/sub-agents/{slug}/assembled` returns correct document_count
- [ ] `GET /api/v1/sub-agents/by-id/{id}` returns exact version (even if not active)
- [ ] `GET /api/v1/sub-agents/by-id/{id}` returns 404 for ID in different hive
- [ ] `GET /api/v1/sub-agents/by-id/{id}/assembled` returns assembled prompt for exact version
- [ ] All endpoints require sanctum-agent authentication (401 without token)
- [ ] All endpoints use standard `{ data }` envelope

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] API responses use `{ data, meta, errors }` envelope
- [ ] Scoped to agent's hive via auth middleware
- [ ] Route registration order correct (by-id before slug)
- [ ] ULIDs used for primary key lookups
