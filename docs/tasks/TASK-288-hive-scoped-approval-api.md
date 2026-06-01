# TASK-288: Hive-scoped approval routes (API)

**Status:** in-progress
**Branch:** `task/288-hive-scoped-approval-api`
**PR:** —
**Depends on:** —
**Blocks:** TASK-289, TASK-290
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§9 "Approval scoping note")

## Objective

Close a pre-existing auth gap on the agent-facing approval API: today
`Api/ApprovalController` only authorizes on `organization_id`, while the
dashboard controller already scopes by `hive_id`. Add new hive-scoped routes
under `/api/v1/hives/{hive}/approvals/...` that enforce
`approval_request.hive_id === {hive}->id` and return **404** on mismatch
(matching the dashboard, doesn't leak existence). Keep the existing
org-scoped routes for backward compatibility, and add an optional `hive_id`
filter parameter to the existing `index()`.

This unblocks Phase 1 of the Issues concept (TASK-289 issue model + API,
TASK-290 issue approval gating with `cancel_issue`).

## Requirements

### Functional

- [ ] FR-1: `GET /api/v1/hives/{hive}/approvals` lists approvals filtered to
      `hive_id = {hive}->id`. Sibling-hive approvals in the same org are
      excluded.
- [ ] FR-2: `GET /api/v1/hives/{hive}/approvals/{approval}` returns the
      approval when `approval.hive_id === {hive}->id`; returns **404**
      (`not_found`) otherwise — even when the approval exists in a sibling
      hive of the same org.
- [ ] FR-3: `POST /api/v1/hives/{hive}/approvals/{approval}/approve`
      approves when the hive matches; **404** on cross-hive; **409** on
      already-decided/expired (reuses existing `ApprovalManager` flow).
- [ ] FR-4: `POST /api/v1/hives/{hive}/approvals/{approval}/deny`
      accepts optional `reason` (max 1000 chars); **404** on cross-hive.
- [ ] FR-5: Channel-type approvals dispatch through the same
      `ApprovalManager::approveChannelApproval` /
      `requestChangesChannelApproval` path as the org-scoped route.
- [ ] FR-6: Existing org-scoped `GET /api/v1/approvals` gains an optional
      `hive_id` query parameter that filters results to that hive when
      provided.
- [ ] FR-7: Permission middleware (`approvals.read` / `approvals.manage`)
      fires before hive resolution, so an under-permissioned agent gets
      **403**, not **404**, when hitting a hive-scoped endpoint.

### Non-Functional

- [ ] NFR-1: PSR-12 + Pint clean.
- [ ] NFR-2: No new migrations — `approval_requests.hive_id` already exists
      (added in `0001_01_01_000020_create_approval_requests_table.php`).
- [ ] NFR-3: No behavior change inside `ApprovalManager`. Controllers reuse
      the existing service unchanged.
- [ ] NFR-4: Org-scoped routes remain wire-compatible (backward compatible)
      with existing agents. Only an additive PHPDoc `@deprecated` note is
      added — no deprecation header, no runtime change.
- [ ] NFR-5: 404 (not 403) on hive mismatch — matches dashboard, avoids
      leaking approval existence across hives.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-288-hive-scoped-approval-api.md` | This file |
| _(skipped)_ | ~~`app/Http/Requests/IndexApprovalsRequest.php`~~ | Originally planned, but extracting validation into a FormRequest would change the existing 400 `invalid_filter` envelope contract on `?status=` (asserted by `ApprovalApiTest`). Inline validation for the new `hive_id` filter is added in the controller instead, matching the existing inline pattern. |
| Create | `tests/Feature/Api/HiveScopedApprovalsTest.php` | Feature tests for the new hive-scoped routes + the org-scoped `?hive_id=` filter regression test |
| Modify | `app/Http/Controllers/Api/ApprovalController.php` | Add hive-scoped action variants (`indexForHive`, `showForHive`, `approveForHive`, `denyForHive`) that assert `$approvalRequest->hive_id === $hive->id` and 404 otherwise; add optional `hive_id` filter to existing `index()`; `@deprecated` PHPDoc on the org-scoped methods |
| Modify | `routes/api.php` | Register the new hive-scoped approval routes inside the existing `Route::prefix('hives/{hive}')` group, using `permission:approvals.read` / `permission:approvals.manage` and `hive` + `cross-hive` middleware |
| Modify | `TASKS.md` | Add TASK-288 row (Phase 14 — Issues / Approval scoping) |

### Key Design Decisions

1. **Route placement** — inside the existing `Route::prefix('hives/{hive}')`
   group so the hive base middleware (`auth:sanctum-agent`,
   `throttle-agent`, `bind-cloud-tenant` in cloud) applies uniformly. The
   `permission` middleware is wrapped first, then `hive` (resolves the
   route param to a Hive model on `$request->attributes`), then
   `cross-hive` — same order as every other hive-scoped resource.
2. **Permission names** — reuse the existing **`approvals.read`** and
   **`approvals.manage`** permissions already used by the org-scoped
   routes. They are not registered in a central registry (the
   permission middleware simply checks the agent's granted permission
   set), so no new wiring is required.
3. **404 over 403 on hive mismatch** — matches the dashboard controller
   behavior and avoids leaking cross-hive approval existence. The existing
   **org-scoped** routes continue to return 403 on cross-org access
   (unchanged for backward compatibility).
4. **Deprecation** — `@deprecated` PHPDoc only on the existing
   org-scoped action methods. No runtime deprecation header (no
   `Sunset`, no log warning). Phase out plan tracked under the Issues
   rollout (proposal §10).
5. **`cancel_issue` flag on `.../deny`** — **DEFERRED** to TASK-290.
   When an Issue-linked approval is denied, the linked Issue may need
   to transition to `cancelled` atomically. That coupling belongs to
   the issue layer and is out of scope here.
6. **`Hive` route-model binding** — not used. The `hive` middleware
   (`ResolveHive`) already resolves the `{hive}` param into a Hive model
   on `$request->attributes->get('hive')`; the new hive-scoped methods
   read from there, matching every other hive-scoped controller in the
   API.

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/hives/{hive}/approvals` | List approvals where `hive_id = {hive}->id`. Supports the same filters as the org-scoped index (`status`, `agent_id`, `service_id`, `channel_id`, `per_page`); a passed-in `hive_id` query value is ignored (the path wins). |
| GET    | `/api/v1/hives/{hive}/approvals/{approval}` | Show one approval. 404 if `approval.hive_id !== {hive}->id`. |
| POST   | `/api/v1/hives/{hive}/approvals/{approval}/approve` | Approve. 404 cross-hive; 409 already-decided/expired. |
| POST   | `/api/v1/hives/{hive}/approvals/{approval}/deny` | Deny with optional `reason` (max 1000). 404 cross-hive; 409 already-decided/expired. |
| GET    | `/api/v1/approvals` | **Modified.** Now also accepts an optional `hive_id` query parameter. Other behavior unchanged. |

Route names: `api.v1.hives.approvals.{index,show,approve,deny}`.

## Test Plan

### Feature Tests (`tests/Feature/Api/HiveScopedApprovalsTest.php`)

- [ ] `index_returns_only_matching_hive_approvals` — sibling-hive
      approvals in the same org are excluded.
- [ ] `show_returns_404_for_sibling_hive_approval` — not 403 — matches
      dashboard semantics.
- [ ] `approve_succeeds_when_hive_matches`
- [ ] `approve_returns_404_for_sibling_hive_approval`
- [ ] `approve_returns_409_for_already_decided_approval`
- [ ] `deny_accepts_optional_reason`
- [ ] `deny_returns_404_for_sibling_hive_approval`
- [ ] `channel_approval_dispatches_through_manager_via_hive_scoped_route`
      — polymorphic dispatch regression guard.
- [ ] `org_scoped_index_filters_by_hive_id_query_param`
- [ ] `permission_check_fires_before_hive_check` — agent without
      `approvals.read` hitting a hive-scoped endpoint gets 403, not 404.

## Out of Scope

- **`cancel_issue` flag** on `.../deny` — deferred to TASK-290 (Issue
  gating). This task does not modify deny semantics for Issue-linked
  approvals.
- **Removing the org-scoped routes** — backward compatibility kept;
  removal is a later cleanup once all clients use the hive-scoped path.
- **Cross-hive approval queries** (one agent listing approvals across
  multiple hives in one call) — explicitly not supported. Agents iterate
  hives instead.

## Validation Checklist

- [ ] All tests pass (`php artisan test --filter=Approval`)
- [ ] PSR-12 / Pint clean
- [ ] API responses use `{ data, meta, errors }` envelope (reuses
      existing `ApiController` helpers)
- [ ] Form Request validation on `deny` (existing
      `DenyApprovalRequest` reused)
- [ ] No new migrations
- [ ] Activity logging unchanged (handled by `ApprovalManager`)
