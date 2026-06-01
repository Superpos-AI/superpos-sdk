# TASK-046: Approval Actions API

**Phase:** 2 — Service Proxy & Security
**Status:** in progress
**Depends On:** TASK-045 (Approval requests migration + model + flow)
**Branch:** `task/046-approval-actions-api`

---

## Objective

Expose REST API endpoints for listing, viewing, approving, and denying approval requests. Integrates with the `ApprovalManager` service from TASK-045. These endpoints serve both agent-facing queries (e.g. "has my proxy request been approved yet?") and dashboard/operator actions (approve/deny).

## Requirements

### Endpoints

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/api/v1/approvals` | `approvals.read` | List approval requests (filtered by status, agent, service) |
| GET | `/api/v1/approvals/{approval}` | `approvals.read` | Show a single approval request |
| POST | `/api/v1/approvals/{approval}/approve` | `approvals.manage` | Approve a pending request |
| POST | `/api/v1/approvals/{approval}/deny` | `approvals.manage` | Deny a pending request |

### Controller: `App\Http\Controllers\Api\ApprovalController`

Extends `ApiController`. Methods:

- **index(Request)** — Lists approval requests scoped to the agent's apiary. Supports query filters: `status`, `agent_id`, `service_id`. Paginated (default 15, max 100). Ordered by `created_at` desc.
- **show(Request, string $approval)** — Returns a single approval request by ID. Validates apiary scope.
- **approve(Request, string $approval)** — Calls `ApprovalManager::approve()`. The `decided_by` is the authenticated agent's name. Returns the updated approval. Handles `LogicException` from double-transition / expiry as 409 Conflict.
- **deny(DenyApprovalRequest, string $approval)** — Calls `ApprovalManager::deny()` with optional reason. Same error handling as approve.

### Form Request: `DenyApprovalRequest`

| Field | Rules |
|-------|-------|
| `reason` | sometimes, nullable, string, max:1000 |

### Routes

Added to `routes/api.php` under the authenticated group:

```php
Route::prefix('approvals')->middleware('auth:sanctum-agent')->group(function () {
    Route::middleware('permission:approvals.read')->group(function () {
        Route::get('/', [ApprovalController::class, 'index']);
        Route::get('/{approval}', [ApprovalController::class, 'show']);
    });
    Route::middleware('permission:approvals.manage')->group(function () {
        Route::post('/{approval}/approve', [ApprovalController::class, 'approve']);
        Route::post('/{approval}/deny', [ApprovalController::class, 'deny']);
    });
});
```

### Response Format

Standard `{ data, meta, errors }` envelope. Approval request data:

```json
{
  "id": "...",
  "superpos_id": "...",
  "hive_id": "...",
  "agent_id": "...",
  "service_id": "...",
  "policy_id": "...",
  "task_id": "...",
  "request_method": "PUT",
  "request_path": "/repos/org/repo/merge",
  "request_body": { ... },
  "reason": "...",
  "status": "pending",
  "decided_by": null,
  "decided_at": null,
  "expires_at": "2024-01-01T00:00:00+00:00",
  "created_at": "2024-01-01T00:00:00+00:00",
  "updated_at": "2024-01-01T00:00:00+00:00"
}
```

## Test Plan

### API Tests (ApprovalApiTest)

1. List: returns approval requests scoped to agent's apiary
2. List: filters by status
3. List: filters by agent_id
4. List: filters by service_id
5. List: paginates results
6. List: requires authentication (401)
7. List: requires approvals.read permission (403)
8. Show: returns single approval request
9. Show: 404 for non-existent approval
10. Show: 403 for approval in different apiary
11. Show: requires authentication (401)
12. Approve: transitions pending request to approved
13. Approve: sets decided_by to agent name
14. Approve: returns 409 for non-pending request
15. Approve: returns 409 for expired request
16. Approve: requires approvals.manage permission (403)
17. Approve: requires authentication (401)
18. Approve: 404 for non-existent approval
19. Deny: transitions pending request to denied
20. Deny: accepts optional reason
21. Deny: returns 409 for non-pending request
22. Deny: returns 409 for expired request
23. Deny: requires approvals.manage permission (403)
24. Deny: validation error for reason exceeding max length

## Design Decisions

- Approval endpoints are apiary-scoped (not hive-scoped) since approvals may span hives via cross-hive proxy requests
- `decided_by` is set to the authenticated agent's name (human-readable identifier)
- LogicException from ApprovalManager is caught and returned as 409 Conflict
- Pagination uses Laravel's simplePaginate for efficiency

## Related

- **Upstream:** TASK-045 (ApprovalManager, ApprovalRequest model)
- **Downstream:** TASK-049 (Dashboard approval queue)
