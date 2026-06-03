---
name: TASK-196 workflow cost dashboard
description: Bridge the existing per-workflow + per-run cost APIs to a real Inertia page and add a nav entry from the workflow list.
type: project
---

# TASK-196: Workflow run cost summary in dashboard

**Status:** pending
**Branch:** `task/196-workflow-cost-dashboard`
**PR:** [#478](https://github.com/Superpos-AI/superpos-app/pull/478)
**Depends on:** TASK-195 (LLM usage tracking infra), TASK-184 (workflow runs)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_WORKFLOWS.md](../features/list-1/FEATURE_WORKFLOWS.md)

## Objective

Cost-tracking infrastructure (TASK-195) and per-workflow / per-run cost APIs already exist. There is no dashboard page for them and no nav link from the workflow list. Wire the existing APIs to a new Inertia page (`WorkflowCost.jsx`) and add a "View costs" entry on each row of `Workflows.jsx`. This closes both GAP-013 ("verify workflow cost dashboard") and GAP-016 ("workflow cost nav link").

## Background

- `LlmUsageService::getWorkflowCostSummary(Workflow)` already returns `{total_runs, avg_cost_per_run, total_cost_usd, total_tokens, most_expensive_step}`.
- `LlmUsageService::getWorkflowRunCost(WorkflowRun)` already returns `{total_tokens, total_cost_usd, request_count, by_step}`.
- `WorkflowDashboardController::cost()` and `::runCost()` already exist but return `JsonResponse` — no Inertia page.
- `LlmUsage.jsx` (the global LLM usage page) is the established pattern for cost UI: summary tiles + daily breakdown chart + breakdown tables.
- The existing JSON endpoints may have external consumers — keep them but route the Inertia page through new controller methods, don't rewrite them.

## Requirements

### Functional

- [ ] FR-1: `GET /dashboard/workflows/{workflow}/cost` renders a new Inertia page `resources/js/Pages/Workflows/Cost.jsx` (or `WorkflowCost.jsx`, whichever fits the existing `Pages/` layout best). Props:
  - `workflow`: `{id, name, slug, version, is_active}`
  - `summary`: result of `LlmUsageService::getWorkflowCostSummary($workflow)`
  - `recent_runs`: last ~25 runs with `{id, status, started_at, finished_at, total_cost_usd, total_tokens}` (pulled inline; no need for a new service method if a one-shot query is enough)
  - `daily_breakdown`: cost grouped by day for the last 30 days `[{date, cost_usd, run_count}]`
- [ ] FR-2: `GET /dashboard/workflows/{workflow}/runs/{run}/cost` renders a sibling page (or a tab on the same page) with the per-run breakdown — `LlmUsageService::getWorkflowRunCost($run)` data including the `by_step` table.
- [ ] FR-3: `Workflows.jsx` (the list page) gets a small `DollarSign` icon button on each row, linking to `route('dashboard.workflows.cost', workflow.id)`. Same visual weight as the existing edit/run buttons.
- [ ] FR-4: The existing JSON endpoints (`WorkflowDashboardController::cost()` and `::runCost()`) are kept as-is for any programmatic consumer. The Inertia views use **new** methods (`showCost()` / `showRunCost()`) so we don't break the JSON contract. Routes:
  ```
  Route::get('/workflows/{workflow}/cost', [..., 'showCost']) // Inertia, NEW
  Route::get('/workflows/{workflow}/cost.json', [..., 'cost']) // JSON, existing — moved/renamed if it collides
  ```
  Pick the route shape that avoids collision with the existing JSON endpoint. If the existing JSON endpoint is at `/workflows/{workflow}/cost`, retire it (no known external consumers — search the repo first to confirm) and let the new Inertia method serve that route. Document the decision in the PR body.
- [ ] FR-5: Hive isolation — `showCost()` and `showRunCost()` resolve the workflow / run via the same hive-scoped pattern used elsewhere in `WorkflowDashboardController` (look at how `index()` resolves the current hive). 404 on cross-hive ids.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Reuse `LlmUsageService` — no new service, no duplicated cost math.
- [ ] NFR-3: No new migrations, no schema changes.
- [ ] NFR-4: Page loads in under one query-set per render — daily breakdown should be a single grouped query, not N+1 per day.
- [ ] NFR-5: CE/Cloud identical — no `app/Cloud` imports.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Http/Controllers/Dashboard/WorkflowDashboardController.php` | Add `showCost()` and `showRunCost()` Inertia methods |
| Create | `resources/js/Pages/Workflows/Cost.jsx` | Cost dashboard page |
| Create | `resources/js/Pages/Workflows/RunCost.jsx` (or include as a tab on `Cost.jsx`) | Per-run cost breakdown |
| Modify | `resources/js/Pages/Workflows.jsx` | Add `DollarSign` icon link on each row |
| Modify | `routes/web.php` | Register the two new Inertia routes; resolve any collision with existing JSON routes |
| Create | `tests/Feature/Dashboard/WorkflowCostDashboardTest.php` | Controller + hive isolation + prop shape tests |
| Create | `resources/js/Pages/Workflows/__tests__/Cost.test.jsx` | JSX render tests |

### Key Design Decisions

- **Reuse `LlmUsageService`** — all cost math is already centralized there. Controller just calls and renders.
- **Keep existing JSON endpoints** unless we confirm zero callers. Easier to add new Inertia methods than to migrate API consumers.
- **`DollarSign` icon link** matches `LlmUsage.jsx`'s visual language and is a one-line addition to `Workflows.jsx`.
- **Page layout mirrors `LlmUsage.jsx`** — summary tiles top, daily chart middle, recent runs / per-step table bottom. Don't invent a new layout language.

## Implementation Plan

1. Grep the repo for callers of `dashboard.workflows.cost` / `dashboard.workflows.run-cost` route names. If no JSON consumers exist outside the dashboard itself, the existing methods can be replaced; otherwise add `.json` suffixed routes for backwards compat.
2. Add `showCost(Workflow $workflow)` and `showRunCost(Workflow $workflow, WorkflowRun $run)` to `WorkflowDashboardController`. Each resolves hive scope, calls the corresponding `LlmUsageService` method, builds `daily_breakdown` (one grouped query — `WHERE workflow_id = ? AND created_at >= NOW() - INTERVAL '30 days' GROUP BY DATE(created_at)`), and returns `Inertia::render(...)`.
3. Update routes — `Route::get('/workflows/{workflow}/cost', 'showCost')` etc.
4. Build `Workflows/Cost.jsx`:
   - Header: workflow name + version
   - Summary tiles: total runs, avg cost / run, total cost, total tokens, most expensive step (link to that step's run)
   - Daily-cost chart (use whatever chart library `LlmUsage.jsx` uses — likely `recharts`)
   - Recent runs table — id, status, started_at, cost, tokens; click → run-cost page
5. Build `Workflows/RunCost.jsx` (or as a tab):
   - Run header: status, started, duration
   - Totals: tokens, cost, request count
   - `by_step` table: step key, model, tokens, cost
6. Update `Workflows.jsx` — add `DollarSign` icon button to each row.
7. Tests.

## Test Plan

### Feature Tests

- [ ] `showCost` renders Inertia page with workflow, summary, recent_runs, daily_breakdown props
- [ ] `showRunCost` renders Inertia page with run + by_step breakdown
- [ ] Cross-hive workflow ID returns 404 from `showCost`
- [ ] Cross-hive run ID returns 404 from `showRunCost`
- [ ] Existing JSON endpoints (if kept) still return the original shape — backwards compat
- [ ] Empty workflow (no runs yet) renders without errors — summary shows zeros, recent_runs empty

### JSX Tests

- [ ] `Cost.jsx` renders summary tiles when summary prop is non-empty
- [ ] `Cost.jsx` renders empty-state message when `total_runs === 0`
- [ ] Daily-breakdown chart receives the right data shape
- [ ] Recent-runs table renders one row per run
- [ ] `Workflows.jsx` row has a working DollarSign link to the cost page

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] No N+1 queries on daily breakdown (verify with `DB::listen` in a test if needed)
- [ ] Backwards-compat for existing JSON endpoints documented in PR
- [ ] Cost icon visible on every workflow row
- [ ] Hive isolation verified
