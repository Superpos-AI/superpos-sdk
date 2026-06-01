# TASK-212: SDK — channel methods (Python + Shell)

**Status:** in_progress
**Branch:** `task/212-sdk-channels`
**Depends on:** TASK-201, TASK-202, TASK-203, TASK-247
**Edition:** shared
**Feature doc:** [FEATURE_CHANNELS.md](../features/list-1/FEATURE_CHANNELS.md) §14

## Objective

Add channel support to the Python and Shell SDKs. Agents need to create channels, post messages, vote, poll for activity, and materialize tasks from resolutions.

## Requirements

### Functional

- [ ] FR-1: Python SDK: `client.create_channel(hive_id, ...)` — create channel with full options
- [ ] FR-2: Python SDK: `client.post_message(hive_id, ...)` — post message with type, metadata, mentions
- [ ] FR-3: Python SDK: `client.poll_events(hive_id)` — poll for channel activity via EventBus (`GET /api/v1/hives/{hive}/events/poll`). Agents subscribe to `channel.*` event types (e.g., `channel.message.created`, `channel.mention`, `channel.vote.needed`) via `POST /api/v1/agents/subscriptions` and receive notifications through the unified event polling endpoint. Replaces the dedicated `poll_channels()` approach from TASK-204.
- [ ] FR-4: Python SDK: `client.get_messages(hive_id, ...)` — list messages with `since` parameter
- [ ] FR-5: Python SDK: `client.materialize(hive_id, ...)` — create tasks from channel resolution
- [ ] FR-6: Python SDK: `client.resolve_channel(hive_id, ...)` — resolve channel manually
- [ ] FR-7: Python SDK: `client.get_channel_summary(hive_id, channel_id)` — fetches on-demand channel summary via `GET /api/v1/hives/{hive}/channels/{channel}/summary` (see TASK-248). Returns unread count, mention status, vote status, and `last_read_at` (the agent's last read position, used for incremental message fetching).
- [ ] FR-8: Shell SDK: equivalent functions in `superpos-sdk.sh`
- [ ] FR-9: Poll loop integration example: poll tasks via `/tasks/poll`, then poll events via `/events/poll` for both task and channel notifications in a single loop
- [ ] FR-10: Convenience: `msg.mentions_me` property for easy mention detection (derived from `channel.mention` events where `mentioned_agent_id` matches the current agent)
- [ ] FR-11: Unit tests for new SDK methods
