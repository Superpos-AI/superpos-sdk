# TASK-034: End-to-End Integration Test Suite

**Status:** Review
**Branch:** `task/034-e2e-integration-tests`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/41
**Depends On:** 014 (Agent registration), 015 (Heartbeat), 016 (Task creation), 017 (Polling/claiming), 018 (Progress/completion), 019 (Timeout/retry), 020 (Knowledge API)
**Blocks:** 035 (CI/CD pipeline)

## Objective

Build a deterministic, CI-friendly integration test suite that validates core
platform flows end-to-end — exercising the full chain from agent registration
through task lifecycle and knowledge operations, including permission and
tenant isolation boundaries.

## Requirements

### Functional

- [x] FR-1: Agent registration → authentication → heartbeat → status lifecycle flow
- [x] FR-2: Task creation → poll → claim → progress → completion lifecycle
- [x] FR-3: Task creation → poll → claim → progress → failure lifecycle
- [x] FR-4: Knowledge create → list → search → show → update → delete flow
- [x] FR-5: Knowledge scope isolation (hive vs apiary vs agent-private)
- [x] FR-6: Permission enforcement — agents without required permissions get 403
- [x] FR-7: Hive isolation — tasks and knowledge in different hives are invisible
- [x] FR-8: Cross-apiary isolation — different apiaries fully isolated

### Non-Functional

- [x] NFR-1: All tests deterministic — no timing dependencies or flaky assertions
- [x] NFR-2: Uses RefreshDatabase trait — clean slate per test
- [x] NFR-3: Reuses existing factories and AssertsApiEnvelope trait
- [x] NFR-4: Tests run in < 30 seconds in CI
- [x] NFR-5: No external service dependencies (self-contained with SQLite)

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `tests/Feature/EndToEndIntegrationTest.php` | E2E integration test suite |
| Create | `docs/tasks/TASK-034-e2e-integration-tests.md` | Task documentation |
| Create | `docs/guide/e2e-integration-tests.md` | VitePress integration testing guide |
| Modify | `docs/index.md` | Link to new guide |

### Key Design Decisions

- **Single test class** with well-organized sections — keeps related flows together
- **Shared helpers** for apiary/hive/agent setup — reduces boilerplate
- **Each test method exercises a full flow** — not individual endpoints (those are covered by per-feature tests)
- **Activity log assertions** verify audit trail is complete for each flow

## Test Plan

### Feature Tests (`tests/Feature/EndToEndIntegrationTest.php`)

1. Agent lifecycle: register → login → heartbeat → status transitions → me
2. Task happy path: create → poll → claim → progress → complete
3. Task failure path: create → poll → claim → fail
4. Knowledge CRUD: create → list → show → search → update → delete
5. Knowledge scope isolation: hive-scoped invisible across hives, apiary-scoped visible, agent-scoped private
6. Permission enforcement: 403 for tasks.create, tasks.claim, tasks.update, knowledge.read, knowledge.write
7. Hive isolation: agent in hive A cannot see tasks/knowledge in hive B
8. Cross-apiary isolation: agent in apiary A gets 403 for hive in apiary B

## Validation Checklist

- [ ] All tests pass (`php artisan test --filter=EndToEndIntegrationTest`)
- [ ] PSR-12 compliant
- [ ] Reuses existing factories and test traits
- [ ] No external dependencies
- [ ] Activity logging verified in lifecycle tests
- [ ] Envelope compliance verified
