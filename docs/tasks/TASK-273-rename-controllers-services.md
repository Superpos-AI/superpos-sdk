# TASK-273: Controllers, Services, Jobs & Routes

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-270, TASK-271, TASK-272
**Blocks:** TASK-275

## Objective

Update all controllers, services, jobs, events, listeners, form requests, and
route definitions to use the renamed Organization model, OrgContext, platform
config, and BelongsToOrganization trait.

## Requirements

### Functional

- [ ] FR-1: Update all API controllers (`app/Http/Controllers/Api/`) — model imports, config calls, OrgContext usage
- [ ] FR-2: Update all Dashboard controllers (`app/Http/Controllers/Dashboard/`) — same
- [ ] FR-3: Update all services (`app/Services/`) — model references, config keys, OrgContext calls
- [ ] FR-4: Update all jobs (`app/Jobs/`) — same
- [ ] FR-5: Update all events and listeners (`app/Events/`, `app/Listeners/`)
- [ ] FR-6: Update all form requests (`app/Http/Requests/`)
- [ ] FR-7: Update route definitions — if any routes use "apiary" in URL paths, change to `/organizations/`
- [ ] FR-8: Update route names if they contain "apiary"

### Non-Functional

- [ ] NFR-1: No `Superpos::`, `BelongsToApiary`, `ApiaryContext::`, or `config('apiary.*')` references remain
- [ ] NFR-2: API URLs that changed should be documented for SDK updates
- [ ] NFR-3: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Http/Controllers/Api/*.php` | All API controllers |
| Modify | `app/Http/Controllers/Dashboard/*.php` | All dashboard controllers |
| Modify | `app/Services/*.php` | All service classes |
| Modify | `app/Jobs/*.php` | All job classes |
| Modify | `app/Events/*.php` | All event classes |
| Modify | `app/Listeners/*.php` | All listener classes |
| Modify | `app/Http/Requests/*.php` | All form requests |
| Modify | `routes/api.php` | API route definitions |
| Modify | `routes/web.php` | Web route definitions |

### Key Design Decisions

- **Bulk find-replace safe here**: After models, traits, config, and support classes are renamed, this is mostly mechanical
- **Route URL changes**: `/apiaries/` becomes `/organizations/` — breaking API change, acceptable since SDKs update later
- **Route names**: `apiary.*` → `organization.*` or `org.*`

## Implementation Plan

1. Grep for remaining `Superpos` references across controllers, services, jobs, events, listeners, requests
2. For each file: update `use` imports, model references, config calls, OrgContext calls
3. Update `routes/api.php`: rename any apiary-related route URLs and names
4. Update `routes/web.php`: same
5. Verify no `Superpos::`, `BelongsToApiary`, `ApiaryContext::`, or `config('apiary.*')` references remain
6. Run `./vendor/bin/pint`
7. Run `php artisan route:list` to verify routes resolve correctly

## API Changes

| Method | Old Endpoint | New Endpoint | Notes |
|--------|-------------|--------------|-------|
| * | `/api/v1/apiaries/*` | `/api/v1/organizations/*` | If such routes exist |

## Test Plan

### Feature Tests

- [ ] All API endpoints return correct responses with new route names
- [ ] Dashboard pages load correctly
- [ ] All service methods function with renamed dependencies

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] `php artisan route:list` shows no apiary-named routes
- [ ] Grep confirms zero remaining old references in app/Http/ and app/Services/
- [ ] Activity logging on state changes (unchanged)
- [ ] API responses use `{ data, meta, errors }` envelope (unchanged)
