# TASK-027: Activity Feed Page

## Status
Review

## PR
https://github.com/Superpos-AI/superpos-app/pull/32

## Description
Build a dashboard page that displays the activity log as a paginated, filterable
feed. Users can search, filter by action type, and sort entries to review what
agents and tasks have been doing across the hive.

## Dependencies
- TASK-010 Activity log migration + model (done)
- TASK-011 ActivityLogger service (done)
- TASK-022 Inertia.js + React + layout (done)

## Requirements

### Route & Controller
- `GET /dashboard/activity` served by `ActivityDashboardController`
- Named route: `dashboard.activity`
- Server-side filtering, sorting, and pagination via Inertia props

### Filters
| Control | Type     | Options |
|---------|----------|---------|
| Action  | Dropdown | All / dynamic from data |
| Search  | Text     | Partial match on action, agent name, task type |
| Sort    | Dropdown | Newest (default) / Oldest / Action |

### Data Shape
Each activity entry includes:
- `id` (bigint PK)
- `action` (string)
- `agent_name` (nullable — from agent relationship)
- `task_type` (nullable — from task relationship)
- `task_id` (nullable)
- `details` (JSONB object)
- `created_at` (ISO 8601 timestamp)

### Action Breakdown
A summary bar showing per-action counts (similar to scope breakdown on knowledge page).

### Pagination
- 20 entries per page
- Previous/Next pagination controls
- Query string preserved across pages

### Scoping & Isolation
- CE mode: scoped to the default hive via `resolveCurrentHiveId()`
- Cloud mode: BelongsToApiary global scope enforces tenant isolation;
  additionally scoped to current hive via `forHive()` query scope
- Fail closed: return empty feed if hive context is missing

### Empty / Loading States
- Empty state: "No activity recorded yet."
- Graceful handling of null agent/task relationships

### Sidebar Navigation
- Enable the existing "Activity" nav item (remove `comingSoon: true`)

## Test Plan
- Page returns HTTP 200
- Inertia component is `Activity`
- Props include `entries` (paginated), `actionBreakdown`, `filters`
- Entry data shape matches spec
- Filter by action
- Search by action/agent name
- Sort by created_at asc/desc and action
- Default sort is newest first
- Pagination at 20 per page
- Empty state (no entries)
- Invalid sort falls back to default
- Array query params are sanitized
- Cloud mode: tenant isolation on list and breakdown
- Hive scoping: entries from other hives are excluded

## Files to Create / Modify
- `app/Http/Controllers/Dashboard/ActivityDashboardController.php` (new)
- `resources/js/Pages/Activity.jsx` (new)
- `routes/web.php` (add route)
- `resources/js/Layouts/AppLayout.jsx` (enable nav item)
- `tests/Feature/Dashboard/ActivityDashboardPageTest.php` (new)
- `docs/guide/activity-feed.md` (new)
- `docs/index.md` (add guide link)
