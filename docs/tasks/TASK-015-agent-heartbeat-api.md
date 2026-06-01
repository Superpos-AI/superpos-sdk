# TASK-015: Agent Heartbeat & Lifecycle API

**Status:** done
**Branch:** `task/015-agent-heartbeat-api`
**PR:** [#14](https://github.com/Superpos-AI/superpos-app/pull/14)
**Depends on:** TASK-014
**Blocks:** TASK-023

## Objective

Implement heartbeat and lifecycle endpoints so registered agents can report liveness, status transitions, and metadata updates reliably for scheduling and dashboard visibility.

## Requirements

### Functional

- [x] FR-1: Heartbeat endpoint updates agent last-seen and runtime metadata
- [x] FR-2: Lifecycle status transitions supported (online, busy, idle, offline, error)
- [x] FR-3: Stale agent detection semantics defined and test-covered
- [x] FR-4: API responses follow envelope conventions
- [x] FR-5: Activity log captures lifecycle/heartbeat changes

### Non-Functional

- [x] NFR-1: Idempotent heartbeat updates for repeated polls
- [x] NFR-2: Scope-safe updates (apiary/hive/agent boundaries)
- [x] NFR-3: PSR-12 + tests

## Implementation Plan

1. Review existing Agent model/auth context and lifecycle fields
2. Add heartbeat/lifecycle endpoint(s) under `/api/v1/agents/*`
3. Add validation request(s) and status transition rules
4. Persist heartbeat metadata and lifecycle timestamps
5. Add activity log events for lifecycle changes
6. Add feature tests for happy path + validation + scope safety + stale semantics
7. Update TASKS/task status and open PR

## Test Plan

- [x] Heartbeat updates last_seen_at and metadata
- [x] Invalid lifecycle state rejected
- [x] Status transitions persist correctly
- [x] Cross-scope update rejected
- [x] Activity logs created for lifecycle transitions
- [x] Stale detection behavior covered
