# TASK-270: Core Models & Traits — Rename Superpos → Organization

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-269
**Blocks:** TASK-272, TASK-273, TASK-275

## Objective

Rename the `Superpos` Eloquent model to `Organization` and the `BelongsToApiary`
trait to `BelongsToOrganization`. Update all models that reference these, plus
factories and seeders.

## Requirements

### Functional

- [ ] FR-1: Rename `app/Models/Superpos.php` → `app/Models/Organization.php` (class, `$table = 'organizations'`, relationships)
- [ ] FR-2: Rename `app/Traits/BelongsToApiary.php` → `app/Traits/BelongsToOrganization.php`
- [ ] FR-3: Update trait internals: `superpos_id` → `organization_id`, scope names `ForApiary` → `ForOrganization`, `ForCurrentApiary` → `ForCurrentOrganization`
- [ ] FR-4: Update all ~35 models that `use BelongsToApiary` to `use BelongsToOrganization`
- [ ] FR-5: Update `Hive` model's `belongsTo(Superpos::class)` → `belongsTo(Organization::class)`
- [ ] FR-6: Update model factories (`ApiaryFactory` → `OrganizationFactory`)
- [ ] FR-7: Update database seeders

### Non-Functional

- [ ] NFR-1: All `use App\Models\Superpos` imports replaced with `use App\Models\Organization`
- [ ] NFR-2: All `use App\Traits\BelongsToApiary` imports replaced with `use App\Traits\BelongsToOrganization`
- [ ] NFR-3: No backward-compat aliases — clean rename
- [ ] NFR-4: PSR-12 compliant (run Pint)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `app/Models/Superpos.php` → `app/Models/Organization.php` | Model class rename |
| Rename | `app/Traits/BelongsToApiary.php` → `app/Traits/BelongsToOrganization.php` | Trait rename |
| Modify | `app/Models/Hive.php` | Update belongsTo relationship |
| Modify | ~35 model files | Update `use BelongsToOrganization` |
| Modify | `database/factories/ApiaryFactory.php` → `OrganizationFactory.php` | Factory rename |
| Modify | `database/seeders/*.php` | Update Superpos references |

### Key Design Decisions

- **BelongsToHive unchanged**: "Hive" is generic enough — no rename needed now
- **Scope method names**: `scopeForOrganization($query, $orgId)` and `scopeForCurrentOrganization($query)` — clear and brand-neutral
- **Global scope**: The auto-scoping global scope in the trait filters on `organization_id` instead of `superpos_id`

## Implementation Plan

1. Create `app/Models/Organization.php` with contents of `Superpos.php`, updated class name and `$table = 'organizations'`
2. Delete `app/Models/Superpos.php`
3. Create `app/Traits/BelongsToOrganization.php` with updated column references (`organization_id`), scope names, and relationship method
4. Delete `app/Traits/BelongsToApiary.php`
5. Find all files with `use App\Models\Superpos` and replace with `use App\Models\Organization`
6. Find all files with `use App\Traits\BelongsToApiary` and replace with `use App\Traits\BelongsToOrganization`
7. Update `Hive` model relationship from `Superpos::class` to `Organization::class`
8. Rename and update factory file
9. Update seeders
10. Run `./vendor/bin/pint` to fix code style

## Test Plan

### Unit Tests

- [ ] `Organization` model can be instantiated and uses `organizations` table
- [ ] `BelongsToOrganization` trait auto-sets `organization_id` on create
- [ ] `scopeForOrganization` filters correctly
- [ ] `scopeForCurrentOrganization` resolves org ID correctly in CE mode

### Feature Tests

- [ ] Models using `BelongsToOrganization` are properly scoped
- [ ] Factory creates valid Organization records
- [ ] Seeder runs without errors

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] No remaining references to `Superpos` model or `BelongsToApiary` trait in app/
- [ ] ULIDs for primary keys (unchanged)
- [ ] No credentials logged in plaintext
