# TASK-275: Tests & Infrastructure

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-269, TASK-270, TASK-271, TASK-272, TASK-273, TASK-274
**Blocks:** —

## Objective

Update all test files to use the new names (Organization, BelongsToOrganization,
OrgContext, platform config) and update Docker/CI infrastructure. Final
validation pass to ensure zero remaining "apiary" references in code.

## Requirements

### Functional

- [ ] FR-1: Update all PHP test files — model references, factory calls, config keys, trait references
- [ ] FR-2: Update all JS test files — component imports, hook references, text assertions
- [ ] FR-3: Update `docker-compose.yml`: `POSTGRES_DB` and `POSTGRES_USER` if they reference "apiary"
- [ ] FR-4: Update CI/CD workflow files (`.github/workflows/`) for new config/env var names
- [ ] FR-5: Update `Dockerfile` if it references apiary-specific names
- [ ] FR-6: Final grep: case-insensitive search for "apiary" across entire codebase — every hit must be addressed or documented as intentional
- [ ] FR-7: Update test helper traits/base classes if they reference old names

### Non-Functional

- [ ] NFR-1: `php artisan test` passes (full suite)
- [ ] NFR-2: `npm run build` succeeds
- [ ] NFR-3: `docker compose up` works with new config
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `tests/Unit/**/*.php` | Update model/trait/config references |
| Modify | `tests/Feature/**/*.php` | Same + route names, API URLs |
| Modify | `tests/TestCase.php` | Base test class if needed |
| Modify | `docker-compose.yml` | DB name/user rename |
| Modify | `.github/workflows/*.yml` | CI env vars |
| Modify | `Dockerfile` | Any apiary references |

### Key Design Decisions

- **Final grep pass is mandatory**: Ensures nothing was missed in earlier tasks
- **Allowed "apiary" references**: Migration file names (historical), git history. Document exceptions.
- **Docker DB rename**: `POSTGRES_DB: apiary` → `POSTGRES_DB: platform` (generic name)

## Implementation Plan

1. Find all test files with `Superpos` or `apiary` references
2. Update model imports: `Superpos::` → `Organization::`, `BelongsToApiary` → `BelongsToOrganization`
3. Update config refs: `config('apiary.*')` → `config('platform.*')`
4. Update factory calls: `Superpos::factory()` → `Organization::factory()`
5. Update OrgContext refs: `ApiaryContext::` → `OrgContext::`
6. Update API URL assertions: `/apiaries/` → `/organizations/`
7. Update JS test files similarly
8. Update `docker-compose.yml`: `POSTGRES_DB`, `POSTGRES_USER`, env vars
9. Update `.github/workflows/` CI files
10. Run full test suite: `php artisan test`
11. Run `npm run build`
12. Run comprehensive grep: `grep -ri "apiary" --include="*.php" --include="*.js" --include="*.jsx" .`
13. Address each remaining hit
14. Run `./vendor/bin/pint`

## Test Plan

### Validation

- [ ] `php artisan test` — all pass
- [ ] `npm run build` — succeeds
- [ ] `docker compose up --build` — boots cleanly
- [ ] Grep for "apiary" returns zero hits in code files (excluding migration filenames)
- [ ] CI pipeline runs green

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] `npm run build` succeeds
- [ ] Docker compose boots with new config
- [ ] Comprehensive "apiary" grep addressed
- [ ] No credentials logged in plaintext
