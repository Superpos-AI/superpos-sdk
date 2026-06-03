# Superpos — Feature: Sub-Agent Definitions

## Addendum to PRODUCT.md

---

## 1. Problem

Today, sub-agent behavior is baked into the local filesystem. In Claude Code, sub-agents live as `.claude/subagents/*.md` files — markdown with YAML frontmatter (`name`, `description`, `model`) plus a system prompt body. This creates problems:

- **No cloud management.** Sub-agent definitions are committed to the agent's repo. Changing a sub-agent's behavior requires a code change, commit, and redeploy — even for a one-line prompt tweak.
- **No visibility.** The dashboard shows agents and their personas, but has zero visibility into what sub-agents an agent can spawn or how they behave.
- **No reuse across agents.** A well-tuned "coder" sub-agent definition can't be shared across multiple agents in a hive. Each agent needs its own copy in its local filesystem.
- **No task-level control.** When a webhook creates a task or a workflow dispatches a step, there's no way to say "run this task with a specific sub-agent." The calling context can set `invoke.instructions` and `target_capability`, but can't control the sub-agent persona used for delegation.
- **No versioning or rollback.** Local `.md` files have no version history, no diffing, no rollback — unlike personas which are fully versioned with immutable snapshots.
- **No orchestration patterns.** Workflows can route steps to different agents via `target_capability`, but can't compose multi-sub-agent pipelines where different steps use different specialized sub-agents on the same or different agents.

## 2. Solution: Sub-Agent Definitions

A **Sub-Agent Definition** is a reusable, cloud-stored, versioned agent persona template that can be attached to tasks. It mirrors the Persona system's architecture but is scoped to the hive (shared) rather than to a single agent.

```
┌─────────────────────────────────────────────────────────────┐
│  🐝 Hive: my-project                                       │
│                                                              │
│  ┌─ Sub-Agent: coder (v3 active) ────────────────────────┐  │
│  │                                                        │  │
│  │  📜 SOUL.md     — Identity and values                  │  │
│  │  📋 AGENT.md    — Workflow and capabilities             │  │
│  │  📏 RULES.md    — Constraints and prohibitions          │  │
│  │  🎨 STYLE.md    — Output formatting                     │  │
│  │  📝 EXAMPLES.md — Few-shot examples                     │  │
│  │  ⚙️  CONFIG      — Model, temperature, tools            │  │
│  │                                                        │  │
│  │  History: v3 ← v2 ← v1                                │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Sub-Agent: reviewer (v1 active) ─────────────────────┐  │
│  │  ...                                                   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Sub-Agent: analyst (v2 active) ──────────────────────┐  │
│  │  ...                                                   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Key relationship:** Persona = "who the agent is." Sub-Agent Definition = "who the agent should delegate to."

When an agent claims a task that has a sub-agent definition attached, it receives the sub-agent's assembled prompt alongside its own persona — instructing it to spawn a sub-agent with those specific instructions for this task.

---

## 3. Design Principles

- **Mirror Persona architecture.** Same immutable-version pattern, same document structure, same assembly logic. If you know Personas, you know Sub-Agent Definitions.
- **Hive-scoped, not agent-scoped.** Sub-agent definitions are shared resources within a hive. Any agent in the hive can use any sub-agent definition. This enables reuse and consistency.
- **Task-level binding.** Sub-agent selection happens at the task level, not the agent level. The same agent can use different sub-agents for different tasks.
- **Workflow-native.** Each workflow step can specify a sub-agent definition. This enables multi-sub-agent pipelines where different steps use different specialized sub-agents.
- **Read-only for agents.** Unlike personas (where MEMORY is self-writable), sub-agent definitions are read-only for agents. Only humans and the dashboard can modify them.
- **Backward compatible.** Agents that don't use sub-agent definitions are unaffected. The `sub_agent` field on tasks is nullable — existing tasks and workflows continue to work unchanged.

---

## 4. Concepts

### 4.1 Sub-Agent Definition

A versioned, immutable record defining a sub-agent's identity and behavior.

| Field | Type | Description |
|---|---|---|
| `id` | ULID | Primary key |
| `superpos_id` | FK → apiaries | Tenant scope |
| `hive_id` | FK → hives | Hive scope |
| `slug` | string(100) | URL-friendly identifier, unique per hive |
| `name` | string(255) | Human-readable display name |
| `description` | text | What this sub-agent does |
| `model` | string(100), nullable | Model override (e.g., `claude-sonnet-4-6`) |
| `documents` | jsonb | Document map (same structure as persona) |
| `config` | jsonb | LLM/runtime config |
| `allowed_tools` | jsonb, nullable | Tool allowlist for the sub-agent |
| `version` | unsigned int | Monotonic per slug+hive |
| `is_active` | boolean | Only one active per slug+hive (partial unique index) |
| `created_by_type` | string(10) | `human`, `agent`, `system` |
| `created_by_id` | string(26) | Creator ID |
| `created_at` | timestamp | Immutable (no updated_at) |

**Documents** follow the same structure as persona documents:

| Document | Purpose |
|---|---|
| `SOUL` | Identity, personality, values |
| `AGENT` | Capabilities, workflow, delegation patterns |
| `RULES` | Hard constraints and prohibitions |
| `STYLE` | Tone, formatting, output conventions |
| `EXAMPLES` | Few-shot examples of desired behavior |
| `NOTES` | Supplemental context |

Note: No `MEMORY` document — sub-agent definitions are stateless templates, not persistent entities.

### 4.2 Task ↔ Sub-Agent Binding

A task can optionally reference a sub-agent definition. When present, the task delivery response includes the assembled sub-agent prompt.

New column on `tasks`:

| Column | Type | Description |
|---|---|---|
| `sub_agent_definition_id` | string(26), nullable | FK → sub_agent_definitions (nullOnDelete) |

### 4.3 Assembly

Sub-agent documents are assembled in the same order as persona documents:

```
SOUL → AGENT → RULES → STYLE → EXAMPLES → NOTES
```

Concatenated with `\n\n`, each prefixed with `# {DOCUMENT_NAME}`.

---

## 5. Schema

### 5.1 `create_sub_agent_definitions_table` Migration

```php
Schema::create('sub_agent_definitions', function (Blueprint $table) {
    $table->string('id', 26)->primary();              // ULID
    $table->string('superpos_id', 26);
    $table->string('hive_id', 26);
    $table->string('slug', 100);
    $table->string('name', 255);
    $table->text('description')->nullable();
    $table->string('model', 100)->nullable();
    $table->json('documents')->default('{}');
    $table->json('config')->default('{}');
    $table->json('allowed_tools')->nullable();
    $table->unsignedInteger('version')->default(1);
    $table->boolean('is_active')->default(false);
    $table->string('created_by_type', 10)->default('human');
    $table->string('created_by_id', 26)->nullable();
    $table->timestamp('created_at')->nullable();

    // Foreign keys
    $table->foreign('superpos_id')->references('id')->on('apiaries');
    $table->foreign('hive_id')->references('id')->on('hives')->cascadeOnDelete();

    // Composite unique: one row per (hive, slug, version)
    $table->unique(['hive_id', 'slug', 'version'], 'uq_sub_agent_slug_version');

    // Lookup indexes
    $table->index('hive_id', 'idx_sub_agent_hive');
    $table->index('superpos_id', 'idx_sub_agent_apiary');
});

// Partial unique index: only one active definition per slug per hive.
// Driver-specific strategy (same pattern as add_approvable_columns migration):
$driver = DB::connection()->getDriverName();

if ($driver === 'pgsql') {
    DB::statement(
        'CREATE UNIQUE INDEX idx_sub_agent_active '
        . 'ON sub_agent_definitions (hive_id, slug) '
        . 'WHERE is_active = true'
    );
} elseif ($driver === 'sqlsrv') {
    // SQL Server supports filtered indexes via WHERE clause.
    DB::statement(
        'CREATE UNIQUE NONCLUSTERED INDEX idx_sub_agent_active '
        . 'ON sub_agent_definitions (hive_id, slug) '
        . 'WHERE is_active = 1'
    );
} elseif ($driver === 'sqlite') {
    // SQLite: no partial index support — regular composite index as fallback.
    Schema::table('sub_agent_definitions', function (Blueprint $table) {
        $table->index(
            ['hive_id', 'slug', 'is_active'],
            'idx_sub_agent_active',
        );
    });
}
// MySQL / MariaDB: skip — uniqueness enforced at application level
// in SubAgentDefinitionService.
```

### 5.2 Add `sub_agent_definition_id` to `tasks` Migration

```php
Schema::table('tasks', function (Blueprint $table) {
    $table->string('sub_agent_definition_id', 26)->nullable();
    $table->foreign('sub_agent_definition_id')
        ->references('id')
        ->on('sub_agent_definitions')
        ->nullOnDelete();
    $table->index('sub_agent_definition_id', 'idx_tasks_sub_agent');
});
```

> **Note on `json` vs `jsonb`:** Laravel's `$table->json()` maps to `JSONB` on PostgreSQL, `JSON` on MySQL, and `NVARCHAR(MAX)` on SQL Server. The migration uses the portable `json()` type; no raw `JSONB` needed.

---

## 6. API — Agent-Facing

All under `auth:sanctum-agent` middleware, scoped to agent's hive.

### 6.1 List Sub-Agent Definitions

```
GET /api/v1/sub-agents
```

Returns all active sub-agent definitions in the agent's hive.

**Response:**
```json
{
  "data": [
    {
      "id": "01JGRX...",
      "slug": "coder",
      "name": "Coding Agent",
      "description": "Focused coding agent for implementing features and fixes",
      "model": "claude-opus-4-7",
      "version": 3,
      "document_count": 4
    }
  ]
}
```

### 6.2 Get Sub-Agent Definition

```
GET /api/v1/sub-agents/{slug}
```

Returns a specific sub-agent definition with full documents.

**Response:**
```json
{
  "data": {
    "id": "01JGRX...",
    "slug": "coder",
    "name": "Coding Agent",
    "description": "Focused coding agent for implementing features and fixes",
    "model": "claude-opus-4-7",
    "version": 3,
    "documents": {
      "SOUL": "You are a focused coding agent...",
      "AGENT": "When you receive a coding task...",
      "RULES": "NEVER commit directly to main..."
    },
    "config": {
      "temperature": 0.2,
      "max_tokens": 8192
    },
    "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
  }
}
```

### 6.3 Get Assembled Prompt

```
GET /api/v1/sub-agents/{slug}/assembled
```

Returns the pre-assembled system prompt (all documents concatenated) for the **current active** version of the given slug.

**Response:**
```json
{
  "data": {
    "slug": "coder",
    "version": 3,
    "prompt": "# SOUL\n\nYou are a focused coding agent...\n\n# AGENT\n\nWhen you receive a coding task...",
    "document_count": 4
  }
}
```

### 6.4 Version-Stable Fetch by ID

The slug-based endpoints (6.2, 6.3) always resolve to the **current active** version for a given slug. When an agent needs to re-fetch a definition that was pinned to a task or workflow step, it must use the **id-based** endpoints to guarantee version determinism.

#### Get Definition by ID

```
GET /api/v1/sub-agents/by-id/{id}
```

Returns the exact sub-agent definition row identified by the immutable `sub_agent_definition_id` (ULID). This always returns the same version regardless of which version is currently active for the slug.

**Response:** Same shape as section 6.2.

#### Get Assembled Prompt by ID

```
GET /api/v1/sub-agents/by-id/{id}/assembled
```

Returns the pre-assembled system prompt for the exact pinned version.

**Response:** Same shape as section 6.3.

> **Version determinism note.** The slug-based endpoints (`/sub-agents/{slug}` and `/sub-agents/{slug}/assembled`) return whichever version is currently active — they are convenience endpoints for discovery and ad-hoc use. For any context where a specific `sub_agent_definition_id` has been pinned (task delivery, workflow step snapshots), agents **must** use the id-based endpoints (`/sub-agents/by-id/{id}`) to avoid fetching a newer version that replaced the pinned one.

### 6.5 Task Delivery Enhancement

When a task has `sub_agent_definition_id` set, the sub-agent information is included at **two different detail levels** depending on the endpoint, to avoid sending large prompt bodies on every poll cycle.

#### Lightweight Reference (`formatTask()` — polls, listings)

`formatTask()` includes only a lightweight `sub_agent` reference — no assembled prompt. This keeps poll responses small, since `formatTask()` is called on every `GET /api/v1/hives/{hive}/tasks/poll` poll cycle and task listing:

```json
{
  "id": "01ABC...",
  "type": "webhook_handler",
  "status": "in_progress",
  "payload": { "prompt": "Review this PR..." },
  "invoke": { "instructions": "..." },
  "sub_agent": {
    "id": "01DEF...",
    "slug": "coder",
    "version": 3
  }
}
```

#### Full Prompt (`claim()` — claim response only)

The full assembled prompt, config, and tool allowlist are included **only** in the `claim()` response — the single moment when the agent actually needs the sub-agent instructions:

```json
{
  "id": "01ABC...",
  "type": "webhook_handler",
  "status": "in_progress",
  "payload": { "prompt": "Review this PR..." },
  "invoke": { "instructions": "..." },
  "sub_agent": {
    "id": "01DEF...",
    "slug": "coder",
    "name": "Coding Agent",
    "model": "claude-opus-4-7",
    "version": 3,
    "prompt": "# SOUL\n\nYou are a focused coding agent...",
    "config": { "temperature": 0.2 },
    "allowed_tools": ["Bash", "Read", "Write", "Edit"]
  }
}
```

If an agent needs the full prompt outside of the claim flow (e.g., for a previously claimed task), it **must** use the id-based endpoint `GET /api/v1/sub-agents/by-id/{id}/assembled` (section 6.4), passing the `sub_agent.id` from the task's lightweight reference. This ensures the agent receives the exact pinned version, not a newer active version that may have replaced it. Do **not** use the slug-based assembled endpoint for this purpose — after a new version is activated for the same slug, the slug-based endpoint would return the newer definition.

---

## 7. API — Dashboard (Human-Facing)

### 7.1 Routes

| Method | Path | Action |
|---|---|---|
| `GET` | `/sub-agents` | Index — list all definitions |
| `POST` | `/sub-agents` | Store — create new definition |
| `GET` | `/sub-agents/{slug}` | Show/edit — definition editor |
| `PUT` | `/sub-agents/{slug}` | Update — creates new version |
| `DELETE` | `/sub-agents/{slug}` | Destroy — soft delete (deactivate) |
| `GET` | `/sub-agents/{slug}/versions` | Version history |
| `POST` | `/sub-agents/{slug}/rollback` | Rollback to prior version |

### 7.2 Create Request

```json
{
  "slug": "coder",
  "name": "Coding Agent",
  "description": "Focused coding agent for implementing features and fixes",
  "model": "claude-opus-4-7",
  "documents": {
    "SOUL": "You are a focused coding agent...",
    "AGENT": "When you receive a coding task..."
  },
  "config": {
    "temperature": 0.2
  },
  "allowed_tools": ["Bash", "Read", "Write", "Edit"]
}
```

### 7.3 Validation Rules

- `slug`: required, alpha_dash, max:100, unique per hive (among active definitions). Recreating a previously deactivated slug is allowed — the new definition receives a monotonically allocated version (`max(version) + 1` across all historical rows for the slug+hive) to avoid collision with the `uq_sub_agent_slug_version` constraint
- `name`: required, string, max:255
- `description`: nullable, string
- `model`: nullable, string, max:100
- `documents`: required, array, keys must be valid document names
- `config`: nullable, array
- `allowed_tools`: nullable, array of strings

---

## 8. Webhook Route Integration

`WebhookRoute.action_config` gains an optional `sub_agent_definition_slug` field.

When a webhook route creates a task, it resolves the slug to the active `sub_agent_definition_id` and stamps it on the task.

```json
{
  "action": "create_task",
  "task_type": "code_review",
  "target_capability": "code-review",
  "sub_agent_definition_slug": "coder",
  "invoke": {
    "instructions": "Review this PR and push fixes"
  }
}
```

Resolution: `SubAgentDefinition::where('slug', $slug)->where('hive_id', $hiveId)->where('is_active', true)->first()`.

If the slug doesn't resolve (deleted, deactivated), the task is still created without a sub-agent definition — fail-open, not fail-closed.

---

## 9. Workflow Integration

Each workflow step definition gains an optional `sub_agent_definition_slug` field. To ensure deterministic execution, the concrete sub-agent definition version is **pinned at workflow version snapshot time** — not resolved at execution time.

### 9.1 Step Definition (Authoring)

In the workflow builder, steps reference sub-agents by slug:

```json
{
  "key": "implement",
  "type": "prompt",
  "prompt": "Implement the fix described in: {{steps.analyze.result}}",
  "target_capability": "engineering",
  "sub_agent_definition_slug": "coder",
  "depends_on_steps": ["analyze"]
}
```

### 9.2 Version Pinning at Snapshot Time

When a workflow version is snapshotted (published), `Workflow::snapshotVersion()` resolves each step's `sub_agent_definition_slug` to the **currently active** `sub_agent_definition_id` and stores the concrete ID in the step configuration snapshot:

```php
// During workflow version snapshot:
foreach ($steps as &$stepDef) {
    if ($slug = $stepDef['sub_agent_definition_slug'] ?? null) {
        $subAgent = SubAgentDefinition::where('slug', $slug)
            ->where('hive_id', $workflow->hive_id)
            ->where('is_active', true)
            ->first();

        // Pin the concrete version ID into the snapshot
        $stepDef['sub_agent_definition_id'] = $subAgent?->id;
    }
}
```

The snapshotted step configuration contains both the human-readable `sub_agent_definition_slug` (for display) and the pinned `sub_agent_definition_id` (for execution). This ensures the same workflow version always runs against the same sub-agent revision, even if the active definition changes later.

### 9.3 Multi-Sub-Agent Pipeline

This enables powerful orchestration patterns where each step uses a different specialized sub-agent:

```
┌──────────────────────────────────────────────────────────────┐
│  Workflow: PR Review & Fix Pipeline                          │
│                                                              │
│  [webhook: github.pull_request_review]                       │
│       │                                                      │
│       ▼                                                      │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐   │
│  │ Step: triage │──▶│ Step: fix    │──▶│ Step: verify    │   │
│  │ sub: analyst │   │ sub: coder   │   │ sub: reviewer   │   │
│  │ cap: triage  │   │ cap: dev     │   │ cap: qa         │   │
│  └─────────────┘   └──────────────┘   └─────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 9.4 Step Task Creation

`WorkflowExecutionService::createStepTask()` uses the **pinned** `sub_agent_definition_id` from the snapshotted step configuration — it does not re-resolve the slug at execution time:

```php
// At execution time: use the pinned ID from the snapshot, not a live slug lookup
if ($pinnedId = $stepDef['sub_agent_definition_id'] ?? null) {
    $task->sub_agent_definition_id = $pinnedId;
}
```

If the pinned definition has been deleted since snapshot time, the task is created without a sub-agent definition (fail-open, same as webhook routes).

---

## 10. Fan-Out Integration

Fan-out child tasks can each specify a different `sub_agent_definition_slug` (resolved to `sub_agent_definition_id` at creation time):

```json
{
  "type": "analysis",
  "payload": { "prompt": "Analyze the data" },
  "completion_policy": { "type": "all" },
  "children": [
    {
      "payload": { "prompt": "Research the topic" },
      "target_capability": "research",
      "sub_agent_definition_slug": "researcher"
    },
    {
      "payload": { "prompt": "Write the code" },
      "target_capability": "engineering",
      "sub_agent_definition_slug": "coder"
    },
    {
      "payload": { "prompt": "Review the output" },
      "target_capability": "qa",
      "sub_agent_definition_slug": "reviewer"
    }
  ]
}
```

---

## 10.5 Marketplace Persona Prefill (TASK-276)

Users creating a new sub-agent definition can bootstrap the form from an existing `MarketplacePersona` via a "Start from Marketplace Persona" dropdown at the top of `/dashboard/sub-agents/create`.

**Fork model, not link.** The prefill is a one-shot snapshot:

- Documents, config (stringified JSON), model, description, and capabilities (mapped to `allowed_tools`) are copied into the form on selection.
- `name` and `slug` are **never** prefilled — the user picks their own identifier.
- There is **no FK** from `sub_agent_definitions` to `marketplace_personas`. Updates to the source persona do not propagate to forks.
- There is **no `install_count` increment** — prefill is a UI preview, not an install.

The dropdown is populated server-side via an Inertia prop (`marketplacePersonas`) filtered by `MarketplacePersona::visibleTo($organizationId)` (public personas from any apiary + private personas owned by the current apiary). On selection the client fetches the full detail via the existing `GET /dashboard/persona-marketplace/{slug}` JSON endpoint — no new endpoint introduced.

---

## 11. SDK Integration

### 11.1 Python SDK

```python
# List available sub-agent definitions
definitions = client.get_sub_agent_definitions()

# Get a specific definition by slug (returns current active version)
coder = client.get_sub_agent_definition("coder")

# Get assembled prompt by slug (current active version)
prompt = client.get_sub_agent_assembled("coder")

# Get a specific pinned definition by ID (version-stable)
pinned = client.get_sub_agent_definition_by_id("01DEF...")

# Get assembled prompt by ID (version-stable, for re-fetch)
pinned_prompt = client.get_sub_agent_assembled_by_id("01DEF...")

# Sub-agent info is included in claimed tasks automatically
# (full prompt only in claim response; lightweight ref in polls)
task = client.claim_task()
if task.sub_agent:
    print(task.sub_agent.slug)    # "coder"
    print(task.sub_agent.prompt)  # assembled prompt (included at claim time)
    print(task.sub_agent.model)   # "claude-opus-4-7"
    print(task.sub_agent.id)      # "01DEF..." — use for version-stable re-fetch
```

### 11.2 Shell SDK

The task JSON response includes the `sub_agent` block. The shell SDK parses it and exposes it as environment variables:

```bash
SUB_AGENT_SLUG="coder"
SUB_AGENT_MODEL="claude-opus-4-7"
SUB_AGENT_PROMPT="# SOUL\n\n..."
```

---

## 12. Relationship Summary

| Aspect | Persona | Sub-Agent Definition |
|---|---|---|
| **Scope** | Per-agent | Per-hive (shared) |
| **Purpose** | "Who the agent is" | "Who the agent delegates to" |
| **Attached to** | Agent record | Task record |
| **Versioning** | Immutable rows, monotonic version | Same pattern |
| **Documents** | SOUL, AGENT, MEMORY, RULES, STYLE, EXAMPLES, NOTES | SOUL, AGENT, RULES, STYLE, EXAMPLES, NOTES (no MEMORY) |
| **Self-editable** | MEMORY is writable by agent | Read-only |
| **A/B Experiments** | Supported | Future (not in v1) |
| **Rollouts** | Canary/rolling supported | Future (not in v1) |
| **Config** | LLM params, custom keys | Same structure |

---

## 13. Implementation Phases

### Phase 1 — Data Model & CRUD

- [ ] Migration: `create_sub_agent_definitions_table`
- [ ] Model: `SubAgentDefinition` with `BelongsToHive`, `BelongsToApiary`
- [ ] Service: `SubAgentDefinitionService` (create, update, activate, rollback, list)
- [ ] Form Requests: `StoreSubAgentDefinitionRequest`, `UpdateSubAgentDefinitionRequest`
- [ ] Dashboard Controller: `SubAgentDefinitionController` (index, store, show, update, destroy, versions, rollback)
- [ ] Inertia Pages: list, create/edit, version history
- [ ] Agent-facing API: `SubAgentApiController` (list, show, assembled — slug-based and id-based)
- [ ] Routes: web + api (including `/sub-agents/by-id/{id}` and `/sub-agents/by-id/{id}/assembled`)

### Phase 2 — Task Integration

- [ ] Migration: add `sub_agent_definition_id` to `tasks`
- [ ] Update `formatTask()` in `TaskController` to include lightweight `sub_agent` reference (id, slug, version)
- [ ] Update `claim()` to include full `sub_agent` block with assembled prompt, config, and allowed_tools
- [ ] Update `CreateTaskRequest` validation to accept `sub_agent_definition_slug`
- [ ] Resolve slug → id in task creation (controller + service)
- [x] Update `FanOutService` to handle `sub_agent_definition_slug` on children
- [x] Python SDK: add `get_sub_agent_definitions()`, `get_sub_agent_definition()`, `get_sub_agent_assembled()`, `get_sub_agent_definition_by_id()`, `get_sub_agent_assembled_by_id()`, parse `sub_agent` from task response
- [x] Shell SDK: parse `sub_agent` block from task JSON

### Phase 3 — Webhook & Workflow Integration

- [x] `WebhookRouteEvaluator::executeCreateTask()` — resolve `sub_agent_definition_slug` from `action_config`
- [x] Webhook route form: add sub-agent definition selector
- [x] Workflow step definition schema: add `sub_agent_definition_slug` field
- [x] `Workflow::snapshotVersion()` — resolve `sub_agent_definition_slug` → pinned `sub_agent_definition_id` at snapshot time
- [x] `WorkflowExecutionService::createStepTask()` — use pinned `sub_agent_definition_id` from snapshot (no live slug resolution)
- [x] Workflow builder UI: sub-agent selector dropdown per step
- [x] `WorkflowValidationService` — validate sub-agent slugs exist

### Phase 4 — Advanced (Future)

- [ ] Sub-agent A/B experiments (mirror `PersonaExperimentService`)
- [ ] Performance tracking per sub-agent definition
- [ ] Sub-agent definition templates (pre-built library)
- [ ] Canary rollouts for sub-agent definitions
- [ ] Cross-hive sub-agent sharing (apiary-scoped definitions)
- [ ] Agent self-discovery: agent can query available sub-agents and select dynamically

---

## 14. Open Questions

1. **Should sub-agent definitions support a MEMORY document?** Current design says no (they're stateless templates). But if a sub-agent needs project-specific context, where does that come from? Options: (a) inject via `invoke.context`, (b) use knowledge entries, (c) add MEMORY support later.

2. **Should agents be able to create sub-agent definitions?** Current design is human-only CRUD. But an agent might want to create a specialized sub-agent for a specific workflow it's building. Gated by permission?

3. **Dynamic sub-agent selection.** Should an agent be able to choose which sub-agent to use at runtime (e.g., based on task content), or must it always be pre-selected by the task creator? Both could be supported — pre-selected via task field, dynamic via API listing.

4. **Sub-agent definition size limits.** Should there be a max document size or total token count? Persona has `PersonaTokenService` for this — should sub-agents get the same?

5. **Cross-hive sub-agents.** Should sub-agent definitions be shareable across hives within an apiary? The schema already includes `superpos_id` for this, but the access control and UI need design.
