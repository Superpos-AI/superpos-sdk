# TASK-269: Database Migration — Rename tables & columns

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** —
**Blocks:** TASK-270, TASK-271, TASK-272, TASK-273, TASK-274, TASK-275

## Objective

Create a single reversible migration to rename the `apiaries` table to
`organizations` and the `superpos_id` column to `organization_id` across all 35
tables. No production data exists, so `Schema::rename()` and `renameColumn()`
are safe to use without data-migration logic.

## Requirements

### Functional

- [ ] FR-1: Rename `apiaries` table to `organizations`
- [ ] FR-2: Rename `superpos_id` to `organization_id` in all 35 tables: agents, action_policies, activity_log, agent_permissions, agent_personas, approval_requests, attachments, channel_messages, channel_participants, channel_tasks, channel_votes, channels, connectors, events, hives, hosted_agent_deployments, hosted_agents, inbox_log, inboxes, knowledge_entries, llm_usage_logs, marketplace_personas, notification_delivery_log, notification_endpoints, persona_experiments, platform_contexts, proxy_log, service_connections, task_idempotency, task_schedules, tasks, thread_messages, threads, webhook_routes, workflow_runs, workflows
- [ ] FR-3: Update all foreign key constraints to reference `organizations(id)` and use the new column name `organization_id`
- [ ] FR-4: Rename all indexes that reference the old table or column names

### Non-Functional

- [ ] NFR-1: Single migration file, fully reversible with `down()` method
- [ ] NFR-2: Migration must run cleanly on a fresh database and on an existing dev database
- [ ] NFR-3: No data transformation logic needed (no production data)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/2026_04_20_000001_rename_apiary_to_organization.php` | Single migration renaming table and all columns |

### Key Design Decisions

- **Single migration file**: All renames in one atomic migration so rollback is all-or-nothing. Prevents partial rename states.
- **Schema::rename() for table**: Laravel's built-in table rename — clean and reversible.
- **renameColumn() for columns**: Doctrine DBAL handles the underlying ALTER TABLE. Each of the 35 tables gets a `renameColumn('superpos_id', 'organization_id')` call.
- **Foreign key and index renames**: Drop old FK constraints and recreate with new names, or use raw SQL `ALTER INDEX ... RENAME TO ...` for PostgreSQL. The `down()` method reverses all operations.
- **No production data**: Since the platform has no production data, there is no need for a staged migration or temporary dual-column approach.

## Implementation Plan

1. Create the migration file `2026_04_20_000001_rename_apiary_to_organization.php`
2. In `up()`: rename `apiaries` table to `organizations` using `Schema::rename()`
3. In `up()`: iterate over all 35 tables and call `renameColumn('superpos_id', 'organization_id')` on each
4. In `up()`: drop old foreign key constraints and recreate them pointing to `organizations(id)` with updated constraint names
5. In `up()`: rename any indexes that contain `apiary` in their name
6. In `down()`: reverse all operations — rename columns back, rename table back, restore original FK and index names
7. Run `php artisan migrate` on a fresh database to validate
8. Run `php artisan migrate:rollback` to validate reversibility

## Database Changes

```sql
-- Table rename
ALTER TABLE apiaries RENAME TO organizations;

-- Column renames (repeated for each of 35 tables)
ALTER TABLE hives RENAME COLUMN superpos_id TO organization_id;
ALTER TABLE agents RENAME COLUMN superpos_id TO organization_id;
ALTER TABLE tasks RENAME COLUMN superpos_id TO organization_id;
-- ... (35 tables total)

-- Foreign key constraint updates
ALTER TABLE hives DROP CONSTRAINT hives_apiary_id_foreign;
ALTER TABLE hives ADD CONSTRAINT hives_organization_id_foreign
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
-- ... (repeated for each table with FK)
```

## API Changes

_None — this is a schema-only change. API changes follow in later tasks._

## Test Plan

### Feature Tests

- [ ] Migration runs without errors on fresh database
- [ ] `organizations` table exists after migration
- [ ] `apiaries` table no longer exists after migration
- [ ] All 35 tables have `organization_id` column and no `superpos_id` column
- [ ] Foreign key constraints reference `organizations(id)`
- [ ] Rollback restores `apiaries` table and `superpos_id` columns
- [ ] Unique/composite indexes still function (e.g., hives unique on org_id + slug)

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on state changes — N/A (migration only)
- [ ] API responses use `{ data, meta, errors }` envelope — N/A
- [ ] Form Request validation on all inputs — N/A
- [ ] ULIDs for primary keys (existing, unchanged)
- [ ] BelongsToApiary/BelongsToHive traits — updated in TASK-270
- [ ] No credentials logged in plaintext
