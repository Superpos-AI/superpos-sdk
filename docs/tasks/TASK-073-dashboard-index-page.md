# TASK-073: Dashboard landing page as app index (replace Laravel welcome)

## Status
In Review

## PR
[#36](https://github.com/Superpos-AI/superpos-app/pull/36)

## Objective
Replace the default Laravel welcome page at `/` with a product-native app landing/index page that routes users into the dashboard experience and reflects current edition/runtime context.

## Why
The generic Laravel welcome page breaks product continuity and makes the app feel unfinished. A purpose-built index page should:
- reinforce product identity,
- expose quick navigation into core dashboard areas,
- present environment health/context,
- and avoid duplicate frontend bootstraps.

## Dependencies
- TASK-022 Inertia + React layout
- TASK-023 Dashboard home page

## Scope
1. Route strategy for `/`:
   - redirect or render a dedicated Inertia landing page (`Dashboard/Index`).
2. UX:
   - primary CTAs into Dashboard, Agents, Tasks, Knowledge, Activity.
   - lightweight status cards/links (no heavy duplicate data loading).
3. Safety/compatibility:
   - preserve Vite entry consistency and remove legacy welcome-page coupling.
   - keep guest/auth behavior explicit and testable.
4. Docs:
   - update VitePress docs for dashboard navigation entrypoint.

## Implementation Plan (recommended)
1. Decide entrypoint behavior
   - Option A (preferred): `/` renders a dedicated dashboard index page (Inertia).
   - Option B: `/` 302 redirects to `/dashboard`.
2. Implement route + controller/page
   - add `Dashboard\IndexController` (or extend existing dashboard controller) with minimal props.
3. Remove old welcome coupling
   - retire/decouple `welcome.blade.php` from app bootstrap path.
4. Navigation UX polish
   - add clear cards/actions to primary sections with edition-aware labels.
5. Tests
   - feature tests for `/` behavior (guest/auth), page component render, no broken Vite entries.
6. Docs
   - task doc status updates + VitePress guide update + docs index link.

## Exit Criteria
- `/` no longer shows Laravel default welcome page.
- Entry flow is dashboard-native and stable across environments.
- Tests pass and docs reflect the new index behavior.
