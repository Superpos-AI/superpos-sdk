# TASK-084: Agent Pool Health Metrics (Derived View)

**Status:** ✅ done
**Branch:** `task/084-agent-pool-health-metrics` (merged)
**PR:** [#136](https://github.com/Superpos-AI/superpos-app/pull/136) (with follow-up hardening in [#143](https://github.com/Superpos-AI/superpos-app/pull/143))
**Depends on:** TASK-007, TASK-015
**Blocks:** TASK-085

## Objective

Enhance the pool health system with derived health status calculation
(healthy/busy/overloaded/degraded/critical/idle), per-capability pool
grouping, average wait/completion times, and scaling recommendations.
The existing `GET /pool/health` endpoint returns raw metrics only —
this task adds the intelligence layer.

## Requirements

### Functional

- [x] FR-1: Calculate derived health status from agent/task metrics
- [x] FR-2: Return avg_wait_seconds for pending tasks
- [x] FR-3: Return avg_completion_seconds for completed tasks in window
- [x] FR-4: Add health_status and recommendation to pool/health response
- [x] FR-5: Add per-capability pool grouping endpoint (GET /pools)
- [x] FR-6: Each pool shows agents, queue, health, recommendation

### Non-Functional

- [x] NFR-1: Health status formula matches FEATURE_PLATFORM_ENHANCEMENTS.md spec
- [x] NFR-2: Hive + apiary scope isolation preserved
- [x] NFR-3: Backward-compatible — existing response fields unchanged
- [x] NFR-4: API envelope format { data, meta, errors }

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Services/PoolHealthService.php` | Add health status, avg times, pool grouping |
| Create | `app/Http/Controllers/Api/PoolsController.php` | Per-capability pools endpoint |
| Modify | `app/Http/Controllers/Api/PoolHealthController.php` | Add health_status to response |
| Modify | `routes/api.php` | Register pools endpoint |
| Modify | `tests/Feature/PoolHealthTest.php` | Add tests for derived metrics |

### Key Design Decisions

- Pool = agents in same hive with overlapping capability (derived, no table)
- Health status uses thresholds from feature spec Section 4
- avg_wait_seconds = average (now - created_at) for pending tasks
- avg_completion_seconds = average (completed_at - claimed_at) within window
- Recommendation is a simple text string based on health status

## Health Status Calculation

```
critical:    online_agents == 0 AND pending > 0
idle:        total_agents == 0 OR (online_agents == 0 AND pending == 0)
overloaded:  pending/online_agents >= 15 OR avg_wait >= 300s   (checked before degraded — higher severity)
degraded:    online_agents < total_agents * 0.5
busy:        pending/online_agents >= 5 OR avg_wait >= 60s
healthy:     (default)
```

## Test Plan

### Unit Tests

- [x] Health status calculation for each status
- [x] Edge cases: zero agents, zero pending, division by zero

### Feature Tests

- [x] Pool health endpoint returns health_status and recommendation
- [x] Pools endpoint returns per-capability breakdown
- [x] Auth (401/403) for pools endpoint
- [x] Scope isolation for pools
- [x] avg_wait_seconds and avg_completion_seconds accuracy

## Validation Checklist

- [x] All tests pass (`php artisan test`)
- [x] PSR-12 compliant
- [x] API responses use `{ data, meta, errors }` envelope
- [x] Form Request validation on all inputs
- [x] BelongsToApiary/BelongsToHive traits applied where needed
