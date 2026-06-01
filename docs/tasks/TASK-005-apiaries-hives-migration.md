# TASK-005: Apiaries & Hives Migrations + Seeder

**Status:** done
**Branch:** `task/005-apiaries-hives-migration`
**PR:** [#5](https://github.com/Superpos-AI/superpos-app/pull/5)
**Depends on:** TASK-001, TASK-002
**Blocks:** TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-031

## Objective

Create the database migrations for the `apiaries` and `hives` tables (the two
foundational tables in the Superpos hierarchy) and a seeder that provisions the
default CE apiary and hive using the stable ULIDs from `config('apiary.ce.*')`.

## Requirements

### Functional

- [x] FR-1: `apiaries` migration creates table per PRODUCT.md schema with ULID primary key
- [x] FR-2: `hives` migration creates table per PRODUCT.md schema with ULID primary key and foreign key to apiaries
- [x] FR-3: CE seeder inserts default apiary using `config('apiary.ce.superpos_id')`
- [x] FR-4: CE seeder inserts default hive using `config('apiary.ce.hive_id')` linked to default apiary
- [x] FR-5: Seeder is idempotent (safe to run multiple times)
- [x] FR-6: Cloud-only columns (stripe_*, trial_ends_at) are nullable

### Non-Functional

- [x] NFR-1: PSR-12 compliant
- [x] NFR-2: ULIDs for all primary keys (VARCHAR(26))
- [x] NFR-3: Proper indexes on slug, superpos_id, and composite unique constraints
- [x] NFR-4: Works with SQLite (testing) and PostgreSQL (production)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/0001_01_01_000010_create_apiaries_table.php` | Apiaries table migration |
| Create | `database/migrations/0001_01_01_000011_create_hives_table.php` | Hives table migration |
| Create | `database/seeders/ApiarySeeder.php` | Default CE apiary + hive seeder |
| Modify | `database/seeders/DatabaseSeeder.php` | Call ApiarySeeder |
| Create | `tests/Feature/ApiariesHivesMigrationTest.php` | Migration & seeder integration tests |

### Key Design Decisions

- **Migration filename prefix `0001_01_01_*`**: Matches existing Laravel baseline convention; uses `000010`/`000011` to sort after framework tables but before future Superpos migrations.
- **VARCHAR(26) for ULID PKs**: Not auto-increment — matches ULID convention from CLAUDE.md.
- **owner_id references users(id)**: Foreign key to Laravel's default users table. Nullable for CE mode (CE may not require a user owner initially); `nullOnDelete` preserves apiary if owner is removed.
- **Cloud columns nullable**: `stripe_customer_id`, `stripe_subscription_id`, `trial_ends_at` are nullable — unused in CE mode.
- **settings as JSON**: Uses Laravel's `json()` column type (maps to JSONB on PostgreSQL, TEXT on SQLite).
- **Composite unique on hives**: `UNIQUE(superpos_id, slug)` ensures slugs unique within an apiary.
- **Idempotent seeder**: Insert-only (raw DB, no model dependency) — if bootstrap rows exist they are left untouched so user-customized data is never overwritten on reseed.
- **Raw DB in seeder**: Avoids dependency on Superpos/Hive model classes (created in TASK-006).

## Implementation Plan

1. Create apiaries migration with all columns, indexes, and constraints
2. Create hives migration with foreign key to apiaries
3. Create ApiarySeeder that provisions CE defaults
4. Update DatabaseSeeder to call ApiarySeeder before user seeding
5. Write feature tests for migration schema and seeder behavior
6. Run full test suite, verify zero new failures

## Database Changes

### apiaries table

| Column | Type | Constraints |
|--------|------|-------------|
| id | VARCHAR(26) | PRIMARY KEY (ULID) |
| name | VARCHAR(255) | NOT NULL |
| slug | VARCHAR(100) | NOT NULL, UNIQUE |
| plan | VARCHAR(20) | DEFAULT 'free' |
| owner_id | BIGINT UNSIGNED | NULLABLE, FK → users(id) SET NULL |
| settings | JSON | DEFAULT '{}' |
| stripe_customer_id | VARCHAR(255) | NULLABLE |
| stripe_subscription_id | VARCHAR(255) | NULLABLE |
| trial_ends_at | TIMESTAMP | NULLABLE |
| created_at | TIMESTAMP | NULLABLE |
| updated_at | TIMESTAMP | NULLABLE |

### hives table

| Column | Type | Constraints |
|--------|------|-------------|
| id | VARCHAR(26) | PRIMARY KEY (ULID) |
| superpos_id | VARCHAR(26) | NOT NULL, FK → apiaries(id) CASCADE |
| name | VARCHAR(255) | NOT NULL |
| slug | VARCHAR(100) | NOT NULL |
| description | TEXT | NULLABLE |
| settings | JSON | DEFAULT '{}' |
| is_active | BOOLEAN | DEFAULT TRUE |
| created_at | TIMESTAMP | NULLABLE |
| updated_at | TIMESTAMP | NULLABLE |
| | | UNIQUE(superpos_id, slug) |

## API Changes

_None._

## Test Plan

### Feature Tests

- [x] Apiaries table exists after migration
- [x] Apiaries table has all expected columns
- [x] Hives table exists after migration
- [x] Hives table has all expected columns
- [x] Unique index enforced on apiaries(slug)
- [x] Composite unique enforced on hives(superpos_id, slug)
- [x] Same slug allowed in different apiaries
- [x] Cascade delete: deleting apiary removes child hives
- [x] CE seeder creates default apiary with config ULID
- [x] CE seeder creates default hive with config ULID linked to default apiary
- [x] Seeder is idempotent (running twice produces same result)
- [x] Seeder uses stable config ULIDs (assertions are config-driven)
- [x] Reseed preserves user-customized apiary/hive data
- [x] apiaries.plan defaults to 'free'
- [x] Cloud-only columns are nullable
- [x] hives.is_active defaults to true

## Validation Checklist

- [x] All TASK-005 tests pass (`php artisan test --filter=ApiariesHivesMigrationTest`)
- [x] PSR-12 compliant
- [ ] Activity logging on state changes — N/A (no runtime state changes)
- [ ] API responses use `{ data, meta, errors }` envelope — N/A
- [ ] Form Request validation on all inputs — N/A
- [x] ULIDs for primary keys
- [ ] BelongsToApiary/BelongsToHive traits — N/A (models in TASK-006)
- [x] No credentials logged in plaintext

## Test Evidence

```
  Tests:    16 passed (52 assertions) — ApiariesHivesMigrationTest
  Duration: 0.36s
```

Full suite: 34 passed, 16 new passed, 1 pre-existing failure (ExampleTest — missing APP_KEY, to be fixed by TASK-004 `.env.testing`).

New tests added: 16 (ApiariesHivesMigrationTest)
