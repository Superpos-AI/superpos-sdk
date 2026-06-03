# TASK-048: Dashboard — Proxy Monitor

**Status:** In Progress
**Phase:** 2 — Service Proxy & Security
**Branch:** `task/048-dashboard-proxy-monitor`
**Depends On:** TASK-042 (Service proxy controller), TASK-047 (Approval decision delivery), TASK-022 (Inertia + React)

---

## Objective

Add a dashboard page that displays proxy request logs with filtering, sorting,
pagination, and real-time WebSocket updates. The proxy monitor provides
org-wide visibility into all service access made through the platform proxy.

## Requirements

### 1. ProxyLog Migration & Model

Create the `proxy_log` table (apiary-scoped, as defined in PRODUCT.md):

| Column | Type | Notes |
|--------|------|-------|
| id | BIGSERIAL | PK |
| superpos_id | VARCHAR(26) | NOT NULL |
| hive_id | VARCHAR(26) | nullable |
| agent_id | VARCHAR(26) | NOT NULL |
| service_id | VARCHAR(26) | NOT NULL |
| method | VARCHAR(10) | NOT NULL (GET, POST, etc.) |
| path | TEXT | NOT NULL |
| status_code | SMALLINT | nullable |
| response_time_ms | INTEGER | nullable |
| policy_result | VARCHAR(20) | nullable (allow, deny, require_approval) |
| approval_id | VARCHAR(26) | nullable |
| created_at | TIMESTAMP | DEFAULT NOW() |

Indexes: `(superpos_id, created_at DESC)`, `(hive_id, created_at DESC)`.

Model: `App\Models\ProxyLog` with `BelongsToApiary` trait, immutable (no
updated_at), relationships to Agent, ServiceConnection, ApprovalRequest.
Scopes: `forHive()`, `forAgent()`, `forService()`, `method()`, `recent()`.

### 2. ProxyDashboardController

`app/Http/Controllers/Dashboard/ProxyDashboardController.php`

- `index()` renders `Proxy` Inertia page
- Filters: method (GET/POST/PUT/DELETE/PATCH), status code range, search
- Sort: created_at (default, desc), response_time_ms, method
- Pagination: 20 per page
- Breakdown: method distribution (bar chart data)
- Scoped to current hive (same pattern as ActivityDashboardController)

### 3. Proxy.jsx React Page

`resources/js/Pages/Proxy.jsx`

- Page header: "Proxy Monitor" + description
- Method breakdown bar (color-coded: GET=blue, POST=green, PUT=amber, DELETE=red, PATCH=purple)
- Filter bar: method select, search, sort
- Table: method badge, path, service name, agent name, status code, response time, policy result, time ago
- Pagination (same pattern as Activity page)
- Live updates via `useHiveChannel` listening for `proxy.logged` events
- Empty state with appropriate icon

### 4. Routes & Navigation

- Route: `GET /dashboard/proxy` -> `ProxyDashboardController@index`
- Navigation: add "Proxy" item to AppLayout.jsx sidebar

### 5. Broadcasting (Optional)

Create `ProxyRequestLogged` event for live updates (same pattern as
`ApprovalStatusChanged`). Broadcasts to `hive.{hiveId}` channel.

## Non-Goals

- Proxy request/response body logging (privacy)
- Proxy controller itself (TASK-042)
- Policy engine integration (TASK-044)

## Files

| File | Action |
|------|--------|
| `docs/tasks/TASK-048-dashboard-proxy-monitor.md` | Create |
| `database/migrations/YYYY_create_proxy_log_table.php` | Create |
| `app/Models/ProxyLog.php` | Create |
| `app/Events/ProxyRequestLogged.php` | Create |
| `app/Http/Controllers/Dashboard/ProxyDashboardController.php` | Create |
| `resources/js/Pages/Proxy.jsx` | Create |
| `routes/web.php` | Modify (add route) |
| `resources/js/Layouts/AppLayout.jsx` | Modify (add nav item) |
| `tests/Feature/Dashboard/ProxyDashboardPageTest.php` | Create |

## Test Plan

1. Proxy page returns 200
2. Proxy page renders correct Inertia component
3. Props structure includes entries, methodBreakdown, filters
4. Entry data shape includes all expected fields
5. Filters by HTTP method
6. Searches by path and agent name
7. Sort by created_at (default), response_time_ms
8. Pagination at 20 per page
9. Scoped to current hive
10. Empty state when no entries
11. Invalid sort falls back to created_at
12. Array params are sanitized
