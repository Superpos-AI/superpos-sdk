# Superpos — Feature: Hive Map (Visual Topology)

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

The current dashboard design is list-based: agent list, task board, log tables. Works for operational tasks but fails to answer the big-picture questions:

- "How does data flow through my system?"
- "Which agents depend on which services?"
- "What happens when GitHub sends a webhook?"
- "Which hives talk to each other?"
- "Where are the bottlenecks right now?"

These are topology questions. They need a visual answer.

## 2. Solution: Hive Map

An interactive, real-time graph showing every node (agent, service, inbox, hive) and every connection (task flow, proxy access, webhook routes, cross-hive links) in the system.

Live. Animated. Showing actual data flowing through edges right now.

## 3. Views

Three zoom levels, from broad to focused.

### 3.1 Superpos View (Organization Level)

Shows all hives and their interconnections. Entry point when you open Hive Map.

```
┌────────────────────────────────────────────────────────────────────┐
│  🏢 Superpos: Acme Engineering                                      │
│                                                                    │
│         ┌──────────────────┐                                       │
│         │  ☁️  Services      │                                       │
│         │                  │                                       │
│         │  🟢 GitHub       │                                       │
│         │  🟢 Slack        │                                       │
│         │  🟢 AWS          │                                       │
│         │  🟡 PagerDuty    │                                       │
│         └────────┬─────────┘                                       │
│                  │                                                 │
│     ┌────────────┼─────────────────────┐                           │
│     │            │                     │                           │
│     ▼            ▼                     ▼                           │
│  ┌──────────┐ ┌──────────┐      ┌──────────┐                      │
│  │🐝 Backend │ │🐝 Mobile  │      │🐝 Infra   │                      │
│  │          │ │          │      │          │                      │
│  │ 3 agents │ │ 2 agents │      │ 1 agent  │                      │
│  │ 12 tasks │ │ 5 tasks  │      │ 0 tasks  │                      │
│  │ 🟢 healthy│ │ 🟡 busy   │      │ 🟢 idle   │                      │
│  └────┬─────┘ └──────────┘      └──────────┘                      │
│       │                                                            │
│       └──── cross-hive (4 tasks today) ────▸ Mobile                │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

What you see:
- Each hive as a card with summary stats
- Service connections shared across hives (top)
- Cross-hive task/event edges with volume indicators
- Health status per hive (derived from agent pool health)
- Click a hive → zoom into Hive View

### 3.2 Hive View (Project Level)

Shows everything inside a single hive: agents, their connections to services, inboxes, task flow between agents.

```
┌──────────────────────────────────────────────────────────────────────┐
│  🐝 Hive: Backend                                                    │
│                                                                      │
│  ┌─ Inboxes ────────────────────────┐   ┌─ Services ──────────────┐  │
│  │                                  │   │                         │  │
│  │  📥 PR Events ──────┐            │   │  🟢 GitHub  ◂─── proxy ──┤  │
│  │     47 today        │            │   │    5,420 reqs           │  │
│  │                     │ creates    │   │                         │  │
│  │  📥 CI Alerts ───┐  │ task       │   │  🟢 AWS     ◂─── proxy ──┤  │
│  │     12 today     │  │            │   │    120 reqs             │  │
│  └──────────────────┼──┼────────────┘   │                         │  │
│                     │  │                │  🟡 Sentry  ◂─── proxy ──┤  │
│                     │  │                │    rate limited          │  │
│                     ▼  ▼                └─────────────────────────┘  │
│              ┌──────────────┐                    ▲   ▲              │
│              │ code-reviewer │────── proxy GET ───┘   │              │
│              │ 🟢 online      │                        │              │
│              │ ⚡ 2 tasks      │                        │              │
│              └──────┬───────┘                        │              │
│                     │ creates task                    │              │
│              ┌──────▼───────┐                        │              │
│              │  deployer    │──── proxy PUT ──────────┘              │
│              │ 🟢 online      │                                       │
│              │ 💤 idle        │                                       │
│              └──────┬───────┘                                       │
│                     │                                               │
│                cross-hive task                                      │
│                     │                                               │
│              ┌──────▼───────────────┐                               │
│              │  → Hive: Mobile      │                               │
│              │    test-runner       │                                │
│              └──────────────────────┘                               │
│                                                                      │
│  ┌─ Schedules ──────────────┐  ┌─ Knowledge ──────────────────────┐  │
│  │  ⏰ Nightly scan (3 AM)  │  │  📦 142 entries (hive)            │  │
│  │  ⏰ Health check (5 min) │  │  📦 23 entries (apiary-shared)    │  │
│  └──────────────────────────┘  └──────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

What you see:
- Every agent as a node with status, current task count, and activity indicator
- Inboxes on the left (external triggers coming in)
- Services on the right (external access going out)
- Edges showing real relationships: "code-reviewer proxies to GitHub", "deployer proxies to AWS"
- Task flow between agents (who creates tasks for whom)
- Cross-hive outbound connections
- Schedules and knowledge store as summary panels
- Click any node → detail panel slides out

### 3.3 Agent View (Node Detail)

Click an agent to see everything about it in context.

```
┌────────────────────────────────────────────────────────┐
│  🤖 code-reviewer-1                                     │
│                                                         │
│  Status:  🟢 online (uptime: 4h 23m)                    │
│  Version: 2.1.0                                         │
│  Model:   claude-sonnet-4-5                             │
│                                                         │
│  ┌─ Capabilities ─────┐  ┌─ Permissions ─────────────┐  │
│  │ code_review         │  │ services:github           │  │
│  │ refactoring         │  │ knowledge:read            │  │
│  └─────────────────────┘  │ knowledge:write           │  │
│                           │ cross_hive:mobile         │  │
│                           └───────────────────────────┘  │
│                                                         │
│  ┌─ Current Tasks ─────────────────────────────────────┐ │
│  │ tsk_abc  code_review  PR #42      ████░░ 67%       │ │
│  │ tsk_def  code_review  PR #38      ██░░░░ 30%       │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─ Connections ───────────────────────────────────────┐ │
│  │                                                     │ │
│  │  IN:   📥 PR Events inbox ──(47 tasks today)──▸ me  │ │
│  │        🤖 deployer ──(3 tasks today)──▸ me          │ │
│  │                                                     │ │
│  │  OUT:  me ──proxy──▸ 🟢 GitHub  (230 reqs today)    │ │
│  │        me ──task──▸ 🤖 deployer  (8 tasks today)    │ │
│  │        me ──task──▸ 🐝 Mobile/test-runner (4 cross) │ │
│  │                                                     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─ Today ─────────────────────────────────────────────┐ │
│  │  Tasks completed: 23  |  Failed: 1  |  Avg: 45s    │ │
│  │  Proxy requests: 230  |  Errors: 2                  │ │
│  │  LLM cost: $1.84     |  Tokens: 412K               │ │
│  └─────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

---

## 4. Live Data Flow Animation

The key differentiator: edges are not static lines. They show **live data flowing**.

### 4.1 Edge Types & Visuals

| Edge Type           | Visual                                    | Animation                            |
|---------------------|-------------------------------------------|--------------------------------------|
| Webhook/inbox → agent | Dashed line, arrow                     | Pulse dot on each incoming webhook   |
| Agent → agent (task)  | Solid line, arrow                       | Dot flows from source to target      |
| Agent → service (proxy)| Dotted line, bidirectional             | Dot out + dot back per request       |
| Cross-hive task       | Thick dashed, different color           | Highlighted pulse                    |
| Cross-hive event      | Broadcast icon, multiple targets        | Ripple animation                     |
| Schedule → agent      | Clock icon on edge                      | Pulse on trigger                     |

### 4.2 Edge Thickness

Edge thickness = volume.
- 1-10 tasks/day: thin line
- 10-100: medium
- 100+: thick
- 1000+: very thick with glow

User can toggle between "last hour", "today", "this week" for volume calculation.

### 4.3 Pulse Speed

Dots travel faster when there's more throughput. Under heavy load, the map visually "lights up" — you can see where work is flowing.

### 4.4 Error Indication

Failed tasks / proxy errors: red pulse along the edge.
Dead letter tasks: red glow on the agent node.
Rate limited service: yellow pulsing border on service node.

---

## 5. Interactive Features

### 5.0 Navigation Between Zoom Levels

A breadcrumb bar at the top of the map shows the current navigation path: `Superpos > Hive: Backend > Agent: code-reviewer-1`. Click any breadcrumb segment to navigate up to that level. The browser back button returns to the previous zoom level. Deep-link URLs update on navigation (e.g., clicking into a hive updates the URL to `/hives/backend/map`).

### 5.1 Drag & Rearrange

Nodes are draggable. Layout auto-saves per user. Default: force-directed graph layout with left-to-right flow (inboxes → agents → services).

### 5.2 Click Node → Detail Panel

Clicking any node opens a slide-out panel on the right with full details. Panel content depends on node type:

| Node Type        | Panel Shows                                         |
|------------------|-----------------------------------------------------|
| Agent            | Status, capabilities, permissions, current tasks, connections, stats |
| Service          | Connection status, credentials health, request volume, error rate, policy summary |
| Inbox            | URL (copy button), request volume, recent payloads, config |
| Hive (in apiary view) | Agent count, task summary, health, top connections |
| Schedule         | Trigger config, last/next run, run history |

### 5.3 Click Edge → Flow Detail

Clicking an edge between two nodes shows:

```
code-reviewer ──task──▸ deployer

Last 24 hours:
  Tasks created: 8
  Completed: 7
  Failed: 1 (tsk_def — timeout)
  Avg completion: 120s

Recent tasks:
  tsk_001  deploy v2.5.1  ✅ completed  45s
  tsk_002  deploy v2.5.2  ✅ completed  38s
  tsk_003  deploy v2.5.3  ❌ failed     timeout
```

### 5.4 Filter & Highlight

- **Filter by status**: show only agents that are online / offline / draining
- **Filter by activity**: hide idle nodes (no tasks in last hour)
- **Highlight path**: "show me everything connected to GitHub" — highlights all edges touching GitHub service
- **Highlight flow**: "trace webhook to completion" — click an inbox, see the full path: inbox → agent → proxy → child task → cross-hive

### 5.5 Time Slider

Scrub through time to see how the topology looked at different points:
- "What was happening at 3 AM when the alert fired?"
- Replay mode: watch task flow animation for a specific time window
- Useful for post-mortems

### 5.6 Quick Actions from Map

Right-click any node:

| Node         | Actions                                                   |
|--------------|-----------------------------------------------------------|
| Agent        | View logs, drain, deregister, edit permissions             |
| Service      | Test connection, view proxy log, edit policy               |
| Inbox        | Copy URL, send test request, view log, edit config         |
| Schedule     | Trigger now, pause/resume, edit                            |
| Hive         | Open hive dashboard, settings                              |

---

## 6. Node States & Visual Language

### 6.1 Agent States

| State      | Visual                                          |
|------------|------------------------------------------------|
| Online idle | Green circle, steady glow                     |
| Online busy | Green circle, pulsing, task count badge        |
| Draining   | Yellow circle, countdown timer                  |
| Offline    | Gray circle, dashed border                      |
| Error      | Red circle, alert icon                          |

### 6.2 Service States

| State         | Visual                                       |
|---------------|----------------------------------------------|
| Connected     | Green square, steady                         |
| Rate limited  | Yellow square, pulsing border                |
| Error         | Red square, error count badge                |
| Unconfigured  | Gray square, dashed, "setup" link            |

### 6.3 Inbox States

| State    | Visual                                          |
|----------|------------------------------------------------|
| Active   | Blue envelope icon, pulse on each request       |
| Inactive | Gray envelope, dashed                           |
| Overloaded | Orange envelope, rate limit warning badge     |

### 6.4 Hive Card (Superpos View)

| State    | Visual                                          |
|----------|------------------------------------------------|
| Healthy  | Green border                                    |
| Busy     | Yellow border, task count badge                 |
| Degraded | Orange border, agent count warning              |
| Critical | Red border, pulsing alert                       |

---

## 7. Layout Algorithms

### 7.1 Default: Left-to-Right Flow

```
[Inboxes/Webhooks] → [Agents] → [Services]
     (triggers)      (workers)   (external)
```

Data flows left to right. Cross-hive links go down/up to other hive groups.

### 7.2 Alternative: Hierarchical

```
        [Services]          (top)
            │
        [Agents]            (middle)
         ╱    ╲
  [Inboxes] [Schedules]    (bottom - triggers)
```

### 7.3 Alternative: Force-Directed

Free-form physics simulation. Nodes with more connections pull closer together. Good for exploring organic cluster patterns.

User picks their preferred layout. Choice persists per user per hive.

---

## 8. Real-Time Updates

The Hive Map stays live via WebSocket (Laravel Reverb).

### 8.1 Events That Update the Map

| Event                     | Map Update                                    |
|---------------------------|-----------------------------------------------|
| Agent comes online        | Node appears, fade-in animation               |
| Agent goes offline        | Node grays out                                |
| Agent starts draining     | Node turns yellow, countdown appears          |
| Task created              | Pulse dot on source → target edge             |
| Task completed            | Green flash on target agent node              |
| Task failed               | Red flash on target agent node                |
| Proxy request             | Dot flows agent → service and back            |
| Webhook received          | Pulse on inbox node + edge to agent           |
| Cross-hive task           | Highlighted pulse between hive cards          |
| Dead letter               | Red badge appears on agent node               |
| Schedule triggered        | Clock pulse on schedule → agent edge          |
| Service error             | Service node flashes red                      |

### 8.2 Reverb Channels

```
apiary.{superpos_id}.topology     — Superpos view updates
hive.{hive_id}.topology         — Hive view updates
```

Payload:

```json
{
  "event": "task.created",
  "source": { "type": "agent", "id": "agt_abc" },
  "target": { "type": "agent", "id": "agt_def" },
  "metadata": { "task_type": "deploy", "priority": "high" }
}
```

Frontend maintains a local graph state, applies incremental updates from WebSocket.
No polling. No page refresh.

**Disconnection recovery:** On WebSocket disconnect, the map shows a "Connection lost" banner. Auto-reconnect uses exponential backoff (1s, 2s, 4s, max 30s). On reconnect, a full topology refetch reconciles any events missed during the disconnection period.

---

## 9. Data Sources

The map is assembled from existing data — no new infrastructure needed.

| Map Element          | Data Source                                    |
|----------------------|------------------------------------------------|
| Agent nodes          | `agents` table (status, capabilities)          |
| Service nodes        | `service_connections` table                    |
| Inbox nodes          | `inboxes` table                                |
| Schedule nodes       | `task_schedules` table                         |
| Agent → service edges| `proxy_log` (aggregate by agent + service)     |
| Agent → agent edges  | `tasks` (aggregate by source_agent + claimed_by)|
| Inbox → agent edges  | `tasks` where payload has `_inbox` (aggregate) |
| Cross-hive edges     | `tasks` where `source_hive_id IS NOT NULL`     |
| Edge volumes         | COUNT queries with time window                 |
| Health metrics       | Agent pool health calculation (derived)        |
| Live updates         | Activity events broadcast via Reverb           |

### 9.1 API Endpoint

```json
GET /api/v1/hives/{hive}/topology?timeframe=24h

{
  "nodes": [
    {
      "id": "agt_reviewer_1",
      "type": "agent",
      "label": "code-reviewer-1",
      "status": "online",
      "metadata": {
        "capabilities": ["code_review"],
        "current_tasks": 2,
        "uptime_seconds": 15780
      }
    },
    {
      "id": "svc_github",
      "type": "service",
      "label": "GitHub",
      "status": "connected",
      "metadata": {
        "request_count_24h": 5420,
        "error_rate": 0.003
      }
    },
    {
      "id": "inb_pr_events",
      "type": "inbox",
      "label": "PR Events",
      "status": "active",
      "metadata": {
        "request_count_24h": 47
      }
    },
    {
      "id": "sch_nightly_scan",
      "type": "schedule",
      "label": "Nightly scan",
      "status": "enabled",
      "metadata": {
        "next_run_at": "2025-02-21T03:00:00Z"
      }
    }
  ],
  "edges": [
    {
      "source": "inb_pr_events",
      "target": "agt_reviewer_1",
      "type": "inbox_trigger",
      "volume": 47,
      "metadata": { "task_type": "code_review" }
    },
    {
      "source": "agt_reviewer_1",
      "target": "svc_github",
      "type": "proxy",
      "volume": 230,
      "metadata": { "methods": ["GET", "POST"], "error_count": 2 }
    },
    {
      "source": "agt_reviewer_1",
      "target": "agt_deployer_1",
      "type": "task_flow",
      "volume": 8,
      "metadata": { "task_type": "deploy", "avg_duration_seconds": 120 }
    },
    {
      "source": "agt_deployer_1",
      "target": "hive:mobile",
      "type": "cross_hive",
      "volume": 4,
      "metadata": { "target_capability": "integration_test" }
    },
    {
      "source": "sch_nightly_scan",
      "target": "agt_reviewer_1",
      "type": "schedule_trigger",
      "volume": 1,
      "metadata": { "last_run": "2025-02-20T03:00:00Z" }
    }
  ]
}
```

Apiary-level topology:

```json
GET /api/v1/topology?timeframe=24h

{
  "hives": [
    {
      "id": "hiv_backend",
      "label": "Backend",
      "health": "healthy",
      "agents": { "total": 3, "online": 3 },
      "tasks": { "pending": 12, "in_progress": 2 }
    },
    ...
  ],
  "services": [
    { "id": "svc_github", "label": "GitHub", "status": "connected" },
    ...
  ],
  "edges": [
    {
      "source": "hiv_backend",
      "target": "hiv_mobile",
      "type": "cross_hive",
      "volume": 4
    },
    {
      "source": "hiv_backend",
      "target": "svc_github",
      "type": "proxy",
      "volume": 5420
    }
  ]
}
```

---

## 10. Frontend Implementation

### 10.1 Library

**React Flow** (https://reactflow.dev) — mature, React-native, supports:
- Custom node types (agent, service, inbox, schedule, hive)
- Custom edge types (animated, with labels)
- Drag, zoom, pan, minimap
- Auto-layout plugins (dagre, elkjs)
- Event handlers for click, hover, connect
- Good performance with 100+ nodes

Alternative: **D3.js** (force-directed) — more control but more work.

Recommendation: React Flow for structured views (hive map) + D3 for the time-slider replay visualization.

### 10.2 Component Structure

```
resources/js/Pages/HiveMap/
├── HiveMap.jsx                    — Main page wrapper
├── components/
│   ├── TopologyGraph.jsx          — React Flow canvas
│   ├── nodes/
│   │   ├── AgentNode.jsx          — Custom agent node with status badge
│   │   ├── ServiceNode.jsx        — Custom service node
│   │   ├── InboxNode.jsx          — Custom inbox node
│   │   ├── ScheduleNode.jsx       — Custom schedule node
│   │   └── HiveCard.jsx           — Hive summary card (apiary view)
│   ├── edges/
│   │   ├── TaskFlowEdge.jsx       — Animated edge with pulse dots
│   │   ├── ProxyEdge.jsx          — Bidirectional dotted edge
│   │   ├── CrossHiveEdge.jsx      — Highlighted dashed edge
│   │   └── TriggerEdge.jsx        — Dashed edge for inboxes/schedules
│   ├── panels/
│   │   ├── AgentDetailPanel.jsx   — Slide-out agent details
│   │   ├── ServiceDetailPanel.jsx
│   │   ├── InboxDetailPanel.jsx
│   │   ├── EdgeDetailPanel.jsx    — Flow details when clicking an edge
│   │   └── QuickActions.jsx       — Right-click context menu
│   ├── controls/
│   │   ├── TimeframeSelector.jsx  — Last hour / today / this week
│   │   ├── LayoutSelector.jsx     — LTR / hierarchical / force-directed
│   │   ├── FilterBar.jsx          — Status filters, activity filters
│   │   └── TimeSlider.jsx         — Scrub through historical state
│   └── overlays/
│       ├── PathHighlight.jsx      — Highlight connected nodes
│       └── FlowTrace.jsx         — Trace webhook → task → completion
├── hooks/
│   ├── useTopologyData.js         — Fetch + cache topology API
│   ├── useTopologyWebSocket.js    — Reverb subscription for live updates
│   └── useGraphLayout.js          — Layout calculation (dagre/elk)
└── utils/
    ├── layoutEngine.js            — Auto-layout algorithms
    ├── healthCalculator.js        — Node health from metrics
    └── volumeScale.js             — Edge thickness calculation
```

### 10.3 State Management

```jsx
// useTopologyData.js
const useTopologyData = (hiveSlug, timeframe) => {
  const [graph, setGraph] = useState({ nodes: [], edges: [] });

  // Initial fetch
  useEffect(() => {
    fetch(`/api/v1/hives/${hiveSlug}/topology?timeframe=${timeframe}`)
      .then(res => res.json())
      .then(data => setGraph(buildGraphFromApi(data)));
  }, [hiveSlug, timeframe]);

  // Live updates via Reverb
  useEffect(() => {
    const channel = Echo.channel(`hive.${hiveId}.topology`);

    channel.listen('.task.created', (e) => {
      setGraph(prev => addPulseToEdge(prev, e.source, e.target));
    });

    channel.listen('.agent.status_changed', (e) => {
      setGraph(prev => updateNodeStatus(prev, e.agent_id, e.status));
    });

    channel.listen('.proxy.request', (e) => {
      setGraph(prev => addPulseToEdge(prev, e.agent_id, e.service_id));
    });

    return () => channel.stopListening();
  }, [hiveId]);

  return graph;
};
```

### 10.4 Performance

**Target:** Smooth rendering at 60fps for up to 200 nodes + 500 edges.

- **Beyond 200 nodes:** Switch to clustered view — agent pools collapse into a single node showing pool health and agent count. User can expand a cluster to see individual agents.
- **React Flow virtualization:** Off-screen nodes are not rendered to the DOM. Only visible nodes + a buffer zone are active.
- **Edge animations:** Throttled to 30fps. Above 500 visible edges, pulse animations are disabled and edges show static thickness only.
- **Batch updates:** WebSocket events are batched in 100ms windows to prevent excessive re-renders during burst activity.

---

## 11. Empty States & Onboarding

### 11.1 New Hive (No Agents)

```
┌──────────────────────────────────────────┐
│                                          │
│     🐝 Your hive is empty                │
│                                          │
│     Register your first agent to         │
│     see the topology come alive.         │
│                                          │
│     [Register Agent]  [Use Template]     │
│                                          │
└──────────────────────────────────────────┘
```

### 11.2 Single Agent, No Connections

Show the agent node centered, with ghost nodes suggesting what to connect:

```
                    ┌ ─ ─ ─ ─ ─ ─ ┐
                      + Add Inbox
    ┌ ─ ─ ─ ─ ─ ┐  └ ─ ─ ─ ─ ─ ─ ┘
      + Service                │
    └ ─ ─ ─ ─ ─ ┘       ┌─────▼─────┐
          │              │ my-agent  │
          └─ ─ ─ ─ ─ ─ ─│ 🟢 online  │
                         └───────────┘
```

Ghost nodes are clickable — "Add Service" opens service connection wizard.

---

## 12. Special Visualizations

### 12.1 Task Chain Trace

Click "Trace" on any task in the task board → Hive Map highlights the full chain:

```
📥 PR Events → [code-reviewer] → [deployer] → [→ Mobile/test-runner]
     ✅              ✅               ⏳              pending

Timeline: webhook 10:00:00 → review done 10:00:26 → deploy started 10:00:27 → ...
```

Each node in the chain shows timing. Bottlenecks highlighted (long edges = slow).

### 12.2 Dependency Graph

For tasks with `depends_on`, show the DAG overlay:

```
[fetch emails ✅] ──┐
[fetch jira ⏳]   ──┼──▸ [generate report ⏸ waiting]
[fetch sales ✅]  ──┘
```

Nodes show completion status. Waiting tasks show which dependencies are blocking.

### 12.3 Pool Heatmap

Toggle "pool view" to see agent pools as clusters with load heatmap:

```
┌─ code_review pool ─────────┐
│  🟢 reviewer-1  ⚡⚡         │  ← 2 tasks
│  🟢 reviewer-2  ⚡           │  ← 1 task
│  🔴 reviewer-3  offline     │
│  Queue: 12 pending          │
│  Health: 🟡 busy             │
└─────────────────────────────┘
```

---

## 13. URL Routing

Hive Map is accessible via deep links:

```
/hives/{slug}/map                          — Hive topology
/hives/{slug}/map?focus=agt_abc            — Open with agent detail panel
/hives/{slug}/map?trace=tsk_xyz            — Open with task chain highlighted
/hives/{slug}/map?highlight=svc_github     — Open with service path highlighted
/map                                       — Apiary-wide topology
```

Shareable URLs for post-mortems and team discussions.

---

## 14. Implementation Priority

| Priority | Feature                          | Effort   |
|----------|----------------------------------|----------|
| P0       | Hive View: static graph with nodes + edges | 1 week |
| P0       | Node detail panels               | 3 days   |
| P1       | Live WebSocket updates           | 3 days   |
| P1       | Animated edges (pulse dots)      | 3 days   |
| P1       | Superpos View (hive cards)         | 3 days   |
| P2       | Edge click → flow detail         | 2 days   |
| P2       | Filter & highlight               | 3 days   |
| P2       | Layout options                   | 2 days   |
| P3       | Task chain trace overlay         | 3 days   |
| P3       | Time slider / replay             | 1 week   |
| P3       | Dependency graph overlay         | 2 days   |
| P3       | Pool heatmap view                | 2 days   |
| P4       | Ghost nodes + onboarding         | 2 days   |
| P4       | Quick actions (right-click menu) | 2 days   |

Total: ~4-5 weeks for full implementation. P0+P1 (usable MVP): ~2.5 weeks.

Recommended phase: **Phase 2-3** — after core task system works, Hive Map becomes the primary way to understand what's happening.

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (agents, services, tasks, hives), FEATURE_INBOX.md, FEATURE_PLATFORM_ENHANCEMENTS.md (schedules, pools)*
*Frontend dependency: React Flow (reactflow.dev)*
