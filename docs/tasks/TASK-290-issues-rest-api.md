# TASK-290: Issues REST API + state machine + blocked-on-human flow

**Status:** in-progress
**Branch:** `task/290-issues-rest-api`
**PR:** —
**Depends on:** TASK-288 (hive-scoped approval routes), TASK-289 (issues data model)
**Blocks:** —
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§5 state machine, §6 closure resolution, §7 blocked-on-human)

## Objective

Land the REST API, state machine, and closure resolution for the
**Issues** management layer (Phase 1 step 3 of 3). This adds:

- `IssueStateMachine` service — validates state transitions per spec §5,
  logs activity on every transition;
- `IssueClosureResolver` service + `ClosureResult` value object —
  trust-based closure resolution with most-restrictive-wins policy
  (spec §6);
- `IssueController` (12 endpoints) and `IssueTypeController` (3
  endpoints) — full CRUD + lifecycle operations;
- 10 `FormRequest` classes for input validation;
- route registration under `/api/v1/hives/{hive}/issues/*` and
  `/api/v1/hives/{hive}/issue-types/*`;
- permissions: `issues.read`, `issues.manage`.

This builds on TASK-289's schema + models and TASK-288's hive-scoped
approval routes.

## Requirements

### Functional

- [ ] FR-1: `IssueStateMachine` enforces valid state transitions per
      spec §5. Invalid transitions return `422`.
- [ ] FR-2: Every state transition is logged via `ActivityLogger`.
- [ ] FR-3: `IssueClosureResolver` applies most-restrictive-wins policy
      across `IssueType.closure_policy` values (`agent_self_close` <
      `human_required` < `gated_by_approval`).
- [ ] FR-4: `ClosureResult` value object carries the resolution
      decision (`allowed`, `needs_approval`, `denied`) plus context.
- [ ] FR-5: Blocked-on-human flow: `request-approval` endpoint creates
      an `ApprovalRequest` and transitions the issue to `blocked` state.
- [ ] FR-6: `IssueController` exposes 12 endpoints: `index`, `store`,
      `show`, `update`, `transition`, `close`, `reopen`, `link-task`,
      `link-channel`, `request-approval`, plus dependencies CRUD
      (`store-dependency`, `destroy-dependency`).
- [ ] FR-7: `IssueTypeController` exposes 3 endpoints: `index`,
      `store`, `update`.
- [ ] FR-8: All 15 endpoints respond with correct HTTP status codes
      (`200`, `201`, `204`, `404`, `422`).
- [ ] FR-9: Cross-hive isolation enforced — accessing an issue from a
      different hive returns `404`.
- [ ] FR-10: Input validated via 10 `FormRequest` classes.

### Non-Functional

- [ ] NFR-1: PSR-12 + Pint clean.
- [ ] NFR-2: Permissions gated by `issues.read` (index, show) and
      `issues.manage` (all mutating endpoints).
- [ ] NFR-3: Routes registered in `routes/api.php` under the existing
      hive-scoped group.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-290-issues-rest-api.md` | This file |
| Create | `app/Services/IssueStateMachine.php` | State transition validation + activity logging |
| Create | `app/Services/IssueClosureResolver.php` | Trust-based closure resolution (most-restrictive-wins) |
| Create | `app/Services/ClosureResult.php` | Value object for closure resolution decision |
| Create | `app/Http/Controllers/Api/IssueController.php` | 12 issue endpoints |
| Create | `app/Http/Controllers/Api/IssueTypeController.php` | 3 issue-type endpoints |
| Create | `app/Http/Requests/CreateIssueRequest.php` | Validation for issue creation |
| Create | `app/Http/Requests/UpdateIssueRequest.php` | Validation for issue update |
| Create | `app/Http/Requests/TransitionIssueRequest.php` | Validation for state transition |
| Create | `app/Http/Requests/CloseIssueRequest.php` | Validation for issue closure |
| Create | `app/Http/Requests/LinkTaskToIssueRequest.php` | Validation for task linking |
| Create | `app/Http/Requests/LinkChannelToIssueRequest.php` | Validation for channel linking |
| Create | `app/Http/Requests/RequestIssueApprovalRequest.php` | Validation for approval request |
| Create | `app/Http/Requests/CreateIssueDependencyRequest.php` | Validation for dependency creation |
| Create | `app/Http/Requests/CreateIssueTypeRequest.php` | Validation for issue-type creation |
| Create | `app/Http/Requests/UpdateIssueTypeRequest.php` | Validation for issue-type update |
| Modify | `routes/api.php` | Register issue + issue-type routes |

### Decisions (locked in)

1. **State machine lives in a service, not the model** — keeps the
   `Issue` model clean. `IssueStateMachine::transition()` accepts
   the issue, target state, and actor; validates the transition; updates
   the model; and logs activity. Returns the updated issue or throws
   `422`.
2. **Closure resolution is a separate service** — decouples the
   most-restrictive-wins policy from the controller. The controller
   calls `IssueClosureResolver::resolve()` before allowing a close,
   then acts on the `ClosureResult`.
3. **`ClosureResult` is a plain value object** — not a model. Carries
   `allowed: bool`, `requiresApproval: bool`, `reason: string`.
4. **Blocked-on-human creates an `ApprovalRequest`** — reuses the
   existing approval infrastructure from Phase 2 (TASK-045/046).
   The issue transitions to `blocked` state until the approval is
   resolved.
5. **10 FormRequests, not fewer** — each endpoint gets its own
   request class. Keeps validation rules explicit and independently
   testable.
6. **Permissions: `issues.read` + `issues.manage`** — follows the
   existing two-tier pattern (`*.read` for GET, `*.manage` for
   mutations). Checked via `CheckPermission` middleware.

### Endpoints

```
GET    /api/v1/hives/{hive}/issues                      → index
POST   /api/v1/hives/{hive}/issues                      → store
GET    /api/v1/hives/{hive}/issues/{issue}               → show
PUT    /api/v1/hives/{hive}/issues/{issue}               → update
POST   /api/v1/hives/{hive}/issues/{issue}/transition    → transition
POST   /api/v1/hives/{hive}/issues/{issue}/close         → close
POST   /api/v1/hives/{hive}/issues/{issue}/reopen        → reopen
POST   /api/v1/hives/{hive}/issues/{issue}/link-task     → linkTask
POST   /api/v1/hives/{hive}/issues/{issue}/link-channel  → linkChannel
POST   /api/v1/hives/{hive}/issues/{issue}/request-approval → requestApproval
POST   /api/v1/hives/{hive}/issues/{issue}/dependencies  → storeDependency
DELETE /api/v1/hives/{hive}/issues/{issue}/dependencies/{dependency} → destroyDependency

GET    /api/v1/hives/{hive}/issue-types                  → index
POST   /api/v1/hives/{hive}/issue-types                  → store
PUT    /api/v1/hives/{hive}/issue-types/{issueType}      → update
```

## Test Plan

### Feature tests

- State machine rejects invalid transitions (`open` → `closed`
  without going through `close` endpoint) with `422`.
- Closure resolver returns `needs_approval` for `gated_by_approval`
  policy, `allowed` for `agent_self_close`.
- `request-approval` creates an `ApprovalRequest` and transitions
  issue to `blocked`.
- Cross-hive isolation: issue from hive A returns `404` when accessed
  via hive B route.
- All 15 endpoints return correct status codes for success and
  validation failure cases.

### Unit tests

- `IssueStateMachine` — each valid transition pair succeeds; each
  invalid pair throws.
- `IssueClosureResolver` — most-restrictive-wins across policy
  combinations.
- `ClosureResult` — value object construction and accessors.

## Out of Scope (deferred)

- `features.issues_enabled` feature flag (gates routes — future task).
- `agents.issue_trust_score` column + trust-modifier logic (spec §6
  advanced scoring).
- Dashboard UI for issues (separate task).
- SDK methods for issues (separate task).

## Validation Checklist

- [ ] All 15 endpoints respond correctly with proper status codes.
- [ ] State machine enforces valid transitions per spec §5.
- [ ] Closure resolver applies most-restrictive-wins policy.
- [ ] Blocked-on-human flow creates `ApprovalRequest` and transitions
      issue to `blocked`.
- [ ] Cross-hive isolation enforced (`404` on hive mismatch).
- [ ] Input validated via FormRequests.
- [ ] Activity logged on state transitions.
- [ ] PSR-12 / Pint clean on every touched PHP file.
- [ ] Full suite green (`php artisan test`).
