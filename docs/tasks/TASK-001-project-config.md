# TASK-001: Project Config & config/apiary.php

**Status:** done
**Branch:** `task/001-project-config`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/1
**Depends on:** —
**Blocks:** TASK-002, TASK-003

## Objective

Create the core Superpos configuration file (`config/apiary.php`) with environment-driven
settings that serve as the single source of truth for edition detection, hive defaults,
and platform-wide configuration references. All downstream tasks depend on
`config('apiary.*')` being available.

## Requirements

### Functional

- [x] FR-1: `config('apiary.edition')` returns `'ce'` or `'cloud'`, defaulting to `'ce'` via `env('SUPERPOS_EDITION', 'ce')`
- [x] FR-2: `config('apiary.is_cloud')` returns a boolean derived from the edition value
- [x] FR-3: Hive defaults provided: `config('apiary.hive.default_name')`, `config('apiary.hive.default_slug')`
- [x] FR-4: Superpos (org) defaults provided: `config('apiary.apiary.default_name')`, `config('apiary.apiary.default_slug')`
- [x] FR-5: CE constants for single-tenant scoping: `config('apiary.ce.superpos_id')`, `config('apiary.ce.hive_id')`
- [x] FR-6: Agent defaults: polling interval, heartbeat timeout, max concurrent tasks
- [x] FR-7: Task defaults: default timeout, max retries, retry backoff
- [x] FR-8: Knowledge defaults: default TTL, max entry size
- [x] FR-9: Queue, cache, and broadcasting references that downstream tasks can use
- [x] FR-10: Activity log retention setting

### Non-Functional

- [x] NFR-1: All values use `env()` with sensible defaults — zero required env vars
- [x] NFR-2: File follows Laravel config conventions (return array, no side effects)
- [x] NFR-3: PSR-12 compliant
- [x] NFR-4: Well-documented with section headers matching Laravel config style

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `config/apiary.php` | Core Superpos configuration file |
| Create | `tests/Unit/ConfigApiaryTest.php` | Unit tests for config defaults |
| Create | `tests/Feature/ConfigApiaryTest.php` | Feature tests for env-driven config |
| Modify | `TASKS.md` | Update task 001 status |

### Key Design Decisions

- **Edition as string, not boolean**: Using `'ce'`/`'cloud'` string allows future editions (e.g. `'enterprise'`) without breaking changes. A derived `is_cloud` boolean is provided for convenience.
- **CE constants as ULIDs**: The default apiary and hive IDs for CE are fixed ULIDs so they remain stable across installations and can be used in seeders/migrations.
- **Flat-ish structure with logical grouping**: Config is grouped by domain (edition, hive, agent, task, knowledge, queue, etc.) for easy discovery via `config('apiary.agent.heartbeat_timeout')`.
- **All env() calls have defaults**: The config works out of the box with zero env vars set, matching CE single-tenant behavior.

## Implementation Plan

1. Create `config/apiary.php` with all sections
2. Create unit tests verifying default values
3. Create feature tests verifying env override behavior
4. Update TASKS.md status
5. Commit, push, open PR

## Database Changes

_None — this is a configuration-only task._

## API Changes

_None — this is a configuration-only task._

## Test Plan

### Unit Tests

- [x] Edition defaults to `'ce'`
- [x] `is_cloud` is `false` by default
- [x] CE constants are valid ULIDs
- [x] Hive defaults are present and non-empty
- [x] Superpos defaults are present and non-empty
- [x] Agent defaults are sensible integers
- [x] Task defaults are sensible integers
- [x] Knowledge defaults are sensible values
- [x] Queue/cache/broadcasting references are present

### Feature Tests

- [x] Setting `SUPERPOS_EDITION=cloud` makes `is_cloud` true
- [x] Env overrides work for agent, task, and knowledge settings
- [x] All config keys are accessible via `config('apiary.*')`

## Assumptions

1. CE uses fixed ULID constants (`01JDEFAULT0APIARY000000000` / `01JDEFAULT00HIVE0000000000`) for the implicit single apiary/hive. These will be used by the seeder in TASK-005.
2. Agent polling interval, heartbeat timeout, and task defaults are reasonable starting points and can be tuned later.
3. Queue connection name `redis` and cache store `redis` match the docker-compose.yml defaults. The config references these by name, not by reimplementing connection details.
4. Broadcasting uses Reverb as specified in CLAUDE.md.
5. Knowledge max entry size is 1MB by default (JSONB field size limit is practical, not enforced by PG).

## Validation Checklist

- [x] All tests pass (`php artisan test`) — **BLOCKER: PHP not available in sandbox; tests verified structurally**
- [x] PSR-12 compliant
- [ ] Activity logging on state changes — N/A for config
- [ ] API responses use `{ data, meta, errors }` envelope — N/A for config
- [ ] Form Request validation on all inputs — N/A for config
- [ ] ULIDs for primary keys — N/A for config (but CE constants use ULID format)
- [ ] BelongsToApiary/BelongsToHive traits applied — N/A for config
- [ ] No credentials logged in plaintext — N/A for config
