# TASK-138: Agent Self-Update (MEMORY Document)

## Status
✅ Done

## Branch
`task/138-agent-self-update-memory-document`

## PR
_See PR_

## Depends On
- TASK-131 ✅ (Document locking enforcement)
- TASK-126 ✅ (Persona SDK API)

## Edition Scope
Both CE and Cloud (core feature)

## Objective
Add a dedicated `PATCH /api/v1/persona/memory` API endpoint as a named shortcut
for agents to update their MEMORY document, plus convenience methods in the Python
and shell SDKs. Agents use this to persist learned context, project facts, and
runtime observations across executions without needing to know the generic document
name.

## Deliverables
1. `PersonaController::updateMemory()` — delegates to `updateDocument()` with `MEMORY`
2. `PATCH /api/v1/persona/memory` route registered under the persona prefix group
3. Python SDK: `SuperposClient.update_memory()` convenience method (default mode: append)
4. Shell SDK: `superpos_update_memory()` function and `persona-update-memory` CLI command
5. Feature tests in `PersonaSdkApiTest` (8 tests covering success, append, prepend,
   locked rejection, auth, validation, no-persona, envelope, version assignment)
6. Python SDK tests in `test_persona.py` (5 tests: default mode, message, replace,
   prepend, invalid mode raises)
7. Shell SDK tests in `test_persona.sh` (jq guard, all modes, missing -c, invalid mode,
   CLI help text, CLI dispatch)

## Acceptance Criteria
- [x] `PATCH /api/v1/persona/memory` updates the MEMORY document and returns new version
- [x] Supports `mode`: `replace`, `append`, `prepend` (same as generic endpoint)
- [x] Rejects locked MEMORY documents with 403
- [x] Requires agent auth (401 without token)
- [x] Returns `{ data, meta, errors }` envelope
- [x] Python SDK `update_memory()` defaults to `mode=append`
- [x] Shell SDK `superpos_update_memory()` defaults to `mode=append`
- [x] Shell SDK `persona-update-memory` CLI command registered with usage hint
- [x] All tests pass
