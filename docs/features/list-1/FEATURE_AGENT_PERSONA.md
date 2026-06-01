# Superpos — Feature: Agent Persona

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

Today an agent's behavior is baked into its code. System prompts, instructions, memory — all hardcoded in the agent's repository or config files. This creates problems:

- **Changing behavior = redeploying code.** Tweak a prompt → commit → build → deploy → wait. For a one-word change.
- **No visibility.** Dashboard shows what an agent *does* (tasks, proxy calls), but not *who it is* (how it thinks, what it knows, what rules it follows). Two agents with identical capabilities but different prompts look the same.
- **No versioning.** Prompt changed → old version gone. Can't compare "before vs after". Can't rollback when a prompt change makes reviews worse.
- **No consistency.** Each developer writes prompts differently. No shared structure. New team member reads agent code and has to reverse-engineer the persona.
- **No separation of concerns.** The person who writes agent runtime code (Python, polling logic) is often not the same person who should be tuning the persona (domain expert, product owner).

## 2. Solution: Agent Persona

A **Persona** is a structured, versioned, platform-managed definition of an agent's identity, behavior, and memory. Stored in Superpos, served to agents at runtime, editable from the dashboard.

```
┌─────────────────────────────────────────────────────────────┐
│  🤖 Agent: code-reviewer                                    │
│                                                              │
│  ┌─ Persona v7 (active) ──────────────────────────────────┐ │
│  │                                                         │ │
│  │  📜 SOUL.md     — Who you are, your values              │ │
│  │  📋 AGENT.md    — What you do, your workflow            │ │
│  │  🧠 MEMORY.md   — What you know, project context        │ │
│  │  ⚙️ CONFIG      — Parameters, thresholds, preferences   │ │
│  │                                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  History: v7 ← v6 ← v5 ← v4 ← v3 ← v2 ← v1               │
│  v6→v7: "Added security focus to review criteria"           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Agent runtime fetches persona on init, re-fetches on change notification. Generic SDK runtime + persona from Superpos = fully configurable agent behavior without code changes.

---

## 3. Persona Structure

Inspired by Claude's system prompt patterns and OpenClaw's file convention, but adapted for multi-agent orchestration.

### 3.1 Documents

A persona consists of **named documents** — markdown files with specific roles.

| Document     | Purpose                                        | Example content                            |
|-------------|------------------------------------------------|--------------------------------------------|
| `SOUL`      | Identity, personality, values, tone            | "You are a senior code reviewer who prioritizes security and readability..." |
| `AGENT`     | Workflow, capabilities, how to handle tasks    | "When you receive a code_review task: 1) fetch PR diff, 2) analyze each file..." |
| `MEMORY`    | Persistent context, project-specific knowledge | "This project uses Laravel 12, PostgreSQL, follows PSR-12. Auth module was refactored in Jan 2025..." |
| `RULES`     | Hard constraints, do/don't rules              | "NEVER approve PRs that modify .env files. ALWAYS flag SQL queries without parameterization..." |
| `STYLE`     | Output format, communication style            | "Write review comments in this format: [SEVERITY] file:line — description..." |
| `EXAMPLES`  | Few-shot examples of good behavior            | "Example good review comment: [MAJOR] auth.py:42 — SQL injection risk..." |
| `NOTES`     | Working notes, scratchpad, internal annotations | "TODO: investigate flaky test in auth module. Learned: users table has soft-delete column..." |

All documents are optional. An agent can have just `SOUL` and `AGENT`, or the full set.

### 3.2 Config (Structured)

Non-prose parameters that control agent behavior:

```json
{
  "config": {
    "llm": {
      "model": "claude-sonnet-4-5-20250514",
      "temperature": 0.3,
      "max_tokens": 4096
    },
    "review": {
      "max_files": 50,
      "skip_patterns": ["*.lock", "*.min.js", "vendor/*"],
      "severity_levels": ["info", "minor", "major", "critical"],
      "auto_approve_threshold": 0
    },
    "behavior": {
      "ask_clarification": true,
      "suggest_fixes": true,
      "max_comments_per_file": 5
    }
  }
}
```

Config values are accessible in agent code via SDK:

```python
config = client.persona.config
model = config["llm"]["model"]
max_files = config["review"]["max_files"]
```

### 3.3 System Prompt Assembly

When an agent initializes an LLM call, the SDK assembles a system prompt from persona documents:

```
[SOUL.md content]

[AGENT.md content]

[RULES.md content]

[STYLE.md content]

[EXAMPLES.md content]

[NOTES.md content]

[MEMORY.md content]

[Task-specific context from channel/knowledge store]
```

Order is configurable. Agent code can also selectively include documents:

```python
# Use all documents
system_prompt = client.persona.assemble()

# Only specific documents
system_prompt = client.persona.assemble(include=["SOUL", "AGENT", "RULES"])

# With additional dynamic context
system_prompt = client.persona.assemble(
    append="Current task context:\n" + task.payload["context"]
)
```

---

## 4. Versioning

### 4.1 Every Change = New Version

```
v1: Initial persona
v2: Added MEMORY.md with project context
v3: Changed SOUL.md — more concise tone
v4: Updated RULES.md — added SQL injection rule
v5: Tweaked CONFIG — temperature 0.5 → 0.3
v6: Updated MEMORY.md — new auth module context
v7: Added security focus to AGENT.md workflow (active)
```

Each version is a **complete snapshot** — all documents + config at that point. No incremental diffs. Simple, no merge conflicts.

### 4.2 Version Metadata

```json
{
  "version": 7,
  "created_at": "2025-02-20T10:00:00Z",
  "created_by": { "type": "human", "id": "user:taras" },
  "message": "Added security focus to review criteria",
  "changes": [
    { "document": "AGENT", "action": "modified" }
  ],
  "active": true,
  "performance": {
    "tasks_completed": 45,
    "avg_rating": 4.2,
    "avg_task_duration": 38
  }
}
```

`performance` is populated over time — how well tasks perform under this persona version.

### 4.3 Diff Between Versions

```json
GET /dashboard/agents/{agent}/persona/diff?from=6&to=7

{
  "from_version": 6,
  "to_version": 7,
  "changes": [
    {
      "document": "AGENT",
      "type": "modified",
      "diff": "--- v6\n+++ v7\n@@ -5,6 +5,8 @@\n When reviewing code:\n 1. Fetch PR diff\n 2. Analyze each file\n+3. Pay special attention to security implications\n+4. Flag any changes to authentication or authorization logic\n 5. Post review comments"
    }
  ]
}
```

Dashboard renders this as a visual diff (like GitHub PR diff view).

### 4.4 Rollback

```json
POST /dashboard/agents/{agent}/persona/rollback
{
  "to_version": 5,
  "reason": "v6-v7 changes caused too many false positives in security reviews"
}
```

Creates v8 with content identical to v5. Version history preserved — nothing deleted.

Active agents pick up the new version on next persona refresh.

---

## 5. Live Updates (Hot Reload)

### 5.1 How Agents Get Persona Updates

Two mechanisms:

**Init fetch:** Agent starts → fetches full persona → caches locally.

```python
client = SuperposClient.from_env()
# SDK auto-fetches persona on init
# client.persona is populated with all documents + config
```

**Change notification:** Persona updated in dashboard → Superpos notifies agent.

Agent poll response includes persona version check:

```json
GET /api/v1/tasks/poll

{
  "tasks": [...],
  "persona_version": 7,
  "platform_context_version": 2,
  "next_poll_ms": 3000
}
```

Agent SDK compares with cached version. If different:

```python
# Automatic in SDK poll loop — respects agent's update policy
# server_persona_version = the version the server says THIS agent should use
# (active version for auto, pinned version for manual, canary-assigned for staged)
if server_persona_version != cached_version:
    client.persona.refresh()
    # Next LLM call uses new persona
```

No restart. No redeploy. The server returns the policy-correct version for each agent in the poll response: the active version for `auto` agents, the pinned version for `manual` agents, or the canary-assigned version for `staged` agents (see §5.2). When a `manual` agent is explicitly promoted to a new version, the poll response reflects the change and the SDK refreshes on the next cycle.

### 5.2 Lock Mechanism

Some agents should NOT auto-update — production agents that need tested personas:

```json
{
  "persona_settings": {
    "auto_update": false,
    "pinned_version": 5,
    "update_policy": "manual"
  }
}
```

| Policy    | Behavior                                         |
|-----------|--------------------------------------------------|
| `auto`    | Hot-reload on any change (default for dev)       |
| `manual`  | Pinned to specific version, explicit promotion   |
| `staged`  | New version → canary agent first → then all      |

### 5.3 Staged Rollout

For agents with multiple replicas, rollout is managed via `PersonaRolloutService` with the following lifecycle methods:

- `startCanary(persona, percentage)` — Begin canary rollout at a given percentage (1-99)
- `promote(persona, percentage)` — Increase rollout percentage (moves status to `rolling`; auto-completes at 100%)
- `pause(persona)` — Pause the rollout, freezing the current percentage
- `complete(persona)` — Set to 100% stable
- `rollback(persona)` — Emergency stop: set to 0% and pause
- `resume(persona)` — Resume a paused rollout (restores `canary` or `rolling` status based on percentage)

Cohort assignment is **deterministic** using CRC32: `crc32(agent_id + ':' + persona_id) % 100 < rollout_percentage`. The same agent always maps to the same cohort for a given persona version.

**Rollout columns on `agent_personas` table:**

| Column               | Type                                              |
|----------------------|---------------------------------------------------|
| `rollout_percentage` | INTEGER (0-100, default 100)                      |
| `rollout_status`     | VARCHAR — `stable`, `canary`, `rolling`, `paused` |
| `promoted_at`        | TIMESTAMP (nullable)                              |
| `paused_at`          | TIMESTAMP (nullable)                              |

**Dashboard routes:**

```
POST /dashboard/agents/{agent}/persona/rollout/start    — Start canary
POST /dashboard/agents/{agent}/persona/rollout/promote  — Increase percentage
POST /dashboard/agents/{agent}/persona/rollout/pause    — Pause rollout
POST /dashboard/agents/{agent}/persona/rollout/complete — Complete to 100% stable
POST /dashboard/agents/{agent}/persona/rollout/rollback — Emergency rollback to 0%
POST /dashboard/agents/{agent}/persona/rollout/resume   — Resume paused rollout
```

Example flow:

1. Start canary at 10%: 10% of agent replicas get persona v8, 90% stay on previous stable version
2. Promote to 50%: half of replicas now serve v8
3. If metrics degrade: pause or rollback
4. If metrics look good: complete to 100%

---

## 6. A/B Testing (Persona Experiments)

Experiments are managed through the dashboard via `PersonaExperimentController` and backed by `PersonaExperimentService`. The actual table is `persona_experiments`.

### 6.1 Create an Experiment

Experiments compare two persona versions by splitting traffic between them. Created from the dashboard:

```
POST /dashboard/experiments
{
  "name": "Security-focused review vs baseline",
  "agent_id": "01HXY...",          (optional — null for hive-wide)
  "persona_a_id": "01HXY...",      (FK to agent_personas.id)
  "persona_b_id": "01HXZ...",      (FK to agent_personas.id)
  "traffic_split": 50              (% of traffic routed to B)
}
```

Only one running experiment is allowed per agent (or per hive if agent_id is null). The service uses application-level locking to prevent concurrent creation races.

Agent cohort assignment is **deterministic** using CRC32: `crc32(agent_id + ':' + experiment_id) % 100 < traffic_split`. The same agent always maps to the same bucket for a given experiment.

### 6.2 Results

Results are computed on-the-fly by `PersonaExperimentService::getResults()`, which aggregates task metrics attributed to the experiment via the `persona_experiment_id` column on the `tasks` table:

```json
{
  "a": {
    "requests": 45,
    "avg_latency": 38.2,
    "success_rate": 0.98
  },
  "b": {
    "requests": 42,
    "avg_latency": 41.1,
    "success_rate": 0.99
  },
  "winner_suggestion": "b"
}
```

The `winner_suggestion` is derived automatically: if both sides have data and success rates differ by more than 1%, the higher rate wins; if within 1%, the side with more requests is suggested.

Dashboard shows side-by-side comparison with charts.

### 6.3 Experiment Lifecycle

```
POST   /dashboard/experiments                          — Create experiment
GET    /dashboard/experiments                          — List experiments (filterable by ?status=)
GET    /dashboard/experiments/{experiment}              — View experiment with results
PATCH  /dashboard/experiments/{experiment}/pause        — Pause running experiment
PATCH  /dashboard/experiments/{experiment}/resume       — Resume paused experiment
POST   /dashboard/experiments/{experiment}/winner       — Declare winner (completes experiment)
DELETE /dashboard/experiments/{experiment}              — Delete (only if not running)
```

### 6.4 Integration with Task Replay

Replay the same task with different persona versions:

```json
POST /api/v1/tasks/{id}/replay
{
  "mode": "sandbox",
  "persona_version": 5
}
```

"How would this task have gone with the old prompt?"

---

## 7. Persona Templates

### 7.1 Built-in Templates

Superpos ships starter templates for common agent roles:

| Template              | Documents included                       |
|-----------------------|------------------------------------------|
| Code Reviewer         | SOUL + AGENT + RULES + STYLE + EXAMPLES  |
| Deployer              | SOUL + AGENT + RULES                     |
| Data Analyst          | SOUL + AGENT + STYLE                     |
| Security Scanner      | SOUL + AGENT + RULES + EXAMPLES          |
| Technical Writer      | SOUL + AGENT + STYLE + EXAMPLES          |
| Incident Responder    | SOUL + AGENT + RULES                     |
| General Assistant      | SOUL + AGENT                             |

### 7.2 Template Example: Code Reviewer

**SOUL.md:**
```markdown
You are a senior code reviewer with 10+ years of experience.

Your core values:
- **Security first**: Always look for vulnerabilities
- **Readability**: Code should be clear to the next developer
- **Pragmatism**: Perfect is the enemy of good — suggest improvements, don't block on style
- **Teaching**: Explain *why* something is a problem, not just *what*

Your tone is professional, constructive, and encouraging.
You praise good code as well as flagging issues.
```

**AGENT.md:**
```markdown
## Workflow

When you receive a `code_review` task:

1. Fetch the PR diff via service proxy
2. Read the PR description for context
3. Check project MEMORY for relevant conventions and past decisions
4. Analyze each changed file:
   - Security implications
   - Logic correctness
   - Error handling
   - Test coverage
5. Assign severity to each finding: info / minor / major / critical
6. Write review comments following STYLE format
7. Make approve/request-changes decision
8. Post review to GitHub via service proxy
9. Write review summary to knowledge store

## Decision criteria

- **Approve**: No major/critical issues
- **Request changes**: Any critical issue OR 3+ major issues
- **Comment only**: Only minor/info issues but want to share feedback

## When stuck

If you encounter code you don't understand:
1. Check knowledge store for architecture docs
2. Check MEMORY for project context
3. If still unclear, post a question in the task channel
```

**RULES.md:**
```markdown
## Hard rules (NEVER violate)

- NEVER approve PRs that modify `.env`, `.env.example`, or any file containing secrets
- NEVER approve PRs that disable security features (CSRF, auth middleware, rate limiting)
- NEVER approve PRs without tests for new business logic
- ALWAYS flag raw SQL queries — require parameterized queries
- ALWAYS flag `eval()`, `exec()`, `unserialize()` with user input

## Soft rules (flag but don't block)

- Methods longer than 50 lines → suggest extraction
- Files longer than 500 lines → suggest splitting
- TODO/FIXME comments without ticket reference → flag
- Console.log / dd() / var_dump() → flag for cleanup
```

### 7.3 Install & Customize

Templates live in the persona marketplace. Two install paths are available:

**Install to existing agent** (apply marketplace persona to the calling agent):

```
POST /api/v1/hives/{hive}/persona-marketplace/{persona}/install
{
  "message": "Installed code-reviewer template"
}
```

**Install as new managed agent** (create a new agent in the hive from the template):

```
POST /api/v1/hives/{hive}/persona-marketplace/{persona}/install-agent
```

Start from template, add project-specific context. Template updates don't overwrite customizations (fork model, not sync).

---

## 8. BYOA Support

Persona is not just for managed agents. BYOA agents can fetch and use personas too.

### 8.1 SDK Usage (BYOA)

```python
from superpos_sdk import SuperposClient

client = SuperposClient(url="https://acme.apiary.ai", token="tok_xxx")

# Fetch persona
persona = client.persona

# Use in LLM call
response = openai.chat.completions.create(
    model=persona.config["llm"]["model"],
    messages=[
        {"role": "system", "content": persona.assemble()},
        {"role": "user", "content": task_prompt}
    ],
    temperature=persona.config["llm"]["temperature"]
)
```

Agent code is generic. All behavior comes from persona. Same code, different persona = different agent.

### 8.2 Thin Agent Pattern

This enables a **thin agent** — minimal code that's just a loop + LLM call:

```python
from superpos_sdk import SuperposClient
import anthropic

client = SuperposClient.from_env()
llm = anthropic.Anthropic()

while True:
    tasks = client.poll()
    for task in tasks:
        # Assemble system prompt from persona
        system = client.persona.assemble(
            append=f"Current task:\n{json.dumps(task.payload, indent=2)}"
        )
        
        # Call LLM
        response = llm.messages.create(
            model=client.persona.config["llm"]["model"],
            system=system,
            messages=[{"role": "user", "content": "Execute this task."}],
            max_tokens=client.persona.config["llm"]["max_tokens"]
        )
        
        # Complete task with LLM response
        client.complete(task.id, result={"response": response.content[0].text})
    
    client.sleep()
```

20 lines of code. All intelligence in the persona. Change persona in dashboard → agent behavior changes instantly.

### 8.3 Superpos Generic Agent

Take this further: Superpos ships a **generic managed agent runtime** that needs zero custom code. Just configure persona + capabilities in dashboard.

```json
POST /api/v1/hives/{hive}/managed-agents
{
  "name": "code-reviewer",
  "source": {
    "type": "builtin",
    "runtime": "apiary-generic-agent",
    "version": "latest"
  },
  "capabilities": ["code_review"],
  "persona": { ... }
}
```

Generic agent runtime: poll → read task → assemble persona + task context → call LLM → parse response → execute actions (proxy calls, knowledge writes) → complete task.

**Zero code deployment** — create agent entirely from dashboard.

---

## 9. API

### 9.1 Dashboard: Persona CRUD

These are dashboard (web) routes, not agent-facing API routes. Managed via `PersonaDashboardController`.

```
GET    /dashboard/agents/{agent}/persona                     — Get current active persona (all docs + config)
PUT    /dashboard/agents/{agent}/persona                     — Update persona (creates new version)
PATCH  /dashboard/agents/{agent}/persona/documents/{name}    — Update single document
PATCH  /dashboard/agents/{agent}/persona/config              — Update config only
```

### 9.2 Dashboard: Versioning

```
GET    /dashboard/agents/{agent}/persona/versions            — List all versions with metadata
GET    /dashboard/agents/{agent}/persona/versions/{version}  — Get specific version
GET    /dashboard/agents/{agent}/persona/diff?from={v1}&to={v2} — Diff between versions
POST   /dashboard/agents/{agent}/persona/rollback            — Rollback to version
POST   /dashboard/agents/{agent}/persona/promote             — Promote version (staged/canary)
GET    /dashboard/agents/{agent}/persona/tokens              — Token count breakdown
GET    /dashboard/agents/{agent}/persona/performance         — Performance metrics per version
```

### 9.3 Dashboard: Persona Experiments (A/B Testing)

Managed via `PersonaExperimentController` at dashboard routes:

```
GET    /dashboard/experiments                          — List experiments
POST   /dashboard/experiments                          — Create experiment
GET    /dashboard/experiments/{experiment}              — View experiment + results
PATCH  /dashboard/experiments/{experiment}/pause        — Pause experiment
PATCH  /dashboard/experiments/{experiment}/resume       — Resume experiment
POST   /dashboard/experiments/{experiment}/winner       — Declare winner
DELETE /dashboard/experiments/{experiment}              — Delete experiment
```

### 9.4 Persona Marketplace (Templates)

Agent-facing API routes via `PersonaMarketplaceApiController`:

```
GET    /api/v1/hives/{hive}/persona-marketplace                     — List marketplace personas
GET    /api/v1/hives/{hive}/persona-marketplace/{persona}           — Get marketplace persona details
POST   /api/v1/hives/{hive}/persona-marketplace/{persona}/install        — Install to calling agent
POST   /api/v1/hives/{hive}/persona-marketplace/{persona}/install-agent  — Install as new managed agent
```

Legacy backward-compatible routes (agent-templates):

```
GET    /api/v1/hives/{hive}/agent-templates                         — List (legacy format)
GET    /api/v1/hives/{hive}/agent-templates/{persona}               — Show (legacy format)
POST   /api/v1/hives/{hive}/agent-templates/{persona}/install       — Install as new agent (legacy)
```

### 9.5 Agent SDK Endpoint

Agent-facing API routes (authenticated via `sanctum-agent`):

```
GET    /api/v1/persona                          — Get MY persona (agent auth, returns policy-selected version: active for auto, pinned for manual, canary-assigned for staged). Includes platform_context and platform_context_version.
GET    /api/v1/persona/config                   — Get config only
GET    /api/v1/persona/documents/{name}         — Get single document
GET    /api/v1/persona/assembled                — Get pre-assembled system prompt string (includes platform context)
GET    /api/v1/persona/version                  — Get current version number + platform_context_version; supports ?known_version= and ?known_platform_version= query params to detect changes
PATCH  /api/v1/persona/documents/{name}         — Update single document (agent self-update, respects lock policy)
PATCH  /api/v1/persona/memory                   — Shortcut for updating MEMORY document (agent self-update)
```

### 9.6 Update Persona (Full Example)

```json
PUT /dashboard/agents/agt_reviewer/persona
{
  "message": "Added security focus and updated project memory",
  "documents": {
    "SOUL": {
      "content": "You are a senior code reviewer with 10+ years of experience.\n\nYour core values:\n- **Security first**: Always look for vulnerabilities\n- **Readability**: Code should be clear to the next developer\n..."
    },
    "AGENT": {
      "content": "## Workflow\n\nWhen you receive a `code_review` task:\n1. Fetch the PR diff\n..."
    },
    "MEMORY": {
      "content": "## Project: Superpos\n- Framework: Laravel 12\n- Database: PostgreSQL 16\n...",
      "locked": false
    },
    "RULES": {
      "content": "## Hard rules\n- NEVER approve PRs that modify .env files\n...",
      "locked": true
    }
  },
  "config": {
    "llm": {
      "model": "claude-sonnet-4-5-20250514",
      "temperature": 0.3,
      "max_tokens": 4096
    }
  }
}
```

Response:

```json
{
  "version": 8,
  "previous_version": 7,
  "created_at": "2025-02-20T12:00:00Z",
  "changes": [
    { "document": "SOUL", "action": "unchanged" },
    { "document": "AGENT", "action": "unchanged" },
    { "document": "MEMORY", "action": "modified" },
    { "document": "RULES", "action": "unchanged" }
  ],
  "active": true,
  "message": "Added security focus and updated project memory"
}
```

---

## 10. Document Locking

Some documents should be editable by agents (MEMORY evolves as project evolves). Others should be locked (RULES set by humans, agents can't weaken their own constraints).

Documents are either **locked** or **unlocked** — a simple boolean check via `AgentPersona::isDocumentLocked()`. The lock state is determined from two sources:

1. The `locked` field within the document entry in the `documents` JSONB column
2. The `lock_policy` JSONB column on the persona

```json
{
  "documents": {
    "SOUL":     { "content": "...", "locked": true },
    "AGENT":    { "content": "...", "locked": true },
    "MEMORY":   { "content": "...", "locked": false },
    "RULES":    { "content": "...", "locked": true },
    "STYLE":    { "content": "...", "locked": true },
    "EXAMPLES": { "content": "...", "locked": false },
    "NOTES":    { "content": "...", "locked": false }
  }
}
```

Agent updates to MEMORY:

```json
PATCH /api/v1/persona/documents/MEMORY
{
  "append": "\n## Learned 2025-02-20\n- The `users` table has a soft-delete column that affects JOIN queries\n- Team prefers early returns over nested if-else"
}
```

Or use the shortcut endpoint:

```json
PATCH /api/v1/persona/memory
{
  "append": "\n## Learned 2025-02-20\n- Team prefers early returns over nested if-else"
}
```

Creates new persona version. Dashboard shows "Agent updated MEMORY" in version history with clear attribution.

Locked documents: API returns 403 if agent tries to modify a locked document. Human must unlock first via the dashboard.

---

## 11. Database Schema

```sql
CREATE TABLE agent_personas (
    id              VARCHAR(26) PRIMARY KEY,
    agent_id        VARCHAR(26) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id) ON DELETE CASCADE,
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id) ON DELETE CASCADE,
    
    version         INTEGER NOT NULL,
    is_active       BOOLEAN DEFAULT FALSE,
    
    documents       JSONB NOT NULL,
    -- {
    --   "SOUL":     { "content": "...", "locked": true },
    --   "AGENT":    { "content": "...", "locked": true },
    --   "MEMORY":   { "content": "...", "locked": false },
    --   "RULES":    { "content": "...", "locked": true },
    --   ...
    -- }
    
    config          JSONB NOT NULL DEFAULT '{}',
    lock_policy     JSONB DEFAULT '{}',
    
    -- Version metadata
    message         TEXT,
    changes         JSONB DEFAULT '[]',
    created_by_type VARCHAR(10) NOT NULL,    -- human, agent, system
    created_by_id   VARCHAR(26) NOT NULL,
    
    -- Performance tracking
    tasks_completed INTEGER DEFAULT 0,
    avg_task_duration FLOAT,
    avg_rating      FLOAT,
    error_rate      FLOAT,
    
    -- Rollout control
    rollout_percentage INTEGER DEFAULT 100,
    rollout_status  VARCHAR(20) DEFAULT 'stable',  -- stable, canary, rolling, paused
    promoted_at     TIMESTAMP,
    paused_at       TIMESTAMP,
    
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_persona_active ON agent_personas (agent_id)
    WHERE is_active = TRUE;
CREATE INDEX idx_persona_versions ON agent_personas (agent_id, version DESC);
CREATE UNIQUE INDEX idx_persona_version_unique ON agent_personas (agent_id, version);

-- A/B tests (persona experiments)
CREATE TABLE persona_experiments (
    id                  VARCHAR(26) PRIMARY KEY,   -- ULID
    superpos_id           VARCHAR(26) NOT NULL REFERENCES apiaries(id) ON DELETE CASCADE,
    hive_id             VARCHAR(26) NOT NULL REFERENCES hives(id) ON DELETE CASCADE,
    agent_id            VARCHAR(26) REFERENCES agents(id) ON DELETE SET NULL,  -- null = hive-wide

    name                VARCHAR(255) NOT NULL,
    status              VARCHAR(20) DEFAULT 'running',  -- running, paused, completed

    persona_a_id        VARCHAR(26) NOT NULL REFERENCES agent_personas(id) ON DELETE CASCADE,
    persona_b_id        VARCHAR(26) NOT NULL REFERENCES agent_personas(id) ON DELETE CASCADE,

    traffic_split       SMALLINT DEFAULT 50,       -- % of traffic routed to B

    winner_persona_id   VARCHAR(26) REFERENCES agent_personas(id) ON DELETE SET NULL,

    started_at          TIMESTAMP,
    ended_at            TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_experiments_scope ON persona_experiments (superpos_id, hive_id, status);
CREATE INDEX idx_experiments_agent ON persona_experiments (agent_id, status);
```

Agents table addition:

```sql
ALTER TABLE agents ADD COLUMN persona_version INTEGER;
ALTER TABLE agents ADD COLUMN persona_update_policy VARCHAR(20) DEFAULT 'auto';
ALTER TABLE agents ADD COLUMN persona_pinned_version INTEGER;
-- Integrity note: persona_version and persona_pinned_version logically reference
-- agent_personas(agent_id, version) but a composite FK here would create a circular
-- dependency (agents ↔ agent_personas). Validity is enforced by PersonaService which
-- verifies the version exists for the agent before writing these columns.
```

---

## 12. Dashboard

### 12.1 Persona Editor

```
┌────────────────────────────────────────────────────────────────────┐
│  🤖 code-reviewer — Persona v7                    [Save v8] 💾    │
│                                                                    │
│  ┌─ Documents ──┐  ┌─ Editor ──────────────────────────────────┐   │
│  │              │  │                                           │   │
│  │  📜 SOUL  🔒  │  │  # Who You Are                           │   │
│  │  📋 AGENT 🔒  │  │                                           │   │
│  │  🧠 MEMORY   │  │  You are a senior code reviewer with     │   │
│  │  ⚡ RULES 🔒  │  │  10+ years of experience.                │   │
│  │  🎨 STYLE 🔒  │  │                                           │   │
│  │  📝 EXAMPLES │  │  Your core values:                        │   │
│  │  📓 NOTES   │  │  - **Security first**: Always look for    │   │
│  │              │  │    vulnerabilities                        │   │
│  │  ⚙️ CONFIG   │  │                                           │   │
│  │              │  │  - **Readability**: Code should be clear  │   │
│  └──────────────┘  │    to the next developer                  │   │
│                    │  - **Pragmatism**: Perfect is the enemy   │   │
│                    │    of good                                │   │
│                    │  █                                         │   │
│                    │                                           │   │
│                    │  Preview assembled prompt: 2,340 tokens   │   │
│                    └───────────────────────────────────────────┘   │
│                                                                    │
│  ┌─ Version History ──────────────────────────────────────────┐    │
│  │  v7  ✅ active  @taras  "Added security focus"  2h ago     │    │
│  │  v6  —         @taras  "Updated project memory" 1d ago    │    │
│  │  v5  —         🤖 self  "Learned: soft-delete"   2d ago    │    │
│  │  v4  —         @taras  "Added SQL injection rule" 5d ago  │    │
│  │  [View diff v6→v7] [Rollback to v6]                       │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌─ Performance ───────────────────────────────────────────────┐   │
│  │  v7 (18h): 45 tasks  avg 38s  4.2★  2% errors             │   │
│  │  v6 (3d):  120 tasks avg 42s  3.9★  4% errors             │   │
│  │  📈 v7 is performing better across all metrics              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### 12.2 Token Counter

Live preview shows assembled prompt token count:

```
SOUL:      320 tokens
AGENT:     580 tokens
MEMORY:    840 tokens
RULES:     290 tokens
STYLE:     180 tokens
EXAMPLES:  450 tokens
NOTES:     120 tokens
─────────────────────
Total:     2,780 tokens

Estimated cost per task: ~$0.009 (input) + ~$0.012 (output) = $0.02
Monthly estimate (500 tasks): ~$10
```

Helps optimize persona size vs. cost.

### 12.3 Diff View

Side-by-side diff between any two versions, like GitHub PR view:

```
┌─ v6 ──────────────────────┐  ┌─ v7 ──────────────────────────┐
│ ## Workflow                │  │ ## Workflow                    │
│                            │  │                                │
│ When reviewing code:       │  │ When reviewing code:           │
│ 1. Fetch PR diff           │  │ 1. Fetch PR diff               │
│ 2. Analyze each file       │  │ 2. Analyze each file           │
│                            │  │+3. Pay special attention to    │
│                            │  │+   security implications       │
│                            │  │+4. Flag auth/authz changes     │
│ 3. Post review comments    │  │ 5. Post review comments        │
└────────────────────────────┘  └────────────────────────────────┘
```

### 12.4 Agent Card (Enhanced)

Agent overview card now shows persona summary:

```
┌────────────────────────────────────────────────┐
│  🤖 code-reviewer         🟢 online             │
│                                                 │
│  Persona: v7 (auto-update)  📜 7 docs  ⚙️ config│
│  Identity: "Senior code reviewer, security-first" │
│  Model: claude-sonnet-4-5 @ temp 0.3           │
│                                                 │
│  [Edit Persona]  [View History]  [A/B Test]    │
└────────────────────────────────────────────────┘
```

---

## 13. Integration with Existing Features

### 13.1 Persona + Managed Agents

Managed agent wizard includes persona step:

```
Step 1: Source (Docker / Git / Inline / Builtin)
Step 2: Capabilities + permissions
Step 3: Persona (template or custom)    ← new
Step 4: Launch mode + resources
Step 5: Environment
→ Deploy
```

For builtin generic runtime: persona IS the agent. No code needed.

### 13.2 Persona + Agent Templates (Marketplace)

Agent templates include default persona:

```yaml
# marketplace template
name: GitHub Code Reviewer
persona:
  documents:
    SOUL: |
      You are a senior code reviewer...
    AGENT: |
      ## Workflow...
    RULES: |
      ## Hard rules...
  config:
    llm:
      model: claude-sonnet-4-5-20250514
      temperature: 0.3
```

Install template → persona auto-configured. User customizes from there.

### 13.3 Persona + Task Replay

Replay task with different persona version:

```json
POST /api/v1/tasks/{id}/replay
{
  "mode": "sandbox",
  "persona_version": 5
}
```

"Same task, old prompt — what would have happened?"

### 13.4 Persona + LLM Cost Tracking

Persona token count feeds into cost estimation. Dashboard shows: "This persona uses 2,780 input tokens per call. At current task volume (500/mo), system prompt costs ~$10/mo."

### 13.5 Persona + Channels

When agent participates in a channel, persona informs its behavior:
- SOUL defines tone and values
- RULES define what it can/cannot agree to
- MEMORY provides context for informed discussion

### 13.6 Persona + Observability

Prometheus metrics include persona version label:

```
superpos_task_duration_seconds{agent="code-reviewer",persona_version="7"} ...
superpos_task_error_rate{agent="code-reviewer",persona_version="7"} ...
```

Enables performance correlation: "error rate dropped when we switched to persona v7."

---

## 14. Permissions

| Permission              | Who can do what                                   |
|------------------------|---------------------------------------------------|
| Human: Admin/Owner     | Full persona CRUD, lock/unlock documents           |
| Human: Member          | Edit unlocked documents, view all                  |
| Human: Viewer          | Read-only persona access                           |
| Agent: self            | Update unlocked self-editable docs (MEMORY)        |
| Agent: other           | Cannot modify other agents' personas               |
| API: manage:personas   | Agent permission to manage own persona via API     |

---

## 15. Implementation Priority

| Priority | Feature                              | Effort  | Phase  |
|----------|--------------------------------------|---------|--------|
| P0       | Persona model + CRUD API             | 3 days  | 2      |
| P0       | SDK: fetch persona, assemble prompt  | 2 days  | 2      |
| P0       | Dashboard: persona editor            | 1 week  | 2      |
| P0       | Versioning (auto on every save)      | 2 days  | 2      |
| P1       | Diff view between versions           | 2 days  | 2      |
| P1       | Rollback                             | 1 day   | 2      |
| P1       | Document locking                     | 1 day   | 2      |
| P1       | Hot reload (poll-based update)       | 2 days  | 2      |
| P1       | Token counter + cost estimate        | 1 day   | 2      |
| P1       | Persona templates (built-in)         | 3 days  | 2-3    |
| P2       | Version performance tracking         | 3 days  | 3      |
| P2       | Agent self-update for MEMORY         | 2 days  | 3      |
| P2       | Staged rollout (canary)              | 3 days  | 3-4    |
| P3       | A/B testing                          | 1 week  | 4      |
| P3       | Generic agent runtime (zero code)    | 1 week  | 4      |
| P3       | Persona marketplace integration      | 2 days  | 4+     |

P0+P1 (usable MVP): ~2.5 weeks. Recommended phase: **Phase 2** — early, because it fundamentally changes how agents are configured and makes everything else more powerful.

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (agents, hives), FEATURE_HOSTED_AGENTS.md (hosted deployment on novps.io), FEATURE_PLATFORM_ENHANCEMENTS.md (LLM tracking, replay)*
