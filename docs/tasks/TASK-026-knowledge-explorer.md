# TASK-026: Knowledge Explorer Page

**Status:** review
**Branch:** `task/026-knowledge-explorer`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/31
**Depends on:** TASK-020, TASK-022
**Blocks:** —

## Objective

Add a dedicated knowledge explorer page at `/dashboard/knowledge` with a
paginated table showing all knowledge entries, scope-aware visibility
(hive/apiary/agent), search, filtering, and sorting.

## Requirements

### Functional

- [x] FR-1: Page renders at `/dashboard/knowledge` via Inertia
- [x] FR-2: Knowledge entries displayed in a paginated table (20 per page)
- [x] FR-3: Scope filter dropdown (All / Hive / Superpos / Agent)
- [x] FR-4: Search filters entries by key and value content
- [x] FR-5: Sort options: newest (default), key, scope
- [x] FR-6: Each row shows key, scope badge, visibility, creator name, version, TTL status, and relative time
- [x] FR-7: Scope breakdown bar at top (reuses shared StatusBar-style component)
- [x] FR-8: Sidebar "Knowledge" link is active (no longer "Coming Soon")
- [x] FR-9: Empty state when no entries exist
- [x] FR-10: Expired entries are excluded (consistent with Knowledge API)

### Non-Functional

- [x] NFR-1: Cross-driver compatible queries (whereLike, not ilike)
- [x] NFR-2: Scope-aware visibility (CE mode shows all entries)
- [x] NFR-3: All counts cast to integer
- [x] NFR-4: ISO8601 date serialization
- [x] NFR-5: Responsive table (horizontal scroll on small screens)
- [x] NFR-6: Input sanitization (reject non-scalar query params)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Http/Controllers/Dashboard/KnowledgeDashboardController.php` | Knowledge explorer controller |
| Modify | `routes/web.php` | Register `/dashboard/knowledge` route |
| Modify | `resources/js/Layouts/AppLayout.jsx` | Remove `comingSoon` from Knowledge nav |
| Create | `resources/js/Pages/Knowledge.jsx` | Knowledge explorer React page |
| Create | `tests/Feature/Dashboard/KnowledgeDashboardPageTest.php` | Feature tests |
| Create | `docs/guide/knowledge-explorer.md` | Feature documentation |
| Modify | `docs/index.md` | Add guide link |
| Modify | `tests/Feature/Dashboard/SidebarNavigationTest.php` | Remove `/dashboard/knowledge` from unimplemented routes |

### Key Design Decisions

- **Table layout over Kanban:** Knowledge entries don't have a status lifecycle;
  a table with sorting and pagination is the natural UI for browsing key-value data
- **Scope breakdown instead of status:** The primary grouping dimension for
  knowledge is scope (hive/apiary/agent), not status
- **Exclude expired entries:** Consistent with Knowledge API behavior; dashboard
  shows only live entries
- **Paginated (20 per page):** Follows Agents dashboard pattern; prevents loading
  unbounded data
- **CE mode shows all entries:** No strict tenant isolation needed in CE mode;
  all entries in the default apiary are visible

## Implementation Plan

1. Create `KnowledgeDashboardController` with paginated query, scope filter, search, sort
2. Register route and remove sidebar comingSoon flag
3. Create `Knowledge.jsx` with table layout, filter bar, pagination
4. Create feature tests
5. Create VitePress documentation and update index
6. Update task file and sidebar navigation test

## Test Plan

### Feature Tests

- [x] Page returns 200
- [x] Renders `Knowledge` Inertia component
- [x] Includes `entries` prop with pagination structure
- [x] Includes `scopeBreakdown` with hive/apiary/agent counts
- [x] Includes `filters` prop (scope, search, sort)
- [x] Entries appear with correct data shape
- [x] Filters by scope (hive)
- [x] Filters by scope (agent)
- [x] Filters by search on key
- [x] Sorts by key (ascending)
- [x] Default sort is `updated_at` descending
- [x] Pagination limits to 20 per page
- [x] Includes creator name from relationship
- [x] Returns empty entries when none exist
- [x] Scope breakdown counts are integers
- [x] Expired entries are excluded
- [x] Invalid sort falls back to `updated_at`
- [x] Array search param is ignored
- [x] Array scope param is ignored

## Validation Checklist

- [ ] All tests pass (`php artisan test --filter=KnowledgeDashboardPageTest`)
- [ ] PSR-12 compliant
- [ ] Cross-driver queries (whereLike)
- [ ] ULIDs for primary keys
- [ ] No credentials logged in plaintext
