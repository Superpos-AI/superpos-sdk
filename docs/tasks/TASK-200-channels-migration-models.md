# TASK-200: Channels migration + models

**Status:** done
**Branch:** `task/200-channels-migration-models`
**Depends on:** TASK-005, TASK-006
**Blocks:** TASK-201, TASK-203, TASK-204, TASK-211
**Edition:** shared
**Feature doc:** [FEATURE_CHANNELS.md](../features/list-1/FEATURE_CHANNELS.md)

## Objective

Create the database schema and Eloquent models for the Channels feature (Waggle Dance). This is the foundation: five tables (`channels`, `channel_participants`, `channel_messages`, `channel_votes`, `channel_tasks`) plus a `channel_id` foreign key on the existing `tasks` table.

## Requirements

### Functional

- [ ] FR-1: `channels` table with all columns from feature spec §13: id (ULID), superpos_id, hive_id, title, topic, channel_type, urgency, status, resolution_policy (JSONB), resolution (JSONB), resolved_by, resolved_at, linked_refs (JSONB), on_resolve (JSONB), stale_after, message_count, last_message_at, created_by_type, created_by_id, timestamps
- [ ] FR-2: `channel_participants` table: composite PK (channel_id, participant_type, participant_id), role, mention_policy, last_read_at, joined_at
- [ ] FR-3: `channel_messages` table: id (ULID), channel_id, author_type, author_id, message_type, content, metadata (JSONB), reply_to (self-ref FK), mentions (JSONB), edited_at, created_at
- [ ] FR-4: `channel_votes` table: composite PK (channel_id, proposal_msg_id, voter_type, voter_id), vote, option_key, timestamps
- [ ] FR-5: `channel_tasks` table: composite PK (channel_id, task_id), created_at
- [ ] FR-6: Add `channel_id` nullable FK column to `tasks` table
- [ ] FR-7: Channel model with `BelongsToHive` trait, status constants, casts for JSONB columns
- [ ] FR-8: ChannelMessage model with relationships to Channel, reply_to self-relation
- [ ] FR-9: ChannelParticipant model
- [ ] FR-10: ChannelVote model
- [ ] FR-11: Indexes: (hive_id, status) on channels, (channel_id, created_at) on messages, GIN on messages.mentions
- [ ] FR-12: Channel status enum: open, deliberating, resolved, stale, archived
- [ ] FR-13: Channel type enum: discussion, review, planning, incident
- [ ] FR-14: Message type enum: discussion, proposal, vote, decision, context, system, action
- [ ] FR-15: Database factories for all new models

### Non-Functional

- [ ] NFR-1: All primary keys use ULIDs
- [ ] NFR-2: Migrations are idempotent and safe for rolling deploys
- [ ] NFR-3: PSR-12 compliant
