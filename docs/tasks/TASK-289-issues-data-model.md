# TASK-289: Issues data model + tasks.issue_id + IssueType seed

**Status:** in-progress
**Branch:** `task/289-issues-data-model`
**PR:** —
**Depends on:** TASK-288 (merged in PR #603)
**Blocks:** TASK-290
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§4 data model, §10 rollout)

## Objective

Land the schema and Eloquent models for the new **Issues** management
layer (Phase 1 step 2 of 3). This adds:

- four new tables: `issues`, `issue_types`, `issue_dependencies`,
  `issue_links`;
- a nullable `tasks.issue_id` FK (the single canonical link between
  Task and Issue — per spec §4 "Canonical linkage: Tasks → Issues");
- the three default `IssueType` rows (`task`, `bug`, `release`) seeded
  per hive — via a `HiveObserver` for new hives, and a
  `DefaultIssueTypesSeeder` for backfill.

This is **schema + models only**. No HTTP, no state machine, no
controllers, no feature flag, no `cancel_issue` flag. Those land in
TASK-290 (REST API + state machine + blocked-on-human).

## Requirements

### Functional

- [ ] FR-1: `issues`, `issue_types`, `issue_dependencies`,
      `issue_links` tables exist with the columns + indexes + FK
      cascade behavior described in §4 of the spec.
- [ ] FR-2: `tasks.issue_id` exists as a nullable ULID FK to
      `issues.id` with `nullOnDelete`. Issue deletion does **not**
      cascade-delete linked tasks.
- [ ] FR-3: `Issue`, `IssueType`, `IssueDependency`, `IssueLink`
      Eloquent models exist with relations, casts, and `STATES` /
      `CLOSURE_POLICIES` / `DEPENDENCY_KINDS` const arrays
      (referenced by TASK-290's state machine + validation).
- [ ] FR-4: `Task::issue()` BelongsTo and `Issue::tasks()` HasMany
      relations exist. `tasks.issue_id` is in `Task::$fillable`.
- [ ] FR-5: Creating a new `Hive` triggers a `HiveObserver` that
      idempotently creates the three default `IssueType` rows for
      that hive (`task` → `agent_self_close`, `bug` →
      `human_required`, `release` → `gated_by_approval`).
- [ ] FR-6: `DefaultIssueTypesSeeder` backfills the three default
      `IssueType` rows for every existing hive idempotently
      (`DB::table::insertOrIgnore` so it bypasses model events and is
      safe to re-run).
- [ ] FR-7: `BelongsToHive` scope isolates `Issue` and `IssueType`
      rows across hives.

### Non-Functional

- [ ] NFR-1: PSR-12 + Pint clean.
- [ ] NFR-2: ULID primary keys for all four new tables
      (`string('id', 26)->primary()`) — matches Channel pattern.
- [ ] NFR-3: Enums stored as `string(20)` columns with PHP-side
      const arrays — no Postgres native enums, no DB CHECK
      constraints. Matches `tasks.status`.
- [ ] NFR-4: Polymorphic columns use explicit
      `string('{actor}_type', 30)->nullable()` +
      `string('{actor}_id', 26)->nullable()` — matches Channel
      `created_by_*`. Do not use Laravel's `morphs()` macro.
- [ ] NFR-5: All migrations live in `database/migrations/` (shared,
      not cloud-only).

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-289-issues-data-model.md` | This file |
| Create | `database/migrations/2026_05_18_100000_create_issue_types_table.php` | `issue_types` table |
| Create | `database/migrations/2026_05_18_100001_create_issues_table.php` | `issues` table |
| Create | `database/migrations/2026_05_18_100002_create_issue_dependencies_table.php` | `issue_dependencies` table |
| Create | `database/migrations/2026_05_18_100003_create_issue_links_table.php` | `issue_links` table (polymorphic, NOT used for Tasks) |
| Create | `database/migrations/2026_05_18_100004_add_issue_id_to_tasks_table.php` | `tasks.issue_id` FK |
| Create | `app/Models/Issue.php` | Issue model |
| Create | `app/Models/IssueType.php` | IssueType model |
| Create | `app/Models/IssueDependency.php` | IssueDependency model |
| Create | `app/Models/IssueLink.php` | IssueLink model |
| Create | `database/factories/IssueFactory.php` | Issue factory |
| Create | `database/factories/IssueTypeFactory.php` | IssueType factory |
| Create | `database/factories/IssueDependencyFactory.php` | IssueDependency factory |
| Create | `database/factories/IssueLinkFactory.php` | IssueLink factory |
| Create | `app/Observers/HiveObserver.php` | `created(Hive $hive)` seeds the 3 default IssueTypes idempotently |
| Create | `database/seeders/DefaultIssueTypesSeeder.php` | Backfill seeder for pre-existing hives |
| Modify | `app/Models/Task.php` | Add `issue_id` to `$fillable`; add `issue(): BelongsTo` relation |
| Modify | `app/Models/Hive.php` | Add `issues()` + `issueTypes()` HasMany |
| Modify | `app/Providers/AppServiceProvider.php` | Register `Hive::observe(HiveObserver::class)` in `boot()` |
| Modify | `database/seeders/DatabaseSeeder.php` | Call `DefaultIssueTypesSeeder` after `OrganizationSeeder` |
| Modify | `TASKS.md` | Add TASK-289 row under Phase 14 — Issues |

### Decisions (locked in)

1. **Enums as strings, not Postgres native enums** — matches
   `tasks.status`. Adding/removing a state in a future task becomes
   a model-const change rather than a DDL migration. PHP-side
   `STATES`, `CLOSURE_POLICIES`, `DEPENDENCY_KINDS` const arrays
   are defined now so the models are self-documenting.
2. **No DB CHECK constraints on enum columns** — kept enforcement
   in PHP for the same reason as (1). TASK-290 adds validation +
   state-machine guards.
3. **ULID PK + explicit `string('xxx_id', 26)` FK columns** —
   matches Channel pattern (`string('id', 26)->primary()`). Not
   `foreignUlid()`. Adds explicit `foreign(...)->references(...)`
   declarations.
4. **Polymorphic columns are explicit `_type` + `_id` strings** —
   not `morphs()`. Matches `channels.created_by_*`. Lets us choose
   our own type/id length (30/26) and skip the inferred index.
5. **`metadata` / `config` are `jsonb` nullable** — same as Channel
   `resolution` / `linked_refs` / `on_resolve`. Cast to `array` on
   the model.
6. **`IssueDependency` and `IssueLink` do NOT use `BelongsToHive`** —
   they are pure join rows. Hive isolation is inherited via cascade
   FK to the parent `issues` row. Mirrors `channel_messages` /
   `channel_votes`.
7. **`Issue` and `IssueType` use `BelongsToHive`** — which brings
   `BelongsToOrganization` along. `organization_id` is required in
   `$fillable` and auto-populated by the trait's `creating` hook.
8. **No morph map registration in this task** — defer to TASK-290.
   The polymorphic columns work via FQCN. If
   `Relation::enforceMorphMap([...])` already exists somewhere when
   TASK-290 lands, we'll extend it then.
9. **Default `IssueType` seeding via `HiveObserver` + a backfill
   seeder** — observer covers all future `Hive::create()` paths
   (Cloud tenant provisioning, admin UI); the seeder covers
   pre-existing hives. The seeder is idempotent
   (`DB::table::insertOrIgnore`) and bypasses model events so it is
   safe to re-run.
10. **`tasks.issue_id` is `nullOnDelete`, not cascade** — deleting
    an Issue should not destroy its execution history. Matches
    `tasks.channel_id` and `tasks.thread_id`.
11. **`issue_links` is NOT used for Tasks** — explicit per spec §4.
    The `Task::issue()` direct-FK relation is the single source of
    truth for the Tasks ↔ Issues link.
12. **Shared edition** — migrations go in `database/migrations/`,
    not `database/migrations/cloud/`. Issues exists in both CE
    (single hive) and Cloud (multi-tenant).

### Schema (per spec §4)

```text
issue_types
  id (ulid, pk)
  organization_id (ulid, fk -> organizations.id, cascade)
  hive_id (ulid, fk -> hives.id, cascade, indexed)
  key (string(50))
  label (string(100))
  closure_policy (string(30))  -- agent_self_close | human_required | gated_by_approval
  default_assignee_type (string(30), nullable)
  default_assignee_id (string(26), nullable)
  config (jsonb, nullable)
  timestamps
  unique (hive_id, key)

issues
  id (ulid, pk)
  organization_id (ulid, fk -> organizations.id, cascade)
  hive_id (ulid, fk -> hives.id, cascade, indexed)
  issue_type_id (ulid, fk -> issue_types.id, restrict)
  title (string(255))
  description (text, nullable)
  state (string(30), default 'open')  -- see Issue::STATES
  assignee_type (string(30), nullable)
  assignee_id (string(26), nullable)
  created_by_type (string(30), nullable)
  created_by_id (string(26), nullable)
  thread_id (string(26), fk -> threads.id, nullOnDelete, nullable)
  channel_id (string(26), fk -> channels.id, nullOnDelete, nullable)
  closed_by_type (string(30), nullable)
  closed_by_id (string(26), nullable)
  closed_at (timestamp, nullable)
  closure_reason (string(255), nullable)
  metadata (jsonb, nullable)
  timestamps
  index (hive_id, state)
  index (hive_id, issue_type_id)
  index (hive_id, updated_at)
  index (assignee_type, assignee_id)

issue_dependencies
  id (ulid, pk)
  issue_id (ulid, fk -> issues.id, cascade)
  depends_on_issue_id (ulid, fk -> issues.id, cascade)
  kind (string(20), default 'blocks')  -- blocks | related
  timestamps
  unique (issue_id, depends_on_issue_id)
  index (depends_on_issue_id)

issue_links
  id (ulid, pk)
  issue_id (ulid, fk -> issues.id, cascade)
  linkable_type (string(50))
  linkable_id (string(26))
  role (string(50), nullable)
  created_at (no updated_at — append-only)
  index (linkable_type, linkable_id)
  index (issue_id, linkable_type)

tasks (added column)
  issue_id (string(26), fk -> issues.id, nullOnDelete, nullable, indexed)
```

## Test Plan

### Feature tests

- `tests/Feature/Migrations/IssuesMigrationTest.php` —
  `migrate:fresh` then `migrate:rollback` round-trip; assert all
  5 schema additions appear and disappear.
- `tests/Feature/Seeders/DefaultIssueTypesSeederTest.php` —
  running the seeder twice produces exactly 3 rows per hive;
  `Hive::create()` triggers the observer and creates 3 rows for
  the new hive.

### Unit tests

- `tests/Unit/Models/IssueTest.php` — factory persists, ULID
  generated, casts hydrate `metadata`, `BelongsToHive` isolation
  works between two hives.
- `tests/Unit/Models/IssueTypeTest.php` — factory works; unique
  `(hive_id, key)` enforced; cross-hive duplicate `key` allowed.
- `tests/Unit/Models/IssueDependencyTest.php` — cascade delete
  when parent issue deleted; unique
  `(issue_id, depends_on_issue_id)`.
- `tests/Unit/Models/IssueLinkTest.php` — polymorphic `linkable()`
  resolves to a Channel; cascade on issue delete.
- `tests/Unit/Models/TaskIssueLinkTest.php` — `Task::issue()`
  returns the issue; `Issue::tasks()` returns linked tasks;
  deleting an issue sets `tasks.issue_id = null` (not cascade).

## Out of Scope (deferred to TASK-290)

- Issue state machine (`IssueStateMachine` service + transition
  validation, `ActivityLog` emission, `422` on invalid transitions).
- REST API endpoints (`IssuesController`, FormRequests, routes).
- `IssuePolicy` (authorization).
- `IssueClosureResolver` (most-restrictive-wins resolution for
  agent self-close — spec §6).
- `cancel_issue` flag on `.../deny` (couples to denial of
  Issue-linked approvals — TASK-290).
- `features.issues_enabled` feature flag (gates routes — TASK-290).
- `agents.issue_trust_score` column + trust-modifier logic
  (spec §6).
- Morph-map registration for the polymorphic columns (defer to
  TASK-290 when the API surfaces these as user-visible discriminators).

## Validation Checklist

- [ ] All new tests pass (`php artisan test --filter=Issue` +
      `php artisan test --filter=DefaultIssueTypes`).
- [ ] Full suite green (`php artisan test`).
- [ ] PSR-12 / Pint clean on every touched PHP file.
- [ ] `migrate:fresh` succeeds on sqlite (in-memory test driver).
- [ ] `migrate:rollback` cleanly reverses all five migrations.
- [ ] No new feature flag, no new route, no new controller, no
      state machine service — those are TASK-290.
