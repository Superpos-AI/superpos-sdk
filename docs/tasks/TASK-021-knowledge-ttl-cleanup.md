# TASK-021: Knowledge TTL Cleanup Job

**Status:** in-progress
**Branch:** `task/021-knowledge-ttl-cleanup`
**PR:** —
**Depends on:** TASK-009 (Knowledge Model)
**Blocks:** —

## Objective

Create a scheduled Artisan command that periodically deletes expired knowledge entries (where `ttl` is non-null and in the past) and logs each deletion via ActivityLogger.

## Requirements

### Functional

- [ ] FR-1: `KnowledgeCleanupService` finds and deletes expired knowledge entries
- [ ] FR-2: Service operates across all apiaries/hives (bypasses global scopes)
- [ ] FR-3: Each deletion is logged via ActivityLogger (`knowledge.expired_cleanup`)
- [ ] FR-4: `apiary:cleanup-expired-knowledge` Artisan command delegates to the service
- [ ] FR-5: Command outputs a summary of deleted entries count
- [ ] FR-6: Scheduled hourly via `bootstrap/app.php` with `withoutOverlapping()`
- [ ] FR-7: Batch deletion for efficiency (configurable batch size)

### Non-Functional

- [ ] NFR-1: PSR-12 compliant
- [ ] NFR-2: Follows existing TaskTimeoutService pattern (thin command, service logic)
- [ ] NFR-3: Uses `withoutGlobalScopes()` for cross-tenant operation
- [ ] NFR-4: Per-entry activity logging with proper apiary/hive context

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Services/KnowledgeCleanupService.php` | Service with cleanup logic |
| Create | `app/Console/Commands/CleanupExpiredKnowledge.php` | Artisan command wrapper |
| Modify | `bootstrap/app.php` | Register hourly schedule |
| Create | `tests/Feature/KnowledgeCleanupTest.php` | Feature tests |
| Create | `docs/tasks/TASK-021-knowledge-ttl-cleanup.md` | Task documentation |

### Key Design Decisions

- Follows the TaskTimeoutService pattern: thin command delegates to service class
- Uses `KnowledgeEntry::expired()` scope (already exists on the model)
- Deletes in batches to avoid memory issues with large datasets
- Activity logging per entry for auditability (apiary + hive context)
- Runs hourly (TTL precision to the hour is sufficient for knowledge entries)
- `withoutOverlapping()` prevents concurrent cleanup runs

## Test Plan

### Feature Tests

- [ ] Expired entries are deleted by the service
- [ ] Non-expired entries are preserved
- [ ] Entries with null TTL are preserved
- [ ] Activity log created for each deleted entry
- [ ] Activity log contains correct superpos_id and hive_id
- [ ] Artisan command executes successfully and outputs count
- [ ] Entries across multiple apiaries/hives are cleaned up
- [ ] Entries expiring exactly now are deleted
- [ ] Mixed batch: some expired, some not — only expired removed

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on every deletion
- [ ] Schedule registered in bootstrap/app.php
