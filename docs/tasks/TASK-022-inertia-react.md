# TASK-022: Install Inertia.js + React + Shared Layout

**Status:** done
**Branch:** `task/022-inertia-react`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/24
**Depends On:** — (no dependencies)
**Unlocks:** 023, 024, 025, 026, 027, 028 (all dashboard pages)

## Requirements

Install the frontend foundation for the Superpos dashboard:

1. **Inertia.js integration** — server-side adapter (`inertiajs/inertia-laravel`) with `HandleInertiaRequests` middleware sharing apiary/hive context
2. **React integration** — `@inertiajs/react`, `react`, `react-dom` with Vite React plugin
3. **Root Blade template** — `resources/views/app.blade.php` with `@inertia`, `@viteReactRefresh`, `@inertiaHead`
4. **React entry point** — `resources/js/app.jsx` with `createInertiaApp`
5. **Shared AppLayout** — sidebar navigation, hive indicator, responsive, dark theme matching existing CSS
6. **Starter Dashboard page** — stat cards (agents, tasks, knowledge) proving end-to-end rendering
7. **DashboardController** — queries aggregate counts, renders via `Inertia::render`
8. **Dashboard web routes** — `GET /dashboard`
9. **Build tooling** — Vite builds successfully with React + Tailwind
10. **Tests** — Inertia assertion tests verifying component, props, shared data

## Implementation

### PHP
- `composer require inertiajs/inertia-laravel`
- `app/Http/Middleware/HandleInertiaRequests.php` — extends `Inertia\Middleware`, shares `apiary` and `hive` props from config
- `app/Http/Controllers/Dashboard/DashboardController.php` — queries Agent, Task, KnowledgeEntry counts
- `bootstrap/app.php` — registers `HandleInertiaRequests` on web middleware stack
- `routes/web.php` — adds `/dashboard` route group

### JavaScript
- `npm install @inertiajs/react react react-dom && npm install -D @vitejs/plugin-react`
- `resources/js/app.jsx` — Inertia app initialization with eager page resolution
- `resources/js/Layouts/AppLayout.jsx` — sidebar + top bar + main content area
- `resources/js/Pages/Dashboard.jsx` — stat cards with props from controller

### Configuration
- `vite.config.js` — added `@vitejs/plugin-react`, changed entry to `.jsx`
- `resources/css/app.css` — added `@source '../**/*.jsx'` for Tailwind scanning
- `resources/views/app.blade.php` — Inertia root template

## Test Plan

1. `GET /dashboard` returns HTTP 200
2. Response renders Inertia `Dashboard` component
3. Shared props include `apiary.name`, `apiary.edition`, `hive.id`, `hive.name`
4. Page props include `agentCount`, `taskCounts.pending`, `taskCounts.in_progress`, `knowledgeCount`
5. All counts default to 0 with empty database
6. Edition defaults to `ce`
7. `npm run build` succeeds (Vite + React + Tailwind)
8. All existing tests continue to pass
