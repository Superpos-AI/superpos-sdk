# TASK-069: Apiary-Scoped Knowledge

**Status:** In Progress
**Depends On:** TASK-009 (Knowledge entries migration + model), TASK-065 (Cross-hive permission middleware)
**Branch:** `task/069-apiary-scoped-knowledge`

## Summary

Harden and complete apiary-scoped knowledge entry support. The schema and basic
permission model already exist (TASK-009, TASK-020); this task enforces strict
tenant safety, adds apiary-level broadcasting, enriches activity logs with
cross-hive context, and provides comprehensive test coverage for cross-apiary
isolation and fail-closed behavior.

## Requirements

1. **Apiary-level broadcasting**: When apiary-scoped knowledge entries are
   created, updated, or deleted, broadcast to `PrivateChannel("apiary.{apiaryId}")`
   so all hives in the apiary receive real-time updates.

2. **Activity log enrichment**: Include `source_hive_id` in activity logs for
   operations performed in a cross-hive context, enabling audit trail tracing.

3. **Cross-apiary isolation**: Verify (via tests) that agents from one apiary
   can never read, write, update, or search apiary-scoped entries belonging to
   a different apiary. Fail-closed on any ambiguity.

4. **Cross-hive visibility**: Apiary-scoped entries must be visible from any
   hive within the same apiary without requiring cross-hive permissions (since
   the agent accesses their own hive route).

5. **Permission enforcement**: `knowledge.write_apiary` required for all
   mutations (create, update, delete) of apiary-scoped entries.

6. **Fail-closed scope validation**: Unknown scope values must be rejected with
   422. The visibility filter must only include explicitly recognized scopes.

## Implementation Plan

### KnowledgeEntryChanged event
- Add `apiaryId` property (nullable)
- Modify `fromEntry()` to capture `superpos_id`
- Modify `broadcastOn()` to return `apiary.{apiaryId}` channel when scope is `apiary`

### KnowledgeController
- In `store()`, `update()`, `destroy()`: broadcast apiary-scoped changes (not just hive-scoped)
- Add `source_hive_id` to activity logs when `is_cross_hive` is set

### Test Plan
- Cross-apiary isolation: apiary-scoped entries invisible to other apiaries
- Cross-apiary isolation: search does not leak apiary-scoped entries
- Cross-apiary isolation: show/update/delete rejected for other apiaries
- Apiary-scoped entries visible from any hive in same apiary (list + search)
- Apiary-scoped CRUD requires `knowledge.write_apiary`
- Apiary-scoped update/delete from different hive (same apiary) with proper permissions
- TTL on apiary-scoped entries
- Broadcasting to apiary channel for apiary-scoped changes
- Fail-closed: unknown scope rejected
- Activity log includes source_hive_id for cross-hive operations

## Files Changed
- `app/Events/KnowledgeEntryChanged.php`
- `app/Http/Controllers/Api/KnowledgeController.php`
- `tests/Feature/ApiaryKnowledgeScopeTest.php` (new)
- `docs/tasks/TASK-069-apiary-scoped-knowledge.md` (this file)
