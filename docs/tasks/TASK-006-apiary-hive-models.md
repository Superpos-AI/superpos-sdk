# TASK-006: Superpos & Hive Models + HasUlid Trait

**Status:** done
**Branch:** `task/006-apiary-hive-models`
**PR:** [#6](https://github.com/Superpos-AI/superpos-app/pull/6)
**Depends on:** TASK-002, TASK-005
**Blocks:** TASK-007, TASK-008, TASK-009, TASK-010, TASK-031

## Objective

Create the Superpos and Hive Eloquent models and a reusable HasUlid trait so that
all future models have consistent ULID primary key handling. These are the
foundational models in the Superpos hierarchy — every other core model depends on
them for foreign key relationships and trait-based scoping.

## Requirements

### Functional

- [x] FR-1: `HasUlid` trait auto-generates ULID primary keys on creation
- [x] FR-2: `HasUlid` trait sets key type to string and disables auto-increment
- [x] FR-3: `Superpos` model maps to `apiaries` table with correct fillable/casts
- [x] FR-4: `Superpos` model has `hives()` HasMany relationship
- [x] FR-5: `Superpos` model has `owner()` BelongsTo relationship to User
- [x] FR-6: `Hive` model maps to `hives` table with correct fillable/casts
- [x] FR-7: `Hive` model uses `BelongsToApiary` trait for apiary scoping
- [x] FR-8: `Hive` model has `apiary()` BelongsTo relationship (via trait)
- [x] FR-9: Both models use `HasUlid` trait for ULID PKs
- [x] FR-10: `settings` column cast to `array` on both models
- [x] FR-11: Cloud-only datetime fields properly cast on Superpos model

### Non-Functional

- [x] NFR-1: PSR-12 compliant
- [x] NFR-2: Models registered in `config('apiary.models')` for swappability
- [x] NFR-3: No business logic in models (thin models, logic in services)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Traits/HasUlid.php` | Reusable ULID PK trait wrapping Laravel's HasUlids |
| Create | `app/Models/Superpos.php` | Superpos (organization) Eloquent model |
| Create | `app/Models/Hive.php` | Hive (project) Eloquent model |
| Modify | `config/apiary.php` | Add `models` key for model class swappability |
| Create | `tests/Feature/ApiaryHiveModelsTest.php` | Feature tests for both models |
| Create | `tests/Unit/HasUlidTest.php` | Unit tests for the HasUlid trait |

### Key Design Decisions

- **HasUlid wraps Laravel's HasUlids**: Provides a project-level abstraction so ULID behavior is consistent across all Superpos models and can be extended later if needed.
- **Superpos does NOT use BelongsToApiary**: The Superpos model is the root of the hierarchy — it doesn't belong to itself. Only child resources use the scoping trait.
- **Hive uses BelongsToApiary (not BelongsToHive)**: A hive belongs to an apiary but is not scoped to another hive. Only resources *within* a hive use BelongsToHive.
- **Config-driven model classes**: `config('apiary.models.apiary')` and `config('apiary.models.hive')` allow cloud edition to extend models without modifying core code.
- **settings cast to array**: Consistent with Laravel JSON column conventions. Default `{}` in migration maps to `[]` in PHP.

## Implementation Plan

1. Create `app/Traits/HasUlid.php` wrapping Laravel's built-in `HasUlids`
2. Create `app/Models/Superpos.php` with HasUlid, fillable, casts, relationships
3. Create `app/Models/Hive.php` with HasUlid, BelongsToApiary, fillable, casts
4. Add `models` config key to `config/apiary.php`
5. Write unit tests for HasUlid trait
6. Write feature tests for Superpos and Hive model behavior
7. Run full test suite, verify zero regressions

## Database Changes

_None — tables already created by TASK-005._

## API Changes

_None._

## Test Plan

### Unit Tests

- [x] HasUlid trait auto-generates valid ULID on creation
- [x] HasUlid trait sets $incrementing = false
- [x] HasUlid trait sets $keyType = 'string'
- [x] HasUlid trait generates unique IDs

### Feature Tests

- [x] Superpos can be created with auto-generated ULID
- [x] Superpos does not use auto-increment
- [x] Superpos fillable fields work correctly
- [x] Superpos settings column casts to/from array
- [x] Superpos settings defaults to empty when not provided
- [x] Superpos trial_ends_at casts to datetime
- [x] Superpos has hives() relationship returning HasMany
- [x] Superpos hives() returns child hives
- [x] Superpos has owner() relationship returning BelongsTo
- [x] Superpos owner() returns User
- [x] Superpos cascade deletes child hives
- [x] Hive can be created with auto-generated ULID
- [x] Hive does not use auto-increment
- [x] Hive fillable fields work correctly
- [x] Hive settings column casts to/from array
- [x] Hive is_active casts to boolean
- [x] Hive BelongsToApiary trait auto-sets superpos_id in CE mode
- [x] Hive apiary() relationship returns parent Superpos
- [x] Cloud mode: Hive global scope filters by apiary context
- [x] Cloud mode: Hive creation fails without apiary context
- [x] Config model classes are resolvable

## Validation Checklist

- [x] All tests pass (`php artisan test`)
- [x] PSR-12 compliant
- [ ] Activity logging on state changes — N/A (no runtime state changes yet)
- [ ] API responses use `{ data, meta, errors }` envelope — N/A
- [ ] Form Request validation on all inputs — N/A
- [x] ULIDs for primary keys
- [x] BelongsToApiary trait applied to Hive
- [x] No credentials logged in plaintext

## Test Evidence

```
  Tests:    25 new passed (55 assertions) — HasUlidTest (4) + ApiaryHiveModelsTest (21)
  Duration: 0.51s
```

Full suite: 143 passed (350 assertions), 0 failures, 0 regressions.
