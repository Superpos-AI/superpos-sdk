# TASK-025: Tasks Dashboard (Kanban Board)

**Status:** review
**Branch:** `task/025-tasks-kanban`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/30
**Depends on:** TASK-016, TASK-017, TASK-018, TASK-022
**Blocks:** —

## Objective

Add a dedicated tasks dashboard page at `/dashboard/tasks` with a Kanban board
layout, showing tasks grouped by status columns with search, sorting, and
priority filtering.

## Requirements

### Functional

- [ ] FR-1: Page renders at `/dashboard/tasks` via Inertia
- [ ] FR-2: Tasks displayed in Kanban columns grouped by status (pending, in_progress, completed, failed, cancelled)
- [ ] FR-3: Each column shows up to 20 tasks with overflow indicator
- [ ] FR-4: Task cards display type, priority, progress bar, claimed agent, and relative time
- [ ] FR-5: Search filters tasks by type and status_message across all columns
- [ ] FR-6: Priority filter shows only tasks of a given priority (0-4)
- [ ] FR-7: Sort options: newest (default), priority, type
- [ ] FR-8: Status breakdown bar at top (reuses shared StatusBar component)
- [ ] FR-9: Sidebar "Tasks" link is active (no longer "Coming Soon")

### Non-Functional

- [ ] NFR-1: Cross-driver compatible queries (whereLike, not ilike)
- [ ] NFR-2: Hive-scoped via BelongsToHive trait
- [ ] NFR-3: All counts cast to integer
- [ ] NFR-4: ISO8601 date serialization
- [ ] NFR-5: Responsive Kanban board (horizontal scroll on small screens)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Models/Task.php` | Add `STATUSES` constant |
| Create | `app/Http/Controllers/Dashboard/TaskDashboardController.php` | Kanban data controller |
| Modify | `routes/web.php` | Register `/dashboard/tasks` route |
| Modify | `resources/js/Layouts/AppLayout.jsx` | Remove `comingSoon` from Tasks nav |
| Create | `resources/js/Pages/Tasks.jsx` | Kanban board React page |
| Modify | `tests/Feature/Dashboard/SidebarNavigationTest.php` | Remove `/dashboard/tasks` from unimplemented list |
| Create | `tests/Feature/Dashboard/TaskDashboardPageTest.php` | 19 feature tests |
| Create | `docs/guide/tasks-dashboard.md` | Feature documentation |
| Modify | `docs/index.md` | Add guide link |

### Key Design Decisions

- **Kanban layout over table:** Tasks have clear status lifecycle; columns make
  state distribution immediately visible compared to a flat table
- **Per-column limit of 20:** Prevents loading all tasks; each column reports
  total count so the UI can show "Showing 20 of 47"
- **Grouped-by-status data model:** Controller returns `columns` object keyed by
  status instead of flat paginated list, since Kanban columns are independent
- **Priority filter replaces status filter:** Status is already represented by
  Kanban columns; priority is the useful cross-column filter
- **Read-only board:** No drag-and-drop; task state changes are API-only

## Implementation Plan

1. Add `Task::STATUSES` constant to model
2. Create `TaskDashboardController` with grouped query per status
3. Register route and remove sidebar comingSoon flag
4. Create `Tasks.jsx` with Kanban column layout
5. Update `SidebarNavigationTest` to remove `/dashboard/tasks` from 404 list
6. Create 19 feature tests
7. Create documentation and task file

## Test Plan

### Feature Tests

- [ ] Page returns 200
- [ ] Renders `Tasks` Inertia component
- [ ] Includes `columns` prop with all 5 statuses
- [ ] Each column has `tasks`, `total`, `showing` structure
- [ ] Includes `statusBreakdown` with all 5 statuses
- [ ] Includes `filters` prop (search, sort, priority)
- [ ] Tasks appear in correct status columns
- [ ] Excludes tasks from other hives (scoping)
- [ ] Filters by search on type field
- [ ] Filters by priority
- [ ] Sorts by priority (descending)
- [ ] Sorts by type (ascending)
- [ ] Default sort is `created_at` descending
- [ ] Per-column limit of 20 (25 created, 20 shown, total=25)
- [ ] Includes `claimed_by_name` from relationship
- [ ] Returns empty columns when no tasks
- [ ] Status breakdown counts are integers
- [ ] Task data shape has all expected fields
- [ ] Invalid sort falls back to `created_at`

## Validation Checklist

- [ ] All tests pass (`php artisan test --filter=TaskDashboardPageTest`)
- [ ] PSR-12 compliant
- [ ] Cross-driver queries (whereLike)
- [ ] BelongsToHive trait scoping
- [ ] ULIDs for primary keys
- [ ] No credentials logged in plaintext
