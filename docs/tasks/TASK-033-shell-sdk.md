# TASK-033: Shell SDK (bash + curl + jq)

**Status:** Review
**Branch:** `task/033-shell-sdk`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/40
**Depends On:** 014 (Agent registration), 015 (Heartbeat), 016 (Task creation), 017 (Polling/claiming), 018 (Progress/completion), 020 (Knowledge API)

## Objective

Ship a pure Bash SDK that wraps the Superpos v1 API, giving agent developers a
zero-dependency (beyond curl + jq) client for the core agent, task, and
knowledge workflows. Usable both as a sourced library and as a standalone CLI
tool, suitable for CI pipelines and ad-hoc scripting.

## Requirements

### Library (`src/superpos-sdk.sh`)
- Pure Bash 4+, curl + jq as only external dependencies
- Dependency check function (`superpos_check_deps`)
- Bearer token auth header management via `SUPERPOS_TOKEN` env var
- Superpos JSON envelope (`{ data, meta, errors }`) unwrapping via jq
- Configurable timeout (`SUPERPOS_TIMEOUT`), debug mode (`SUPERPOS_DEBUG=1`)
- stdout/stderr split: data to stdout, errors/debug to stderr

### Exit code mapping
- `0` — success (2xx)
- `1` — general error (5xx, network)
- `2` — validation error (422)
- `3` — authentication error (401)
- `4` — permission denied (403)
- `5` — not found (404)
- `6` — conflict (409)
- `7` — missing dependencies

### Endpoints covered (18 functions)
1. **Agent auth:** `superpos_register`, `superpos_login`, `superpos_logout`, `superpos_me`
2. **Agent lifecycle:** `superpos_heartbeat`, `superpos_update_status`
3. **Tasks:** `superpos_create_task`, `superpos_poll_tasks`, `superpos_claim_task`, `superpos_update_progress`, `superpos_complete_task`, `superpos_fail_task`
4. **Knowledge:** `superpos_list_knowledge`, `superpos_search_knowledge`, `superpos_get_knowledge`, `superpos_create_knowledge`, `superpos_update_knowledge`, `superpos_delete_knowledge`

### CLI wrapper (`bin/superpos-cli`)
- Standalone executable wrapping all SDK functions
- Subcommand interface: `superpos-cli <command> [options]`
- Usage help on `superpos-cli help` or no arguments

### Examples
- `quickstart.sh` — register, create task, store knowledge
- `worker_agent.sh` — poll/claim/complete loop with error handling

## Test Plan

- 115 tests with mocked HTTP (custom test harness, no external framework):
  - Envelope parsing (data unwrap, 204 handling)
  - Auth header presence/absence
  - Error mapping for 401, 403, 404, 409, 422, 500
  - Laravel object-style error parsing
  - JSON builder (strings, numbers, arrays, objects, booleans, null, empty omission)
  - Token auto-storage (register, login)
  - Token clearing on logout (success + error)
  - All agent auth endpoints (register, login, me)
  - Heartbeat and status update
  - Task lifecycle (create, poll, claim, progress, complete, fail)
  - Knowledge CRUD (list, search, get, create, update, delete)
  - Request body correctness (optional fields omitted when empty)
  - HTTP method verification (GET/POST/PATCH/PUT/DELETE)
  - URL construction with query parameters

## Files Changed

- `sdk/shell/src/superpos-sdk.sh` — core library
- `sdk/shell/bin/superpos-cli` — CLI wrapper
- `sdk/shell/README.md` — SDK documentation
- `sdk/shell/examples/quickstart.sh` — quickstart example
- `sdk/shell/examples/worker_agent.sh` — worker loop example
- `sdk/shell/tests/test_harness.sh` — test framework with mock HTTP
- `sdk/shell/tests/test_client.sh` — core client tests (29 tests)
- `sdk/shell/tests/test_agents.sh` — agent endpoint tests (22 tests)
- `sdk/shell/tests/test_tasks.sh` — task endpoint tests (34 tests)
- `sdk/shell/tests/test_knowledge.sh` — knowledge endpoint tests (30 tests)
- `sdk/shell/tests/run_tests.sh` — test runner
- `docs/guide/shell-sdk.md` — VitePress guide
- `docs/index.md` — link to SDK guide
- `docs/tasks/TASK-033-shell-sdk.md` — this file

## Definition of Done

- [x] Library sources and functions work correctly
- [x] All 115 tests pass
- [x] Covers auth, lifecycle, tasks, and knowledge endpoints
- [x] Error responses map to stable exit codes
- [x] CLI wrapper covers all SDK functions
- [x] Examples demonstrate core workflows
- [x] VitePress guide added and linked from docs index
- [ ] PR merged to `main`
- [ ] TASKS.md updated to `✅`
