# Superpos — Feature: Knowledge Graph & Context Assembly

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

Current Knowledge Store is a key-value bag. Agent writes `key: "auth:login-flow"`, `value: {...}`. Another agent reads it if it knows the exact key. This is a filesystem without `find`, a database without `JOIN`, a wiki without links.

What's missing:

- **No discovery.** Agent working on auth has no way to find "what do we know about auth?" without knowing exact keys.
- **No connections.** Decision made in channel → became a task → produced code → generated knowledge entry. But there's no link between them. Context is scattered.
- **No accumulation.** Each task produces results, but insights don't compound. Yesterday's code review doesn't make today's review smarter.
- **No maintenance.** Knowledge gets stale. Nobody checks for contradictions. No "health score" for the knowledge base.
- **No assembly.** When agent starts a task, it gets the payload and nothing else. It should get the payload + everything it needs to know to do the job well.

As Karpathy puts it: the LLM is a CPU, the context window is RAM. Right now Superpos gives agents a task (instruction) but barely fills their RAM with knowledge. The result: agents re-discover what the system already knows.

## 2. Vision

Transform Knowledge Store from a key-value bag into a **living, self-maintaining knowledge graph** that agents read from, write to, and that the platform uses to automatically assemble rich context for every task.

```
Raw inputs                   Knowledge Graph                  Context Assembly
─────────────               ────────────────                 ─────────────────

Task results     ──┐
Channel decisions ──┤        ┌──────────────────┐
Proxy responses   ──┼──────▸ │  Entries + Links  │──────────▸ Agent gets task +
Webhook data      ──┤        │  Index + Summary  │            everything it needs
Agent observations ──┤        │  Embeddings       │            to do it well
Human annotations ──┘        └──────────────────┘
                                     ▲
                                     │
                              Knowledge Compiler
                              Knowledge Curator
                              (auto-maintain)
```

---

## 3. Three Layers

### Layer 1: Full-Text Search (Phase 1)

PostgreSQL native. Zero new dependencies.

**What it adds:** Agent can search knowledge by natural language query instead of exact key.

```sql
ALTER TABLE knowledge_entries ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(key, '') || ' ' ||
            coalesce(value->>'title', '') || ' ' ||
            coalesce(value->>'content', '') || ' ' ||
            coalesce(value->>'summary', '')
        )
    ) STORED;

CREATE INDEX idx_knowledge_fts ON knowledge_entries USING gin(search_vector);
```

API:

```json
GET /api/v1/hives/{hive}/knowledge/search?q=authentication+refactor&limit=10

{
  "results": [
    {
      "id": "kn_abc",
      "key": "decisions:auth-approach",
      "score": 0.92,
      "snippet": "...decided on cache-based approach with rate limiting for auth refactor...",
      "value": { ... }
    },
    {
      "id": "kn_def",
      "key": "reviews:pr-42",
      "score": 0.78,
      "snippet": "...N+1 query found in login flow, auth module...",
      "value": { ... }
    }
  ]
}
```

**Effort:** 2 days. Immediate value.

### Layer 2: Knowledge Links + Graph (Phase 2)

Entries link to each other and to other Superpos entities (tasks, channels, agents).

#### Link Types

| Link type        | Meaning                                    | Example                                    |
|-----------------|--------------------------------------------|--------------------------------------------|
| `relates_to`    | Topically related                          | auth:login ──▸ arch:sessions               |
| `depends_on`    | Required prerequisite knowledge            | feature:oauth ──▸ decisions:auth-approach   |
| `supersedes`    | This entry replaces an older one           | auth:v2 ──▸ auth:v1                        |
| `derived_from`  | Generated from this source                 | summary:pr-42 ──▸ task:tsk_review_42       |
| `decided_in`    | Decision made in this channel              | decisions:cache ──▸ channel:auth-refactor   |
| `implemented_by`| Implemented by this task                   | decisions:cache ──▸ task:tsk_refactor       |
| `authored_by`   | Created by this agent                      | reviews:pr-42 ──▸ agent:code-reviewer      |
| `part_of`       | Belongs to a larger topic                  | auth:login ──▸ topic:authentication        |

#### Schema

```sql
CREATE TABLE knowledge_links (
    id              BIGSERIAL PRIMARY KEY,
    source_id       VARCHAR(26) NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    target_id       VARCHAR(26) REFERENCES knowledge_entries(id) ON DELETE SET NULL,
    target_type     VARCHAR(20),            -- knowledge, task, channel, agent
    target_ref      VARCHAR(26),            -- ID of non-knowledge target
    link_type       VARCHAR(30) NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_by      VARCHAR(26),            -- agent or system
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_links_source ON knowledge_links (source_id);
CREATE INDEX idx_links_target ON knowledge_links (target_id);
CREATE INDEX idx_links_ref ON knowledge_links (target_type, target_ref);
```

#### Graph Walk API

"Give me everything connected to this entry, N hops deep."

```json
GET /api/v1/hives/{hive}/knowledge/kn_auth_login/graph?depth=2&link_types=relates_to,depends_on

{
  "root": "kn_auth_login",
  "nodes": [
    { "id": "kn_auth_login", "key": "auth:login-flow", "depth": 0 },
    { "id": "kn_sessions", "key": "arch:session-management", "depth": 1, "link": "relates_to" },
    { "id": "kn_cache_decision", "key": "decisions:auth-cache", "depth": 1, "link": "depends_on" },
    { "id": "kn_redis_config", "key": "infra:redis-config", "depth": 2, "link": "relates_to" }
  ],
  "edges": [
    { "from": "kn_auth_login", "to": "kn_sessions", "type": "relates_to" },
    { "from": "kn_auth_login", "to": "kn_cache_decision", "type": "depends_on" },
    { "from": "kn_sessions", "to": "kn_redis_config", "type": "relates_to" }
  ]
}
```

#### Auto-Linking

When an entry is created, system auto-detects potential links:

1. **Keyword overlap** — entries sharing significant terms → `relates_to` (suggested, agent confirms)
2. **Entity extraction** — mentions of file paths, PR numbers, agent names → auto-link to those entities
3. **Temporal proximity** — entries created around the same task/channel → `derived_from`

Auto-links are marked with `confidence` score. High confidence → auto-created. Low → suggested in dashboard for human/agent confirmation.

### Layer 3: Semantic Search + Embeddings (Phase 3-4)

pgvector extension. Embeddings computed on write.

```sql
-- Requires: CREATE EXTENSION vector;

ALTER TABLE knowledge_entries ADD COLUMN embedding vector(1536);

CREATE INDEX idx_knowledge_embedding ON knowledge_entries
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

On every knowledge write:

```python
# In KnowledgeStore service
def create_entry(key, value, ...):
    entry = KnowledgeEntry.create(key=key, value=value, ...)

    # Async job: compute embedding
    ComputeEmbedding.dispatch(entry.id)

    return entry

# Job
class ComputeEmbedding:
    def handle(entry_id):
        entry = KnowledgeEntry.find(entry_id)
        text = entry.to_searchable_text()  # key + value.title + value.content + value.summary
        embedding = embed(text)  # OpenAI ada-002 or local model
        entry.update(embedding=embedding)
```

Semantic search API:

```json
GET /api/v1/hives/{hive}/knowledge/search?q=how+do+we+handle+user+sessions&semantic=true

{
  "results": [
    {
      "id": "kn_sessions",
      "key": "arch:session-management",
      "similarity": 0.94,
      "snippet": "Sessions use Redis with 24h TTL...",
    },
    {
      "id": "kn_auth_login",
      "key": "auth:login-flow",
      "similarity": 0.87,
      "snippet": "Login flow creates session after JWT validation..."
    }
  ]
}
```

Combined search: FTS for exact matches + semantic for conceptual matches → merged + reranked.

---

## 4. Auto-Index Entries

Inspired by Karpathy's "auto-maintaining index files and brief summaries."

System-maintained special entries that provide a compact overview of the entire knowledge base. Agents read the index first, then dive deeper only where needed.

### 4.1 Topic Index

```json
// Auto-maintained entry: _index:topics
{
  "key": "_index:topics",
  "value": {
    "topics": [
      {
        "name": "Authentication",
        "entry_count": 12,
        "key_entries": ["auth:login-flow", "auth:jwt-config", "decisions:auth-cache"],
        "summary": "JWT-based auth with Redis session cache. Refactored Feb 2025. Cache approach chosen over eager loading for security.",
        "last_updated": "2025-02-20T10:00:00Z"
      },
      {
        "name": "Deployment",
        "entry_count": 8,
        "key_entries": ["deploy:pipeline", "deploy:rollback-procedure"],
        "summary": "GitHub Actions → Docker build → K8s rolling deploy. Rollback via helm.",
        "last_updated": "2025-02-19T15:00:00Z"
      }
    ]
  },
  "scope": "hive"
}
```

### 4.2 Decision Log

```json
// Auto-maintained entry: _index:decisions
{
  "key": "_index:decisions",
  "value": {
    "decisions": [
      {
        "date": "2025-02-20",
        "topic": "Auth refactor approach",
        "decision": "Cache-based approach with rate limiting",
        "channel": "ch_auth_refactor",
        "entry": "decisions:auth-cache",
        "participants": ["code-reviewer", "security-agent", "@taras"]
      },
      {
        "date": "2025-02-18",
        "topic": "Database migration strategy",
        "decision": "Blue-green deployment with dual writes",
        "entry": "decisions:db-migration"
      }
    ]
  }
}
```

### 4.3 Agent Knowledge Map

Per-agent: what does this agent know and frequently reference?

```json
// Auto-maintained: _index:agent:code-reviewer
{
  "key": "_index:agent:code-reviewer",
  "value": {
    "frequently_read": ["project:conventions", "arch:patterns", "decisions:auth-cache"],
    "authored": ["reviews:pr-42", "reviews:pr-38", "reviews:pr-35"],
    "expertise_topics": ["authentication", "code quality", "security"],
    "knowledge_gaps": ["deployment", "infrastructure"]
  }
}
```

### 4.4 Update Strategy

Index entries are updated by a scheduled job (every 5 minutes or on significant changes):

```
IndexUpdater job:
  1. Scan recently created/modified knowledge entries
  2. Classify into topics (LLM or keyword-based)
  3. Update _index:topics with new summaries
  4. Update _index:decisions from resolved channels
  5. Update _index:agent:* from read/write patterns
  6. Recompute entry counts and freshness
```

For small knowledge bases (<500 entries): full recompute.
For large (>500): incremental — only process entries changed since last run.

---

## 5. Knowledge Compiler (Agent Pattern)

A system agent that transforms raw data into structured, linked knowledge entries. Karpathy's "compile raw/ into wiki" — automated.

### 5.1 What It Compiles

| Raw source                  | Compiled into                              |
|-----------------------------|--------------------------------------------|
| Task result                 | Summary entry + links to task and agent    |
| Channel resolution          | Decision entry + links to channel and participants |
| Proxy response (significant)| Fact entry (API response data)             |
| Webhook payload (pattern)   | Event summary entry                        |
| Agent observation           | Insight entry + links to related entries   |
| Multiple related entries    | Synthesis entry (cross-reference summary)  |

### 5.2 Compiler as Persona Template

```yaml
name: Knowledge Compiler
capabilities: [knowledge_compilation]
permissions:
  - knowledge:read
  - knowledge:write
  - knowledge:manage

persona:
  SOUL: |
    You are a Knowledge Compiler. Your role is to transform raw data
    into clean, structured, interlinked knowledge entries.
    
    You write clearly and concisely. Every entry you create should be
    understandable without reading the source material. You always add
    links to related entries and source materials.
    
  AGENT: |
    ## Workflow
    
    You receive tasks of type `compile_knowledge` containing raw data
    from task results, channel discussions, or other sources.
    
    For each input:
    1. Extract key facts, decisions, and insights
    2. Check existing knowledge for related entries
    3. Create new entry or update existing if superseded
    4. Add links: source (derived_from), related (relates_to), topic (part_of)
    5. Update topic classification
    6. Write brief summary (1-3 sentences) as entry.value.summary
    
    ## Entry Format
    
    Every entry you create must have:
    - value.title: Clear descriptive title
    - value.summary: 1-3 sentence summary
    - value.content: Full structured content (markdown)
    - value.source: Where this knowledge came from
    - value.confidence: high/medium/low
    - value.tags: Array of topic tags
    
  RULES: |
    - NEVER invent facts. Only compile what's in the source data.
    - ALWAYS check for existing entries before creating new ones.
    - If an entry supersedes another, create a `supersedes` link.
    - Keep summaries under 3 sentences.
    - Use consistent terminology — check _index:topics for established terms.
```

### 5.3 Trigger: Auto-Compile

System automatically creates `compile_knowledge` tasks when:

```json
// hive.settings
{
  "knowledge_compiler": {
    "enabled": true,
    "triggers": {
      "task_completed": {
        "compile": true,
        "min_result_size": 100,
        "exclude_types": ["data_request", "health_check"]
      },
      "channel_resolved": {
        "compile": true,
        "include_types": ["discussion", "review", "planning"]
      },
      "knowledge_batch": {
        "threshold": 10,
        "description": "When 10+ new raw entries accumulate, compile a synthesis"
      }
    }
  }
}
```

Task completed with substantial result → compile_knowledge task auto-created → Knowledge Compiler processes → structured entry with links → index updated.

---

## 6. Knowledge Curator (Agent Pattern)

Scheduled maintenance agent. Karpathy's "linting" and "health checks."

### 6.1 Curator Responsibilities

| Check                    | Action                                      | Frequency  |
|--------------------------|---------------------------------------------|------------|
| **Stale entries**        | Flag entries not referenced in 30+ days     | Daily      |
| **Contradictions**       | Find entries with conflicting facts         | Weekly     |
| **Broken links**         | Links pointing to deleted entries/tasks     | Daily      |
| **Missing links**        | Entries that should be connected but aren't | Weekly     |
| **Gap detection**        | Topics with thin coverage                   | Weekly     |
| **Duplicate detection**  | Similar entries that should be merged       | Weekly     |
| **Summary freshness**    | Index summaries that are outdated           | Daily      |
| **Confidence decay**     | Lower confidence on old unverified entries  | Monthly    |

### 6.2 Health Score

```json
GET /api/v1/hives/{hive}/knowledge/health

{
  "score": 82,
  "grade": "B+",
  "metrics": {
    "total_entries": 342,
    "linked_percentage": 78,
    "avg_links_per_entry": 2.4,
    "stale_entries": 12,
    "contradictions_found": 2,
    "broken_links": 0,
    "orphan_entries": 8,
    "index_freshness": "2 hours ago",
    "topic_coverage": {
      "authentication": { "entries": 12, "health": "good" },
      "deployment": { "entries": 8, "health": "good" },
      "monitoring": { "entries": 2, "health": "thin" }
    }
  },
  "recommendations": [
    "2 contradictions in 'auth' topic — review decisions:auth-cache vs reviews:pr-35",
    "8 orphan entries have no links — consider connecting to topics",
    "'monitoring' topic has only 2 entries — consider enriching"
  ]
}
```

### 6.3 Curator as Scheduled Agent

```yaml
name: Knowledge Curator
capabilities: [knowledge_curation]

schedule:
  trigger: { type: cron, expression: "0 2 * * *" }  # daily at 2 AM

persona:
  SOUL: |
    You are a Knowledge Curator. You maintain the health and quality
    of the team's knowledge base. You find issues, suggest fixes,
    and keep knowledge organized and trustworthy.
  
  AGENT: |
    ## Daily routine
    1. Scan for stale entries (no reads in 30 days) → flag or archive
    2. Check for broken links → fix or remove
    3. Verify index freshness → recompile if stale
    4. Scan for duplicates → suggest merges
    
    ## Weekly deep check
    5. Run contradiction detection across related entries
    6. Identify topic gaps → suggest areas to explore
    7. Check link density → suggest missing connections
    8. Generate health report → write to knowledge store
```

---

## 7. Context Assembly

The payoff of all the above: when an agent gets a task, the system automatically assembles the ideal context window.

### 7.1 Assembly Pipeline

```
Task arrives for agent
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                    Context Assembly Pipeline                  │
│                                                              │
│  Step 1: Persona                                             │
│    → SOUL + AGENT + RULES + STYLE + EXAMPLES                │
│    → Budget: ~2,500 tokens                                   │
│                                                              │
│  Step 2: Task context                                        │
│    → Payload + parent task + channel history (if any)        │
│    → Budget: ~1,000 tokens                                   │
│                                                              │
│  Step 3: Explicit references                                 │
│    → context_refs from task → fetch linked entries           │
│    → Budget: ~2,000 tokens                                   │
│                                                              │
│  Step 4: Graph walk                                          │
│    → From explicit refs, walk 1-2 hops                       │
│    → Prioritize: decisions > architecture > reviews          │
│    → Budget: ~3,000 tokens                                   │
│                                                              │
│  Step 5: Semantic search                                     │
│    → Query: task type + payload keywords                     │
│    → Top 5 results not already included                      │
│    → Budget: ~2,000 tokens                                   │
│                                                              │
│  Step 6: Agent memory                                        │
│    → Persona MEMORY.md (agent-specific learned knowledge)    │
│    → _index:agent:{id} for frequently used knowledge         │
│    → Budget: ~1,500 tokens                                   │
│                                                              │
│  Step 7: Compress & rank                                     │
│    → Total budget: configurable (default 12,000 tokens)      │
│    → If over budget: summarize longer entries, drop lowest    │
│    → Rank by: relevance score × freshness × link proximity   │
│                                                              │
│  Step 8: Format                                              │
│    → Assemble into structured context block                  │
│    → Include source references for traceability              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
  Agent receives task + rich context
```

### 7.2 Context Delivery

Agent receives assembled context in the poll response or task claim:

```json
GET /api/v1/tasks/tsk_abc

{
  "id": "tsk_abc",
  "type": "code_review",
  "payload": { "repo": "acme/backend", "pr_number": 42 },
  
  "context": {
    "assembled_at": "2025-02-20T10:00:00Z",
    "token_count": 8420,
    "sections": [
      {
        "type": "knowledge",
        "key": "decisions:auth-cache",
        "title": "Auth Refactor Decision",
        "summary": "Cache-based approach with rate limiting. Decided in #auth-refactor channel.",
        "relevance": 0.95,
        "source": "graph_walk"
      },
      {
        "type": "knowledge",
        "key": "project:conventions",
        "title": "Project Coding Conventions",
        "summary": "PSR-12, ULIDs, BelongsToHive trait on all models.",
        "relevance": 0.88,
        "source": "agent_memory"
      },
      {
        "type": "knowledge",
        "key": "reviews:pr-38",
        "title": "Previous Review: PR #38 (same module)",
        "summary": "Found N+1 in user query, added eager load. Pattern: always check auth module queries.",
        "relevance": 0.82,
        "source": "semantic_search"
      },
      {
        "type": "channel",
        "id": "ch_auth_refactor",
        "title": "Auth Refactor Discussion",
        "summary": "Team decided on cache approach. Security agent confirmed no data exposure. Rate limiting required.",
        "relevance": 0.91,
        "source": "graph_walk"
      }
    ]
  }
}
```

### 7.3 SDK: Context-Aware Task Handling

```python
tasks = client.poll()
for task in tasks:
    # Persona assembles the system prompt
    system_prompt = client.persona.assemble()
    
    # Context is already there — assembled by Superpos
    context_block = task.context.to_prompt()
    # Returns formatted text:
    # "## Relevant Knowledge
    #  ### Auth Refactor Decision
    #  Cache-based approach with rate limiting...
    #  ### Previous Review: PR #38
    #  Found N+1 in user query..."
    
    # Agent combines persona + context + task
    response = llm.messages.create(
        model=client.persona.config["llm"]["model"],
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"{context_block}\n\n## Your Task\n{task.payload}"
        }]
    )
```

Agent code is minimal. All the intelligence of "what should this agent know right now" lives in the platform.

### 7.4 Context Budget Configuration

Per-hive or per-task-type:

```json
// hive.settings
{
  "context_assembly": {
    "enabled": true,
    "default_budget_tokens": 12000,
    "budgets_per_type": {
      "code_review": 16000,
      "simple_task": 4000,
      "planning": 20000
    },
    "section_priorities": [
      "persona",
      "task_payload",
      "explicit_refs",
      "channel_context",
      "graph_walk",
      "semantic_search",
      "agent_memory"
    ],
    "compression": {
      "strategy": "summarize",
      "min_entry_tokens": 50,
      "max_entry_tokens": 500
    }
  }
}
```

If total exceeds budget: lower-priority sections get summarized or dropped. Persona and task payload are never dropped.

### 7.5 Opt-Out

Agent can skip auto-assembly if it manages context itself:

```python
tasks = client.poll(include_context=False)  # raw task, no assembly
```

Or request specific assembly:

```python
tasks = client.poll(context_sections=["explicit_refs", "graph_walk"])
```

---

## 8. Knowledge Write-Back Loop

Every task execution enriches the knowledge base. The flywheel.

### 8.1 Automatic on Task Completion

Already exists in task API: `knowledge_entries` in completion payload. Enhanced with auto-linking:

```json
PATCH /api/v1/tasks/tsk_review_42/complete
{
  "result": { "approved": true, "comments": 3 },
  "knowledge_entries": [
    {
      "key": "reviews:pr-42",
      "value": {
        "title": "PR #42 Review: Auth Cache Implementation",
        "summary": "Approved. Clean implementation of Redis cache for auth tokens. Minor suggestion: add TTL config to env.",
        "content": "## Review Summary\n...",
        "tags": ["authentication", "cache", "redis"],
        "confidence": "high"
      },
      "scope": "hive",
      "auto_link": true
    }
  ]
}
```

`auto_link: true` → system automatically:
1. Links to task: `derived_from → tsk_review_42`
2. Links to agent: `authored_by → agt_code_reviewer`
3. Scans for related entries by tags/keywords → suggests `relates_to` links
4. Updates `_index:topics` for "authentication" topic
5. Queues `compile_knowledge` if auto-compile is enabled

### 8.2 Channel Resolution Write-Back

When channel resolves, auto-creates knowledge entry:

```json
{
  "key": "decisions:{channel_slug}",
  "value": {
    "title": "Decision: {channel_title}",
    "summary": "{resolution.outcome}",
    "content": "{auto-generated summary of discussion}",
    "participants": ["code-reviewer", "security-agent", "@taras"],
    "date": "2025-02-20",
    "tags": ["decision", ...extracted_tags]
  },
  "links": [
    { "type": "decided_in", "target_type": "channel", "target_ref": "ch_xxx" }
  ]
}
```

Every decision is automatically captured. Decision log stays current without manual effort.

### 8.3 Agent Self-Learning

Agent updates its own MEMORY based on discoveries:

```python
# After reviewing code and learning something new
client.persona.append_memory(
    "## Learned from PR #42 (2025-02-20)\n"
    "- The users table has a soft-delete column — JOIN queries must filter deleted_at IS NULL\n"
    "- Team preference: early returns over nested if-else in auth module\n"
)

# Also write to shared knowledge so other agents benefit
client.knowledge.create(
    key="patterns:soft-delete-joins",
    value={
        "title": "Soft-Delete Affects JOIN Queries",
        "summary": "users table has soft-delete. All JOINs must include deleted_at IS NULL filter.",
        "confidence": "high",
        "source": "Discovered during PR #42 review"
    },
    auto_link=True
)
```

Personal learning (MEMORY) + shared learning (Knowledge Store). Both accumulate.

---

## 9. Visualization: Knowledge Explorer

### 9.1 Graph View

Interactive visualization of knowledge graph. Part of dashboard, also accessible from Hive Map.

```
┌────────────────────────────────────────────────────────────────────┐
│  🧠 Knowledge Graph — Hive: Backend            [Search] [Health]  │
│                                                                    │
│           ┌────────────┐                                           │
│           │  🏗 arch:    │                                           │
│           │  sessions   │                                           │
│           └──────┬─────┘                                           │
│                  │ relates_to                                      │
│    ┌─────────────┼──────────────┐                                  │
│    │             │              │                                  │
│    ▼             ▼              ▼                                  │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐                            │
│ │🔑 auth:   │ │📋 decisions│ │🔧 infra:  │                            │
│ │login-flow │ │:auth-cache│ │redis-cfg │                            │
│ │           │ │           │ │           │                            │
│ │ 12 links  │ │ decided_in│ │ 3 links   │                            │
│ └──────────┘ │ ch_auth   │ └──────────┘                            │
│               └──────────┘                                         │
│                                                                    │
│  Topics: [Authentication ●12] [Deployment ●8] [Monitoring ●2]     │
│                                                                    │
│  Health: 82/100 (B+) — 2 contradictions, 8 orphans                │
└────────────────────────────────────────────────────────────────────┘
```

Click node → see entry content + all links.
Click topic → filter graph to that topic.
Click health → see recommendations.

### 9.2 Timeline View

Knowledge entries on a timeline, showing how knowledge accumulated:

```
Feb 15 ──── project:conventions created (by @taras)
Feb 16 ──── reviews:pr-35 compiled (by knowledge-compiler)
Feb 18 ──── decisions:db-migration decided (in #db-migration channel)
Feb 19 ──── patterns:soft-delete-joins discovered (by code-reviewer)
Feb 20 ──── decisions:auth-cache decided (in #auth-refactor)
           ├── reviews:pr-42 compiled
           └── auth:login-flow updated
```

### 9.3 Context Preview

Before running a task, see what context would be assembled:

```
Dashboard → Tasks → "Create Task" → Preview Context

"If you create a code_review task for PR #42, the agent would receive:"

📜 Persona: 2,500 tokens (SOUL + AGENT + RULES)
📋 Task payload: 200 tokens
🔗 Explicit refs: — (none specified)
🕸️ Graph walk: 2,800 tokens (4 entries from auth topic)
🔍 Semantic: 1,400 tokens (2 related reviews)
🧠 Agent memory: 800 tokens (MEMORY.md)
───────────────────────────
Total: 7,700 / 12,000 token budget

[View full context] [Adjust budget] [Create Task]
```

---

## 10. Entry Structure (Enhanced)

Knowledge entries get a richer structure:

```json
{
  "id": "kn_abc123",
  "key": "decisions:auth-cache",
  "superpos_id": "...",
  "hive_id": "...",
  
  "value": {
    "title": "Auth Refactor: Cache Approach Decision",
    "summary": "Team chose Redis cache over eager loading for auth token management. Driven by security concerns.",
    "content": "## Decision\n\nAfter reviewing two approaches...\n\n## Rationale\n...\n\n## Implications\n...",
    "source": "Channel: Auth Refactor (#ch_auth_refactor)",
    "confidence": "high",
    "tags": ["authentication", "cache", "redis", "decision"],
    "format": "markdown"
  },
  
  "scope": "hive",
  "visibility": "public",
  "created_by": "agt_knowledge_compiler",
  "version": 3,
  
  "search_vector": "...",          -- FTS (Layer 1)
  "embedding": "[0.023, ...]",    -- Semantic (Layer 3)
  
  "stats": {
    "read_count": 23,
    "last_read_at": "2025-02-20T09:00:00Z",
    "last_read_by": "agt_code_reviewer",
    "link_count": 5
  },
  
  "ttl": null,
  "created_at": "2025-02-20T10:05:00Z",
  "updated_at": "2025-02-20T10:05:00Z"
}
```

New fields: `title`, `summary`, `content`, `source`, `confidence`, `tags`, `format`, `stats`.
`stats.read_count` and `last_read_at` feed into staleness detection and agent knowledge maps.

---

## 11. API Additions

### 11.1 Search

```
GET  /api/v1/hives/{hive}/knowledge/search?q={query}&semantic={bool}&limit={n}
```

### 11.2 Graph

```
GET  /api/v1/hives/{hive}/knowledge/{id}/graph?depth={n}&link_types={csv}
POST /api/v1/hives/{hive}/knowledge/{id}/links                    — Add link
DELETE /api/v1/hives/{hive}/knowledge/links/{link_id}              — Remove link
GET  /api/v1/hives/{hive}/knowledge/links?source={id}              — List links from entry
GET  /api/v1/hives/{hive}/knowledge/links?target_ref={id}&target_type={type} — List links TO an entity
```

### 11.3 Index

```
GET  /api/v1/hives/{hive}/knowledge/index/topics                   — Topic index
GET  /api/v1/hives/{hive}/knowledge/index/decisions                — Decision log
GET  /api/v1/hives/{hive}/knowledge/index/agent/{agent_id}         — Agent knowledge map
```

### 11.4 Health

```
GET  /api/v1/hives/{hive}/knowledge/health                         — Health score + recommendations
```

### 11.5 Context Assembly (for debugging/preview)

```
POST /api/v1/hives/{hive}/context/preview
{
  "task_type": "code_review",
  "payload": { "repo": "acme/backend", "pr_number": 42 },
  "agent_id": "agt_reviewer",
  "budget_tokens": 12000
}

→ Returns what context would be assembled, with token counts per section
```

---

## 12. Implementation Priority

| Priority | Feature                                     | Layer | Effort  | Phase | Backlog Status |
|----------|---------------------------------------------|-------|---------|-------|----------------|
| P0       | FTS search on knowledge entries              | 1     | 2 days  | 1     | TASK-213 |
| P0       | Enhanced entry structure (title, summary, tags) | —  | 1 day   | 1     | TASK-214 |
| P0       | Entry read stats tracking                    | —     | 1 day   | 1     | TASK-215 |
| P1       | Knowledge links table + CRUD API             | 2     | 3 days  | 2     | TASK-216 |
| P1       | Graph walk API                               | 2     | 2 days  | 2     | TASK-217 |
| P1       | Auto-linking on create (keyword + entity)    | 2     | 3 days  | 2     | TASK-218 |
| P1       | Auto-index entries (_index:topics, decisions)| —     | 3 days  | 2     | TASK-219 |
| P1       | Task completion → auto write-back + linking  | —     | 2 days  | 2     | TASK-220 |
| P1       | Channel resolution → knowledge entry         | —     | 1 day   | 2     | TASK-221 |
| P2       | Knowledge Compiler persona template          | —     | 2 days  | 2-3   | TASK-222 |
| P2       | Context Assembly pipeline (basic)            | —     | 1 week  | 3     | TASK-223 |
| P2       | SDK: context-aware task handling              | —     | 2 days  | 3     | Deferred — not in current backlog |
| P2       | Dashboard: Knowledge Explorer graph view     | 2     | 1 week  | 3     | TASK-224 |
| P2       | Dashboard: Context Preview                   | —     | 2 days  | 3     | Deferred — not in current backlog |
| P2       | Knowledge Curator agent template             | —     | 2 days  | 3     | TASK-225 |
| P2       | Health score API + dashboard                 | —     | 3 days  | 3     | TASK-225 |
| P3       | pgvector + embeddings                        | 3     | 1 week  | 3-4   | TASK-226 |
| P3       | Semantic search                              | 3     | 3 days  | 3-4   | TASK-226 |
| P3       | Combined search (FTS + semantic + reranking) | 3     | 3 days  | 4     | Deferred — not in current backlog |
| P3       | Context Assembly: semantic section            | 3     | 2 days  | 4     | Deferred — not in current backlog |
| P3       | Auto-linking via embeddings similarity       | 3     | 2 days  | 4     | Deferred — not in current backlog |
| P4       | Timeline view                                | —     | 2 days  | 4+    | Deferred — not in current backlog |
| P4       | Agent self-learning write-back patterns      | —     | 3 days  | 4+    | Deferred — not in current backlog |
| P4       | Knowledge A/B (context assembly variants)    | —     | 1 week  | 5     | Deferred — not in current backlog |

FTS + enhanced structure = Phase 1 (3 days, immediate value).
Links + graph + auto-index + write-back = Phase 2 (2 weeks, transforms the system).
Context Assembly + semantic = Phase 3-4 (the payoff — agents get smart automatically).

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (Knowledge Store), FEATURE_AGENT_PERSONA.md (persona in assembly), FEATURE_CHANNELS.md (channel → knowledge), FEATURE_TASK_SEMANTICS.md (task completion write-back)*
*Inspired by: Karpathy's "LLM Knowledge Bases" concept*
