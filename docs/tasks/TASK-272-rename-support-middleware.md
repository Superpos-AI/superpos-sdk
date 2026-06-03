# TASK-272: Support Classes & Middleware

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-270, TASK-271
**Blocks:** TASK-273, TASK-274, TASK-275

## Objective

Rename `ApiaryContext` to `OrgContext` and update all middleware, service
providers, and support classes to use the new Organization model, platform
config, and brand-neutral container binding keys.

## Requirements

### Functional

- [ ] FR-1: Rename `app/Support/ApiaryContext.php` → `app/Support/OrgContext.php`
- [ ] FR-2: Rename methods: `resolveApiaryId()` → `resolveOrgId()`, update internal references from `superpos_id` to `organization_id`
- [ ] FR-3: Update container binding keys: `apiary.current_apiary_id` → `platform.current_org_id`, `apiary.current_hive_id` → `platform.current_hive_id`
- [ ] FR-4: Update `BindSessionContext` middleware to use new binding keys and session key names
- [ ] FR-5: Update `HandleInertiaRequests` middleware to use `OrgContext` and new config keys
- [ ] FR-6: Update all service providers that reference `ApiaryContext` or `Superpos` model
- [ ] FR-7: Update all `use App\Support\ApiaryContext` imports across codebase
- [ ] FR-8: Update config internal keys: `config('platform.ce.superpos_id')` → `config('platform.ce.org_id')`

### Non-Functional

- [ ] NFR-1: Container binding keys are brand-neutral (`platform.*` prefix)
- [ ] NFR-2: Session keys updated to match (e.g., `current_org_id`)
- [ ] NFR-3: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `app/Support/ApiaryContext.php` → `app/Support/OrgContext.php` | Support class rename |
| Modify | `app/Http/Middleware/BindSessionContext.php` | New binding keys |
| Modify | `app/Http/Middleware/HandleInertiaRequests.php` | Use OrgContext |
| Modify | `app/Providers/AppServiceProvider.php` | Update bindings |
| Modify | `config/platform.php` | Rename internal `ce.superpos_id` → `ce.org_id` keys |
| Modify | All files importing ApiaryContext | Update imports |

### Key Design Decisions

- **`OrgContext`** not `OrganizationContext`: shorter, matches `org_id` column naming
- **Container bindings use `platform.*` prefix**: `platform.current_org_id`, `platform.current_hive_id`
- **Config key rename**: `platform.ce.superpos_id` → `platform.ce.org_id` inside config/platform.php

## Implementation Plan

1. Create `app/Support/OrgContext.php` from `ApiaryContext.php` with renamed class and methods
2. Delete `app/Support/ApiaryContext.php`
3. Update method names: `resolveApiaryId()` → `resolveOrgId()`, internal `superpos_id` refs → `organization_id`
4. Update `config/platform.php`: rename `ce.superpos_id` → `ce.org_id` key and its env var
5. Update `.env.example` / `.env.testing` for renamed config keys
6. Update `BindSessionContext` middleware: session keys, container binding keys
7. Update `HandleInertiaRequests` middleware: use OrgContext, new config keys
8. Update service providers
9. Global find-replace: `use App\Support\ApiaryContext` → `use App\Support\OrgContext`
10. Global find-replace: `ApiaryContext::` → `OrgContext::`
11. Run `./vendor/bin/pint`

## Test Plan

### Unit Tests

- [ ] `OrgContext::resolveOrgId()` returns correct ID in CE mode
- [ ] `OrgContext::resolveOrgId()` returns correct ID from container binding in Cloud mode
- [ ] `OrgContext::resolveHiveId()` still works correctly

### Feature Tests

- [ ] Middleware correctly sets `platform.current_org_id` binding
- [ ] Dashboard pages load with correct org context
- [ ] API endpoints resolve agent correctly via OrgContext

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] No remaining references to `ApiaryContext` in app/
- [ ] No remaining `apiary.current_apiary_id` container bindings
- [ ] CE mode works correctly with new config keys
