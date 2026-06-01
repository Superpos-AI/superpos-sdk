# TASK-071: Dashboard Cross-Hive Monitor

**Status:** In Progress
**Branch:** `task/071-dashboard-cross-hive-monitor`
**Depends On:** 067, 068, 022

## Summary

Add a dashboard page that monitors cross-hive activity across the current
apiary: cross-hive tasks, cross-hive events, and cross-hive agent permissions.

## Requirements

1. **Apiary-scoped controller** (`CrossHiveMonitorDashboardController`)
   - Resolves current apiary ID (not hive — this is an apiary-level view)
   - Returns cross-hive tasks (source_hive_id IS NOT NULL AND source_hive_id != hive_id)
   - Returns cross-hive events (is_cross_hive = true)
   - Returns cross-hive permission summary (agent_permissions LIKE 'cross_hive:%')
   - Breakdown by event type and task status

2. **CE mode fail-closed**
   - CE has one hive → no cross-hive activity is possible
   - Return empty datasets with proper pagination structure

3. **Tenant-safe scoping**
   - All queries scoped to current superpos_id
   - Cross-apiary data never exposed

4. **Filtering, pagination, input sanitization**
   - Tab filter: tasks | events | permissions (default: tasks)
   - Search across agent names, task types, event types
   - Sort: created_at (default, desc), type/status (asc)
   - 20 items per page with standard pagination metadata
   - Non-scalar query params rejected (array injection)

5. **React page + sidebar integration**
   - `CrossHiveMonitor.jsx` page component
   - Tab-based UI for tasks/events/permissions
   - Sidebar nav entry with GitCompare icon
   - Standard empty state, pagination, filter bar

6. **Route**
   - `GET /dashboard/cross-hive` → `CrossHiveMonitorDashboardController@index`

## Test Plan

- [ ] Page returns 200
- [ ] Renders correct Inertia component
- [ ] Props structure (entries, breakdown, filters, permissions)
- [ ] Entry data shapes for tasks, events, permissions
- [ ] CE mode returns empty data
- [ ] Tenant isolation (cross-apiary data excluded)
- [ ] Cross-apiary exclusion in breakdown
- [ ] Filtering by tab (tasks/events/permissions)
- [ ] Search filtering
- [ ] Pagination (20 per page)
- [ ] Invalid sort falls back to default
- [ ] Array params sanitized
- [ ] Only cross-hive tasks shown (not same-hive tasks)
- [ ] Only cross-hive events shown (not hive-scoped events)

## Files

- `app/Http/Controllers/Dashboard/CrossHiveMonitorDashboardController.php`
- `resources/js/Pages/CrossHiveMonitor.jsx`
- `routes/web.php` (add route)
- `resources/js/Layouts/AppLayout.jsx` (add nav item)
- `tests/Feature/Dashboard/CrossHiveMonitorDashboardTest.php`
- `docs/tasks/TASK-071-dashboard-cross-hive-monitor.md`
