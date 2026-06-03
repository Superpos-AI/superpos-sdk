# TASK-023: Dashboard Home Page

**Status:** done
**Branch:** `task/023-dashboard-home`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/26
**Depends On:** TASK-015 (Agent Heartbeat), TASK-022 (Inertia + React)

## Objective

Build a rich dashboard home page that gives operators an at-a-glance view of
their hive's health: agent fleet status, task pipeline summary, knowledge
store size, and recent activity. Extends the basic stat-card stub from
TASK-022 into a full operational overview.

## Requirements

### Data (Backend)

1. **Agent summary** — counts by status (online, busy, idle, offline, error)
   plus total active count.
2. **Task summary** — counts by status (pending, in_progress, completed,
   failed, cancelled) plus total count.
3. **Knowledge count** — total knowledge entries.
4. **Recent activity** — latest 10 activity log entries with action, agent
   name, task type, and timestamp.
5. **Recent tasks** — latest 5 tasks with type, status, priority, assigned
   agent name, and timestamps.

### UI (Frontend)

1. **Summary stat cards** — four top-level cards: Active Agents, Pending
   Tasks, In-Progress Tasks, Knowledge Entries (preserving existing layout).
2. **Agent status breakdown** — visual breakdown of agent counts per status
   with color-coded indicators.
3. **Task status breakdown** — visual breakdown of task counts per status
   with color-coded indicators.
4. **Recent activity feed** — scrollable list of latest activity entries.
5. **Recent tasks table** — compact table of latest tasks with status badges.
6. **Empty states** — friendly empty-state messages when no data exists.
7. **Responsive layout** — works well on mobile, tablet, and desktop.

### Non-Goals

- Real-time WebSocket updates (TASK-028).
- Full agent/task/knowledge CRUD pages (TASK-024/025/026).
- Charts or time-series graphs (future enhancement).

## Technical Approach

- Enhance `DashboardController::index()` to query all summary data.
- Use Eloquent scopes and relationships for efficient queries.
- Render data via Inertia props — no separate API calls.
- Keep all UI in `Dashboard.jsx` using Tailwind utility classes.
- Match existing dark theme (slate-900/950, amber-500 accent).

## Test Plan

1. **Dashboard returns new props** — verify all new data shapes are present.
2. **Agent status counts** — create agents with different statuses, verify
   breakdown matches.
3. **Task status counts** — create tasks with different statuses, verify
   breakdown matches.
4. **Recent activity** — create activity entries, verify latest 10 returned
   in descending order.
5. **Recent tasks** — create tasks, verify latest 5 returned with related
   agent names.
6. **Empty state** — verify zero counts and empty arrays when no data exists.
7. **Existing tests still pass** — no regressions.

## Files Changed

- `app/Http/Controllers/Dashboard/DashboardController.php`
- `resources/js/Pages/Dashboard.jsx`
- `tests/Feature/Dashboard/DashboardPageTest.php`
- `docs/tasks/TASK-023-dashboard-home.md` (this file)
- `docs/guide/dashboard-home.md`
- `docs/index.md`
