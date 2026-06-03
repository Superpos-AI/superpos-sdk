# TASK-271: Config & Environment — Rename to platform config

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-269
**Blocks:** TASK-272, TASK-273, TASK-274, TASK-275

## Objective

Rename `config/apiary.php` to `config/platform.php` and all `SUPERPOS_*` env
vars to `PLATFORM_*`. This decouples configuration from the product brand so
future rebrands only require UI text changes.

## Requirements

### Functional

- [ ] FR-1: Rename `config/apiary.php` → `config/platform.php`
- [ ] FR-2: Rename all ~80 `SUPERPOS_*` env vars to `PLATFORM_*` inside config file
- [ ] FR-3: Update `.env.example` with new `PLATFORM_*` var names
- [ ] FR-4: Update `.env.testing` with new `PLATFORM_*` var names
- [ ] FR-5: Find and replace all `config('apiary.*')` calls across the entire PHP codebase to `config('platform.*')`
- [ ] FR-6: Update `docker-compose.yml` env var references
- [ ] FR-7: Update `CLAUDE.md` references to config keys and env vars

### Non-Functional

- [ ] NFR-1: No backward-compat env fallbacks — clean cut since no production
- [ ] NFR-2: `PLATFORM_EDITION`, `PLATFORM_CE_*` as new prefixes
- [ ] NFR-3: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `config/apiary.php` → `config/platform.php` | Config file rename |
| Modify | `.env.example` | Update all SUPERPOS_* → PLATFORM_* |
| Modify | `.env.testing` | Same |
| Modify | `docker-compose.yml` | Update env vars |
| Modify | All PHP files with `config('apiary.*')` | Update config key prefix |
| Modify | `CLAUDE.md` | Update documentation references |

### Key Design Decisions

- **`PLATFORM_*` prefix**: Brand-neutral, won't need changing if product renames again
- **`config('platform.*')`**: Matches the file name, consistent with Laravel convention
- **No fallback layer**: No production deployment, no need for backwards-compat shims
- **Config structure unchanged**: Only the file name and env var prefixes change

## Implementation Plan

1. Copy `config/apiary.php` to `config/platform.php`
2. In `config/platform.php`, find-replace all `SUPERPOS_` env references to `PLATFORM_`
3. Delete `config/apiary.php`
4. Update `.env.example`: rename all `SUPERPOS_*` lines to `PLATFORM_*`
5. Update `.env.testing`: same
6. Global find-replace across all PHP files: `config('apiary.` → `config('platform.`
7. Global find-replace: `config("apiary.` → `config("platform.` (double-quote variant)
8. Update `docker-compose.yml` env var names
9. Update `CLAUDE.md` documentation
10. Run `./vendor/bin/pint`
11. Verify `php artisan config:show platform` works

## Test Plan

### Unit Tests

- [ ] `config('platform.edition')` returns expected value
- [ ] `config('platform.ce.superpos_id')` resolves correctly (key renamed to `org_id` in TASK-272)
- [ ] All existing config-dependent tests pass with new key names

### Feature Tests

- [ ] Application boots successfully with new config
- [ ] CE mode resolves correctly with `PLATFORM_EDITION=ce`
- [ ] Docker compose starts with updated env vars

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] No remaining `config('apiary.*')` references in PHP files
- [ ] No remaining `SUPERPOS_*` in `.env.example`
- [ ] `CLAUDE.md` updated
- [ ] Docker compose boots cleanly
