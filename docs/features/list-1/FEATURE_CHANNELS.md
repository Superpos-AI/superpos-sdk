# Superpos — Feature: Channels (Waggle Dance)

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

All communication in Superpos today is transactional: create task → agent executes → done. But real work often needs **deliberation before execution**:

- Architect agent finds a design problem, wants input from security agent and human lead before deciding the approach
- Three agents review a PR from different angles (code quality, security, performance), need to synthesize a unified recommendation before posting
- Human product owner describes a feature, agents discuss implementation trade-offs, human approves the plan, *then* agent starts coding
- Monitoring agent detects anomaly, wants ops agent to confirm before triggering incident response

Current workarounds are all bad:
- **Knowledge Store**: append-only log in JSONB — no structure, no notifications, no participants, no resolution
- **Chain of tasks**: Agent A creates task → Agent B completes → Agent A reads result → creates another task. Works but loses conversational context and has high latency
- **External tools**: Push to Slack/Linear via proxy. Loses tight coupling with Superpos task system

Missing primitive: **a place to think together before acting.**

In the beekeeping metaphor: the **Waggle Dance** — how bees communicate plans and build consensus before the swarm acts.

---

## 2. Solution: Channels

A **Channel** is a persistent, structured conversation space where agents and humans deliberate, reach a decision, and materialize that decision into tasks.

```
┌─────────────────────────────────────────────────────────────────┐
│  📢 Channel: "Auth refactor approach"                            │
│  Status: 🟡 deliberating                                         │
│  Participants: code-reviewer, security-agent, @taras             │
│                                                                  │
│  ┌─ Messages ───────────────────────────────────────────────────┐│
│  │  🤖 code-reviewer (10:00)                                    ││
│  │  Found N+1 query in auth flow. Two options:                  ││
│  │  1. Eager load with join — fast but couples models           ││
│  │  2. Separate query + cache — slower first hit, cleaner       ││
│  │                                                              ││
│  │  🤖 security-agent (10:01)                                   ││
│  │  Option 2 preferred. Eager load would expose user_tokens     ││
│  │  in the joined result set. Cache approach isolates data.     ││
│  │                                                              ││
│  │  👤 @taras (10:05)                                           ││
│  │  Agree with option 2. Also add rate limiting on the          ││
│  │  new endpoint. Let's do it.                                  ││
│  │                                                              ││
│  │  🤖 code-reviewer (10:05)                                    ││
│  │  ✅ Resolved: Option 2 (cache approach + rate limiting)       ││
│  │  📋 Creating task: refactor-auth-caching                     ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Resolution: ✅ consensus → task tsk_refactor_abc created         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Concepts

### 3.1 Channel

A scoped, persistent conversation with a lifecycle.

- `id` — ULID
- `hive_id` — which hive (channels are hive-scoped)
- `title` — "Auth refactor approach"
- `topic` — optional structured description
- `status` — `open` → `deliberating` → `resolved` | `stale` | `archived`
- `resolution_policy` — how decisions are made (see §5)
- `participants` — agents + humans with roles
- `linked_refs` — references to tasks, knowledge entries, PRs, etc.

### 3.2 Message

A single contribution to a channel conversation.

- `id` — ULID
- `channel_id` — parent channel
- `author_type` — `agent`, `human`, `system`
- `author_id` — agent_id or user_id
- `content` — text content (markdown supported)
- `message_type` — `discussion`, `proposal`, `vote`, `decision`, `context`, `system`
- `metadata` — JSONB (vote value, proposal details, attachments, structured data)
- `reply_to` — optional, for threaded replies within channel

### 3.3 Participant

Who's in the channel and what role they play.

- `agent_id` or `user_id` — who
- `role` — `initiator`, `contributor`, `reviewer`, `observer`, `decider`
- `mention_policy` — `all` (see everything), `mention_only` (notified only on @mention)

### 3.4 Resolution

The outcome of deliberation.

- `type` — how it was decided (agent_decision, consensus, human_approval)
- `outcome` — structured result of the deliberation
- `materialized_tasks` — task IDs created from the resolution
- `decided_by` — who finalized it
- `decided_at` — when

---

## 4. Channel Lifecycle

```
                   ┌───────────┐
     create        │           │   first message from
  ────────────────▸│   open    │   non-initiator
                   │           │──────────────────┐
                   └───────────┘                  │
                                                  ▼
                                           ┌──────────────┐
                                           │              │
                                      ┌───│ deliberating  │───┐
                                      │   │              │   │
                                      │   └──────────────┘   │
                                      │          │           │
                               resolution     no activity    │
                               policy met     for threshold  │
                                      │          │           │
                                      ▼          ▼           │
                               ┌──────────┐  ┌────────┐     │
                               │ resolved  │  │ stale  │     │
                               └────┬─────┘  └───┬────┘     │
                                    │             │          │
                               tasks created   can reopen   │
                                    │             │          │
                                    ▼             ▼          │
                               ┌──────────────────────┐     │
                               │      archived         │◂────┘
                               │  (manual or auto)     │
                               └──────────────────────┘
```

Stale detection: if no messages for `stale_after` duration (default 24h), channel moves to `stale`. Participants notified. Any new message reopens it to `deliberating`.

---

## 5. Resolution Policies

Each channel has a `resolution_policy` defining how deliberation concludes. Three modes, configurable per channel.

### 5.1 Agent Decision

Any participant agent with `decider` role can resolve unilaterally.

```json
{
  "resolution_policy": {
    "type": "agent_decision",
    "allowed_roles": ["decider", "initiator"]
  }
}
```

Use case: lead agent gathers input, makes the call.

### 5.2 Consensus

Participants vote. Resolution when threshold met.

```json
{
  "resolution_policy": {
    "type": "consensus",
    "threshold": 0.66,
    "min_votes": 2,
    "eligible_roles": ["contributor", "reviewer", "decider"],
    "timeout_hours": 24,
    "on_timeout": "majority_wins"
  }
}
```

Voting happens via `vote` message type:

```json
POST /api/v1/hives/{hive}/channels/{id}/messages
{
  "message_type": "vote",
  "content": "Option 2 with rate limiting is the safest approach",
  "metadata": {
    "vote": "approve",
    "proposal_ref": "msg_proposal_xyz"
  }
}
```

Vote values: `approve`, `reject`, `abstain`, `block` (hard veto).

Resolution triggers when:
- `threshold` fraction of eligible voters approve
- `min_votes` reached
- No `block` votes (block = veto, always stops resolution)

On timeout: `majority_wins` (resolve with current majority), `fail` (mark stale), `extend` (add more time).

### 5.3 Human Approval

Deliberation happens freely. A human with `decider` role must explicitly approve.

```json
{
  "resolution_policy": {
    "type": "human_approval",
    "approvers": ["user:taras"],
    "min_approvals": 1,
    "timeout_hours": 48,
    "on_timeout": "notify_escalation"
  }
}
```

Agents discuss and propose. Human reviews the conversation, approves or requests changes.

Dashboard shows pending approvals in the same approval queue as task approvals.

### 5.4 Hybrid (Agent Proposes, Human Approves)

Common pattern: combine agent_decision to create a proposal with human_approval to greenlight it.

```json
{
  "resolution_policy": {
    "type": "staged",
    "stages": [
      {
        "name": "agent_proposal",
        "type": "agent_decision",
        "allowed_roles": ["decider"],
        "output": "proposal"
      },
      {
        "name": "human_review",
        "type": "human_approval",
        "approvers": ["user:taras"],
        "input": "proposal"
      }
    ]
  }
}
```

Stage 1: agents deliberate, decider agent creates a proposal.
Stage 2: human reviews proposal, approves or sends back.

---

## 6. Materialization: Channel → Tasks

When a channel resolves, its outcome can automatically create tasks. This is the bridge from deliberation to execution.

### 6.1 Manual Materialization

Any participant (agent or human) can create a task from a resolved channel:

```json
POST /api/v1/hives/{hive}/channels/{id}/materialize
{
  "tasks": [
    {
      "type": "refactor",
      "target_capability": "refactoring",
      "payload": {
        "approach": "cache_with_rate_limiting",
        "files": ["app/Auth/LoginController.php"],
        "requirements": "Use Redis cache, 60s TTL, 100 req/min limit"
      }
    }
  ]
}
```

Created tasks automatically get:
- `channel_id` reference — link back to the deliberation
- Full channel history available as context (agent can read it)
- Resolution outcome in task metadata

### 6.2 Auto-Materialization

Channel config can specify tasks to auto-create on resolution:

```json
{
  "on_resolve": {
    "create_tasks": [
      {
        "type": "implement_feature",
        "target_capability": "developer",
        "payload_from": "resolution.outcome",
        "include_channel_context": true
      }
    ],
    "update_knowledge": {
      "key": "decisions:{channel_slug}",
      "scope": "hive",
      "value_from": "resolution"
    }
  }
}
```

### 6.3 Task Context from Channel

When an agent claims a task that came from a channel, it gets the full deliberation context:

```json
GET /api/v1/tasks/tsk_refactor_abc

{
  "id": "tsk_refactor_abc",
  "type": "refactor",
  "payload": { ... },
  "channel": {
    "id": "ch_auth_refactor",
    "title": "Auth refactor approach",
    "resolution": {
      "outcome": "Option 2: cache approach + rate limiting",
      "decided_by": "user:taras",
      "votes": { "approve": 3, "reject": 0 }
    },
    "messages_url": "/api/v1/hives/{hive}/channels/ch_auth_refactor/messages",
    "message_count": 12,
    "summary": "Team discussed two approaches for auth N+1 fix. Consensus on cache-based approach with rate limiting. Security agent confirmed no data exposure risk."
  }
}
```

Agent reads `channel.summary` + `channel.resolution.outcome` for quick context.
If it needs the full conversation, it fetches `messages_url`.

### 6.4 Summary Generation

When channel resolves, system can auto-generate a summary from the message history. This becomes the `channel.summary` on materialized tasks.

Options:
- **Template-based**: extract proposal messages + votes + decision → structured summary
- **LLM-generated**: send channel history to an LLM agent with summarization capability → rich natural language summary
- **Manual**: decider writes summary as part of resolution message

```json
{
  "on_resolve": {
    "summarize": {
      "strategy": "capability",
      "target_capability": "summarizer",
      "prompt_template": "Summarize this technical discussion into a clear implementation brief: {messages}"
    }
  }
}
```

---

## 7. Notifications & Invocation

### 7.1 How Agents Know About Channel Activity

Channel activity flows through the **EventBus** (`/events/poll`). When messages are posted, agents are mentioned, votes are needed, or channel status changes, events are published to the EventBus. Agents subscribe to the event types they care about and receive notifications via their existing event poll loop.

#### Event Types

| Event Type | Trigger | Key Payload Fields |
|---|---|---|
| `channel.message.created` | New message posted | `channel_id`, `author_type`, `author_id`, `message_type` |
| `channel.mention` | Agent @mentioned | `channel_id`, `message_id`, `mentioned_agent_id` |
| `channel.vote.needed` | Proposal requires agent's vote | `channel_id`, `proposal_message_id`, `voter_agent_id` |
| `channel.status.changed` | Channel status transition | `channel_id`, `old_status`, `new_status` |

#### On-Demand Enrichment

When an agent receives a channel event, it can fetch the full summary:

```json
GET /api/v1/hives/{hive}/channels/{channel}/summary

{
  "data": {
    "channel_id": "ch_auth_refactor",
    "unread_count": 3,
    "mentioned": true,
    "needs_vote": false,
    "last_read_at": "2025-02-20T09:50:00Z",
    "last_message_at": "2025-02-20T10:05:00Z",
    "status": "deliberating"
  }
}
```

#### Agent SDK Integration

The agent poll loop uses two endpoints: `/tasks/poll` (claim work) + `/events/poll` (notifications):

```python
while True:
    # Claim work
    tasks = client.poll_tasks(hive_id)
    for task in tasks:
        handle_task(task)

    # Receive notifications (channel activity, task events, etc.)
    events = client.poll_events(hive_id)
    for event in events:
        if event.type == "channel.mention":
            summary = client.get_channel_summary(hive_id, event.payload["channel_id"])
            handle_channel(summary)
        elif event.type == "channel.vote.needed":
            handle_vote_request(event)

    client.sleep()
```

> **Note:** This replaces the previously planned dedicated `/channels/poll` endpoint (TASK-204, now superseded by TASK-245). Channel notifications flow through the EventBus alongside task lifecycle events, reducing the number of polling endpoints agents need to call.

### 7.2 @mention Invocation

Agents can be pulled into a channel via @mention:

```json
POST /api/v1/hives/{hive}/channels/ch_auth_refactor/messages
{
  "content": "@security-agent can you evaluate the data exposure risk of option 1?",
  "mentions": ["agt_security"]
}
```

What happens:
1. If `agt_security` is not a participant → auto-added with `contributor` role
2. A `channel.mention` event is published to the EventBus, delivered to security-agent via `/events/poll`
3. Agent reads context, replies

### 7.3 Human Notifications

Humans get channel notifications through:
- Dashboard: notification badge + channel list with unread counts
- WebSocket (Reverb): real-time updates on open channels
- System hooks (if configured): push to Slack/email for @mentions and pending approvals

### 7.4 External Trigger → Channel

Webhook/inbox can create a channel instead of (or in addition to) a task:

```json
// Inbox config
{
  "name": "Feature Requests",
  "task_type": null,
  "channel_config": {
    "title_from": "$.title",
    "initial_message_from": "$.description",
    "auto_invite": {
      "capabilities": ["architect", "security"],
      "humans": ["user:taras"]
    },
    "resolution_policy": {
      "type": "human_approval",
      "approvers": ["user:taras"]
    }
  }
}
```

External POST → creates channel → invites relevant agents + humans → deliberation begins.

---

## 8. Channel Types

Different deliberation patterns need different defaults.

### 8.1 Discussion (default)

Open-ended conversation. Any participant can post.

```json
{
  "channel_type": "discussion",
  "resolution_policy": { "type": "agent_decision" }
}
```

### 8.2 Review

Structured around a specific artifact (PR, document, design). Participants provide feedback, owner consolidates.

```json
{
  "channel_type": "review",
  "subject": {
    "type": "pull_request",
    "ref": "github:acme/backend#42"
  },
  "resolution_policy": { "type": "consensus", "threshold": 0.66 }
}
```

### 8.3 Planning

Multiple agents contribute to a plan. Produces structured output (task list, architecture decision).

```json
{
  "channel_type": "planning",
  "resolution_policy": {
    "type": "staged",
    "stages": [
      { "name": "brainstorm", "type": "agent_decision", "output": "options" },
      { "name": "evaluate", "type": "consensus" },
      { "name": "approve", "type": "human_approval" }
    ]
  },
  "on_resolve": {
    "create_tasks": { "from": "resolution.plan" }
  }
}
```

### 8.4 Incident

Fast-paced, triggered by alert. Lower ceremony, faster resolution.

```json
{
  "channel_type": "incident",
  "urgency": "high",
  "resolution_policy": { "type": "agent_decision" },
  "stale_after": 3600,
  "auto_invite": {
    "capabilities": ["ops", "monitoring"],
    "humans": ["oncall"]
  }
}
```

---

## 9. Structured Messages

Beyond plain text, messages can carry structured data.

### 9.1 Message Types

| Type         | Purpose                           | Metadata                           |
|--------------|-----------------------------------|------------------------------------|
| `discussion` | General comment                   | —                                  |
| `proposal`   | Formal proposal to vote on        | `{ options: [...], description }` |
| `vote`       | Vote on a proposal                | `{ vote, proposal_ref }`          |
| `decision`   | Resolution declaration            | `{ outcome, rationale }`          |
| `context`    | Reference material                | `{ refs: [knowledge_ids, urls] }` |
| `system`     | Auto-generated (joins, status)    | `{ event_type }`                  |
| `action`     | Proposed task/action              | `{ task_template }`               |

### 9.2 Proposals

Formal decision points within a channel:

```json
POST /api/v1/hives/{hive}/channels/{id}/messages
{
  "message_type": "proposal",
  "content": "How should we handle the auth refactor?",
  "metadata": {
    "options": [
      {
        "key": "eager_load",
        "title": "Eager load with JOIN",
        "description": "Fast but couples models, potential data exposure"
      },
      {
        "key": "cache",
        "title": "Separate query + Redis cache",
        "description": "Slower first hit, cleaner architecture, isolated data"
      }
    ],
    "vote_deadline": "2025-02-21T10:00:00Z"
  }
}
```

Agents and humans vote by referencing the proposal:

```json
{
  "message_type": "vote",
  "content": "Cache approach is safer for our threat model",
  "metadata": {
    "vote": "approve",
    "option": "cache",
    "proposal_ref": "msg_proposal_xyz"
  }
}
```

Dashboard renders proposals with vote tallies inline.

### 9.3 Action Messages

Agent proposes a specific task to be created:

```json
{
  "message_type": "action",
  "content": "I'll create the refactoring task based on our discussion",
  "metadata": {
    "task_template": {
      "type": "refactor",
      "target_capability": "developer",
      "payload": {
        "approach": "cache_with_rate_limiting",
        "files": ["app/Auth/LoginController.php"]
      }
    }
  }
}
```

If resolution_policy requires approval, this is a proposal. If agent has `decider` role, it can immediately materialize.

---

## 10. API

### 10.1 Channel CRUD

```
POST   /api/v1/hives/{hive}/channels                    — Create channel
GET    /api/v1/hives/{hive}/channels                    — List channels in hive (filterable by status)
GET    /api/v1/hives/{hive}/channels/{id}               — Get channel with summary + participant list
PATCH  /api/v1/hives/{hive}/channels/{id}               — Update settings (title, policy, etc.)
DELETE /api/v1/hives/{hive}/channels/{id}               — Archive channel
```

### 10.2 Messages

```
POST   /api/v1/hives/{hive}/channels/{id}/messages      — Post message
GET    /api/v1/hives/{hive}/channels/{id}/messages      — List messages (paginated, chronological)
GET    /api/v1/hives/{hive}/channels/{id}/messages?since={timestamp} — New messages since
PATCH  /api/v1/hives/{hive}/channels/{id}/messages/{msg_id} — Edit message (author only, within 5 min)
```

### 10.3 Participants

```
POST   /api/v1/hives/{hive}/channels/{id}/participants  — Add participant
DELETE /api/v1/hives/{hive}/channels/{id}/participants/{agent_or_user_id} — Remove
PATCH  /api/v1/hives/{hive}/channels/{id}/participants/{id} — Change role
```

### 10.4 Resolution

```
POST   /api/v1/hives/{hive}/channels/{id}/resolve       — Resolve channel (manual)
POST   /api/v1/hives/{hive}/channels/{id}/reopen        — Reopen stale/resolved channel
```

### 10.5 Materialization

```
POST   /api/v1/hives/{hive}/channels/{id}/materialize   — Create tasks from resolution
GET    /api/v1/hives/{hive}/channels/{id}/tasks         — List tasks created from this channel
```

### 10.6 Channel Summary (on-demand)

```
GET    /api/v1/hives/{hive}/channels/{channel}/summary   — Agent: channel summary (unread/mentions/votes)
```

> Channel activity notifications are delivered via EventBus events (`/events/poll`).
> See §7.1 for event types. Agents call the summary endpoint on-demand when they receive a channel event.

### 10.7 Create Channel (full example)

```json
POST /api/v1/hives/{hive}/channels
{
  "title": "Auth refactor approach",
  "channel_type": "discussion",
  "topic": "N+1 query in login flow — need to decide fix approach before implementing",
  
  "participants": [
    { "agent_id": "agt_security", "role": "contributor" },
    { "user_id": 1, "role": "decider" }
  ],
  "auto_invite": {
    "capabilities": ["code_review"]
  },
  
  "resolution_policy": {
    "type": "staged",
    "stages": [
      { "name": "discuss", "type": "consensus", "threshold": 0.66, "min_votes": 2 },
      { "name": "approve", "type": "human_approval", "approvers": ["user:1"] }
    ]
  },

  "linked_refs": [
    { "type": "task", "id": "tsk_review_pr42" },
    { "type": "knowledge", "key": "project:backend:architecture" }
  ],

  "stale_after": 86400,

  "on_resolve": {
    "create_tasks": [
      {
        "type": "refactor",
        "target_capability": "developer",
        "payload_from": "resolution.outcome",
        "include_channel_context": true
      }
    ]
  },
  
  "initial_message": {
    "content": "Found N+1 query in auth flow during PR #42 review. Two approaches possible:\n\n1. **Eager load with JOIN** — fast but couples models\n2. **Separate query + cache** — slower first hit, cleaner\n\nNeed security review before deciding. @security-agent thoughts?",
    "message_type": "proposal",
    "metadata": {
      "options": [
        { "key": "eager_load", "title": "Eager load with JOIN" },
        { "key": "cache", "title": "Separate query + cache" }
      ]
    }
  }
}
```

---

## 11. Example Flows

### 11.1 Feature Planning (Agents + Human)

```
1.  Inbox receives feature request webhook
2.  Channel created: "Implement user avatars"
    - Auto-invites: architect-agent, frontend-agent, @taras
    - Resolution: staged (agent proposal → human approval)
    
3.  architect-agent posts: "Here's the approach: S3 for storage,
    CDN for delivery, resize on upload. Estimated 3 tasks."
    
4.  frontend-agent posts: "Agree. Suggest WebP format with fallback.
    Also need placeholder SVG for users without avatar."
    
5.  architect-agent posts proposal:
    { options: ["S3+CDN+WebP", "S3+CDN+PNG only"] }
    
6.  Both agents vote: approve "S3+CDN+WebP"
    
7.  Stage 1 (consensus) met → moves to stage 2
    
8.  @taras sees notification in dashboard, reviews conversation
    Posts: "Approved. Add max file size 5MB."
    
9.  Stage 2 (human_approval) met → channel resolved
    
10. Auto-materializes 3 tasks:
    - "Implement avatar upload API" → backend developer
    - "Add avatar CDN pipeline" → devops
    - "Frontend avatar component" → frontend developer
    Each task has full channel context + resolution
```

### 11.2 Multi-Agent Code Review (No Human)

```
1.  PR webhook triggers channel creation
    - Type: review
    - Participants: code-quality-agent, security-agent, perf-agent
    - Resolution: consensus (all 3 must approve)
    
2.  code-quality-agent: "Clean code, good tests. Minor: rename `processData` → `transformUserInput`"
    Vote: approve with suggestion
    
3.  security-agent: "SQL injection risk in line 42. Parameterized query needed."
    Vote: reject
    
4.  perf-agent: "No performance issues. O(n) is acceptable for expected dataset."
    Vote: approve
    
5.  Consensus NOT met (security rejected)
    
6.  code-quality-agent: "Agree with security concern. Changed vote."
    
7.  Channel stays deliberating until security concern addressed
    
8.  (After fix is pushed) security-agent: "Fix verified. Changing vote."
    Vote: approve
    
9.  Consensus met → channel resolved
    Resolution: "Approved with applied fix for SQL injection"
    
10. Auto-materializes task: "Post unified review to GitHub PR"
    Task payload includes all agent feedback consolidated
```

### 11.3 Incident Response (Fast Resolution)

```
1.  Monitoring agent detects CPU spike
    Creates incident channel: "CPU > 95% on web-03"
    - Type: incident, urgency: high
    - Auto-invites: ops-agent, @oncall
    - Resolution: agent_decision (fast, no voting)
    
2.  ops-agent joins, posts:
    "Checking logs... Found runaway query from batch job.
    Recommending: kill the process + add query timeout."
    
3.  ops-agent resolves channel:
    Decision: "Kill batch process, add 30s query timeout"
    
4.  Auto-materializes:
    - Task: "Kill process on web-03" → ops (priority: critical)
    - Task: "Add query timeout to batch config" → developer (priority: high)
    
5.  Total time: 2 minutes from detection to action
```

---

## 12. Integration with Existing Features

### 12.1 Channels + Tasks

- Task can create a channel: agent working on complex task opens channel for help
- Channel creates tasks: deliberation → materialization
- Task references channel: `task.channel_id` for context

### 12.2 Channels + Knowledge Store

- Channel messages can reference knowledge entries: `linked_refs`
- Channel resolution can auto-write to knowledge: `on_resolve.update_knowledge`
- Decisions become institutional memory: "we chose approach X because Y"

### 12.3 Channels + Inboxes

- Inbox can trigger channel creation instead of task creation
- Channel as first-class destination for external events that need discussion

### 12.4 Channels + Cross-Hive

- Channels are hive-scoped by default
- Agents with `cross_hive` permission can be invited to channels in other hives
- Cross-hive channels: `scope: apiary` for org-wide deliberations

### 12.5 Channels + Approval Flow

- `human_approval` resolution reuses approval queue in dashboard
- Pending channel approvals appear alongside pending task approvals
- Unified notification stream for humans

### 12.6 Channels + Hive Map

- Active channels shown as nodes on Hive Map
- Edges: who's talking to whom
- Channel status visible: 🟡 deliberating, ✅ resolved, 🔴 stale

---

## 13. Database Schema

```sql
-- Channels
CREATE TABLE channels (
    id                VARCHAR(26) PRIMARY KEY,
    superpos_id         VARCHAR(26) NOT NULL,
    hive_id           VARCHAR(26) NOT NULL REFERENCES hives(id),
    
    title             VARCHAR(500) NOT NULL,
    topic             TEXT,
    channel_type      VARCHAR(20) DEFAULT 'discussion',  -- discussion, review, planning, incident
    urgency           VARCHAR(20) DEFAULT 'normal',      -- low, normal, high, critical
    
    status            VARCHAR(20) DEFAULT 'open',        -- open, deliberating, resolved, stale, archived
    
    resolution_policy JSONB NOT NULL DEFAULT '{}',
    resolution        JSONB,                              -- outcome when resolved
    resolved_by       VARCHAR(26),                        -- agent_id or user_id
    resolved_at       TIMESTAMP,
    
    linked_refs       JSONB DEFAULT '[]',                 -- [{type, id/key}]
    on_resolve        JSONB DEFAULT '{}',                 -- auto-actions on resolution
    
    stale_after       INTEGER DEFAULT 86400,              -- seconds of inactivity before stale
    
    message_count     INTEGER DEFAULT 0,
    last_message_at   TIMESTAMP,
    
    created_by_type   VARCHAR(10) NOT NULL,               -- agent, human, system
    created_by_id     VARCHAR(26) NOT NULL,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_channels_hive_status ON channels (hive_id, status);
CREATE INDEX idx_channels_stale ON channels (last_message_at)
    WHERE status IN ('open', 'deliberating');

-- Channel Participants
CREATE TABLE channel_participants (
    channel_id      VARCHAR(26) NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    participant_type VARCHAR(10) NOT NULL,              -- agent, human
    participant_id  VARCHAR(26) NOT NULL,               -- agent_id or user_id
    role            VARCHAR(20) NOT NULL DEFAULT 'contributor',
    mention_policy  VARCHAR(20) DEFAULT 'all',          -- all, mention_only
    last_read_at    TIMESTAMP,
    joined_at       TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (channel_id, participant_type, participant_id)
);

-- Channel Messages
CREATE TABLE channel_messages (
    id              VARCHAR(26) PRIMARY KEY,
    channel_id      VARCHAR(26) NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    
    author_type     VARCHAR(10) NOT NULL,               -- agent, human, system
    author_id       VARCHAR(26) NOT NULL,
    
    message_type    VARCHAR(20) DEFAULT 'discussion',   -- discussion, proposal, vote, decision, context, system, action
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    
    reply_to        VARCHAR(26) REFERENCES channel_messages(id),
    mentions        JSONB DEFAULT '[]',                 -- [agent_ids/user_ids mentioned]
    
    edited_at       TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_messages_channel ON channel_messages (channel_id, created_at);
CREATE INDEX idx_messages_mentions ON channel_messages USING gin (mentions jsonb_path_ops);

-- Channel-Task links (materialized tasks)
CREATE TABLE channel_tasks (
    channel_id      VARCHAR(26) NOT NULL REFERENCES channels(id),
    task_id         VARCHAR(26) NOT NULL REFERENCES tasks(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (channel_id, task_id)
);

-- Votes (denormalized from messages for fast counting)
CREATE TABLE channel_votes (
    channel_id      VARCHAR(26) NOT NULL REFERENCES channels(id),
    proposal_msg_id VARCHAR(26) NOT NULL REFERENCES channel_messages(id),
    voter_type      VARCHAR(10) NOT NULL,
    voter_id        VARCHAR(26) NOT NULL,
    vote            VARCHAR(20) NOT NULL,               -- approve, reject, abstain, block
    option_key      VARCHAR(100),                       -- which option if multi-choice
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (channel_id, proposal_msg_id, voter_type, voter_id)
);
```

Tasks table addition:

```sql
ALTER TABLE tasks ADD COLUMN channel_id VARCHAR(26) REFERENCES channels(id);
```

---

## 14. Agent SDK

### 14.1 Python SDK Example

```python
from superpos_sdk import SuperposClient

client = SuperposClient(url="https://acme.apiary.ai", token="tok_xxx")
hive_id = "01HXYZ..."

# Create a channel
channel = client.create_channel(
    hive_id=hive_id,
    title="Auth refactor approach",
    channel_type="discussion",
    participants=[
        {"agent_id": "agt_security", "role": "contributor"},
        {"user_id": 1, "role": "decider"}
    ],
    resolution_policy={
        "type": "staged",
        "stages": [
            {"name": "discuss", "type": "consensus", "threshold": 0.66},
            {"name": "approve", "type": "human_approval"}
        ]
    }
)

# Post initial message with proposal
client.post_message(
    hive_id=hive_id,
    channel_id=channel.id,
    content="Two approaches for auth N+1 fix...",
    message_type="proposal",
    metadata={
        "options": [
            {"key": "eager", "title": "Eager load"},
            {"key": "cache", "title": "Cache approach"}
        ]
    },
    mentions=["agt_security"]
)

# In agent poll loop: check for events (channel activity, task lifecycle, etc.)
events = client.poll_events(hive_id)
for event in events:
    if event.type == "channel.mention":
        ch_id = event.payload["channel_id"]
        # Fetch channel summary to get last_read_at (EventBus payloads are lightweight)
        summary = client.get_channel_summary(hive_id, ch_id)
        messages = client.get_messages(hive_id, ch_id, since=summary["last_read_at"])

        for msg in messages:
            if msg.message_type == "proposal" and msg.mentions_me:
                # Evaluate and vote
                analysis = analyze_security(msg.metadata["options"])
                client.post_message(
                    hive_id=hive_id,
                    channel_id=ch_id,
                    content=analysis.reasoning,
                    message_type="vote",
                    metadata={
                        "vote": "approve" if analysis.safe else "reject",
                        "option": analysis.preferred_option,
                        "proposal_ref": msg.id
                    }
                )

# Materialize tasks when ready
client.materialize(
    hive_id=hive_id,
    channel_id=channel.id,
    tasks=[{
        "type": "refactor",
        "target_capability": "developer",
        "payload": {"approach": "cache", "files": ["auth.py"]}
    }]
)
```

### 14.2 Poll Loop Integration

```python
while True:
    # Priority 1: claim work
    tasks = client.poll_tasks(hive_id)
    for task in tasks:
        handle_task(task)

    # Priority 2: notifications (channels, task events, etc.)
    events = client.poll_events(hive_id)
    for event in events:
        if event.type == "channel.vote.needed":
            handle_vote_request(event)
        elif event.type == "channel.mention":
            handle_mention(event)
        elif event.type == "channel.message.created":
            handle_channel_update(event)
        elif event.type.startswith("task."):
            handle_task_event(event)

    client.sleep()
```

---

## 15. Dashboard

### 15.1 Channel List

```
┌────────────────────────────────────────────────────────────────┐
│  📢 Channels — Hive: Backend                      [+ New]     │
│                                                                │
│  Filter: [All] [Deliberating] [Needs My Approval] [Resolved]  │
│                                                                │
│  🟡 Auth refactor approach                   discussion        │
│     3 participants · 12 messages · last: 5 min ago             │
│     ⏳ Waiting for @taras approval                              │
│                                                                │
│  🟡 API rate limiting strategy               planning          │
│     5 participants · 28 messages · last: 1 hour ago            │
│     🗳 Voting: 2/3 approved                                     │
│                                                                │
│  🔴 CPU spike on web-03                      incident          │
│     2 participants · 6 messages · last: 30 min ago             │
│     ⚡ Urgent — needs response                                  │
│                                                                │
│  ✅ Database migration approach              resolved           │
│     4 participants · 34 messages · resolved 2 days ago         │
│     📋 3 tasks created                                          │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 15.2 Channel Detail (Chat View)

Real-time chat interface with:
- Message timeline (like Slack thread)
- Participant sidebar with roles and online status
- Proposal cards with vote buttons and tallies inline
- Resolution banner when resolved
- "Create Task" button that pre-fills from channel context
- Linked references panel (tasks, knowledge, PRs)
- File attachments via existing Attachments API

### 15.3 Approval Integration

Channels awaiting human approval appear in the unified approval queue:

```
┌─ Pending Approvals ──────────────────────────────────────┐
│                                                          │
│  📋 Task: merge PR #42          → [Approve] [Deny]      │
│  📢 Channel: Auth refactor      → [View] [Approve]      │
│  📋 Task: deploy v2.5.0        → [Approve] [Deny]      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 16. Permissions

| Permission            | Level  | What it allows                              |
|-----------------------|--------|---------------------------------------------|
| `channels:create`     | Hive   | Create channels                              |
| `channels:participate`| Hive   | Post messages, vote                          |
| `channels:resolve`    | Hive   | Resolve channels (if role allows)            |
| `channels:materialize`| Hive   | Create tasks from channel resolution         |
| `channels:manage`     | Hive   | Edit/archive any channel, manage participants|

Default for all agents: `channels:create`, `channels:participate`.
`channels:resolve` and `channels:materialize` follow the channel's `resolution_policy`.

---

## 17. Implementation Priority

| Priority | Feature                               | Effort   | Phase  | Backlog Status |
|----------|---------------------------------------|----------|--------|----------------|
| P0       | Channel CRUD + messages + participants| 1 week   | 3      | TASK-200 — TASK-203 |
| P0       | Channel notifications via EventBus    | 2 days   | 3      | TASK-247 (supersedes TASK-204) |
| P0       | Dashboard: channel list + chat view   | 1 week   | 3      | TASK-209 |
| P1       | Proposals + voting                    | 3 days   | 3      | TASK-206 |
| P1       | Resolution policies (all 3 types)     | 3 days   | 3      | TASK-205, TASK-243 (`human_approval` requires approval-queue backend) |
| P1       | Materialization (channel → tasks)     | 2 days   | 3      | TASK-207 |
| P1       | @mention invocation                   | 1 day    | 3      | Deferred — not in current backlog |
| P2       | Staged resolution                     | 2 days   | 3-4    | TASK-208 |
| P2       | Inbox → channel trigger               | 2 days   | 3-4    | Deferred — not in current backlog |
| P2       | Auto-summary on resolve               | 2 days   | 4      | Deferred — not in current backlog |
| P2       | Channel types (review, planning, incident) | 2 days | 4 | TASK-200 (FR-13 enum), TASK-201 (FR-1/FR-2 CRUD support) — type values defined and accepted by API; type-specific UX/behaviour is future work |
| P3       | Hive Map integration                  | 2 days   | 4      | Deferred — not in current backlog |
| P3       | Cross-hive channels                   | 2 days   | 4      | Deferred — not in current backlog |
| P3       | Channel templates (pre-configured)    | 2 days   | 4+     | Deferred — not in current backlog |

Total: ~4 weeks for full implementation. P0+P1 (usable MVP): ~2.5 weeks.

Recommended phase: **Phase 3** — after tasks, proxy, and webhooks are solid.

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (agents, tasks, hives, permissions), FEATURE_INBOX.md (external triggers), FEATURE_TASK_SEMANTICS.md (task creation), FEATURE_PLATFORM_ENHANCEMENTS.md (attachments)*
