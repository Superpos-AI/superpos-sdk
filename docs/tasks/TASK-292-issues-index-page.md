# TASK-292: Issues Index page

**Status:** pending
**Branch:** `task/292-issues-index-page`
**PR:** —
**Depends on:** TASK-291 (sidebar restructure — transitively includes TASK-290)
**Blocks:** TASK-293 (reuses `IssueStatePill` created here, and owns
wiring the row-click navigation to `/dashboard/issues/{id}` — see FR-8)
**Unblocks (follow-up):** TASK-294 re-enables the disabled "New issue"
CTA shipped here once the create route / modal exists.
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§8 UI — Issue list view)

## Objective

Ship the Issues list page — the default landing under the new **Work**
sidebar section. Replaces the placeholder stub introduced in TASK-291.

The page is an Inertia page (`Pages/Issues/Index.jsx`) backed by an
`IssueDashboardController@index` action that queries the `Issue` model
directly (the same pattern used by `TaskDashboardController`,
`ApprovalDashboardController`, and other dashboard controllers). The
existing agent API endpoint `GET /api/v1/hives/{hive}/issues` cannot
be reused because it only supports a single `state` filter and lacks
the `has_open_approval` toggle required here. The dashboard controller
builds its own Eloquent query with multi-select state and the approval
join.

## Requirements

### Functional

- [ ] FR-1: Route `GET /dashboard/issues` renders Inertia component
      `Issues/Index` with an `issues` paginator prop and a `filters`
      prop reflecting the current query string.
- [ ] FR-2: Default sort is `updated_at desc`.
- [ ] FR-3: Table columns: title, state (pill), type, assignee,
      open-approval indicator, updated_at. The **assignee** column
      renders both user and agent assignees (the underlying contract
      is polymorphic — `assignees.assignee_type` is one of
      `App\Models\User` or `App\Models\Agent`, per
      `docs/proposals/issues-concept.md` §3-§4 and the shipped
      `CreateIssueRequest` / `UpdateIssueRequest` rules); the cell
      shows a unified label/avatar with a small badge indicating
      whether the assignee is a user or an agent.
- [ ] FR-4: Filters: state (multi-select), type (single-select),
      assignee (single-select — a unified picker over both users and
      agents in the current hive; selecting an entry submits both
      `assignee_type` and `assignee_id` in the query string so the
      server-side filter scopes correctly against the polymorphic
      column pair, not against an agent-only field),
      `has_open_approval` (toggle). Filters are reflected in the URL
      query string and persist on reload.
- [ ] FR-5: Quick actions per row: assign, change state (opens a small
      inline form / popover). State change POSTs to the existing
      dashboard transition route
      (`POST /dashboard/issues/{issue}/transition`, shipped in
      TASK-290). Assign POSTs to a **new** dashboard route
      (`POST /dashboard/issues/{issue}/assign`) added in this task —
      the agent API `PATCH /api/v1/hives/{hive}/issues/{issue}` is
      gated behind `auth:sanctum-agent` and is not callable from the
      dashboard session.
      **Quick-assign request body (polymorphic, matches the shipped
      API contract):**
      `{ "assignee_type": "App\\Models\\User" | "App\\Models\\Agent" | null,
      "assignee_id": "<ulid>" | null }`.
      Both fields are nullable together to **unassign** (matches the
      paired-nullability invariant enforced by
      `CreateIssueRequest::withValidator` and
      `UpdateIssueRequest::withValidator`). The assignee picker in
      the row popover is a **unified list of users + agents in the
      current hive**, not an agent-only dropdown.
      **Dashboard-scoped validation:** The `assign()` action must not
      bind directly to `UpdateIssueRequest` — that FormRequest resolves
      the current hive via `$this->attributes->get('hive')?->id`, which
      is only populated by the route-model-bound `{hive}` segment on
      the agent API. The dashboard route has no `{hive}` segment, so
      the polymorphic assignee membership check (agent must belong to
      the current hive; user must exist) and tenant-scoped
      `Rule::exists(..., 'hive_id', $hiveId)` validations would run
      with `hive_id = null` and silently bypass cross-hive isolation.
      Instead, the action validates via a new dashboard-scoped
      FormRequest (`App\Http\Requests\Dashboard\DashboardAssignIssueRequest`)
      that accepts the polymorphic `assignee_type` + `assignee_id`
      pair (same rule shape as `UpdateIssueRequest`) and resolves the
      current hive from the authenticated session/user context (see
      Files table and Decisions below).
- [ ] FR-6: Empty state shows the in-product decision tree from spec
      §8 mitigation ("Need to plan something? → Issue. Need to chat?
      → Channel. Need to run automation? → Automations.").
- [ ] FR-7: Header includes a "New issue" CTA button rendered as
      **disabled** with tooltip "Coming soon" until TASK-294 ships the
      create route. TASK-294 will replace the disabled state with the
      active link / modal handler. This avoids shipping a broken CTA
      in TASK-292 (the `/dashboard/issues/create` route and modal do
      not exist until TASK-294).
- [ ] FR-8: Rows are visually clickable (cursor-pointer + hover style)
      but the actual navigation/link to `/dashboard/issues/{id}` is
      **deferred to TASK-293**. The `GET /dashboard/issues/{issue}`
      show route does not exist on `main` (`routes/web.php:268-278`
      only exposes `transition`, `close`, `reopen` mutation endpoints
      for issues); it is first introduced by TASK-293
      (`docs/tasks/TASK-293-issues-show-page.md`, FR-1). To avoid
      shipping rows that link to a non-existent route, this task
      renders rows as plain `<tr>` elements with the hover/cursor
      styling only — no `<Link>` and no click handler that calls
      `router.visit('/dashboard/issues/{id}')`. TASK-293 owns wiring
      the actual row navigation when it lands the show route.

### Non-Functional

- [ ] NFR-1: Permission gated by `issues.read`.
- [ ] NFR-2: Cross-hive isolation — the controller scopes by current
      hive context (same pattern as other dashboard controllers).
- [ ] NFR-3: PSR-12 + Pint clean. ESLint clean.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-292-issues-index-page.md` | This file |
| Create | `app/Http/Controllers/Dashboard/IssueDashboardController.php` (extend if already created in TASK-290) | `index()` action — paginated list; `assign()` action — quick assignee change |
| Create | `app/Http/Requests/Dashboard/DashboardAssignIssueRequest.php` | Dashboard-scoped FormRequest for the `assign()` action. Accepts the polymorphic assignee contract `assignee_type` (`Rule::in(['App\\Models\\User', 'App\\Models\\Agent'])`, nullable) + `assignee_id` (nullable, max:26, paired-nullable with `assignee_type`), mirroring the assignee-related rules from `UpdateIssueRequest`. Runs the same after-validator membership check (agent must belong to the current hive; user must exist). Resolves the current hive from the authenticated session/user context (not from a `{hive}` route segment). Must not bind to `UpdateIssueRequest` directly. |
| Create | `resources/js/Pages/Issues/Index.jsx` | List page |
| Create | `resources/js/Components/Issues/IssueStatePill.jsx` | Reusable state badge |
| Create | `resources/js/Components/Issues/IssueRow.jsx` | Single-row component |
| Create | `resources/js/Components/Issues/IssueFilters.jsx` | Filter bar |
| Modify | `routes/web.php` | Register `/dashboard/issues` → `IssueDashboardController@index` (replaces placeholder from TASK-291) and `POST /dashboard/issues/{issue}/assign` → `IssueDashboardController@assign` |
| Modify | `resources/js/Pages/Issues/Placeholder.jsx` | Removed (replaced by Index) |

### Decisions (locked in)

1. **Server-driven pagination + filters.** The controller uses
   Laravel's paginator and passes `links` + `meta` to Inertia. Filters
   are read from query string and re-emitted as defaults. This
   matches the existing Tasks index pattern.
2. **State pill is a shared component.** Lives in
   `resources/js/Components/Issues/IssueStatePill.jsx` so the Show
   page (TASK-293) and any future Board view reuse it.
3. **Quick actions inline.** State change uses the existing dashboard
   `POST /dashboard/issues/{issue}/transition` endpoint (from
   `IssueDashboardController@transition`, shipped in TASK-290). The
   agent-only API endpoint
   (`POST /api/v1/hives/{hive}/issues/{issue}/transition`) is gated
   behind `auth:sanctum-agent` and is not callable from the dashboard
   session.
4. **New dashboard `assign` route.** Quick-assign needs an
   `issues.manage`-gated dashboard route because the agent API
   `PATCH /api/v1/hives/{hive}/issues/{issue}` (which carries the
   assignee update) sits behind `auth:sanctum-agent`. This task adds
   `POST /dashboard/issues/{issue}/assign` →
   `IssueDashboardController@assign`. The action accepts polymorphic
   assignee fields — `assignee_type` (`App\Models\User` or
   `App\Models\Agent`) and `assignee_id` — matching the existing API
   contract in `CreateIssueRequest`. Both fields nullable to unassign.
   Validates that the assignee belongs to the current hive (for agents)
   or exists (for users), persists the change, and returns an Inertia
   partial reload of the row.
   No new *API* endpoint is introduced.

   **Dashboard-scoped FormRequest for `assign()`.** The `assign()`
   action must not bind directly to `UpdateIssueRequest` — that
   FormRequest resolves the current hive via
   `$this->attributes->get('hive')?->id`, which is only populated by
   the route-model-bound `{hive}` segment on the agent API. The
   dashboard route has no `{hive}` segment, so the assignee membership
   check (polymorphic assignee validation for agents/users) and
   tenant-scoped `Rule::exists(..., 'hive_id', $hiveId)` validations
   would run with `hive_id = null` and silently bypass cross-hive
   isolation. Instead, introduce
   `App\Http\Requests\Dashboard\DashboardAssignIssueRequest` that
   resolves the current hive from the authenticated session/user
   context (the same way other dashboard controllers do). The
   dashboard FormRequest may extend `UpdateIssueRequest` and override
   the hive resolver, or duplicate the assignee-related rule shape —
   but it must own its own hive resolution and support the same
   polymorphic assignee contract (`assignee_type` + `assignee_id`,
   accepting both `App\Models\User` and `App\Models\Agent`). Reference
   `UpdateIssueRequest` only as the rule template, not as the request
   to bind to the dashboard route.
5. **Dashboard controller queries the model directly.** The existing
   agent API `IssueController@index` only supports single `state`
   filter and does not have `has_open_approval`. Rather than extend
   the agent API (which has its own contract), the dashboard
   controller builds a direct Eloquent query with multi-select state
   (`whereIn`) and a `has_open_approval` toggle (subquery
   `whereHas('approvalRequests', ...)`). This matches the pattern
   used by `TaskDashboardController`, `ApprovalDashboardController`,
   and other existing dashboard controllers.

## Test Plan

### Feature tests

- `IssueDashboardController@index` returns 200 and includes filtered
  issues in `issues` prop.
- Filtering by state returns only matching issues.
- Filtering by `has_open_approval` returns only issues with at least
  one open `ApprovalRequest`.
- Cross-hive isolation: an issue from hive A does not appear when
  visiting hive B's `/dashboard/issues`.
- `issues.read` permission required (403 otherwise).
- `assign()` updates the assignee and requires `issues.manage`.
  Covers all four assignee shapes:
  (a) assign an **agent** in the current hive — accepted;
  (b) assign a **user** that exists — accepted;
  (c) `assignee_type = null, assignee_id = null` — unassigns;
  (d) mismatched nullability (one field set, the other null) — 422.
- `assign()` rejects an **agent** from another hive (422) and a
  non-existent **user** id (422) — cross-hive isolation enforced by
  the dashboard-scoped `DashboardAssignIssueRequest`, not the
  agent-API `UpdateIssueRequest`. Verify that `hive_id` scoping uses
  the session-resolved hive, not a null value from an absent `{hive}`
  route segment.
- `assign()` rejects an unknown `assignee_type` value (anything other
  than `App\Models\User` or `App\Models\Agent`) with 422.

### Render tests

- Empty state renders the decision-tree copy.
- State pill renders the correct color per state value.
- Rows render as plain `<tr>` elements with cursor-pointer/hover
  styling but **no** `<Link>` or `router.visit` handler pointing at
  `/dashboard/issues/{id}` — the actual navigation is wired in
  TASK-293 once the show route exists. A regression test asserts
  that the Index page does not emit anchors/handlers to
  `/dashboard/issues/{id}`.

## Out of Scope (deferred)

- Kanban board view (Phase 5 — TASK to be created later).
- Bulk transition / bulk assign (Phase 5).
- Full-text search across description (Phase 5).
- Saved filter views.
- Assignment activity-log auditing — both the dashboard `assign()` and
  the API `PATCH` update currently skip `activity_log` for assignee
  changes. If auditing is needed, it should be introduced as a shared
  concern across both surfaces to keep them aligned.

## Validation Checklist

- [ ] `/dashboard/issues` renders the new list page.
- [ ] Filters round-trip through the URL query string.
- [ ] State pill renders for every documented state.
- [ ] Quick-action transition calls the API and refreshes the row.
- [ ] Quick-action assign accepts both **user** and **agent**
      assignees (polymorphic `assignee_type` + `assignee_id`),
      supports unassign (both fields `null`), and the unified picker
      surfaces both users and agents in the current hive.
- [ ] Cross-hive isolation verified by test (agent from another hive
      rejected; non-existent user id rejected).
- [ ] Rows render with cursor-pointer/hover styling but **do not**
      navigate to `/dashboard/issues/{id}` in this task — that
      route is introduced by TASK-293, which also wires the row
      click. Verified by render test.
- [ ] PSR-12 / Pint + ESLint clean.
- [ ] Full suite green (`php artisan test`, `npm test`).
