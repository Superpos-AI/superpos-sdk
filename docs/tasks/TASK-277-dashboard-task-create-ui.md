---
name: TASK-277 dashboard task-create ui
description: Standalone "Create Task" dashboard page plus prefilled variants launched from agent + webhook route detail pages.
type: project
---

# TASK-277: Dashboard "Create Task" UI

**Status:** pending
**Branch:** `task/277-dashboard-task-create-ui`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/470
**Depends on:** TASK-263 (task ↔ sub-agent binding), TASK-265 (webhook sub-agent — reference for slug resolution pattern), TASK-276 (marketplace prefill — reference for prefill-from-link pattern)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §11 (new subsection to add)

## Objective

Give users a first-class way to create tasks from the dashboard. Today tasks only arrive via webhooks, schedules, the SDK, or other tasks — there is no manual "Create Task" button anywhere in the UI. Ship:

1. A standalone form at `/dashboard/tasks/create` covering every field a webhook route's `action_config.create_task` can set today (task_type, target_capability, target_agent_id, sub_agent_definition_slug, invoke payload, priority, timeout).
2. Prefilled variants launched from the **agent detail page** ("Create task for this agent") and the **webhook route edit page** ("Create task from this route") so users can quickly one-off-dispatch without retyping.

## Background

- `WebhookRouteEvaluator::executeCreateTask()` already encodes the canonical task-creation shape (task_type, target_capability, target_agent_id, sub-agent slug resolution as of TASK-265, invoke payload mapping).
- `TaskCreationService::create()` is the shared sink — it enforces contract validation, queue depth, and the hive lock. Both the webhook evaluator and the new dashboard controller call it.
- `TaskDashboardController` already has `index()`, `show()`, `cancel()`, `restart()`, `bulkCancel()`. It has no `create()`/`store()`.
- `resources/js/Pages/Tasks.jsx` (board) and `resources/js/Pages/Tasks/Show.jsx` exist. No `Tasks/Create.jsx`.
- Sub-agent dropdown pattern already proven in TASK-265 (`WebhookRouteDashboardController::create()` passes `subAgentDefinitions`) and TASK-276 (`SubAgentDashboardController::create()` passes `marketplacePersonas`). Reuse the exact prop shape `[{slug, name}]`.

## Requirements

### Functional

- [ ] FR-1: `GET /dashboard/tasks/create` renders `resources/js/Pages/Tasks/Create.jsx` with the following Inertia props:
  - `agents`: `[{id, name, capabilities}]` — active agents in the current hive (same shape `WebhookRouteDashboardController::create()` uses).
  - `subAgentDefinitions`: `[{slug, name}]` — active sub-agent definitions in the current hive (same shape as TASK-265).
  - `capabilities`: `string[]` — deduplicated union of all agent capabilities in the hive, for the target_capability autocomplete.
  - `taskTypes`: `string[]` — distinct `type` values observed on recent tasks in the hive (last 30 days, capped at ~50). Free-text entry still allowed; this is a convenience datalist.
  - `prefill`: optional object describing initial form values (see FR-5/FR-6).

- [ ] FR-2: Form fields (all optional unless marked):
  - `type` (required, string, free text with datalist from `taskTypes`)
  - `target_capability` (string, free text with datalist from `capabilities`)
  - `target_agent_id` (dropdown, agents list, "(any matching capability)" default)
  - `sub_agent_definition_slug` (dropdown, subAgentDefinitions list, "(none)" default)
  - `priority` (integer 0–4, default 2; render as labeled select: Low / Normal / High / Urgent / Critical)
  - `timeout_seconds` (integer, default from config — see NFR-3)
  - `payload` (JSON textarea; validated parseable-JSON on submit; empty → `{}`)
  - Hidden: `source_agent_id = null`, `status = 'pending'`, `organization_id` and `hive_id` from request context.

- [ ] FR-3: `POST /dashboard/tasks` validates via a `CreateTaskRequest` form request, resolves `sub_agent_definition_slug` → `sub_agent_definition_id` using the **same logic** as TASK-265 (`withoutGlobalScopes()`, match on `slug` + `hive_id` + `is_active=true`), then calls `TaskCreationService::create($data, $hive)`. On success, redirects to `/dashboard/tasks/{task}` with a flash message. On `ContractViolationException` or `QueueDepthExceededException`, re-renders the form with the error attached to the relevant field.

- [ ] FR-4: Fail-open on unresolved slug — mirrors TASK-265 exactly. If the slug is present but doesn't resolve, create the task without a sub-agent and log an activity event `dashboard.task_create.sub_agent_fail_open` with the submitted slug and the acting user's id. (This case is rare — the dropdown only lists active definitions — but a stale slug could be posted via form replay.)

- [ ] FR-5: **Prefill from agent detail page** — `resources/js/Pages/Agents/Show.jsx` gains a "Create task for this agent" button linking to `/dashboard/tasks/create?agent_id={id}`. The controller reads the `agent_id` query param, validates it is an agent in the current hive, and sets `prefill.target_agent_id` accordingly. If the param is invalid or the agent is not in-hive, drop it silently (do not error) and render the bare form.

- [ ] FR-6: **Prefill from webhook route edit page** — `resources/js/Pages/WebhookRouteForm.jsx` (edit mode only) gains a "Create task from this route" button linking to `/dashboard/tasks/create?webhook_route_id={id}`. The controller loads the route's `action_config` and derives `prefill` as:
  ```
  prefill = {
      type: action_config.task_type ?? null,
      target_capability: action_config.target_capability ?? null,
      target_agent_id: action_config.target_agent_id ?? null,
      sub_agent_definition_slug: action_config.sub_agent_definition_slug ?? null,
      payload: action_config.invoke ?? {},
  }
  ```
  As in FR-5, a stale/cross-hive route id is dropped silently.

- [ ] FR-7: User can edit any prefilled field before submitting. A small info banner ("Prefilled from agent X" / "Prefilled from webhook route Y — edit or clear before submitting") appears at the top of the form when `prefill` is non-empty; it disappears once the user edits a field or clicks "Clear prefill."

- [ ] FR-8: Activity log entry on successful dashboard-initiated creation: event `dashboard.task.created` with `{task_id, type, target_agent_id, sub_agent_definition_id, prefill_source: null | "agent" | "webhook_route"}`.

### Non-Functional

- [ ] NFR-1: PSR-12. Pint clean.
- [ ] NFR-2: Authorization — `TaskPolicy::create(User $user, Hive $hive)` gate; users must be members of the current hive. Reuse the same policy wiring that gates `TaskDashboardController::cancel()` etc.
- [ ] NFR-3: `timeout_seconds` default pulled from `config('platform.tasks.default_timeout_seconds')` if defined, else fall back to the same default `TaskCreationService` uses today (check the model default on the `timeout_seconds` column; do not hard-code a new one).
- [ ] NFR-4: No new tables, no migrations — this is pure UI + controller glue on top of existing services.
- [ ] NFR-5: Backwards compatible — existing task board and show page unaffected. The new route `/dashboard/tasks/create` must be registered **before** the `/dashboard/tasks/{task}` route to avoid collision.
- [ ] NFR-6: CE/Cloud identical — no `app/Cloud` imports; TaskCreationService already handles the CE/Cloud fork for managed-agent wake.

## Out of scope (deferred)

- Bulk task creation from a CSV or paste (future task — this is a single-task form).
- Scheduling ("create this task every Monday") — schedules already have their own UI at `/dashboard/schedules`. The Create Task form creates one task now.
- Cross-hive task creation — the form creates tasks in the current hive only. Cross-hive dispatch already has its own path (`CrossHiveRouter`) and is not part of this UX.
- Editing a task after creation — tasks are immutable once queued (cancel + recreate is the workflow).

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Http/Controllers/Dashboard/TaskDashboardController.php` | Add `create()` and `store()` |
| Create | `app/Http/Requests/CreateTaskRequest.php` | Form-request validation |
| Modify | `routes/web.php` | Register `/dashboard/tasks/create` (before `/{task}`) and `POST /dashboard/tasks` |
| Create | `resources/js/Pages/Tasks/Create.jsx` | Form page |
| Modify | `resources/js/Pages/Agents/Show.jsx` | Add "Create task for this agent" button |
| Modify | `resources/js/Pages/WebhookRouteForm.jsx` | Add "Create task from this route" button (edit mode only) |
| Create | `tests/Feature/Dashboard/CreateTaskDashboardTest.php` | Controller + validation + slug resolution + prefill tests |
| Create | `resources/js/Pages/Tasks/__tests__/Create.test.jsx` | JSX form-state tests |

### Key Design Decisions

- **Reuse `TaskCreationService::create()`** — do not re-implement queue-depth or contract logic in the controller. The controller's job is: validate form input, resolve slug → id, map to the `$data` shape `TaskCreationService` expects, call it.
- **Slug resolution lives in the controller**, not the service — matches the TASK-265 precedent. Keeps `TaskCreationService` ignorant of sub-agents (which is correct; sub-agent is a task attribute, not a service concern).
- **Prefill via query param, not session** — shareable/bookmarkable URLs; avoids flash-session fragility. Invalid ids drop silently (FR-5/FR-6) rather than erroring, because a stale link shouldn't block the user from manually filling the form.
- **`prefill_source` in activity log** — lets us later measure "what % of manually-created tasks came from the agent-detail shortcut vs. webhook-route shortcut vs. bare form" without new telemetry.
- **No sub-agent-definition_id in the form** — users pick by slug (human-readable), controller resolves. Same UX as webhook routes.

## Implementation Plan

1. `CreateTaskRequest` with rules:
   - `type: required|string|max:255`
   - `target_capability: nullable|string|max:255`
   - `target_agent_id: nullable|ulid|exists:agents,id` (with hive-scoped validator — see `WebhookRouteDashboardController` validators)
   - `sub_agent_definition_slug: nullable|string|max:255`
   - `priority: integer|min:0|max:4`
   - `timeout_seconds: nullable|integer|min:10|max:86400`
   - `payload: nullable|array`

2. `TaskDashboardController::create(Request $request)`:
   - Resolve current hive.
   - Build `prefill` from `agent_id` and/or `webhook_route_id` query params (drop silently on mismatch).
   - Load `agents`, `subAgentDefinitions`, `capabilities`, `taskTypes`.
   - Return `Inertia::render('Tasks/Create', [...])`.

3. `TaskDashboardController::store(CreateTaskRequest $request, TaskCreationService $service)`:
   - Pull validated data.
   - Resolve `sub_agent_definition_slug` → `sub_agent_definition_id` (copy the block from `WebhookRouteEvaluator::executeCreateTask` after TASK-265).
   - Shape `$data` array (type, payload, target_agent_id, target_capability, priority, timeout_seconds, sub_agent_definition_id, organization_id, hive_id, status=`pending`).
   - `$service->create($data, $hive)` inside try/catch for `ContractViolationException` and `QueueDepthExceededException` → redirect back with errors.
   - Log activity `dashboard.task.created` with `prefill_source`.
   - Redirect to `route('dashboard.tasks.show', $task)` with flash.

4. Routes — register **before** `{task}` catch-all:
   ```php
   Route::get('/tasks/create', [TaskDashboardController::class, 'create'])->name('dashboard.tasks.create');
   Route::post('/tasks', [TaskDashboardController::class, 'store'])->name('dashboard.tasks.store');
   Route::get('/tasks/{task}', [TaskDashboardController::class, 'show'])->name('dashboard.tasks.show');
   ```

5. `Create.jsx`:
   - Controlled form using `useForm` (Inertia).
   - Seed form state from `prefill` prop on mount; show info banner when prefill is non-empty.
   - JSON textarea with live parse-error hint.
   - Priority as `<select>` with labeled options (0=Low, 1=Below Normal, 2=Normal, 3=High, 4=Critical).
   - "Clear prefill" button resets to empty defaults.
   - Submit disabled while JSON invalid.

6. Entry-point buttons:
   - `Agents/Show.jsx`: add a link button near the existing action buttons — `<Link href={route('dashboard.tasks.create', { agent_id: agent.id })}>Create task for this agent</Link>`.
   - `WebhookRouteForm.jsx` (edit mode, i.e. `route.id` present and `action_config.action === 'create_task'`): same pattern with `webhook_route_id`.

7. Tests.

## Test Plan

### Feature Tests (`CreateTaskDashboardTest`)

- [ ] Renders create page with agents, subAgentDefinitions, capabilities, taskTypes props populated from the current hive.
- [ ] `prefill` empty when no query params.
- [ ] `prefill.target_agent_id` set when `?agent_id=` points at an in-hive agent; dropped when pointing at a different hive's agent.
- [ ] `prefill` populated from webhook route's `action_config` when `?webhook_route_id=` points at an in-hive route; dropped for cross-hive route.
- [ ] Store creates a task with all fields, redirects to show page, flashes success.
- [ ] Store resolves `sub_agent_definition_slug` to `sub_agent_definition_id` (active definition in same hive).
- [ ] Store fail-opens when slug doesn't resolve (task created with `sub_agent_definition_id=null`, activity event `dashboard.task_create.sub_agent_fail_open` logged).
- [ ] Store respects hive isolation: slug matching an active definition in *another* hive is not resolved.
- [ ] `ContractViolationException` surfaces as a form error on `payload` (or `type`).
- [ ] `QueueDepthExceededException` surfaces as a form-level error.
- [ ] Activity log entry `dashboard.task.created` includes `prefill_source` = `"agent"` / `"webhook_route"` / `null` matching the query param.
- [ ] Policy gate: non-member of the hive receives 403 on GET and POST.

### JSX Tests (`Tasks/__tests__/Create.test.jsx`)

- [ ] Form renders with empty defaults when `prefill` is empty.
- [ ] Form initial state reflects `prefill.target_agent_id`, `prefill.sub_agent_definition_slug`, `prefill.payload`, etc.
- [ ] Info banner appears when `prefill` is non-empty; "Clear prefill" resets to empty defaults and hides the banner.
- [ ] Priority select renders labeled options 0–4.
- [ ] Invalid JSON in payload disables submit and shows a hint; valid JSON re-enables it.
- [ ] Changing any prefilled field clears the "Prefilled from …" label from that field.

## Validation Checklist

- [ ] All tests pass (`php artisan test`, `npm test`)
- [ ] Pint clean
- [ ] Route registered **before** `/tasks/{task}` catch-all
- [ ] Hive isolation verified (cross-hive ids drop silently on prefill, reject on store)
- [ ] Fail-open behavior verified
- [ ] Activity logging verified (success + fail-open)
- [ ] Agent detail page has working "Create task for this agent" link
- [ ] Webhook route edit page has working "Create task from this route" link
