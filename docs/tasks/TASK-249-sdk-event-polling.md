# TASK-249: Python SDK — event polling client

**Status:** done
**Branch:** `task/249-sdk-event-polling`
**Depends on:** TASK-246
**Edition:** shared
**Feature doc:** [FEATURE_CHANNELS.md](../features/list-1/FEATURE_CHANNELS.md) §7.1

## Objective

Add event polling support to the Python SDK so agents can subscribe to and receive EventBus notifications alongside their task polling loop. This closes the gap where the EventBus API exists (TASK-054) but the SDK has no client for it.

## Background

The EventBus API was built in Phase 3 (TASK-054) but the Python SDK (TASK-032) never implemented client methods for it. With task and channel events now flowing through the EventBus (TASK-246, TASK-247), the SDK needs to support event polling as a first-class operation.

The actual server endpoints are:
- **Poll:** `GET /api/v1/hives/{hive}/events/poll` — query params: `since` (ISO8601 datetime), `last_event_id` (cursor), `limit` (int, default 50)
- **Subscribe:** `POST /api/v1/agents/subscriptions` — body: `{ event_type, scope }` (scope: `hive` or `apiary`)
- **Unsubscribe:** `DELETE /api/v1/agents/subscriptions/{eventType}`
- **List subscriptions:** `GET /api/v1/agents/subscriptions`
- **Replace subscriptions:** `PUT /api/v1/agents/subscriptions` — body: `{ subscriptions: [{ event_type, scope }] }`

Poll response uses cursor-based pagination with meta: `{ count, has_more, next_cursor, limit }`. There is no `event_types` filter parameter on the poll endpoint — filtering is done server-side based on the agent's subscriptions. There is no `next_poll_ms` in the response — the SDK must manage its own poll interval.

The agent poll loop becomes:

```python
while True:
    # Claim work
    tasks = client.poll_tasks(hive_id)
    for task in tasks:
        handle_task(task)

    # Receive notifications
    events = client.poll_events(hive_id)
    for event in events:
        handle_event(event)

    time.sleep(poll_interval)
```

## Requirements

### Functional

- [ ] FR-1: `client.poll_events(hive_id, limit=50)` — polls `GET /api/v1/hives/{hive}/events/poll` for new events matching the agent's subscriptions. Server-side filtering by subscribed event types (no client-side `event_types` parameter). Supports `last_event_id` cursor and optional `since` datetime.
- [ ] FR-2: `client.subscribe(event_type, scope="hive")` — creates a subscription via `POST /api/v1/agents/subscriptions`. Scope can be `hive` (default) or `apiary` (requires cross-hive permission).
- [ ] FR-3: `client.unsubscribe(event_type)` — removes a subscription via `DELETE /api/v1/agents/subscriptions/{eventType}`
- [ ] FR-4: Internal cursor management — SDK tracks `last_event_id` (from response meta `next_cursor`) and passes it on subsequent polls to avoid re-fetching events. Also tracks `has_more` to immediately re-poll when there are remaining events.
- [ ] FR-5: `client.list_subscriptions()` — lists current subscriptions via `GET /api/v1/agents/subscriptions`
- [ ] FR-6: `client.replace_subscriptions(subscriptions)` — atomically replaces all subscriptions via `PUT /api/v1/agents/subscriptions`
- [ ] FR-7: Events returned as typed objects with `id`, `type`, `payload`, `source_agent_id`, `hive_id`, `superpos_id`, `is_cross_hive`, `seq`, `created_at` attributes (matching the server response format)

### Non-Functional

- [ ] NFR-1: Cursor persisted in memory (not to disk) — cursor resets on agent restart, which is acceptable (events have TTL)
- [ ] NFR-2: Backward compatible — existing agents that don't call `poll_events()` continue to work unchanged
- [ ] NFR-3: Follow existing SDK patterns (error handling, retry, logging) established in TASK-032

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `sdk/python/src/superpos_sdk/client.py` | Add `poll_events()`, `subscribe()`, `unsubscribe()` methods |
| Create | `sdk/python/src/superpos_sdk/models.py` | Add `Event` and `Subscription` data classes |
| Create | `sdk/python/tests/test_event_polling.py` | Unit tests for event polling client |

### Key Design Decisions

- Event polling is opt-in — agents must call `poll_events()` explicitly; the SDK does not auto-poll events
- Cursor (`last_event_id`) is managed internally using the `next_cursor` value from the poll response meta, so the caller doesn't need to track pagination state
- Poll interval is managed by the SDK (no server-suggested `next_poll_ms`) — use a sensible default (e.g., 5s) with configurable override
- Subscription management (subscribe/unsubscribe/list/replace) maps directly to the `/api/v1/agents/subscriptions` endpoints

## Implementation Plan

1. Create `models.py` with `Event` and `Subscription` data classes — `Event` fields: `id`, `type`, `payload`, `source_agent_id`, `hive_id`, `superpos_id`, `is_cross_hive`, `seq`, `created_at`; `Subscription` fields: `agent_id`, `event_type`, `scope`, `created_at`
2. Add `poll_events(hive_id, limit=50)` method to `client.py` — calls `GET /api/v1/hives/{hive}/events/poll` with `last_event_id` cursor and `limit`, manages internal cursor from response meta `next_cursor`
3. Add `subscribe(event_type, scope="hive")` method — calls `POST /api/v1/agents/subscriptions`
4. Add `unsubscribe(event_type)` method — calls `DELETE /api/v1/agents/subscriptions/{eventType}`
5. Add `list_subscriptions()` method — calls `GET /api/v1/agents/subscriptions`
6. Add `replace_subscriptions(subscriptions)` method — calls `PUT /api/v1/agents/subscriptions`
7. Write unit tests with mocked HTTP responses

## Test Plan

### Unit Tests

- [ ] `poll_events(hive_id)` calls `GET /api/v1/hives/{hive}/events/poll` with `last_event_id` and `limit`
- [ ] `poll_events(hive_id)` updates internal cursor from response meta `next_cursor`
- [ ] `poll_events(hive_id)` re-polls immediately when `has_more` is true
- [ ] `subscribe()` calls `POST /api/v1/agents/subscriptions` with `event_type` and `scope`
- [ ] `unsubscribe()` calls `DELETE /api/v1/agents/subscriptions/{eventType}`
- [ ] `list_subscriptions()` calls `GET /api/v1/agents/subscriptions`
- [ ] `replace_subscriptions()` calls `PUT /api/v1/agents/subscriptions`
- [ ] Events parsed into typed Event objects with correct attributes (`id`, `type`, `payload`, `source_agent_id`, `superpos_id`, `seq`, etc.)
- [ ] First poll (no cursor) works correctly — omits `last_event_id` param

## Validation Checklist

- [ ] All tests pass
- [ ] Backward compatible — existing agent scripts work without changes
- [ ] Follows existing SDK conventions (error handling, retry, logging)
- [ ] No credentials logged in plaintext
