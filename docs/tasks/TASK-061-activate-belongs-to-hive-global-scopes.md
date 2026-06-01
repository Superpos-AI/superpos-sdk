# TASK-061: Activate BelongsToHive Global Scopes

**Phase:** 4 — Multi-Hive
**Status:** In Progress
**Depends On:** 002 (base traits), 006 (apiary/hive models)
**Branch:** `task/061-activate-belongs-to-hive-global-scopes`

## Objective

Make BelongsToHive (and BelongsToApiary) global scopes always-on in both
CE and Cloud editions, providing consistent hive/apiary isolation at the
query layer regardless of deployment mode.

## Background

Currently, the global scopes that enforce hive and apiary isolation are
only registered when `config('apiary.is_cloud')` is true. In CE mode,
queries run unscoped — relying solely on the fact that only one apiary and
one hive exist. While safe in single-tenant CE, this creates a gap:

- CE queries don't exercise the scoping path, masking bugs that surface
  only in Cloud.
- Any future CE multi-hive support would require retroactively activating
  scopes.
- Defense-in-depth: even single-tenant deployments benefit from query-level
  isolation.

## Design Decisions

1. **Remove cloud-only guard** from `bootBelongsToApiary()` and
   `bootBelongsToHive()` scope registration. The scope closures already
   call `resolveCurrentApiaryId()` / `resolveCurrentHiveId()` which return
   the CE config constants in CE mode — so the scope always resolves to a
   valid ID.

2. **No CE behavior change in practice.** In CE mode, all records have the
   default CE apiary/hive IDs. Adding `WHERE hive_id = CE_HIVE_ID` to
   every query matches all records, producing identical results.

3. **Fail-closed preserved.** In Cloud mode, missing context still triggers
   `WHERE 1 = 0` (returns nothing). In CE mode, context is always available
   from config.

4. **Existing bypass points unchanged.** Code that already calls
   `withoutGlobalScopes()` or `withoutGlobalScope('hive')` continues to
   work as before.

5. **Write-side guards unchanged.** The creating/updating event handlers
   retain their cloud-specific validation logic (e.g., reject null context,
   reject cross-apiary writes).

## Scope

### In Scope

- Remove cloud-only guard from `BelongsToApiary::bootBelongsToApiary()`
- Remove cloud-only guard from `BelongsToHive::bootBelongsToHive()`
- Update existing BelongsToHive/BelongsToApiary feature tests
- Add multi-hive isolation tests

### Out of Scope

- Write-side guard changes (creation/update validation)
- EventSubscription manual scoping (no BelongsToHive trait)
- Dashboard or API controller changes (unaffected — see analysis below)

## Impact Analysis

### Models Affected (BelongsToHive — gets both scopes)

| Model           | CE Impact | Notes |
|-----------------|-----------|-------|
| Agent           | None      | All agents have CE hive_id |
| Task            | None      | All tasks have CE hive_id |
| WebhookRoute    | None      | All routes have CE hive_id |
| ApprovalRequest | None      | All requests have CE hive_id |
| ActionPolicy    | None      | All policies have CE hive_id |

### Models Affected (BelongsToApiary only)

| Model             | CE Impact | Notes |
|-------------------|-----------|-------|
| Hive              | None      | All hives have CE superpos_id |
| ServiceConnection | None      | All connections have CE superpos_id |
| KnowledgeEntry    | None      | All entries have CE superpos_id |
| Event             | None      | All events have CE superpos_id |
| Connector         | None      | All connectors have CE superpos_id |
| ProxyLog          | None      | All logs have CE superpos_id |
| ActivityLog       | None      | All logs have CE superpos_id |

### Why Dashboard/API Controllers Are Unaffected

In CE mode, `resolveCurrentHiveId()` returns `config('apiary.ce.hive_id')`
(never null). All records have this same hive_id. The global scope adds
`WHERE hive_id = 'CE_HIVE_ID'` which matches all records — identical
result set to unscoped queries.

Controllers that already use `withoutGlobalScopes()` continue to work.
Controllers that don't use it see no behavior change in CE mode.

## Test Plan

1. **CE mode: global scope filters by CE hive_id** — verify records with CE
   hive_id are returned, records with other hive_ids are filtered out.
2. **CE mode: global scope filters by CE superpos_id** — same for apiary.
3. **CE mode: withoutGlobalScope bypass** — verify bypass returns all records.
4. **Cloud mode: existing behavior preserved** — verify context-based
   filtering and fail-closed still work.
5. **Multi-hive isolation** — in cloud mode, switch hive context and verify
   records from other hives are invisible.
6. **Regression** — full test suite passes.

## Files Changed

- `app/Traits/BelongsToApiary.php`
- `app/Traits/BelongsToHive.php`
- `tests/Feature/BelongsToHiveTest.php`
- `tests/Feature/BelongsToApiaryTest.php`
- `tests/Feature/MultiHiveIsolationTest.php` (new)
- `docs/tasks/TASK-061-activate-belongs-to-hive-global-scopes.md` (this file)
