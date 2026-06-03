# TASK-045: Approval Requests Migration + Model + Flow

**Phase:** 2 — Service Proxy & Security
**Status:** in progress
**Depends On:** TASK-043 (Action policies migration + model), TASK-044 (Policy engine service)
**Branch:** `task/045-approval-requests-flow`

---

## Objective

Create the `approval_requests` database table, corresponding Eloquent model, factory, and `ApprovalManager` service that handles the approval lifecycle. When the PolicyEngine evaluates a request and returns `require_approval`, the ApprovalManager creates an approval request record and manages its lifecycle (pending → approved/denied/expired).

## Requirements

### Migration

Create `approval_requests` table per PRODUCT.md §9.2:

| Column | Type | Notes |
|--------|------|-------|
| `id` | `string(26)` PK | ULID |
| `superpos_id` | `string(26)` FK | References `apiaries(id)`, cascade delete |
| `hive_id` | `string(26)` FK | References `hives(id)`, cascade delete |
| `agent_id` | `string(26)` FK | References `agents(id)`, cascade delete |
| `service_id` | `string(26)` FK | References `service_connections(id)`, cascade delete |
| `policy_id` | `string(26)` FK | References `action_policies(id)`, nullable, set null on delete |
| `task_id` | `string(26)` FK | References `tasks(id)`, nullable, set null on delete |
| `request_method` | `string(10)` | HTTP method |
| `request_path` | `text` | Request path |
| `request_body` | `jsonb` | Nullable, request body |
| `reason` | `text` | Nullable, why approval was required |
| `status` | `string(20)` | Default `pending` — pending/approved/denied/expired |
| `decided_by` | `string(255)` | Nullable, who approved/denied |
| `decided_at` | `timestamp` | Nullable |
| `expires_at` | `timestamp` | Required, deadline for approval |
| `created_at` | `timestamp` | |
| `updated_at` | `timestamp` | |

**Indexes:**
- Partial index on `(superpos_id, status, created_at)` WHERE `status = 'pending'`
- `index(hive_id)`
- `index(agent_id)`
- `index(service_id)`

**Composite FKs** (matching action_policies pattern):
- `(superpos_id, agent_id)` → agents
- `(superpos_id, hive_id)` → hives
- `(superpos_id, service_id)` → service_connections

### Model

- Uses traits: `HasUlid`, `HasFactory`, `BelongsToHive`
- Constants: `STATUSES = ['pending', 'approved', 'denied', 'expired']`
- Casts: `request_body` as array, `decided_at` as datetime, `expires_at` as datetime
- Relationships: `agent()`, `service()`, `policy()`, `task()`, `hive()` (via trait), `apiary()` (via trait)
- Query scopes: `pending()`, `expired()`, `forAgent()`, `forService()`
- Helpers: `isPending()`, `isApproved()`, `isDenied()`, `isExpired()`

### Factory

- `ApprovalRequestFactory` with hive/apiary resolution (matching ActionPolicyFactory)
- States: `forHive()`, `forAgent()`, `forService()`, `forPolicy()`, `forTask()`, `pending()`, `approved()`, `denied()`, `expired()`

### Service: `App\Services\ApprovalManager`

Core approval lifecycle management:

**Methods:**
- `create(Agent, ServiceConnection, string $method, string $path, PolicyResult, ?array $body, ?Task): ApprovalRequest` — creates pending approval request from policy evaluation
- `approve(ApprovalRequest, string $decidedBy): ApprovalRequest` — marks as approved
- `deny(ApprovalRequest, string $decidedBy, ?string $reason): ApprovalRequest` — marks as denied
- `expirePending(): int` — expires all pending requests past `expires_at`

**Activity logging:**
- `approval.created` — when approval request created
- `approval.approved` — when approved
- `approval.denied` — when denied
- `approval.expired` — for each expired request

**Configuration:**
- Default expiry: `config('apiary.approval.default_expiry_hours', 24)`

### Relationships on Existing Models

- Add `approvalRequests(): HasMany` to `Agent` model
- Add `approvalRequests(): HasMany` to `Hive` model

## Test Plan

### Model Tests (ApprovalRequestModelTest)

1. ULID auto-generation
2. Non-auto-incrementing key
3. Fillable fields round-trip
4. `request_body` array cast
5. `decided_at` datetime cast
6. `expires_at` datetime cast
7. `status` defaults to `pending`
8. BelongsToHive trait integration (CE mode auto-scoping)
9. Cloud mode creation fails without context
10. Cascade delete when agent is deleted
11. Cascade delete when hive is deleted
12. Relationship: `agent()` returns parent
13. Relationship: `service()` returns parent
14. Relationship: `policy()` returns parent (nullable)
15. Relationship: `task()` returns parent (nullable)
16. Agent model: `approvalRequests()` returns children
17. Hive model: `approvalRequests()` returns children
18. Query scope: `pending()`
19. Query scope: `expired()`
20. Query scope: `forAgent()`
21. Query scope: `forService()`
22. Helper: `isPending()`
23. Helper: `isApproved()`
24. Helper: `isDenied()`
25. Helper: `isExpired()`
26. Constants: `STATUSES`

### Service Tests (ApprovalManagerTest)

1. Creates pending approval request from PolicyResult
2. Sets correct request details (method, path, body)
3. Links to policy and task when provided
4. Sets expiry from config
5. Logs `approval.created` activity
6. Approve transitions status to `approved`
7. Approve sets `decided_by` and `decided_at`
8. Approve logs `approval.approved` activity
9. Cannot approve non-pending request
10. Deny transitions status to `denied`
11. Deny sets `decided_by` and `decided_at`
12. Deny logs `approval.denied` activity
13. Cannot deny non-pending request
14. expirePending expires overdue requests
15. expirePending does not expire future requests
16. expirePending logs activity for each expired request
17. expirePending returns count of expired records

## Design Decisions

- Hive-scoped (uses `BelongsToHive` trait)
- `policy_id` is nullable with SET NULL on delete — if the policy that triggered the approval is deleted, the approval record stays for audit
- `task_id` is nullable with SET NULL on delete — same reasoning
- Status includes `expired` in addition to PRODUCT.md's pending/approved/denied — cleaner than relying solely on expires_at comparison
- Composite FKs enforce apiary isolation (matching action_policies pattern)
- ApprovalManager is a thin service focused on lifecycle; the proxy controller (TASK-042) will integrate with it
- Partial index on pending status for efficient dashboard polling

## Related

- **Upstream:** TASK-043 (ActionPolicy model), TASK-044 (PolicyEngine provides PolicyResult)
- **Downstream:** TASK-046 (Approval API), TASK-049 (Dashboard approval queue)
- **Spec reference:** PRODUCT.md §9.2 (approval_requests schema), §20.5 (policy evaluation)
