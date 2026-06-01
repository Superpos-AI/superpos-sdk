# TASK-294: Issues Create page

**Status:** pending
**Branch:** `task/294-issues-create-page`
**PR:** —
**Depends on:** TASK-293 (Issues Show page — provides redirect target & `Index.jsx` from TASK-292; transitively includes TASK-290, TASK-291, TASK-292)
**Blocks:** —
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§8 UI — Create issue)

## Objective

Ship the Issue creation flow. Spec §8 calls it a "modal", but for V1
we ship a dedicated page (`Pages/Issues/Create.jsx`) at
`/dashboard/issues/create` plus a modal variant invoked from the
Index page CTA. Both forms post to a **new** dashboard route
`POST /dashboard/issues` added in this task — the agent API
`POST /api/v1/hives/{hive}/issues` (shipped in TASK-290) sits behind
`auth:sanctum-agent` and is not callable from a dashboard session.
The new dashboard `store()` action mirrors the agent-API logic and
reuses the **rule shape** of the existing `CreateIssueRequest`, but
**must not bind to `CreateIssueRequest` directly** — that FormRequest
resolves the current hive via `$this->attributes->get('hive')?->id`,
which is only populated by the route-model-bound `{hive}` segment on
the agent API. The dashboard route has no `{hive}` segment, so
binding `CreateIssueRequest` to it would run every tenant-scoped
`Rule::exists(..., 'hive_id', $hiveId)` (and the assignee check)
with `hive_id = null`, silently bypassing cross-hive isolation.
Instead, introduce a dashboard-scoped FormRequest (e.g.
`App\Http\Requests\Dashboard\StoreIssueRequest`) that resolves the
current hive from the authenticated user / session context (the same
way other dashboard controllers do) and either extends
`CreateIssueRequest` overriding the hive resolver, or duplicates the
rule shape. Reference `CreateIssueRequest` only as the rule template,
not as the request to bind to the dashboard route.

## Requirements

### Functional

- [ ] FR-1: Route `GET /dashboard/issues/create` renders Inertia
      component `Issues/Create`.
- [ ] FR-2: Form fields per spec §8: `title` (required),
      `description` (markdown), `type` (select — from
      `GET /issue-types`), `assignee` (optional — a **unified
      polymorphic assignee picker over both users and agents** in the
      current hive; the picker submits the paired
      `assignee_type` + `assignee_id` body fields matching the
      existing API contract in `CreateIssueRequest`:
      `assignee_type ∈ { "App\\Models\\User", "App\\Models\\Agent", null }`,
      `assignee_id ∈ { "<ulid>", null }`, both nullable together to
      leave the issue unassigned, never agent-only),
      `linked_channel` (optional — Channel picker).
- [ ] FR-3: Submit posts to the new dashboard route
      `POST /dashboard/issues` →
      `IssueDashboardController@store`. The action is gated by
      `issues.manage` and validates via a **new dashboard-scoped
      FormRequest** (e.g. `App\Http\Requests\Dashboard\StoreIssueRequest`)
      that reuses the rule shape of `CreateIssueRequest` but resolves
      the current hive from the authenticated session, not from a
      `{hive}` route segment. The store() action MUST NOT bind
      directly to `App\Http\Requests\CreateIssueRequest` — its hive
      resolver depends on a `{hive}` route segment that the dashboard
      route does not have, so tenant-scoped validations would run
      with `hive_id = null` and bypass cross-hive isolation.
- [ ] FR-4: On 422, surface field-level errors next to the
      corresponding input.
- [ ] FR-5: On success, redirect to
      `/dashboard/issues/{newIssue.id}` (TASK-293).
- [ ] FR-6: A reusable `<IssueCreateForm />` component is invoked from
      the Index page CTA inside a modal — same component, different
      wrapper.
- [ ] FR-7: Type select defaults to the hive's `task` IssueType
      (seeded by TASK-289).
- [ ] FR-8: When opened from a Channel context (query param
      `?from_channel={id}`), the `linked_channel` field is
      pre-populated.
- [ ] FR-9: Re-enable the placeholder "New issue" CTA introduced in
      TASK-292 on `Pages/Issues/Index.jsx` — remove the disabled state
      and "Coming soon" tooltip, and wire the button to
      `/dashboard/issues/create` (or, when invoked from the Index page
      header, open the `IssueCreateModal` variant directly).

### Non-Functional

- [ ] NFR-1: Permission gated by `issues.manage`.
- [ ] NFR-2: PSR-12 + Pint clean. ESLint clean.
- [ ] NFR-3: Form submits via Inertia `useForm` for consistency with
      other create flows.
- [ ] NFR-4: The `store()` action MUST NOT bind directly to
      `App\Http\Requests\CreateIssueRequest` — its hive resolver
      depends on a `{hive}` route segment that the dashboard route
      does not have. A dashboard-scoped FormRequest that resolves the
      hive from the session/user context is required.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-294-issues-create-page.md` | This file |
| Modify | `app/Http/Controllers/Dashboard/IssueDashboardController.php` | `create()` action — render form with type list, assignee list (agents + users), channel list; `store()` action — persist a new issue from the dashboard form |
| Create | `app/Http/Requests/Dashboard/StoreIssueRequest.php` | Dashboard-scoped FormRequest mirroring `CreateIssueRequest` rules (including polymorphic `assignee_type` + `assignee_id` accepting both `App\Models\User` and `App\Models\Agent`) but resolving the current hive from the authenticated session/user context (not from a `{hive}` route segment). Bound to the dashboard `store()` action. |
| Create | `resources/js/Pages/Issues/Create.jsx` | Standalone create page |
| Create | `resources/js/Components/Issues/IssueCreateForm.jsx` | Reusable form (used by page + Index modal). The **assignee** field is a unified picker over users + agents in the current hive — it emits `assignee_type` + `assignee_id` (paired-nullable to leave unassigned), not an agent-only id. |
| Create | `resources/js/Components/Issues/IssueCreateModal.jsx` | Modal wrapper around the form |
| Modify | `resources/js/Pages/Issues/Index.jsx` | Wire CTA button to open the modal |
| Modify | `routes/web.php` | Register `GET /dashboard/issues/create` and `POST /dashboard/issues` |

### Decisions (locked in)

1. **Page + modal, same form component.** The form lives in
   `IssueCreateForm.jsx`. The page (`Create.jsx`) wraps it in the
   standard `AppLayout`; the modal wraps it in a `Modal` from the
   existing UI kit. This avoids duplicate logic and gives the CTA
   flow (modal) the bookmarkable fallback (`/issues/create`) the
   spec implies.
2. **New dashboard `store` route, no new API endpoint.** Submit hits
   the new `POST /dashboard/issues` →
   `IssueDashboardController@store`. The action persists via the same
   `Issue` model + state-machine path used by the agent-API
   counterpart, so no business logic is duplicated. The agent-API
   endpoint (`POST /api/v1/hives/{hive}/issues`) sits behind
   `auth:sanctum-agent` and is not reachable from the dashboard
   session, which is why a sibling dashboard route is required.
   **Thread auto-creation:** When creating an issue via the
   dashboard, if no `thread_id` is provided, the `store()` action
   MUST auto-create a Thread and associate it with the issue. This
   ensures the Discussion tab (TASK-293 FR-6) always has backing
   data for dashboard-created issues. The thread is created eagerly
   during issue creation, not lazily on first Discussion tab visit.

   Validation lives in a **new dashboard FormRequest** (e.g.
   `App\Http\Requests\Dashboard\StoreIssueRequest`) that reuses the
   rule shape of `CreateIssueRequest` — **including the polymorphic
   assignee contract**: `assignee_type` is validated via
   `Rule::in(['App\\Models\\User', 'App\\Models\\Agent'])` (nullable,
   `required_with:assignee_id`), `assignee_id` is nullable
   `required_with:assignee_type` (max:26), and a `withValidator`
   after-hook runs the same membership check as
   `CreateIssueRequest::withValidator` (agent must belong to the
   current hive; user must exist). The dashboard request resolves
   the current hive from the authenticated session/user context
   instead of a `{hive}` route segment. The dashboard `store()`
   action **must not** bind directly to
   `App\Http\Requests\CreateIssueRequest`: that FormRequest reads
   `$this->attributes->get('hive')?->id`, which only resolves on
   routes carrying a `{hive}` route segment (the agent API). The
   dashboard route has no such segment, so tenant-scoped exists
   rules and the assignee check would all run with `hive_id = null`
   and silently bypass cross-hive isolation. The dashboard request
   may extend `CreateIssueRequest` and override the hive resolver,
   or duplicate the rule array — but it owns its own hive resolution
   and preserves the same polymorphic (user-or-agent) assignee
   contract end-to-end; it must not narrow the field to an
   agent-only id.
3. **Type defaults to `task`.** This matches the most common case
   (lowest-friction issue creation) and uses the seeded IssueType
   from TASK-289. Other types remain selectable.
4. **Route registration order: `/issues/create` before
   `/issues/{issue}`.** Laravel matches routes top-down, so the
   literal `/dashboard/issues/create` route **must** be registered
   before the wildcard `/dashboard/issues/{issue}` route (from
   TASK-293). Otherwise the framework treats `create` as an `{issue}`
   parameter and the create page returns a 404 (or the wrong
   controller action). This is the same pattern used by the Tasks
   dashboard — see `routes/web.php` lines around TASK-277 where
   `/tasks/create` is explicitly placed before `/tasks/{task}`.

## Test Plan

### Feature tests

- `create()` returns 200 and includes `types`, `assignees` (both
  agents and users), `channels` in props.
- `store()` with valid payload creates an `Issue` scoped to the
  current hive and redirects to `/dashboard/issues/{id}`. Covered
  for **all three assignee shapes**:
  (a) `assignee_type = "App\\Models\\Agent"` with an agent id in the
  current hive — persists with `assignee_type/id` populated;
  (b) `assignee_type = "App\\Models\\User"` with an existing user id
  — persists with `assignee_type/id` populated;
  (c) both `assignee_type` and `assignee_id` omitted (or both `null`)
  — persists as unassigned.
- `store()` with a mismatched assignee pair (one of `assignee_type` /
  `assignee_id` set without the other) returns 422.
- `store()` with `assignee_type` outside the allowed set
  (`App\\Models\\User`, `App\\Models\\Agent`) returns 422.
- `store()` with missing title returns 422 with `errors.title`.
- `store()` without `issues.manage` permission returns 403.
- `store()` respects cross-hive isolation (assignee/channel pickers
  reject entries from another hive — agents must belong to the current
  hive, users must exist).
- `store()` auto-creates a Thread when no `thread_id` is provided
  and associates it with the new issue.
- **Note:** `activity_log` writes on issue creation are not yet
  implemented in the API and are deferred to a future
  API-hardening ticket.

### Render tests

- Form renders all required fields.
- `from_channel` query param pre-populates the channel field.
- Modal variant renders the same fields and posts to the same URL.

## Out of Scope (deferred)

- Inline dependency creation at issue-create time (add later via the
  Dependencies tab on Show).
- Bulk-create flow.
- Attaching files / images.

## Validation Checklist

- [ ] `/dashboard/issues/create` renders the standalone form.
- [ ] Index page CTA opens the modal with the same form.
- [ ] Submit creates an issue and redirects to detail.
- [ ] Assignee field is a unified user-or-agent picker and submits
      polymorphic `assignee_type` + `assignee_id` (verified by
      feature tests covering: assigning a user, assigning an agent,
      and leaving the issue unassigned with both fields `null`).
- [ ] Validation errors surface inline.
- [ ] `from_channel` pre-population works.
- [ ] Permission gating verified.
- [ ] PSR-12 / Pint + ESLint clean.
- [ ] Full suite green (`php artisan test`, `npm test`).
