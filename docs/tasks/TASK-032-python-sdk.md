# TASK-032: Python SDK (minimal)

**Status:** Review
**Branch:** `task/032-python-sdk`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/39
**Depends On:** 014 (Agent registration), 015 (Heartbeat), 016 (Task creation), 017 (Polling/claiming), 018 (Progress/completion), 020 (Knowledge API)

## Objective

Ship a minimal but usable Python SDK that wraps the Superpos v1 API, giving agent
developers a clean, typed client for the core agent → task → knowledge workflow.

## Requirements

### Package structure
- Installable Python package (`superpos-sdk`) in `sdk/python/`
- Requires Python 3.10+, single runtime dependency: `httpx`
- Dev dependencies: `pytest`, `pytest-httpx`, `ruff`

### Client core (`SuperposClient`)
- `base_url` + optional `token` constructor
- Bearer token auth header management
- Superpos JSON envelope (`{ data, meta, errors }`) unwrapping
- Context manager support (`with` statement)
- Configurable timeout

### Error mapping
- HTTP status → typed exception hierarchy:
  - `SuperposError` (base)
  - `ValidationError` (422)
  - `AuthenticationError` (401)
  - `PermissionError` (403)
  - `NotFoundError` (404)
  - `ConflictError` (409)
- Each exception carries `status_code` and structured `errors` list

### Endpoints covered
1. **Agent auth:** `register`, `login`, `logout`, `me`
2. **Agent lifecycle:** `heartbeat`, `update_status`
3. **Tasks:** `create_task`, `poll_tasks`, `claim_task`, `update_progress`, `complete_task`, `fail_task`
4. **Knowledge:** `list_knowledge`, `search_knowledge`, `get_knowledge`, `create_knowledge`, `update_knowledge`, `delete_knowledge`

### Examples
- `quickstart.py` — register, create task, store knowledge
- `worker_agent.py` — poll/claim/complete loop with error handling

## Test Plan

- 40 tests with mocked HTTP (pytest-httpx):
  - Envelope parsing (data unwrap, 204 → None)
  - Auth header presence/absence
  - Error mapping for 401, 403, 404, 409, 422, 500
  - All agent auth endpoints (register, login, logout, me)
  - Heartbeat and status update
  - Task lifecycle (create, poll, claim, progress, complete, fail)
  - Knowledge CRUD (list, search, get, create, update, delete)
  - Request body correctness (optional fields omitted when None)

## Files Changed

- `sdk/python/pyproject.toml` — package configuration
- `sdk/python/README.md` — SDK documentation
- `sdk/python/src/superpos_sdk/__init__.py` — public API exports
- `sdk/python/src/superpos_sdk/client.py` — main client class
- `sdk/python/src/superpos_sdk/exceptions.py` — error hierarchy
- `sdk/python/tests/conftest.py` — shared fixtures
- `sdk/python/tests/test_client.py` — core client tests
- `sdk/python/tests/test_agents.py` — agent endpoint tests
- `sdk/python/tests/test_tasks.py` — task endpoint tests
- `sdk/python/tests/test_knowledge.py` — knowledge endpoint tests
- `sdk/python/examples/quickstart.py` — quickstart example
- `sdk/python/examples/worker_agent.py` — worker loop example
- `docs/guide/python-sdk.md` — VitePress guide
- `docs/index.md` — link to SDK guide
- `docs/tasks/TASK-032-python-sdk.md` — this file

## Definition of Done

- [x] Package installs and imports cleanly
- [x] All 40 tests pass
- [x] Covers auth, lifecycle, tasks, and knowledge endpoints
- [x] Error responses map to typed exceptions
- [x] Examples demonstrate core workflows
- [x] VitePress guide added and linked from docs index
- [ ] PR merged to `main`
- [ ] TASKS.md updated to `✅`
