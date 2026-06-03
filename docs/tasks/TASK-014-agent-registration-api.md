# TASK-014: Agent Registration API

**Status:** done
**Branch:** `task/014-agent-registration-api`
**PR:** —
**Depends on:** TASK-003, TASK-007, TASK-011, TASK-012
**Blocks:** TASK-015

## Objective

Implement agent registration API endpoints and flow so agents can self-register (or be provisioned) safely within hive/apiary scope, returning credentials/tokens needed for outbound polling.

## Requirements

### Functional

- [x] FR-1: Registration endpoint validates payload and creates agent record safely
- [x] FR-2: Registration enforces apiary/hive scoping and permission constraints
- [x] FR-3: Registration response uses API envelope and returns auth material per policy
- [x] FR-4: Duplicate/invalid registration attempts return deterministic errors
- [x] FR-5: Activity log records registration events

### Non-Functional

- [x] NFR-1: No plaintext credential leakage in logs/responses beyond one-time secrets
- [x] NFR-2: PSR-12 compliance
- [x] NFR-3: Feature tests for happy path + failure paths + tenant isolation behavior

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Http/Controllers/Api/AgentAuthController.php` | Registration behavior/response contract updates |
| Modify | `app/Http/Requests/AgentRegisterRequest.php` | Request validation for registration payload |
| Create | `tests/Feature/AgentRegistrationTest.php` | TASK-014 specific test coverage |

### Key Design Decisions

- Reuse Sanctum auth foundation from TASK-012
- Keep controller thin; push business logic to service layer where complex
- Enforce tenant safety via model scoping + explicit consistency checks
- Composite uniqueness: name + hive_id enforced via Form Request validation
- Optional superpos_id in payload for explicit scope verification (mismatch → 422)
- Enriched activity log details: agent_name, agent_type alongside token_name

## Implementation Plan

1. Review existing TASK-012 registration endpoint behavior and gaps vs TASK-014
2. Implement/adjust registration contract to meet TASK-014 requirements
3. Add robust validation and conflict handling
4. Add activity logging and scope consistency checks
5. Expand test coverage (success, duplicate, invalid, cross-scope)
6. Run test suite and finalize docs/task status

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/agents/register` | Register agent and return auth bootstrap payload |

## Test Plan

### Feature Tests

- [x] Successful registration returns expected envelope
- [x] Duplicate identity rejected with clear error
- [x] Invalid payload rejected (422)
- [x] Cross-hive/apiary mismatch rejected
- [x] Activity log event written

## Validation Checklist

- [x] All tests pass (`php artisan test`) — 526 passed, 14 skipped, 0 failures
- [x] PSR-12 compliant
- [x] Activity logging on registration
- [x] API responses use `{ data, meta, errors }` envelope
- [x] Form Request validation on all inputs
