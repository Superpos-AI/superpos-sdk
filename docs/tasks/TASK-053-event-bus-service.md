# TASK-053: Event Bus Service

**Status:** In Progress
**Branch:** `task/053-event-bus-service`
**Depends On:** 051 (Events migration + model), 052 (Event subscriptions migration + model)

## Requirements

Create the `EventBus` service that provides the core publish/subscribe/dispatch logic for the hive-scoped and cross-hive event system described in PRODUCT.md §6.5, §7.2, and §9.2.

### Service Responsibilities

1. **Publish** — Create an `Event` record with proper scoping:
   - Hive-scoped events: require `hive_id`, set `is_cross_hive = false`
   - Cross-hive events (`apiary.*` prefix): set `hive_id = null`, `is_cross_hive = true`
   - Validate source agent belongs to correct apiary
   - Log activity via `ActivityLogger`

2. **Subscribe / Unsubscribe** — Manage `EventSubscription` records:
   - Create subscriptions with scope (`hive` or `apiary`)
   - Remove subscriptions by agent + event type
   - Bulk-replace subscriptions for an agent

3. **Dispatch (subscription matching)** — Given an event, find all matching subscriptions:
   - Hive events → subscriptions with `scope='hive'` where agent's `hive_id` matches event's `hive_id`
   - Cross-hive events → subscriptions with `scope='apiary'` where agent's `superpos_id` matches event's `superpos_id`
   - Return the matched agent IDs (for polling/notification)

4. **Poll** — Retrieve events for a given agent based on their subscriptions:
   - Fetch hive-scoped events matching hive subscriptions
   - Fetch cross-hive events matching apiary subscriptions
   - Support `since` timestamp for incremental polling
   - Return merged, chronologically ordered results

### Key Design Decisions

- Follows `ActivityLogger` pattern: service class with context validation
- Uses `withoutGlobalScopes()` for cross-tenant queries where needed
- Cross-hive detection via `apiary.*` type prefix (consistent with PRODUCT.md §7.2)
- Activity logging on publish (event_published action)
- No broadcasting integration (that's for dashboard layer, not agent bus)

## Test Plan

### Publish
- Publish hive-scoped event creates Event record with correct fields
- Publish cross-hive event (apiary.* prefix) sets is_cross_hive=true, hive_id=null
- Publish with source agent validates apiary membership
- Publish with invalid agent throws exception
- Publish logs activity via ActivityLogger
- Publish with payload persists payload correctly

### Subscribe / Unsubscribe
- Subscribe creates EventSubscription with correct scope
- Subscribe with duplicate (agent_id, event_type) is idempotent
- Unsubscribe removes subscription
- Unsubscribe non-existent subscription returns false
- Bulk replace replaces all subscriptions for agent

### Dispatch (subscription matching)
- Hive event matches hive-scoped subscriptions in same hive
- Hive event does not match subscriptions in different hive
- Cross-hive event matches apiary-scoped subscriptions in same apiary
- Cross-hive event does not match subscriptions in different apiary
- Event matches only subscriptions for matching event type
- Wildcard-free: exact type matching only

### Poll
- Poll returns hive events matching agent's hive subscriptions
- Poll returns cross-hive events matching agent's apiary subscriptions
- Poll respects `since` parameter for incremental polling
- Poll merges hive + cross-hive events in chronological order
- Poll returns empty collection when no matching subscriptions
- Poll does not return events from other hives/apiaries

## Validation Checklist

- [ ] EventBus service implements publish, subscribe, unsubscribe, dispatch, poll
- [ ] Cross-hive detection uses apiary.* prefix
- [ ] Activity logging on event publication
- [ ] Tenant isolation maintained (hive/apiary scoping)
- [ ] All tests pass
- [ ] PSR-12 compliant (Pint)
