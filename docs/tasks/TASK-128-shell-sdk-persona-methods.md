# TASK-128: Shell SDK persona methods

## Status
⬜ Pending

## Branch
`task/128-shell-sdk-persona-methods`

## PR
_Not yet created_

## Depends On
- TASK-126 ✅ (Persona SDK API)
- TASK-033 ✅ (Shell SDK)

## Blocks
_None_

## Edition Scope
Both CE and Cloud (core feature)

## Objective
Add Shell SDK wrapper functions for the 5 persona API endpoints introduced in Task 126. Mirror the Python SDK persona methods (Task 127) into Bash, following the existing Shell SDK conventions (`_superpos_request`, `_superpos_build_json`, `OPTIND`/`OPTARG` pattern).

## Deliverables
1. `sdk/shell/src/superpos-sdk.sh` — new `── Persona ──` section with 5 functions
2. `sdk/shell/tests/test_persona.sh` — test suite for all 5 functions
3. `sdk/shell/tests/run_tests.sh` — `"persona"` added to the suites array

## Acceptance Criteria
- [ ] `superpos_get_persona` — GET /api/v1/persona
- [ ] `superpos_get_persona_config` — GET /api/v1/persona/config
- [ ] `superpos_get_persona_document NAME` — GET /api/v1/persona/documents/{name}
- [ ] `superpos_get_persona_assembled` — GET /api/v1/persona/assembled
- [ ] `superpos_update_persona_document NAME -c CONTENT [-m MESSAGE]` — PATCH /api/v1/persona/documents/{name}
- [ ] Missing `-c` flag returns error exit code
- [ ] `message` field omitted from JSON body when not provided (empty-value skipping via `_superpos_build_json`)
- [ ] All tests pass
