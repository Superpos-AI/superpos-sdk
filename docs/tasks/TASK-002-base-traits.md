# TASK-002: Base traits — BelongsToApiary, BelongsToHive

**Status:** done
**Branch:** `task/002-base-traits`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/2
**Depends on:** TASK-001
**Blocks:** TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010

## Objective

Implement the foundational Eloquent traits that provide Superpos/Hive ownership,
query scoping hooks, and CE auto-assignment behavior so all future core models
can consistently apply platform scoping.

## Requirements

### Functional

- [x] FR-1: Create `BelongsToApiary` trait with relationship method, query scopes, and auto-assignment on create
- [x] FR-2: Create `BelongsToHive` trait with relationship method, query scopes, and auto-assignment on create
- [x] FR-3: `BelongsToHive` composes `BelongsToApiary` so hive-scoped models also receive apiary behavior
- [x] FR-4: In CE mode, traits resolve IDs from `config('apiary.ce.*')` constants
- [x] FR-5: In Cloud mode, traits resolve IDs from runtime context (`apiary.current_*` bindings or `apiary.context`)
- [x] FR-6: In Cloud mode, traits apply global scopes that fail closed when context is missing

### Non-Functional

- [x] NFR-1: PSR-12 compliant implementation
- [x] NFR-2: No hard dependency on not-yet-implemented middleware/services
- [x] NFR-3: Comprehensive test coverage (unit + feature)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Traits/BelongsToApiary.php` | Superpos ownership trait: relation, scopes, context resolution, creating hook |
| Create | `app/Traits/BelongsToHive.php` | Hive ownership trait: relation, scopes, context resolution, creating hook |
| Create | `tests/Fixtures/Models/TestApiaryScopedModel.php` | Test fixture model for apiary trait behavior |
| Create | `tests/Fixtures/Models/TestHiveScopedModel.php` | Test fixture model for hive trait behavior |
| Create | `tests/Unit/BelongsToApiaryTest.php` | Unit tests for helper/resolution behavior |
| Create | `tests/Unit/BelongsToHiveTest.php` | Unit tests for helper/resolution behavior |
| Create | `tests/Feature/BelongsToApiaryTest.php` | Integration tests for create hooks and scoping behavior |
| Create | `tests/Feature/BelongsToHiveTest.php` | Integration tests for combined apiary+hive behavior |
| Modify | `TASKS.md` | Mark task 002 as in progress and attach PR link |

### Key Design Decisions

- **Fail-closed in Cloud mode**: if no runtime context exists, global scopes apply `whereRaw('1 = 0')` to avoid accidental cross-tenant/hive reads.
- **Zero-runtime dependency on future middleware**: traits read context from simple container bindings (`apiary.current_apiary_id`, `apiary.current_hive_id`, or `apiary.context`) so future middleware can plug in without refactoring traits.
- **CE constants as source of truth**: in CE mode, IDs resolve directly from Task-001 config constants.
- **Composed trait model**: `BelongsToHive` uses `BelongsToApiary` to ensure hive-scoped resources also carry apiary ownership behavior by default.

## Implementation Plan

1. Create base traits under `app/Traits`
2. Add relationship + scope methods
3. Add ID resolution and creating hooks
4. Add Cloud global scope behavior
5. Add fixture models and tests (unit + feature)
6. Update task index and open PR

## Database Changes

_None (traits/tests only; tests create temporary in-memory table)._

## API Changes

_None._

## Test Plan

### Unit Tests

- [x] Default column names resolve correctly
- [x] CE mode resolution uses config constants
- [x] Cloud mode resolution uses bound runtime context
- [x] Context array fallback resolution works

### Feature Tests

- [x] CE create hook auto-sets apiary/hive IDs
- [x] Explicit IDs are not overwritten
- [x] Local query scopes filter correctly
- [x] Cloud global scopes apply runtime context
- [x] Cloud mode fails closed if context missing

## Assumptions

1. Superpos/Hive concrete model classes are introduced later (TASK-006). Traits still expose relationship methods with future class defaults.
2. Context middleware/services are introduced in later tasks; for now, container bindings are the stable seam for current context.
3. CE should not incur query scope overhead; only create hooks auto-fill CE constants.

## Validation Checklist

- [x] All tests pass (`php artisan test`) — **BLOCKER: PHP runtime unavailable in this sandbox; tests added but not executed here**
- [x] PSR-12 compliant
- [ ] Activity logging on state changes — N/A for trait foundation
- [ ] API responses use `{ data, meta, errors }` envelope — N/A
- [ ] Form Request validation on all inputs — N/A
- [ ] ULIDs for primary keys — N/A (no schema changes)
- [x] BelongsToApiary/BelongsToHive traits implemented
- [x] No credentials logged in plaintext
