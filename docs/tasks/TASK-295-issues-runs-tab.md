# TASK-295: Runs tab wiring (Issue-scoped task list)

**Status:** pending
**Branch:** `task/295-issues-runs-tab`
**PR:** —
**Depends on:** TASK-293 (issues Show page)
**Blocks:** —
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§8 UI — Runs tab; §3 Task → Run naming)

## Objective

Replace the Runs-tab stub from TASK-293 with the filtered, issue-scoped
task list. The tab shows all `Task` rows where `issue_id = <this issue>`
and links each row to the existing Task detail page.

This is the **only** place where Task data is rendered inside the Issue
UI tree. The standalone `/dashboard/tasks` page (relabeled "Runs" in
the sidebar by TASK-291) is unchanged and continues to show **all**
tasks regardless of `issue_id` — see spec §8 "Naming — Task → Run".

## Requirements

### Functional

- [ ] FR-1: `RunsTab.jsx` renders a table of `Task` rows linked to
      the current issue: columns title (or task type), state,
      agent, created_at.
- [ ] FR-2: Default sort `created_at desc`. Optional client-side
      filter by state.
- [ ] FR-3: Row click navigates to the existing Task detail page
      (`/dashboard/tasks/{task}` — unchanged URL).
- [ ] FR-4: Tab header displays the linked-task count from the
      eager-loaded relation.
- [ ] FR-5: Empty state shows a "Link Task" CTA that opens a task
      picker and POSTs to the **new** dashboard route
      `POST /dashboard/issues/{issue}/link-task` added in this task
      (the agent-API endpoint
      `POST /api/v1/hives/{hive}/issues/{issue}/link-task` from
      TASK-290 sits behind `auth:sanctum-agent` and cannot be called
      from a dashboard session). The empty state also references the
      agent-API endpoint for programmatic linking from outside the
      dashboard.
      **Dashboard-scoped validation:** The `linkTask()` action must
      not bind directly to `LinkTaskToIssueRequest` — that FormRequest
      resolves the current hive via
      `$this->attributes->get('hive')?->id`, which is only populated
      by the route-model-bound `{hive}` segment on the agent API. The
      dashboard route has no `{hive}` segment, so tenant-scoped
      `Rule::exists(..., 'hive_id', $hiveId)` checks would run with
      `hive_id = null` and silently bypass cross-hive isolation.
      Instead, the action validates via a new dashboard-scoped
      FormRequest (`App\Http\Requests\Dashboard\LinkTaskRequest`) that
      resolves the current hive from the authenticated session/user
      context (see Files table and Decisions below).
- [ ] FR-6: Tab uses Inertia partial reload (`only: ['issue']`) when
      a task is linked/unlinked elsewhere, to refresh the count
      without a full navigation.

### Non-Functional

- [ ] NFR-1: PSR-12 + Pint clean (controller eager-load update).
- [ ] NFR-2: ESLint clean.
- [ ] NFR-3: Reuses the existing `StatusBadge` / state-pill component
      where appropriate — no new color tokens.
- [ ] NFR-4: Does not introduce a new *API* endpoint. The data comes
      from `Issue::tasks()` eager-loaded by the Show controller. The
      new `POST /dashboard/issues/{issue}/link-task` dashboard route
      mirrors the existing agent-API logic and does not change the
      agent-facing surface.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-295-issues-runs-tab.md` | This file |
| Modify | `app/Http/Controllers/Dashboard/IssueDashboardController.php` | Eager-load `tasks` with relevant columns in `show()`; add `linkTask()` action for the new dashboard route |
| Create | `app/Http/Requests/Dashboard/LinkTaskRequest.php` | Dashboard-scoped FormRequest mirroring `LinkTaskToIssueRequest` rules but resolving the current hive from the authenticated session/user context (not from a `{hive}` route segment). Bound to the dashboard `linkTask()` action. |
| Modify | `routes/web.php` | Register `POST /dashboard/issues/{issue}/link-task` |
| Modify | `resources/js/Components/Issues/Tabs/RunsTab.jsx` | Replace stub with real table |
| Create | `resources/js/Components/Issues/RunRow.jsx` (optional) | Per-row component if RunsTab grows |
| Modify | `resources/js/Pages/Issues/Show.jsx` | Pass tasks prop into RunsTab; update tab badge count |

### Decisions (locked in)

1. **No new API endpoint.** The Show controller already eager-loads
   tasks (per TASK-293 plan). This task adds the columns we need and
   wires the table — that's it. The global `/dashboard/tasks` route
   remains the source of truth for the cross-issue task list per
   spec §8.
2. **Click goes to existing Task detail.** Do not build a new
   "issue-scoped task detail" view. The existing Tasks page handles
   detail.
3. **New dashboard `link-task` route.** The "Link Task" button in
   this tab POSTs to the new dashboard route
   `POST /dashboard/issues/{issue}/link-task` →
   `IssueDashboardController@linkTask`, gated by `issues.manage`. The
   action mirrors the agent-API counterpart from TASK-290 (same
   validation, same cross-hive guard). The agent-API endpoint
   (`POST /api/v1/hives/{hive}/issues/{issue}/link-task`) remains
   the integration surface for SDK / agent flows. Failure cases:
   cross-hive mismatch, issue not found, and task not found.
   **Note:** `activity_log` writes on task linking are not yet
   implemented in the API and are deferred to a future
   API-hardening ticket.
4. **Dashboard-scoped FormRequest for `linkTask()`.** The `linkTask()`
   action must not bind directly to `LinkTaskToIssueRequest` — that
   FormRequest resolves the current hive via
   `$this->attributes->get('hive')?->id`, which is only populated by
   the route-model-bound `{hive}` segment on the agent API. The
   dashboard route has no `{hive}` segment, so tenant-scoped
   `Rule::exists(..., 'hive_id', $hiveId)` checks would run with
   `hive_id = null` and silently bypass cross-hive isolation. Instead,
   introduce `App\Http\Requests\Dashboard\LinkTaskRequest` that
   resolves the current hive from the authenticated session/user
   context. The dashboard FormRequest may extend
   `LinkTaskToIssueRequest` and override the hive resolver, or
   duplicate the rule shape — but it must own its own hive resolution.

## Test Plan

### Feature tests

- Show controller returns 200 with `tasks` eager-loaded; count
  matches `Task::where('issue_id', $issue->id)->count()`.
- Linking a task via the new dashboard route and visiting the tab
  shows the row.
- Unlinking (`tasks.issue_id = null`) removes the row on next reload.
- `linkTask()` requires `issues.manage`, rejects a task from another
  hive, rejects issue-not-found and task-not-found cases (same
  invariants as the current agent-API counterpart from TASK-290).
  **Note:** `activity_log` writes on task linking are not yet
  implemented in the API and are deferred to a future
  API-hardening ticket.
- `linkTask()` via the dashboard route rejects a task from another
  hive (cross-hive isolation enforced by the dashboard-scoped
  `LinkTaskRequest`, not the agent-API `LinkTaskToIssueRequest`).
  Verify that `hive_id` scoping uses the session-resolved hive, not
  a null value from an absent `{hive}` route segment.

### Render tests

- Empty state renders the help copy.
- Rows render state badge and link to the correct
  `/dashboard/tasks/{task}` URL.
- Tab badge shows the correct count.

## Out of Scope (deferred)

- Inline state-change actions on Run rows (the standalone Tasks page
  remains the primary action surface).
- Bulk link / unlink from this tab.
- Cross-hive task linking — the API already rejects it; this task
  does not surface a cross-hive picker.

## Validation Checklist

- [ ] Runs tab shows the correct filtered list of tasks.
- [ ] Tab badge count matches the linked-task count.
- [ ] Row click navigates to Task detail.
- [ ] Empty state copy and CTA verified.
- [ ] Linking via the API surfaces the row on reload.
- [ ] PSR-12 / Pint + ESLint clean.
- [ ] Full suite green (`php artisan test`, `npm test`).
