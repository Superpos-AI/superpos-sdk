# TASK-132: Persona Hot Reload (Poll-Based Version Notification)

## Status
⬜ In Progress

## Branch
`task/132-persona-hot-reload`

## Depends On
- TASK-122 ✅ (Agent persona migration + model)
- TASK-127 ✅ (Python SDK persona methods)
- TASK-017 ✅ (Task polling)
- TASK-015 ✅ (Agent authentication)

## Edition Scope
Both CE and Cloud (core feature)

## Objective
Allow running agents to detect when their persona version changes without
restarting. Agents poll for tasks anyway — include the server-assigned persona
version in the poll response meta so the SDK can detect changes on every cycle.
Also add a dedicated lightweight `GET /api/v1/persona/version` endpoint for
agents that want to check for updates without polling tasks.

## Deliverables

### Backend (PHP)
1. `GET /api/v1/persona/version` — lightweight version check endpoint.
   - Returns `{ version }` (agent's server-assigned persona version, null if none).
   - Accepts optional `?known_version=N` query param; when present, response also
     includes `changed` (bool): `true` if `version != known_version`.
   - Auth required (401 without token).
   - Rejects non-integer `known_version` with 422.
2. Poll response (`GET /api/v1/hives/{hive}/tasks/poll`) extended with
   `meta.persona_version` — the server-assigned persona version for the polling
   agent (null when no persona assigned). Agents check this on every poll cycle.

### Python SDK
3. `SuperposClient.get_persona_version(known_version=None)` — calls the new
   `/api/v1/persona/version` endpoint. When `known_version` is provided, the
   `changed` field is included in the response.
4. `SuperposClient.check_persona_version(known_version)` — convenience bool helper:
   returns `True` when the server version differs from `known_version`.
5. `SuperposClient.poll_tasks_with_meta(hive_id, ...)` — like `poll_tasks()` but
   returns the full `{data, meta, errors}` envelope so callers can read
   `meta["persona_version"]` without a second request.
6. `SuperposClient._request_envelope(...)` — internal helper returning the full
   envelope (used by `poll_tasks_with_meta`).

### Shell SDK
7. `superpos_get_persona_version [-k KNOWN_VERSION]` — calls
   `/api/v1/persona/version`, passing `?known_version=N` when `-k` is provided.
8. `superpos_check_persona_version -k KNOWN_VERSION` — returns exit code 0 when
   changed, 1 when unchanged. Requires jq.
9. CLI commands: `persona-get-version` and `persona-check-version -k N`.

### Tests
10. Feature tests in `PersonaSdkApiTest` (11 tests covering version endpoint,
    poll meta, auth, changed flag, version bump detection, envelope).
11. Python SDK tests in `test_persona.py` (9 tests covering
    get_persona_version, check_persona_version, poll_tasks_with_meta).
12. Shell SDK tests in `test_persona.sh` (12 tests covering get/check functions
    and CLI commands).

## Acceptance Criteria
- [x] `GET /api/v1/persona/version` returns `{ version }` for authenticated agent
- [x] `?known_version=N` adds `changed` bool to response
- [x] Rejects non-integer `known_version` with 422
- [x] Requires agent auth (401 without token)
- [x] Poll response `meta.persona_version` reflects server-assigned version
- [x] `meta.persona_version` is null when agent has no persona
- [x] `meta.persona_version` increments after persona update
- [x] Python SDK `get_persona_version()` works without `known_version`
- [x] Python SDK `get_persona_version(known_version=N)` includes `changed`
- [x] Python SDK `check_persona_version(N)` returns bool
- [x] Python SDK `poll_tasks_with_meta()` returns full envelope with `meta.persona_version`
- [x] Shell SDK `superpos_get_persona_version` with and without `-k`
- [x] Shell SDK `superpos_check_persona_version -k N` exits 0 on change, 1 on same
- [x] Shell CLI `persona-get-version` and `persona-check-version -k N`
- [x] All tests pass
