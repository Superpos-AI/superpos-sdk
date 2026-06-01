# End-to-End Integration Tests

The E2E integration test suite validates core platform flows across multiple API
endpoints in a single test method — exercising the full chain that a real agent
would traverse rather than testing endpoints in isolation.

## What It Covers

| Flow | Endpoints Exercised |
|------|---------------------|
| Agent lifecycle | `POST /register` → `GET /me` → `POST /heartbeat` → `PATCH /status` |
| Task happy path | `POST /tasks` → `GET /tasks/poll` → `PATCH /claim` → `PATCH /progress` → `PATCH /complete` |
| Task failure path | `POST /tasks` → `GET /tasks/poll` → `PATCH /claim` → `PATCH /progress` → `PATCH /fail` |
| Knowledge CRUD | `POST /knowledge` → `GET /knowledge` → `GET /knowledge/{id}` → `GET /knowledge/search` → `PUT /knowledge/{id}` → `DELETE /knowledge/{id}` |
| Scope isolation | Hive-scoped, apiary-scoped, and agent-private knowledge visibility |
| Permission boundaries | 403 enforcement for tasks.create, tasks.claim, knowledge.read, knowledge.write |
| Hive isolation | Cross-hive access rejected without `*.cross_hive` permission |
| Superpos isolation | Cross-apiary access fully blocked |
| Race prevention | Double-claim returns 409 Conflict |
| State machine | Invalid transitions (e.g. progress on pending task) return 409 |
| Task ownership | Non-claimer cannot update a claimed task |

## Running the Suite

```bash
# Run only the E2E tests
php artisan test --filter=EndToEndIntegrationTest

# Run with verbose output
php artisan test --filter=EndToEndIntegrationTest -v
```

## Design Principles

### Flow-Based, Not Endpoint-Based

Each test method exercises a **complete flow** — for example, the task lifecycle
test creates a task, polls for it, claims it, reports progress twice, and
completes it. This catches integration issues that per-endpoint tests miss, such
as state not propagating correctly between operations.

### Deterministic and CI-Friendly

- Uses `RefreshDatabase` trait — clean database per test
- No timing dependencies (no `sleep()` calls, no event-driven waits)
- No external service dependencies
- Consistent ordering via priority-based assertions

### Activity Log Verification

Every lifecycle test verifies the activity log trail to ensure all state changes
are audited. For example, the task lifecycle test asserts that `task.created`,
`task.polled`, `task.claimed`, `task.progress`, and `task.completed` actions all
appear in the correct order.

### Reuses Existing Infrastructure

- `AssertsApiEnvelope` trait for response format assertions
- Same helper patterns as per-feature tests (createApiaryAndHive, createAgentWithToken)
- Standard Sanctum authentication flow

## Test Structure

```
tests/Feature/EndToEndIntegrationTest.php
├── Agent lifecycle (register → auth → heartbeat → status)
├── Task lifecycle: complete path
├── Task lifecycle: failure path
├── Knowledge CRUD + search
├── Knowledge scope isolation
├── Permission enforcement
├── Hive isolation
├── Cross-apiary isolation
├── Double-claim race prevention
├── State machine enforcement
├── Task ownership
├── Knowledge duplicate conflict
└── Multi-task priority ordering
```

## Relationship to Per-Feature Tests

The E2E tests are **complementary** to per-feature tests, not a replacement:

| Aspect | Per-Feature Tests | E2E Tests |
|--------|-------------------|-----------|
| Scope | Single endpoint | Full flow across endpoints |
| Depth | Edge cases, validation, error paths | Happy paths and key boundaries |
| Count | 50–100+ per feature | 13 flow tests |
| Purpose | Exhaustive coverage | Integration confidence |

Both suites run in CI. The per-feature tests catch regressions in individual
endpoints; the E2E tests catch regressions in the interactions between them.
