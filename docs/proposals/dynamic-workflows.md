# Dynamic Workflows: Native Support for Claude Code-Style Agentic Scripts

Status: Approved (architecture decisions locked 2026-06-09)
Owner: workflow track
Scope: Adds a fourth `kind` value to the existing `registry_items` table
(see [registry.md](./registry.md)) so Claude Code Dynamic Workflows —
LLM-authored JS scripts that orchestrate sub-agents — become a
first-class composable in Superpos. Tasks and static-DAG workflow
steps can reference a `dynamic_workflow` by registry revision. The
agent's Claude Code runtime runs the script locally; Superpos
provides the substrate (state, audit, credentials, policy, marketplace,
multi-tenant).

This proposal is intentionally *additive* — it does not touch the
existing static-DAG `Workflow` system beyond what's required to let
static-DAG steps reference a dynamic workflow. The static DAG keeps
its dedicated `workflows` / `workflow_versions` / `workflow_runs`
tables; dynamic workflows live on the registry because their unit of
composition is much smaller (a script + metadata) and they benefit
from the registry's revision-pinning + attachment model that
sub-agents / skills / modules already use.

---

## 1. What this proposal does

1. **Add a `kind = 'dynamic_workflow'` value** to the registry's
   kind list. `registry_items.kind` is a `string(20)` column, *not*
   a Postgres enum, so this is a **code-only addition to
   `RegistryItem::KINDS`** validated by the registry service — no
   enum / schema migration, no `ALTER TYPE` (see
   [§6.1](#61-the-new-kind-value)). The discriminated table from
   [registry.md §5](./registry.md#5-data-model) already supports
   this — we just add a 4th value and define its payload shape.

2. **Define the `dynamic_workflow` payload** — script content
   (a JS source file), runtime metadata (entry function, declared
   inputs/outputs), declared capabilities (which tools the
   script will invoke, for policy pre-evaluation) and per-revision
   limits (wallclock, memory, fan-out concurrency, checkpoint
   size, proxy allowlist) — see [§6.2](#62-payload-shape)
   and [§8.6](#86-per-revision-limits-locked-decision).

3. **Allow `scope = 'task'` for `kind = 'dynamic_workflow'`** —
   the registry's v1 restriction in
   [registry.md §6](./registry.md#6-attachment-model) currently
   limits task-scoped attachments to `subagent` and `skill`. We
   relax that for `dynamic_workflow` so a task can be *executed by*
   a dynamic workflow.

4. **Extend the static-DAG `Workflow` step model** so a step of
   `type = 'dynamic_workflow'` references a `registry_items` row
   by `id` + `revision_id`. The static-DAG executor dispatches a
   `platform.dynamic_workflow.run.requested` event; an agent in
   the hive claims it; the script runs locally; phase events flow
   back through the same `platform.workflow.*` channels.

5. **Add `platform.dynamic_workflow.*` event topics** — symmetric
   with the existing `platform.workflow.*` topics so dashboards
   and subscribers can listen for both kinds uniformly.

6. **Ship a new SDK namespace** (`superpos.workflows.dynamic`)
   with: `create`, `list`, `get`, `update`, `run`, `await_run`,
   `subscribe`, `checkpoint`, `cancel`.

7. **Add a code-editor view** to the dashboard WorkflowBuilder
   for the dynamic kind, alongside the existing DAG canvas. The
   marketplace category ships both kinds under "Workflows".

## 2. What this proposal does NOT do

- **Does not replace static-DAG workflows.** They have a richer
  lifecycle (DAG snapshots, versioned runs, per-step knowledge
  attachment, marketplace templates with the `superpos-` prefix)
  that does not fit a single `registry_items.payload` jsonb. The
  static DAG stays in its dedicated table; the dynamic kind lives
  on the registry. Both are "workflows" from the user's
  perspective; both go through the same permissions and event bus.

- **Does not implement the Claude Code runtime.** We do not ship
  a JS execution engine. The script runs in the agent's existing
  Claude Code installation, which already has it (Dynamic Workflows
  shipped May 28, 2026, research preview, requires Claude Code
  2.1+). Superpos is the substrate, not the executor. Both
  editions execute scripts on Node.js (`node:vm`), and in both
  cases the Node runtime must be **explicitly provided** in the
  agent's runtime image — it is *not* present in the app/runtime
  container by default (the production image is
  `dunglas/frankenphp:1-php8.3` and ships no Node binary; see
  [§8.5](#85-scriptruntime-interface-locked-decision)). CE runs
  scripts in an in-process Node 22 runtime co-located with the
  agent, which means the CE agent/runtime image must install or
  copy a Node 22 binary (or run CE through a sidecar/agent image
  that includes Node); Cloud adds a `node:vm` sidecar per agent
  wrapped in an OS-level sandbox (see
  [§8.8](#88-trust-boundary-and-sandboxing-locked-decision)) —
  multi-tenant isolation comes from that sandbox, not from the
  per-agent process topology or from `node:vm`, which is not a
  security boundary. The sidecar is a thin Unix-socket service,
  not a new distributed system.

- **Does not implement the executor-side polling loop.** The agent
  runtime subscribes to `platform.dynamic_workflow.run.requested`
  events using its existing poll infrastructure (the same loop
  that handles `platform.tasks.claim`). This proposal documents
  the contract; the agent-side subscription is wired up in
  superpos-agent-core, not in superpos-app.

- **Does not implement LLM authoring tooling.** The LLM writes
  the workflow.js; humans don't author it through a wizard. The
  dashboard's code-editor view is for *reviewing and editing*
  scripts the LLM produced, not for greenfield authoring.

- **Does not rename Superpos "workflows" to "pipelines" yet.**
  That rename is the right long-term move (see [§14](#14-deferred-work-the-pipeline-rename))
  but its blast radius is too large to bundle with this
  integration. The dynamic-workflow kind lands behind a `kind`
  discriminator; the rename can follow as its own project.

## 3. Goals / Non-goals

### Goals

- **Composable**: dynamic workflows are first-class artifacts
  that can be referenced by tasks, by static-DAG steps, and by
  the marketplace — using the same attachment primitives that
  sub-agents already use.
- **Reproducible**: a dynamic-workflow run carries the content
  hash of the script that was used, so historical runs replay
  deterministically even if a newer revision has shipped.
- **Auditable**: every run + every phase transition lands in
  `activity_log` and emits a `platform.*` event, exactly like
  static-DAG workflow runs.
- **Policy-brokered**: a script that wants to call GitHub does
  not hold a token. It calls `superpos.proxy.github.*`; Superpos
  evaluates the calling agent's `action_policies` and either
  allows, denies, or raises an `approval_request`.
- **Multi-tenant**: every dynamic workflow is hive-scoped, like
  every other registry item. Cross-hive access follows the
  existing `cross_hive:*` permission model.
- **Marketplace-installable**: a `dynamic_workflow` is a
  marketplace-shippable artifact, versioned, signed, installable
  via the existing `WorkflowTemplate` flow with a `kind`
  discriminator on the template.

### Non-goals

- Not a replacement for the LLM-side orchestrator when a static
  DAG suffices. The DAG is the right tool for *known-shape*
  multi-step agent work; dynamic workflows are the right tool
  for *unknown-shape* work that benefits from the LLM's ability
  to improvise control flow.
- Not a service-mesh / sidecar. The agent's Claude Code is the
  CE runtime; the Cloud runtime adds a `node:vm` sidecar inside an
  OS-level sandbox, which is where multi-tenant isolation actually
  comes from (`node:vm` is not a security boundary — see
  [§8.8](#88-trust-boundary-and-sandboxing-locked-decision)). In
  both cases, the runtime lives on
  the agent's side of the trust boundary. Superpos is the
  *registrar* (what workflows exist, who can run them, what
  they did) — not the *executor* (the JS engine itself).
- Not a new event bus. The existing `events` table + pub/sub
  carries the new topics.

## 4. Background: why the registry, not a new table

The original impulse was to add a `dynamic_workflows` table
alongside the existing `workflows` table. After reviewing the
[registry.md](./registry.md) proposal, that would be the wrong
move. The registry already provides:

| Concern | Registry primitive | What it gives us |
|---|---|---|
| Versioning | `registry_items` + `registry_item_revisions` | Immutable revisions, content-hash pinning, replay determinism |
| Multi-tenancy | `hive_id` on every item | Per-hive isolation without extra columns |
| Composition | `registry_attachments(scope, scope_id, role)` | Tasks and workflow steps can attach dynamic workflows by id+revision |
| Visibility | `visibility ∈ {hive, private}` + `owner_agent_id` | Hive-wide or agent-private scripts |
| Marketplace | Same `WorkflowTemplate` installer, gated on `kind` | Installable, signed bundles, the same `superpos-` prefix |
| Permissions | Reuses the agent permission catalog (`UpdateAgentPermissionsRequest`) | One permission decision to make (reuse `workflows:*` vs a new `registry:*` category — see §11), not a bespoke per-resource ACL |

The only thing missing is the `kind = 'dynamic_workflow'`
discriminator value and the `dynamic_workflow` payload shape.
`registry_items.kind` is a `string(20)` column (not a pg enum),
so adding the kind is a one-line change to `RegistryItem::KINDS`
plus a service-layer payload validator — no schema migration,
not a new subsystem.

The static-DAG `Workflow` table stays separate because:

1. Its schema is *much* richer (`steps` jsonb DAG, `trigger_config`,
   per-step knowledge attachments, marketplace `WorkflowTemplate`
   with install/fork semantics). Cramming all of that into a
   `registry_items.payload` jsonb is the same anti-pattern as
   the JSONB knowledge-entry blob we're trying to move away from
   in the [knowledge-wiki-redesign](./knowledge-wiki-redesign.md).

2. Its lifecycle is fundamentally different: a `Workflow` has
   *versions* and *runs* (parent/child of `Task`); a registry
   item has *revisions* (immutable content snapshots). The
   semantic mismatch is real, not a matter of degree.

3. The existing static-DAG API (`/api/v1/hives/{hive}/workflows`,
   `/workflows/{id}/runs`, `/versions/{v}/rollback`) is widely
   used. Disrupting it would be gratuitous.

So: **dynamic workflows go on the registry. Static workflows
stay in their dedicated table. Both are workflows from the
user's perspective; both go through the same permissions and
event channels.**

## 5. Naming

- **The artifact**: `dynamic_workflow`. Plural: `dynamic_workflows`.
  Used in code (`registry_items.kind = 'dynamic_workflow'`),
  URLs (`/registry/dynamic_workflow/{slug}`), and event topics
  (`platform.dynamic_workflow.*`). The URL segment **is** the
  `kind` value verbatim: the registry routes pass the literal
  `{kind}` segment to `RegistryApiController`, which validates it
  with an exact `in_array($kind, RegistryItem::KINDS, true)`
  check (`RegistryItem::KINDS = ['subagent', 'skill', 'module']`,
  extended with `'dynamic_workflow'` by DW-1). The underscore
  form is therefore mandatory — a hyphenated `/registry/dynamic-workflow`
  URL would resolve to `$kind = 'dynamic-workflow'`, fail the
  exact-match validation, and 404. No hyphen→underscore
  normalization is introduced; the convention (URL segment ==
  `kind` literal) matches the existing `subagent`/`skill`/`module`
  routes.
- **The umbrella noun**: "workflow" stays. The existing static
  DAGs are *static workflows*; the new scripts are *dynamic
  workflows*. The product surface never has to qualify — the
  dashboard picks the right UI based on `kind`.
- **The deferred rename**: "workflow" → "pipeline" is the right
  long-term move. See [§14](#14-deferred-work-the-pipeline-rename)
  for the sequencing. It is not part of this proposal.
- **What "dynamic" means here**: the script is *authored
  dynamically* by the LLM at run time, not *executed
  dynamically* (Claude Code's runtime executes the script
  deterministically once written). The name aligns with
  Anthropic's "Dynamic Workflows" terminology (May 28, 2026)
  so the SDK and docs match the upstream vocabulary.

## 6. Data model

### 6.1 The new kind value

**There is no schema migration.** `registry_items.kind` is *not*
a Postgres enum — the `create_registry_items_table` migration
declares it as `$table->string('kind', 20)`
(`database/migrations/2026_06_01_100000_create_registry_items_table.php`),
and valid kinds are enforced in application code, not by the
database type system. The canonical kind list lives in
`App\Models\RegistryItem::KINDS` (currently
`['subagent', 'skill', 'module']`), and `RegistryService` rejects
anything outside it (`! in_array($kind, RegistryItem::KINDS, true)`
in `app/Services/RegistryService.php`).

Adding `dynamic_workflow` is therefore a **code-only** change:

1. Append `'dynamic_workflow'` to `RegistryItem::KINDS`.
2. Ensure any request validators / service guards that gate on
   `RegistryItem::KINDS` pick up the new value automatically
   (they read the const, so no separate change is needed — but
   confirm with a test).

`'dynamic_workflow'` fits within the `string(20)` column, so no
column alteration is required either. No `ALTER TYPE` and no
`registry_item_kind` type exist — running such a migration would
fail.

**DW-1 also adds a defence-in-depth CHECK constraint** on the
`kind` column (`registry_items_kind_check`) listing the four
valid values. The application-level `KINDS` constant is the
source of truth; the CHECK constraint is a backstop against
direct `DB::table('registry_items')->insert(['kind' => ...])`
calls and against future code that forgets the in-app
validator. The migration is reversible (`DROP CONSTRAINT` in
`down()`).

### 6.2 Payload shape

```
dynamic_workflow.payload = {
  entry: string,                   # default-exported function name; e.g. "run"
  inputs: {                        # JSON Schema for the script's input object
    type: "object",
    required: ["..."],             # list of required input keys
    properties: { ... }            # per-key type/description
  },
  outputs: {                       # JSON Schema for the script's output object
    type: "object",
    properties: { ... }
  },
  capabilities: {                 # declared limits + actions, for policy pre-eval
    declared: [                    # what the script intends to call
      "github.read",
      "github.write",
      "knowledge.read",
      "service_proxy.*"            # wildcard allowed
    ],
    limits: {                      # per-revision declared ceilings;
                                   # runtime enforces min(declared, platform_ceiling).
                                   # Declarations can only self-cap; the platform
                                   # ceiling is absolute.
      max_wallclock_ms: number,    # total wallclock for the run
      max_memory_mb: number,       # Node RSS / --max-old-space-size cap
      max_await_run_concurrent: number,  # 8 default, 256 platform ceiling
      max_checkpoint_bytes: number, # per-checkpoint state size
      proxy_allowlist: [string]    # explicit service names; empty = all declared
    }
  },
  script_sha256: string,           # content hash of `script` (set on revision)
  script: string                   # JS source — workflow.js, ES module syntax,
                                   #   exports a default async function matching
                                   #   `entry`. Size cap 256 KB; larger scripts
                                   #   must be split across multiple revisions
                                   #   with a thin entry shim.
}
```

**Why the payload is structured this way:**

- `entry` / `inputs` / `outputs` give the dashboard and the
  Superpos-side validator enough to render a typed form for
  inputs and a typed display for outputs without re-parsing the
  script.
- `capabilities` is a *declaration* — the script's own statement
  about what it will need and how much of the runtime it will
  consume. The service layer uses this to pre-evaluate
  `action_policies` *before* dispatch: a script that declares
  `github.write` against an agent that has no GitHub connection
  can be rejected at dispatch time with a clear error, instead
  of failing at run time. The `limits` sub-object is enforced
  by the runtime (see [§8.6](#86-per-revision-limits)); the
  platform ceiling is absolute and live in
  `config('dynamic_workflow.platform_ceiling')`, keyed by edition.
- `script_sha256` is the deterministic identifier; the actual
  source is in `script` for now. Future revisions may externalise
  `script` to a content-addressed blob store once we have
  evidence of large scripts in practice.

### 6.3 Revision model

The existing `RegistryItemRevision` table covers dynamic workflows
unchanged. Every script change creates a new revision; old
revisions remain replayable. The `pinned` (non-null `revision_id`)
attachment model from [registry.md §6](./registry.md#6-attachment-model)
is what gives us reproducibility — a workflow run records the
revision id it was spawned from, so a year-old run can be
replayed against the same script content.

### 6.4 Run record

Dynamic workflow runs do *not* use the `workflow_runs` table —
that table is for the static-DAG lifecycle (steps, fan-in
serialization via `SELECT FOR UPDATE`, per-step knowledge
attachments). Dynamic-workflow runs are simpler:

```
DynamicWorkflowRun
  id                  ulid
  organization_id     ulid
  hive_id             ulid
  registry_item_id    ulid                    # FK registry_items.id
  registry_revision_id ulid                   # FK registry_item_revisions.id
  task_id             ulid | null             # entry-point backref to tasks.id;
                                               #   null when invoked from a parent
                                               #   run (nested await_run or static-DAG step)
  status              enum { pending, claimed, running,
                              completed, failed, cancelled }
  inputs              jsonb                   # the script's input object
  outputs             jsonb | null            # populated on completion
  error               text | null             # populated on failure
  claimed_by_agent_id ulid | null             # the agent that claimed the run
  step_states         jsonb                   # per-script-phase STATUS map
                                               #   { phase_key: status } — observability
                                               #   only, mirrors WorkflowRun.step_states
  checkpoints         jsonb                   # ORDERED append-only recovery log:
                                               #   [{ sequence, phase_key,
                                               #      checkpointed_at, state }, ...]
                                               #   resumeFrom = the highest-sequence entry
  started_at          timestamp | null
  completed_at        timestamp | null
  created_at          timestamp
  updated_at          timestamp
```

**Task drives run (canonical framing).** A dynamic workflow is a
specialization of a task: when a task carries a
`role = 'executor'` attachment to a `dynamic_workflow` registry
item, the task's lifecycle *drives* the run's lifecycle. **The two
are distinct state machines that advance in lockstep — they are
not the same column.** The `tasks.status` column keeps the live
task state machine unchanged; the finer-grained DW phases live on
`dynamic_workflow_runs.status`.

The live `tasks` status enum is
`['waiting', 'pending', 'in_progress', 'completed', 'failed', 'cancelled', 'dead_letter', 'expired', 'awaiting_children']`
(`app/Models/Task.php:20`, `Task::STATUSES`) — there is **no**
`claimed` or `running` task status — and `TaskController::claim`
transitions a task `pending → in_progress`
(`app/Http/Controllers/Api/TaskController.php:522-533`). The DW
run state machine (`dynamic_workflow_runs.status`, enum
`{ pending, claimed, running, completed, failed, cancelled }`)
maps onto that as follows:

| `tasks.status` (unchanged) | `dynamic_workflow_runs.status` | trigger |
|---|---|---|
| `pending` | `pending` | run row created, not yet picked up |
| `in_progress` | `claimed` | agent claims the task; runtime fetches the script content |
| `in_progress` | `running` | the script's `entry` returns its first `await` |
| `completed` / `failed` / `cancelled` | `completed` / `failed` / `cancelled` | script return, throw, or user abort |

- The single live `tasks` claim transition (`pending →
  in_progress`) is what flips the run from `pending → claimed`;
  the run-only `claimed → running` step has **no** task
  counterpart (the task stays `in_progress`).
- The task's `output` field carries the DW's `outputs`; the
  task's existing `claimed_by_agent_id` and heartbeat machinery
  are reused unchanged.

`dynamic_workflow_runs` is canonical: every execution gets a row
here, including nested `await_run` invocations and static-DAG
step invocations that have no task. `tasks.dynamic_workflow_run_id`
is the optional entry-point pointer — set when the run was
triggered as a task, null when it was triggered by a parent run.
This means the existing `Task` claim/complete endpoints can be
extended to handle DW runs without a new claim primitive, and
nested invocations stay first-class without polluting the task
queue.

`step_states` mirrors the static-DAG `WorkflowRun.step_states`
shape — a per-phase **status map** keyed by phase key
(`{ phase_key: status }`), exactly like the live
`WorkflowRun.step_states` JSONB column
(`database/migrations/2026_03_25_320000_create_workflow_runs_table.php:26`,
`jsonb('step_states')->default('{}')`; built as
`array<string, string>` by
`WorkflowExecutionService::buildInitialStepStates`). It exists so
dashboards and the activity log can render both run kinds
uniformly. The structure is intentionally loose because *what* a
"step" is in a dynamic workflow is defined by the script — a phase
can be an HTTP call, a `superpos.knowledge.read`, a fan-out,
whatever the script chose to instrument.

**`step_states` is observability, not recovery.** Because it is a
keyed status map it has no stable ordering, no sequence, and no
timestamp, and a repeated `phase_key` overwrites the prior value —
so it cannot answer "what was the *last* checkpoint?" Crash
recovery therefore does **not** read from `step_states`. Manual
checkpoints (§8.7) are written to a separate **ordered,
append-only** `checkpoints` array, where each entry carries a
monotonic `sequence`, the `phase_key`, a `checkpointed_at`
timestamp, and the `state` object. `resumeFrom` is the
highest-`sequence` entry, which is unambiguous even when the same
`phase_key` is checkpointed more than once.

**Claiming is an atomic row-status transition, not a uniqueness
constraint.** A claim is modeled exactly like the live task claim
path (`TaskController::claim` in
`app/Http/Controllers/Api/TaskController.php`): the server runs an
atomic conditional update against the individual run row —
`UPDATE dynamic_workflow_runs SET status='claimed',
claimed_by_agent_id=:agent, ... WHERE id=:run_id AND
status='pending'` — and only the first agent to flip the row from
`pending` wins the race (`affected_rows = 0` means it was already
claimed or no longer pending). There is **no** uniqueness index on
`(registry_revision_id, claimed_by_agent_id)`; the task claim path
does not serialize claims per `(agent, revision)` and neither
should this. Such an index would be wrong: two concurrent runs of
the *same* revision claimed by the *same* agent are distinct run
records and must both be allowed. The only indexes needed are
ordinary status / lease-lookup indexes (e.g. on `status` and
`claimed_by_agent_id`) to keep the conditional update and any
lease GC scan fast — none of them unique.

### 6.5 Phase event payload

Both static-DAG and dynamic-workflow runs emit the same phase
event shape:

```json
{
  "run_id": "01HX...",
  "run_kind": "static_dag | dynamic_workflow",
  "phase": "started | completed | failed | checkpointed",
  "phase_key": "step_3 | fetch_github_issues | validate_output",
  "data": { ... },             // run_kind-specific
  "occurred_at": "2026-06-09T12:00:00Z"
}
```

A `data` schema per `run_kind` is documented in the SDK; the
event itself is shape-stable so dashboards can render any
combination without branching on the `data` schema.

**This full shape — including `data` — is the *persisted* phase
record (stored on `dynamic_workflow_runs.step_states` and returned
by the `workflows:read`-gated run-read API). It is NOT the
cross-hive broadcast payload.** Because every
`platform.dynamic_workflow.phase.*` event is cross-hive (§12), the
broadcast carries only `{ run_id, slug, revision_id, status,
phase_key, occurred_at }` and omits `data` entirely. A dashboard
or apiary-scoped subscriber that needs the `data` object reads it
from the run-read API in the run's own hive, not off the bus.

## 7. Attachment model

### 7.1 Task-scoped attachment

A task can be *executed by* a dynamic workflow, using the
existing `registry_attachments` join table with
`scope = 'task'` and a reserved role:

```
RegistryAttachment
  scope        = 'task'
  scope_id     = task.id
  item_id      = registry_items.id (kind = 'dynamic_workflow')
  revision_id  = registry_item_revisions.id   # nullable; null = latest
  role         = 'executor'                   # reserved (see below)
```

The `role = 'executor'` reservation extends the v1 rule from
[registry.md §6](./registry.md#6-attachment-model) which
currently reserves `executor` for `kind = 'subagent'`. We add
`kind = 'dynamic_workflow'` to the reservation list, and the
service layer enforces "at most one `executor` per task" across
both kinds — a task has *either* a sub-agent executor *or* a
dynamic-workflow executor, never both. The legacy
`task.sub_agent` field becomes "the attachment in the `executor`
role" without breaking the wire format.

**Task drives DW run lifecycle (locked decision).** When the
executor is a dynamic workflow, the task and the run are two
distinct state machines advancing in lockstep (see
[§6.4](#64-run-record)). The `tasks.status` column keeps its live
machine unchanged — `pending → in_progress → completed | failed |
cancelled` (`Task::STATUSES`; `TaskController::claim` flips
`pending → in_progress`) — while the finer-grained DW phases
(`pending → claimed → running → completed | failed | cancelled`)
live on `dynamic_workflow_runs.status`. There is no `claimed` or
`running` *task* status. The task's `output` carries the run's
`outputs`; the task's existing claim/heartbeat/complete endpoints
are reused (the claim transition flips the run to `claimed`); the
`task_id` is back-referenced on `dynamic_workflow_runs` for
audit and replay.

### 7.2 Static-DAG step attachment

A static-DAG workflow step of `type = 'dynamic_workflow'`
references the registry item directly via two new columns on
`workflows.steps[]` (or on a new `workflow_step_dynamic_refs`
join table — see [§13 Open Questions](#13-open-questions)):

```
step = {
  type: "dynamic_workflow",
  registry_item_id: "01HX...",
  registry_revision_id: "01HX..." | null,   # null = latest
  inputs: { ... },                          # template values from step outputs
  ...
}
```

The static-DAG executor (today `WorkflowExecutionService`) grows
a new branch for this step type. The branch:

1. Resolves the `registry_item_id` + `revision_id` to the
   script content.
2. Creates a `DynamicWorkflowRun` row.
3. Emits `platform.dynamic_workflow.run.requested`.
4. On phase events, updates `DynamicWorkflowRun.step_states`.
5. On completion, returns the run's `outputs` as the step's
   output value (so downstream static-DAG steps can reference it
   via the existing `{{steps.step_3.outputs}}` template).

### 7.3 Hive / agent scope

Unchanged from the existing attachment model. A dynamic
workflow can be `scope = 'hive'` (any agent in the hive can run
it) or `scope = 'agent'` (only the owner agent can run it). The
private-visibility constraint from
[registry.md §6](./registry.md#6-attachment-model) is inherited
unchanged.

## 8. Execution model

### 8.1 Trigger sources

A dynamic-workflow run starts from any of:

| Trigger | Path |
|---|---|
| Manual API | `POST /registry/dynamic_workflow/{slug}/runs` |
| SDK | `await superpos.workflows.dynamic.run(slug, inputs)` |
| Static-DAG step | `WorkflowExecutionService` reaches a step of `type = 'dynamic_workflow'` |
| Schedule | A future enhancement (Phase 3) — uses the existing `TaskSchedule` infrastructure |
| Webhook | A future enhancement — uses the existing `WebhookRoute` infrastructure |

The first two are in scope for this proposal. The schedule and
webhook triggers are noted as future work because they require
either new `trigger_config` plumbing on the registry item or
a small join table; neither is hard, but neither is required
to prove the substrate.

### 8.2 The claim path

The agent's Claude Code subscribes to
`platform.dynamic_workflow.run.requested` events (the same poll
loop that handles `platform.tasks.claim`). On a match:

1. The agent's runtime sends `POST /api/v1/agents/claims/dynamic_workflow`
   with the run id. The server runs an atomic conditional update on
   the run row — `UPDATE ... SET status='claimed' WHERE id=:run_id
   AND status='pending'` — transitioning `status` from `pending` to
   `claimed`. Only the first agent to flip the row wins (a zero
   affected-row count means it was already claimed). This is the
   same mechanism as `TaskController::claim` (see [§6.4](#64-run-record)).
2. The server returns the script content, the `inputs` object,
   and the resolved (clamped) `capabilities` — the sensitive
   payload travels **only** on this hive/permission-checked claim
   response, never on the cross-hive `run.requested` broadcast
   (see [§12](#12-events)).
3. The agent's Claude Code loads the script and invokes the
   `entry` function. The function receives `inputs` and a
   `superpos` SDK client pre-bound with the agent's identity.
4. The script runs. Throughout, the script (or the agent
   runtime wrapping it) emits `platform.dynamic_workflow.phase.*`
   events via the SDK to record progress. The phase `data` object
   is persisted to `dynamic_workflow_runs.step_states`; the
   cross-hive broadcast carries only `{ run_id, slug, revision_id,
   status, phase_key, occurred_at }` and never the `data` itself
   (§12).
5. On completion, the agent runtime posts
   `POST /api/v1/agents/claims/dynamic_workflow/{run_id}/complete`
   with `outputs` (or `error`). The server transitions the run
   to `completed`/`failed`.

The claim path is *exactly* the existing `TaskController::claim`
shape, ported to dynamic-workflow runs. No new claim primitive.

### 8.3 The superpos SDK inside the script

The script is given a context object as the second argument to
its `entry` function. The context carries the `superpos` client
and (on resume) the latest checkpoint's state as `resumeFrom`
(the highest-`sequence` entry of `checkpoints`, see §8.7):

```js
// workflow.js
export default async function run(inputs, { superpos, resumeFrom }) {
  // resumeFrom — latest checkpoint state, or undefined on the first run
  if (resumeFrom) {
    // skip already-completed work using resumeFrom (see §8.7)
  }

  // Read knowledge
  const ctx = await superpos.knowledge.read('topic:incident-response');

  // Call a service via the proxy (no token in the script)
  const issues = await superpos.proxy.github.list_issues({
    owner: 'superpos', repo: 'superpos-app', labels: 'incident'
  });

  // Append an ordered recovery checkpoint (sequence + phase_key + state)
  await superpos.workflows.dynamic.checkpoint('gathered_context', {
    issues_count: issues.length,
  });

  return {
    summary: `Found ${issues.length} matching issues`,
    recommended_action: issues.length > 5 ? 'triage_batch' : 'triage_one'
  };
}
```

The SDK namespace is `superpos.workflows.dynamic` (matching the
existing `superpos.workflows` for static DAGs) and includes:

- `superpos.proxy.X.Y` — service proxy (existing)
- `superpos.knowledge.read/write` — knowledge store (existing)
- `superpos.workflows.run(slug, inputs)` — kick off a static-DAG run from inside a script
- `superpos.workflows.dynamic.checkpoint(phaseKey, state)` — append an ordered recovery checkpoint (the run is resolved from the invocation context; the script never threads a run id). Each call appends `{ sequence, phase_key, checkpointed_at, state }` to `dynamic_workflow_runs.checkpoints`; `resumeFrom` is the highest-`sequence` entry's `state` and carries only state written this way. The runtime also auto-emits phase events after awaits for observability, but those are not recovery boundaries (see §8.7).
- `superpos.workflows.dynamic.phase(event)` — emit a phase event

The agent's Claude Code injects the `superpos` client into the
script's `entry` invocation. The client is *scoped* to the
agent's identity — when the script calls
`superpos.proxy.github.list_issues`, the call is attributed to
the agent, and the policy engine evaluates the agent's
`action_policies` for the `github.read` action.

This is the load-bearing integration: a script can do everything
a static-DAG step can do, but the control flow is *code* (a
`for` loop, an `if` branch) instead of a graph node. The
substrate (credentials, policy, audit) is identical.

### 8.4 Failures and retries

A script can fail in three ways:

1. **Claim failure**: no agent claims the run within the
   claim-timeout window. The run transitions to `failed` with
   `error = "no_agent_claimed"`. Configurable per-run; default
   5 minutes.
2. **Runtime failure**: the script throws or returns an unhandled
   rejection. The agent runtime captures the stack trace and
   posts it as `error`. The run transitions to `failed`.
3. **Policy failure**: the script calls
   `superpos.proxy.X.Y` against an action that requires approval
   and is denied. The SDK raises `ApprovalRequired`; the script
   is expected to handle it (or let it propagate to a `failed`
   run).

Retries are *not* automatic in v1. A failed run can be retried
manually via `POST /registry/dynamic_workflow/{slug}/runs/{run_id}/retry`,
which creates a *new* run record (immutable history) with the
same inputs. The retry may be picked up by a different agent.
This is the same model the static-DAG executor uses today.

### 8.5 ScriptRuntime interface (locked decision)

Superpos does not own a JS engine — the agent's Claude Code is
the runtime. To keep the contract portable across the
agent fleet and across editions, the agent runtime exposes a
narrow `ScriptRuntime` interface that the Superpos server side
talks to:

```
interface ScriptRuntime {
  // Resolve the executor for a given edition + script content.
  // The implementation may swap based on PLATFORM_EDITION.
  resolveExecutor(script: string, declaredCapabilities: Capabilities): Executor

  // Invoke the script as `entry(inputs, { superpos, resumeFrom })`.
  // `resumeFrom` is the latest checkpoint state (highest-sequence;
  //  undefined on first run — see §8.7).
  // Returns when the script returns, throws, or exceeds a limit.
  invoke(executor: Executor, inputs: object, ctx: { superpos: Client, resumeFrom?: object }): Promise<outputs>
}
```

Both editions run scripts on **Node.js** (`node:vm`); they
differ only in *where* the Node runtime lives:

| Edition | Executor | Why |
|---|---|---|
| CE (`PLATFORM_EDITION=ce`) | `node:vm` in an in-process Node 22 runtime co-located with the agent | Single-tenant CE can run scripts in one shared Node runtime alongside the agent — low overhead, fast startup, no per-agent sidecar to operate. **The Node runtime is not present in the app/runtime container today** — the production image is `dunglas/frankenphp:1-php8.3` and only COPYs the *built* frontend assets (`public/build`, `bootstrap/ssr`) out of the `node:22` build stage, not the Node binary; the `dev` target adds only PHP zip/git/unzip. So the CE agent/runtime image must **explicitly install or copy a Node 22 binary** (or CE must run through a sidecar/agent image that bundles Node). This is a hard-gated container test in the DW rollout — see §15. |
| Cloud (`PLATFORM_EDITION=cloud`) | `node:vm` via a sidecar (one runtime process per agent, restarted daily) | Multi-tenant isolation comes from an **OS-level sandbox around the sidecar** (no ambient secrets/network/FS — see [§8.8](#88-trust-boundary-and-sandboxing-locked-decision)), **not** from the per-agent process topology by itself. `node:vm` is defense-in-depth only. The sidecar pays the cold-start cost once per agent-day; per-script invocation reuses the warm process. |

The script is identical in both editions, and so is the engine
(Node `vm` module). The agent runtime's `resolveExecutor()`
picks the *deployment topology* (in-process vs. sidecar); the
rest of the system sees a single `ScriptRuntime` abstraction.
This mirrors the `PLATFORM_EDITION`-driven code paths used
everywhere else in the platform.

**Why not V8 isolates / `ext-v8`?** An earlier draft assumed CE
could use a PHP V8 binding "for free" because FrankenPHP requires
V8. That is incorrect. The production image is
`dunglas/frankenphp:1-php8.3` (`Dockerfile`), and there is **no**
`ext-v8` / `v8js` / `php-v8` installed in the Dockerfile
(`install-php-extensions pdo_pgsql redis pcntl ...`) or required
in `composer.json`. FrankenPHP does not expose a V8 binding to
application PHP. Adding one would mean a custom extension build
plus CI coverage for it, with no isolation benefit over Node. We
therefore standardise on Node for **both** editions; the only
edition difference is process topology. The Cloud sidecar is a
thin Node 22 process that exposes the `ScriptRuntime` interface
over a Unix socket and ships as a new container in the Cloud
docker-compose profile.

Note that `node:vm` is **not** a security sandbox and the per-agent
sidecar topology is **not** by itself the multi-tenant trust
boundary — the boundary is the OS-level sandbox the sidecar runs
inside. See [§8.8](#88-trust-boundary-and-sandboxing-locked-decision)
for the locked trust-boundary contract and its release-gating
escape tests.

### 8.6 Per-revision limits (locked decision)

The runtime enforces `min(declared, platform_ceiling)` for
every field in `payload.capabilities.limits`:

| Field | Declared default | CE ceiling | Cloud ceiling | Enforced how |
|---|---|---|---|---|
| `max_wallclock_ms` | 30 000 | 300 000 | 600 000 | `setTimeout` wrapper around `entry` invocation |
| `max_memory_mb` | 64 | 256 | 512 | Node `--max-old-space-size` (heap) + RSS watchdog |
| `max_await_run_concurrent` | 8 | 64 | 256 | In-memory semaphore keyed by run id |
| `max_checkpoint_bytes` | 65 536 | 1 048 576 | 4 194 304 | Server-side `JSON.stringify` size check |
| `proxy_allowlist` | `[]` (= declared) | unrestricted | unrestricted | Pre-call filter on `superpos.proxy.*` |

The platform ceiling is a per-edition constant in
`config/dynamic_workflow.php`:

```php
return [
    'platform_ceiling' => [
        'ce' => [
            'max_wallclock_ms' => 300_000,
            // ...
        ],
        'cloud' => [
            'max_wallclock_ms' => 600_000,
            // ...
        ],
    ],
];
```

A revision that *under*-declares is fine — it can only
self-cap. A revision that *over*-declares is silently clamped
to the ceiling at dispatch time, and a warning is logged to
`activity_log` so dashboards can show "script asked for 10 GB,
ceiling is 512 MB".

### 8.7 Checkpointing (locked decision)

Crash recovery is **manual and explicit**. The script persists
state at idempotent boundaries via
`superpos.workflows.dynamic.checkpoint(phaseKey, state)`, which
**appends** an entry
`{ sequence, phase_key, checkpointed_at, state }` to the ordered
`dynamic_workflow_runs.checkpoints` array (see
[§6.4](#64-run-record)). On restart the runtime re-injects the
highest-`sequence` entry as `resumeFrom`; the script inspects it
and skips the work it already finished.

Recovery deliberately does **not** use `step_states`: that column
is a per-phase status *map* (mirroring the live
`WorkflowRun.step_states`), so it has no ordering or timestamp and
a re-checkpointed `phase_key` overwrites the previous state —
making "the last checkpoint" ambiguous and lossy. The append-only
`checkpoints` array gives every checkpoint a monotonic `sequence`,
so "resume from the latest checkpoint" is well-defined even when a
script checkpoints the same `phase_key` repeatedly (e.g. inside a
loop). `step_states` continues to track per-phase status for
dashboards only.

**Why not automatic checkpoints after every `await`?** An earlier
draft promised that every resolved `await` was a recovery boundary
and that a crashed run would resume from the last successful
`await`. That is not implementable on the chosen runtime. A
`node:vm` wrapper cannot reconstruct a suspended async function's
lexical / closure state after the process exits, and Claude Code's
workflow runtime only resumes *within the same live session* —
once the process is gone a run starts fresh from `entry(inputs)`
(https://code.claude.com/docs/en/workflows). So "resume from the
last await" would, after a real crash, replay side effects (e.g. a
proxy write that already happened) while `resumeFrom` lacked the
state needed to skip them. True await-level automatic recovery
would require an owned code-transform / durable-execution runtime
that captures every awaited result and replays deterministically —
out of scope for v1, and gated on crash/restart tests before it
could be claimed.

The contract is therefore:

- **Manual checkpoints (the recovery boundary)**: the script calls
  `await superpos.workflows.dynamic.checkpoint(phaseKey, state)`
  after each idempotent unit of work — especially after any
  side-effecting proxy call it does not want to repeat. This is the
  *only* state `resumeFrom` carries. Scripts are responsible for
  placing checkpoints so that re-running from `entry(inputs)` with
  `resumeFrom` skips already-applied effects.
- **Auto phase events (observability only)**: the runtime still
  emits a `platform.dynamic_workflow.phase.*` event after notable
  awaits for progress and dashboards. These are *not* recovery
  boundaries — they record that a phase happened, they do not
  capture resumable lexical state.
- **Resume semantics**: on restart the runtime fetches the
  highest-`sequence` entry from the ordered
  `dynamic_workflow_runs.checkpoints` array (the latest manual
  `checkpoint`), deserialises its `state`, and re-injects it as the
  second `entry` argument:
  `entry(inputs, { superpos, resumeFrom: latestCheckpoint.state })`.
  A run with no manual checkpoints (empty `checkpoints` array)
  restarts from the top.

The resume hook is the contract change vs. Claude Code's default
`entry(inputs, ctx)` shape — the second arg carries
`{ superpos, resumeFrom? }`, and a script that wants to survive a
crash must (a) checkpoint around its side effects and (b) check
`resumeFrom` to skip them on replay. DW-3 ships the SDK update.

### 8.8 Trust boundary and sandboxing (locked decision)

**`node:vm` is not a security sandbox.** This is the single most
important constraint in this document, so it is stated plainly:
the Node.js `vm` module does *not* provide a security boundary for
untrusted code, and the Node maintainers
[explicitly say so](https://nodejs.org/api/vm.html) — *"The `node:vm`
module is not a security mechanism. Do not use it to run untrusted
code."* A script that escapes the `vm` context (via the well-known
`this.constructor.constructor('return process')()` class of
breakouts, prototype reachability, or any future V8 quirk) runs
with the **full authority of the host Node process**: it can read
`process.env`, the filesystem, and open arbitrary sockets, which
would let it read ambient secrets and bypass the Superpos
service-proxy / `action_policies` entirely. Since dynamic-workflow
scripts are **LLM-authored at run time** — and an LLM's output can
be steered by untrusted data flowing in through `inputs`,
knowledge, or proxied responses (prompt injection) — they cannot
be assumed trusted. `node:vm` alone is therefore *resource
governance and namespace hygiene*, never the isolation boundary.

The earlier framing — "Cloud gets multi-tenant isolation from the
per-agent sidecar **process topology**" (§8.5) — was imprecise and
is corrected here: process *topology* alone (one Node process per
agent) is not a trust boundary, because an escaped script inside
that process still sees whatever that process can see. The
boundary must come from what the process is *denied*, not from how
many processes there are. We lock **both** contracts the review
raised, split by edition:

| Edition | Trust model | Boundary mechanism |
|---|---|---|
| **CE** (`PLATFORM_EDITION=ce`, single-tenant, self-hosted) | Scripts are **trusted-equivalent to the operator's own agent**. There is no cross-tenant boundary to defend: the operator owns both the agent and the scripts it runs. `node:vm` is used for ergonomics + the §8.6 resource limits, and is **explicitly not claimed as a security/isolation boundary**. Operators who run third-party / marketplace scripts on CE are documented to treat them with the same trust as any code they install. | Operator trust + §8.6 resource limits. No isolation claim. |
| **Cloud** (`PLATFORM_EDITION=cloud`, multi-tenant) | Scripts are **untrusted**. `node:vm` is defense-in-depth only; the real boundary is an OS-level sandbox around the per-agent sidecar. A `node:vm` escape must yield **no usable authority** — the sidecar holds no ambient secrets and can reach nothing but the brokered Superpos API. | Real OS sandbox (see required properties below) + `node:vm` as a second layer. |

**Cloud sidecar — required sandbox properties (hard requirements,
gated before GA):**

1. **No ambient secrets.** The sidecar process environment carries
   **no** service-connection credentials, no `APP_KEY`, no database
   DSN, no GitHub token. Credentials live only behind the Superpos
   proxy on the server side; the script reaches them solely through
   `superpos.proxy.*`, where `action_policies` are evaluated
   server-side and attributed to the agent identity.
2. **No ambient network.** Default-deny egress. The only reachable
   endpoint is the brokered Superpos API (over the sidecar's Unix
   socket / a single allow-listed host). An escaped script that
   opens a raw socket reaches nothing — DNS, metadata endpoints
   (`169.254.169.254`), and the open internet are firewalled off.
3. **No ambient filesystem.** Read-only root FS, a non-root user,
   no host mounts, no access to other tenants' run state. The
   script gets only the `inputs` + `resumeFrom` payload the server
   handed it.
4. **Disposable, per-tenant.** One sidecar per agent process,
   recycled daily (and on any detected anomaly); a tenant's run
   never shares a live process image with another tenant's run.
5. **Hardened runtime.** seccomp/`--no-new-privileges`, dropped
   capabilities, memory/CPU cgroup limits aligned with §8.6.

Because the proxy and `action_policies` are enforced **on the
Superpos server**, not inside the sidecar, the security argument
reduces to one property: *an escaped script inside the Cloud
sidecar gains nothing it could not already do through the brokered
API as that agent.* The OS sandbox is what makes that true; the
`node:vm` layer just raises the cost of getting there.

**Escape / isolation tests are a release gate.** The Cloud
sandbox is not "done" on the strength of this prose. DW-2 / the
Cloud rollout (§15) must ship adversarial tests that *attempt* the
known `node:vm` breakouts and assert that, post-escape, the
process can read no secret env var, touch no credential file, and
reach no network endpoint other than the broker. A failing escape
test blocks the Cloud DW execution path; CE ships without the
multi-tenant claim and is documented accordingly.

## 9. API surface

All routes inherit the registry's existing `/api/v1/registry/...`
prefix. The kind-discriminated routes are:

The kind segment is the literal `dynamic_workflow` (underscore) —
it must equal the `RegistryItem::KINDS` value verbatim, because
the existing `/registry/{kind}` routes validate `{kind}` with an
exact `in_array($kind, RegistryItem::KINDS, true)` check
(`RegistryApiController::index/store/...`; `RegistryService.php:533`).
A hyphenated `/registry/dynamic-workflow` would not match any
registered kind and would 404. There is no hyphen alias.

```
# Read
GET    /registry/dynamic_workflow                       # list (hive-visible + owned private)
GET    /registry/dynamic_workflow/{slug}                # read one
GET    /registry/dynamic_workflow/{slug}/revisions      # list revisions
GET    /registry/dynamic_workflow/{slug}/revisions/{id} # read a specific revision

# Write
POST   /registry/dynamic_workflow                       # create (owner = caller agent)
PATCH  /registry/dynamic_workflow/{slug}                # update name/description/payload
POST   /registry/dynamic_workflow/{slug}/revisions      # publish a new revision
PATCH  /registry/dynamic_workflow/{slug}/deactivate     # pause
DELETE /registry/dynamic_workflow/{slug}                # soft-delete (tombstone + slug-reuse guard)

# Run
POST   /registry/dynamic_workflow/{slug}/runs           # start a run
GET    /registry/dynamic_workflow/{slug}/runs           # list runs (filter by status)
GET    /registry/dynamic_workflow/runs/{run_id}         # read one run (incl. step_states)

# Agent claim (same shape as TaskController::claim)
POST   /api/v1/agents/claims/dynamic_workflow
POST   /api/v1/agents/claims/dynamic_workflow/{run_id}/complete
POST   /api/v1/agents/claims/dynamic_workflow/{run_id}/phase    # phase event
```

**Middleware reality check.** The existing registry routes are
*not* behind a permission middleware. In `routes/api.php` the
group is:

```php
Route::prefix('registry')->middleware([
    'registry.enabled',      // feature gate
    'auth:sanctum-agent',    // agent token auth
    'throttle-agent',        // rate limiting
])->group(function () { ... });
```

There is no `permission:*` / `hive` / `cross-hive` middleware on
registry routes today, and there is no `registry` permission
category in the catalog (see [§11](#11-permissions)). So the new
dynamic-workflow routes do **not** inherit a permission check by
sitting under `/registry` — one must be added explicitly. DW-3
introduces a `CheckAgentPermission` middleware on the
read/write/run routes using the permission slugs decided in §11,
and adds the chosen category to `UpdateAgentPermissionsRequest`
so grants validate and persist.

## 10. SDK

A new namespace `superpos.workflows.dynamic` is added to the
Python and Node SDKs (the shell SDK gets a thin wrapper):

```python
# Python
from superpos.workflows.dynamic import DynamicWorkflowsClient

dwf = superpos.workflows.dynamic

# Authoring
dwf.create(slug="incident-triage", payload={...}, visibility="hive")
dwf.publish_revision(slug="incident-triage", script="...", inputs={...}, ...)

# Running
run = dwf.run(slug="incident-triage", inputs={"severity": "high"})
result = dwf.await_run(run.id, timeout=300)
print(result.outputs)

# Subscription (for the agent runtime)
async for event in dwf.subscribe():
    if event.kind == "run_requested" and event.run.registry_item.slug == "incident-triage":
        await dwf.claim(event.run.id)
        # run the script locally
        await dwf.complete(event.run.id, outputs={...})
```

**Script-side SDK.** The `superpos` client injected into the
script's `entry(inputs, { superpos, resumeFrom? })` (see
[§8.7](#87-checkpointing-locked-decision) for the resume hook)
exposes:

```js
// Inside workflow.js
export default async function run(inputs, ctx) {
  // ctx.superpos — Superpos SDK client, scoped to the calling agent
  // ctx.resumeFrom — last checkpoint, or undefined on first run
  if (ctx.resumeFrom) {
    // skip already-done work
  }

  await ctx.superpos.workflows.dynamic.checkpoint('phase_1', { foo: 'bar' });
  await ctx.superpos.proxy.github.list_issues({ ... });
  await ctx.superpos.knowledge.read('topic:incident-response');
}
```

The Node SDK mirrors the shape. The shell SDK gets
`superpos-workflows-dynamic run <slug> --input key=value`
plus `subscribe` and `complete` subcommands.

## 11. Permissions

**There is no `registry.*` / `registry:*` permission surface
today.** The permission catalog is centralized in
`App\Http\Requests\UpdateAgentPermissionsRequest`
(`PERMISSION_CATALOG`, `STATIC_CATEGORY_ACTIONS`,
`RECOGNIZED_CATEGORIES`), and permissions use a `category:action`
format (colon, not dot — `prepareForValidation()` normalises
`tasks.create` → `tasks:create`). `registry` is **not** in
`RECOGNIZED_CATEGORIES`, so any `registry:...` grant is rejected
with a 422. There is, however, a fully-defined `workflows`
category: `workflows:read|write|run|manage|*`.

**Decision: reuse the existing `workflows:*` category.** Dynamic
workflows are workflows from the user's perspective (§4), the
actions map cleanly, and reuse means zero new catalog entries
and zero new validation rules. Note that hosted agents do **not**
hold the full `workflows:*` today: `HOSTED_AGENT_DEFAULT_PERMISSIONS`
(in `HostedAgentController`) and the
`backfill_hosted_agent_workflows_permissions` migration grant only
`workflows:read` and `workflows:run`. So hosted agents can list and
run dynamic workflows out of the box, but **not** create/update
revisions (`workflows:write`) or cancel/retry/deactivate runs
(`workflows:manage`) — those must be granted explicitly, or DW-3
must extend the default set and add a new backfill if hosted agents
are intended to author/manage dynamic workflows (see §11 touch
point 3). The mapping is:

| Action | Permission | Gates |
|---|---|---|
| List/read items + runs | `workflows:read` | the read routes in §9 |
| Create/update/publish revisions | `workflows:write` | the write routes |
| Start a run | `workflows:run` | `POST .../runs` |
| Cancel/retry/deactivate | `workflows:manage` | run-management routes |

*(Alternative considered: a new `registry:*` category. Rejected
for now — it would require adding `registry` to
`PERMISSION_CATALOG`, `STATIC_CATEGORY_ACTIONS`, and
`RECOGNIZED_CATEGORIES`, plus a new hosted-agent backfill, with
no behavioural benefit over reusing `workflows:*`. If registry
items beyond dynamic workflows ever need their own grantable
surface, revisit then.)*

**Concrete DW-3 touch points** for the chosen `workflows:*`
reuse:

1. **Route middleware** — add `CheckAgentPermission` (the
   existing `app/Http/Middleware/CheckAgentPermission.php`) to the
   dynamic-workflow read/write/run/manage routes with the slugs
   above. The registry group itself stays on `registry.enabled`,
   `auth:sanctum-agent`, `throttle-agent`; the permission check is
   added per-route (or via a nested sub-group) so the existing
   subagent/skill/module routes are unaffected.
2. **`UpdateAgentPermissionsRequest`** — **no change needed**,
   since `workflows:*` is already a recognised category. (If the
   `registry:*` alternative were taken, this is where the new
   category, its actions, and `RECOGNIZED_CATEGORIES` entry would
   be added — plus a regression test asserting unknown categories
   still 422.)
3. **Hosted-agent defaults / backfills** — hosted agents receive
   only `workflows:read` and `workflows:run` by default, not the
   full `workflows:*`. The grant set lives in
   `HostedAgentController::HOSTED_AGENT_DEFAULT_PERMISSIONS`
   (`app/Cloud/Http/Controllers/Api/HostedAgentController.php`) and
   was backfilled onto existing agents by
   `2026_05_26_000001_backfill_hosted_agent_workflows_permissions`
   (which inserts exactly `workflows.read` + `workflows.run`). This
   is enough to **list and run** dynamic workflows. If hosted agents
   are intended to **create/update** revisions (`workflows:write`)
   or **cancel/retry/deactivate** runs (`workflows:manage`), DW-3
   must (a) add those slugs to `HOSTED_AGENT_DEFAULT_PERMISSIONS`
   and (b) ship a new Cloud backfill migration (mirroring the
   2026_05_26 one) to grant them to existing hosted agents. Do not
   assume `write`/`manage` are already present — they are not.
4. **Tests** — assert each dynamic-workflow route returns 403 for
   an agent lacking the relevant `workflows:*` slug and 200/201
   when granted; assert the kind discriminator still rejects
   unknown kinds; if a new category is ever added, assert
   `UpdateAgentPermissionsRequest` accepts the new slugs and still
   rejects unrecognised ones.

**Agent claim endpoint.** The agent's run-claim endpoint stays
gated on the existing `tasks:claim` permission, because claiming
a unit of work is the *action* the agent performs, even though
the resource is a run record rather than a task — consistent with
how the static-workflow claim path is gated.

## 12. Events

**Every topic below is `platform.*`, hence cross-hive (see note).
All payloads are identifiers- and status-only — no `inputs`,
`capabilities`, `outputs`, `error`, `stack`, or arbitrary phase
`data` ever rides any of these broadcasts.** Consumers fetch the
sensitive run state (outputs, error, phase `data`) through the
hive/permission-checked run API (`GET /registry/dynamic_workflow/runs/{run_id}`)
or the claim response (§8.2), exactly as `run.requested` already
requires for `inputs`/`capabilities`.

| Topic | Emitted on | Payload shape (identifiers / status only) |
|---|---|---|
| `platform.dynamic_workflow.run.requested` | `POST /runs` | `{ run_id, slug, revision_id, status }` — no `inputs`/`capabilities` |
| `platform.dynamic_workflow.run.claimed` | Agent claims a run | `{ run_id, slug, revision_id, status, agent_id, claimed_at }` |
| `platform.dynamic_workflow.phase.started` | Script emits `phase('started', ...)` | `{ run_id, slug, revision_id, status, phase_key, occurred_at }` — **no `data`** |
| `platform.dynamic_workflow.phase.completed` | Script emits `phase('completed', ...)` | `{ run_id, slug, revision_id, status, phase_key, occurred_at }` — **no `data`** |
| `platform.dynamic_workflow.phase.failed` | Script emits `phase('failed', ...)` | `{ run_id, slug, revision_id, status, phase_key, occurred_at }` — **no `data`/`error`** |
| `platform.dynamic_workflow.run.completed` | Agent posts `complete` with outputs | `{ run_id, slug, revision_id, status, duration_ms }` — **no `outputs`** |
| `platform.dynamic_workflow.run.failed` | Agent posts `complete` with error | `{ run_id, slug, revision_id, status, duration_ms }` — **no `error`/`stack`** |
| `platform.dynamic_workflow.run.cancelled` | `POST /runs/{id}/cancel` | `{ run_id, slug, revision_id, status, cancelled_by }` — **no free-text `reason`** |

The full phase event shape from §6.5 (including the `data`
object) and the run `outputs`/`error`/`stack` are persisted on
`dynamic_workflow_runs` (`step_states`, `outputs`, error columns)
and are returned **only** by the hive/permission-checked run API,
never on the cross-hive broadcast. The broadcast exists purely so
an apiary-scoped subscriber can decide whether to fetch the
authoritative record over the scoped channel.

The cross-hive prefix `platform.*` is preserved for the
broadcast. The legacy `apiary.*` prefix is also accepted for
backward compatibility (per CLAUDE.md). The existing
`event_subscriptions` table indexes these topics without schema
change.

**ALL `platform.dynamic_workflow.*` lifecycle events carry
identifiers/status only — never `inputs`, `capabilities`,
`outputs`, `error`, `stack`, or arbitrary phase `data` (locked
decision).** This is **not** scoped to `run.requested`: it applies
uniformly to `run.requested`, `run.claimed`, every `phase.*`,
`run.completed`, `run.failed`, and `run.cancelled`. In the live
event bus, `EventBus::publish()` treats **every** `platform.*`
(and `apiary.*`) type as cross-hive: it forces `hive_id = null`
and sets `is_cross_hive = true`
(`app/Services/EventBus.php:52-60,97`), and dispatch then fans the
event out to **apiary-scoped** subscribers across every hive in
the organization, not the originating hive
(`app/Services/EventBus.php:481-487`). There is **no** same-hive
variant of these topics — the `platform.*` prefix is the single
cross-hive code path, so a phase event's `data`, a run's
`outputs`, or a failure `error`/`stack` placed on any of these
payloads would leak workflow state to agents in *other* hives,
not just the originating one. Every broadcast is therefore reduced
to non-sensitive routing identifiers + status (`run_id, slug,
revision_id, status`, plus `phase_key`/actor/timing metadata where
relevant) — exactly what an apiary-scoped subscriber needs to
decide whether to fetch the authoritative record.

The sensitive payload — the `inputs` object and resolved (clamped)
`capabilities`, the phase `data`, the run `outputs`, and any
`error`/`stack` — is returned **only** over hive- and
permission-checked channels: the claim response (§8.2 step 2),
after the atomic `pending → claimed` transition has bound the run
to a single agent in the run's own hive, and the run-read API
(`GET /registry/dynamic_workflow/runs/{run_id}`), gated by
`workflows:read` in the run's hive. Subscribers in the originating
hive read the full state there; subscribers in other hives never
see it at all.

*Rejected alternative:* introducing a new hive-scoped dispatch
topic for these lifecycle events so the full payloads could ride
the broadcast. This was rejected because it forks the event-bus
contract (the live bus has exactly one cross-hive code path, keyed
off the `platform.*`/`apiary.*` prefix) and the claim/run-read
responses already provide hive- and permission-checked channels
for the sensitive payload — there is no second mechanism to
maintain.

## 13. Decisions and remaining open questions

### 13.1 Decisions made during review (locked 2026-06-09)

These are the architecture-level decisions resolved during the
proposal review. The implementation in DW-1+ must conform to
them; the rollout plan (§15) is unblocked as a result.

1. **Script runtime is Node.js in both editions; only the
   process topology is edition-swapped**
   ([§8.5](#85-scriptruntime-interface-locked-decision)).
   Both editions execute scripts with Node's `vm` module. CE runs
   them in an in-process Node 22 runtime co-located with the
   agent; Cloud uses a `node:vm` sidecar per agent process. The Node runtime must be **explicitly
   provided** in the agent/runtime image in both editions — it is
   not present in the app/runtime container today (the production
   image `dunglas/frankenphp:1-php8.3` only COPYs *built* frontend
   assets out of the `node:22` build stage, not the Node binary).
   The CE agent/runtime image must install/copy a Node 22 binary
   (or CE must run through a sidecar/agent image that bundles
   Node), gated by a container test in the rollout (§15). (The
   earlier "V8 isolate via FrankenPHP for free" assumption was
   dropped — the production image ships no `ext-v8`/`v8js` either.)
   A `ScriptRuntime` interface is the only thing the server-side
   sees, so the script payload is identical across editions.

2. **Per-revision declared limits, with a hard platform ceiling**
   ([§8.6](#86-per-revision-limits-locked-decision)). The
   `payload.capabilities.limits` object declares ceilings
   (wallclock, memory, fan-out concurrency, checkpoint size,
   proxy allowlist). The runtime enforces
   `min(declared, platform_ceiling)`. Declarations can only
   self-cap. The ceiling is per-edition in
   `config/dynamic_workflow.php`.

3. **Fan-out is configurable, not unbounded**
   ([§8.6](#86-per-revision-limits-locked-decision)). The
   declared `max_await_run_concurrent` (default 8) is
   enforced by an in-memory semaphore keyed by run id. CE
   ceiling 64, Cloud ceiling 256. Unbounded was rejected —
   one runaway script could starve the runtime.

4. **Manual/explicit checkpointing for crash recovery**
   ([§8.7](#87-checkpointing-locked-decision)). Crash recovery is
   explicit: the script calls
   `superpos.workflows.dynamic.checkpoint(phaseKey, state)` around
   idempotent boundaries, and `resumeFrom` carries only that state.
   The runtime auto-emits phase events after awaits for
   observability, but those are not recovery boundaries — a
   `node:vm` wrapper cannot resume a suspended async function after
   a crash. Checkpoints are appended to an **ordered**
   `dynamic_workflow_runs.checkpoints` array
   (`{ sequence, phase_key, checkpointed_at, state }`), *not* to
   the per-phase `step_states` status map — the latter mirrors the
   live `WorkflowRun.step_states` keyed map and has no ordering, so
   it cannot define "the last checkpoint" and re-checkpointing a
   phase would overwrite recovery state. The resume hook re-injects
   the highest-`sequence` checkpoint as
   `entry(inputs, { resumeFrom })`, so scripts that want to be
   replay-safe must checkpoint their side effects and check
   `resumeFrom`.

5. **Task drives run (two distinct state machines)**
   ([§6.4](#64-run-record),
   [§7.1](#71-task-scoped-attachment)). A DW run triggered
   as a task is driven by that task's lifecycle — claim/run/complete
   endpoints are reused, the task's `output` carries the
   `outputs`, the task's `claimed_by_agent_id` and heartbeat
   machinery are reused unchanged. The `tasks.status` column keeps
   the **live** task machine unchanged
   (`pending → in_progress → completed | failed | cancelled`;
   `Task::STATUSES` has no `claimed`/`running`, and
   `TaskController::claim` flips `pending → in_progress`); the
   finer-grained DW phases (`pending → claimed → running → …`) live
   on a separate `dynamic_workflow_runs.status` column that advances
   in lockstep. `dynamic_workflow_runs` is the canonical run record
   (every execution gets a row, including nested `await_run` and
   static-DAG step invocations that have no task);
   `tasks.dynamic_workflow_run_id` is the optional entry-point
   backref.

6. **`node:vm` is not the trust boundary; the boundary is
   edition-specific** ([§8.8](#88-trust-boundary-and-sandboxing-locked-decision)).
   `node:vm` is explicitly not a security sandbox for the
   LLM-authored (therefore untrusted) scripts, and per-agent
   process topology alone is not multi-tenant isolation. **CE**
   treats scripts as trusted-equivalent to the operator's own
   agent and makes no isolation claim. **Cloud** treats scripts
   as untrusted and runs each sidecar inside a real OS-level
   sandbox — no ambient secrets, default-deny egress except the
   brokered Superpos API, read-only non-root FS, disposable
   per-tenant — with `node:vm` as defense-in-depth only.
   Adversarial escape tests are a release gate for the Cloud
   execution path (§15, DW-2).

7. **ALL `platform.dynamic_workflow.*` lifecycle broadcasts carry
   identifiers/status only; every sensitive field travels on
   hive-checked channels**
   ([§12](#12-events), [§8.2](#82-the-claim-path)). This applies to
   the entire topic family — `run.requested`, `run.claimed`, every
   `phase.*`, `run.completed`, `run.failed`, `run.cancelled` — not
   just `run.requested`. In the live event bus, **every**
   `platform.*` event is cross-hive — `EventBus::publish()` forces
   `hive_id = null` / `is_cross_hive = true`
   (`app/Services/EventBus.php:52-60`) and dispatches to
   apiary-scoped subscribers across all hives
   (`app/Services/EventBus.php:481-487`); there is no same-hive
   variant of these topics. So each broadcast carries only
   `{ run_id, slug, revision_id, status }` plus non-sensitive
   `phase_key`/actor/timing metadata. The sensitive fields — a
   script's `inputs`/resolved `capabilities`, phase `data`, run
   `outputs`, and `error`/`stack` — are returned **only** by the
   hive/permission-checked claim response (after the atomic
   `pending → claimed` transition) and the `workflows:read`-gated
   run-read API (`GET /registry/dynamic_workflow/runs/{run_id}`).
   A new hive-scoped dispatch topic was rejected — it would fork
   the single cross-hive event-bus contract, and the claim/run-read
   responses already provide scoped channels.

### 13.2 Open implementation questions

These can be resolved during DW-1 / DW-2 implementation. They
do not block the design.

1. **Where does the `step_key` mapping live?** A static-DAG
   step of `type = 'dynamic_workflow'` needs to know how to
   emit phase events that look like a normal workflow step.
   Options: (a) a `workflow_step_dynamic_refs` join table that
   pins the step to a registry item, or (b) inline columns on
   `workflows.steps[]`. (a) is cleaner for queries; (b) is
   cheaper for the executor. Lean: (a).

2. **Should the script content live in the payload or be
   externalised?** A 256 KB JSONB payload is fine for the
   99% case, but a script that pulls in helper modules is
   bigger. Decision: keep `script` inline in v1, externalise
   in v2 once we have evidence.

3. **What's the claim-lease duration?** If an agent claims a
   run and then crashes, the run is stuck. Options: (a) lease
   timeout (5 min default, refreshable via heartbeat), (b)
   optimistic GC after N minutes, (c) require a heartbeat
   every 60s or the lease is lost. Lean: (a) with (c) as
   future work.

4. **Can a static-DAG step output template-reference a
   dynamic-workflow run's intermediate state?** E.g. `{{steps.step_3.run.outputs}}`?
   In v1, no — only the final `outputs` are exposed. The
   script can checkpoint intermediate state via
   `superpos.workflows.dynamic.checkpoint`, but a downstream
   static step can't read it. Adding this would require
   templating extensions in the static-DAG executor.

5. **Does the marketplace template `WorkflowTemplate.kind`
   discriminator land in this PR or a follow-up?** The
   marketplace installer needs to know whether to install
   a static-DAG workflow (today's flow) or a dynamic
   workflow (the new registry-item installer). Lean: ship
   the discriminator in this PR; the dynamic template kind
   ships empty (`kind` field exists but no template ships
   for it yet). Templates follow as content.

## 14. Deferred work: the pipeline rename

This proposal deliberately does not rename Superpos's existing
"workflow" concept to "pipeline." That rename is the right
long-term move (the noun collision with Claude Code's Dynamic
Workflows is real, and the static-DAG product reads better as
"pipeline" anyway), but its blast radius is too large to bundle
with this integration.

### 14.1 Touch list for the rename

Estimated scope of a full rename:

- **Internal (refactor-only)**: 5 model files, 5 DB tables, 5+
  controllers, 2 services (`WorkflowExecutionService`,
  `WorkflowScheduleTriggerService`), 4 permission constants,
  Python SDK method names, routes file, route-name helpers,
  service container bindings, config keys, 30+ test files.
- **External (user-visible)**: all Inertia page names, React
  component display names, nav labels, breadcrumb copy, form
  labels, button text, empty states, error messages, marketplace
  category label, documentation, API URL paths, webhook config
  keys, event names (`platform.workflow.*`), telemetry.

### 14.2 Recommended sequencing

1. **Now (this proposal)**: ship dynamic workflows behind a
   `kind` discriminator. No public-facing rename.
2. **Next (its own project, ~2 weeks)**: UI-only soft rename.
   Change user-visible copy to "Pipelines" while keeping all
   internal names (`Workflow` model, `workflows` table, route
   URLs, permission names, event names) unchanged. Touch list
   is bounded: dashboard nav, form labels, React component
   *display* names (not file names), help text, marketplace
   label.
3. **Later (its own project, quarter-long)**: full rename.
   Routes, permissions, events, DB tables, SDK methods. With
   deprecation windows for the old names. The `kind`
   discriminator from step 1 makes this much easier — the
   "static DAG" kind can be renamed to "pipeline" without
   rearchitecting, because the discriminator already exists.

### 14.3 The principle

The rename should not block the dynamic-workflow integration,
and the dynamic-workflow integration should not block the
rename. Decoupling them through the `kind` discriminator is
the lowest-risk path that keeps both options open.

## 15. Rollout phases

The integration is split into 4 sub-PRs, mirroring the
knowledge-wiki-redesign pattern.

### Phase DW-1: kind + payload

- **No migration.** Add `'dynamic_workflow'` to
  `App\Models\RegistryItem::KINDS` (the `kind` column is already
  `string(20)`; see §6.1). No `ALTER TYPE`, no column change.
- `dynamic_workflow` payload validation in the registry service
- Hard-gate test: kind discriminator accepts the new value,
  rejects unknown values; payload shape is validated. The kind
  literal is the **underscore** form `dynamic_workflow` — the
  same string the `/registry/{kind}` route segment must carry
  (§5, §9). Assert `in_array('dynamic_workflow', RegistryItem::KINDS, true)`
  is true and that the hyphenated `'dynamic-workflow'` is **not**
  accepted, so the URL/route layer in DW-2/DW-3 can rely on the
  underscore segment matching exactly.
- *No* API surface yet; tests touch the model/service directly
- ~1 week, 1 PR

### Phase DW-2: runs + claim

- `dynamic_workflow_runs` table + model
- Run lifecycle: `pending → claimed → running → completed | failed`
- `POST /registry/dynamic_workflow/{slug}/runs` endpoint
- `POST /api/v1/agents/claims/dynamic_workflow` endpoint
- Phase event recording (no broadcasting yet — events land in
  the `events` table but no realtime push)
- **Node runtime provisioning** — the agent/runtime image must
  carry a Node 22 binary (install/copy it, or run via a
  sidecar/agent image that bundles Node); the app/runtime
  container does not ship one today (§8.5).
- **Cloud sidecar sandbox** — the per-agent runtime is wrapped in
  the OS-level sandbox from §8.8 (no ambient secrets, default-deny
  egress except the brokered API, read-only non-root FS, disposable
  per-tenant). CE ships without the sandbox and without the
  multi-tenant isolation claim.
- Hard-gate test: claim atomicity, lease timeout, retry semantics;
  **a route test that hits the live `/registry/dynamic_workflow/{slug}/runs`
  and `/api/v1/agents/claims/dynamic_workflow` URLs** (underscore
  kind segment) and asserts they resolve through the existing
  `/registry/{kind}` group — plus a negative case asserting the
  hyphenated `/registry/dynamic-workflow/...` URL 404s (it fails
  the exact `in_array($kind, RegistryItem::KINDS, true)` check),
  so the doc's URL convention is locked by a test;
  **a container test that asserts the agent/runtime image actually
  has a working Node 22 runtime** (e.g. `node --version` succeeds
  inside the image and a trivial `node:vm` script executes) — the
  DW execution path is broken without it.
- **Release-gating escape tests (Cloud)** — adversarial tests that
  run the known `node:vm` breakouts inside the sidecar and assert
  the escaped process can read **no** secret env var, touch **no**
  credential file, and reach **no** network endpoint other than the
  Superpos broker (§8.8). A failing escape test blocks the Cloud DW
  execution path.
- ~1.5 weeks, 1 PR

### Phase DW-3: SDK + events + permissions

- Python + Node + shell SDK namespaces
- `platform.dynamic_workflow.*` event topics
- Permissions: add `CheckAgentPermission` middleware to the
  dynamic-workflow routes using the `workflows:*` slugs (§11). No
  new permission *category* under the chosen reuse approach.
  However, hosted agents currently hold only `workflows:read` and
  `workflows:run` by default (see §11 touch point 3), so read/run
  works out of the box but **authoring (`workflows:write`) and run
  management (`workflows:manage`) are not granted by default**. If
  hosted agents must author/manage dynamic workflows, DW-3 also
  extends `HOSTED_AGENT_DEFAULT_PERMISSIONS` and ships a new Cloud
  backfill migration for those two slugs. (A `registry:*` category
  instead would additionally add catalog entries + its own
  backfill.)
- The `superpos` SDK injected into scripts (so they can call
  `superpos.proxy.X.Y` etc.)
- Hard-gate test: routes 403 without the relevant `workflows:*`
  grant and succeed with it; end-to-end "script runs, emits
  phases, completes" via a test agent. **SDK URL coverage** — a
  test asserts every SDK method (Python/Node/shell) targets the
  underscore `dynamic_workflow` kind segment (no hyphenated
  `dynamic-workflow` URLs leak into the client), since a hyphenated
  path would 404 against the registry kind validation.
- **Cross-hive lifecycle payload test** — assert that the
  `platform.dynamic_workflow.*` events published to the bus carry
  **only** the identifiers/status fields from §12 (`run_id`,
  `slug`, `revision_id`, `status`, `phase_key`, plus non-sensitive
  timing/actor metadata) and **never** `inputs`, `capabilities`,
  `outputs`, `error`, `stack`, or arbitrary phase `data`. Since
  `EventBus::publish()` forces every `platform.*` event cross-hive
  (`hive_id = null`, `is_cross_hive = true`), this test guards the
  apiary-wide-leak invariant for the whole topic family, not just
  `run.requested`.
- ~2 weeks, 1 PR

### Phase DW-4: dashboard + marketplace + static-DAG integration

- Code-editor view in `WorkflowBuilder.jsx`
- Static-DAG step of `type = 'dynamic_workflow'`
- `WorkflowTemplate.kind` discriminator
- Marketplace installer handles the new kind
- Hard-gate test: a static-DAG workflow with a dynamic-workflow
  step runs end-to-end
- ~2 weeks, 1 PR

Total: ~6.5 weeks, 4 PRs, 1 design doc (this one).

## 16. Success criteria

The integration is "done" when:

1. An LLM can write a workflow.js, post it as a `dynamic_workflow`
   in any hive, and have an agent in that hive pick it up and
   run it — without any human in the loop.
2. The run is auditable: every phase transition lands in
   `activity_log` and the script's service-proxy calls land in
   `proxy_log` and `approval_requests` as appropriate.
3. The script can call any Superpos primitive (knowledge,
   proxy, tasks, sub-agents) with the calling agent's
   permissions — and the call is attributed correctly.
4. A static-DAG workflow can include a dynamic-workflow step
   and the step's outputs flow into downstream static steps
   via the existing templating.
5. A marketplace template of `kind = 'dynamic_workflow'` can
   be installed, versioned, and run.
6. The `kind` discriminator is in place; the pipeline rename
   is unblocked.

## 17. Why now

The trigger for this work is the May 28, 2026 release of
Claude Code's Dynamic Workflows (research preview, requires
Claude Code 2.1+). Superpos has an opportunity to be the
*substrate* for this new authoring model before the ecosystem
converges on a different substrate (LangGraph JS, Mastra, etc.).
The 4-week window between this release and the GA drop is the
right time to be the first multi-tenant control plane for
Dynamic Workflows.

The static-DAG product is not threatened by this work — the
two systems target different authoring models and the kind
discriminator keeps them composable. The marketplace, audit
log, and policy engine that Dynamic Workflows *need* are
exactly what Superpos already has.

---

## Appendix A: comparison matrix

| Concern | Static DAG | Dynamic workflow |
|---|---|---|
| Authoring | Human, via builder UI / API | LLM, via JS script |
| Definition format | JSON DAG (named steps, edges) | JS module (default export, `entry`) |
| Storage | `workflows` table + `workflow_versions` + `workflow_runs` | `registry_items` (kind=dynamic_workflow) + `registry_item_revisions` + `dynamic_workflow_runs` |
| Step vocabulary | Fixed: `agent`, `loop`, `fan_out`, `webhook_wait`, `conditional` | Unlimited: any JS |
| Control flow | At definition time (static graph) | At run time (JS loops/branches) |
| Executor | Server-side state machine (`WorkflowExecutionService`) | Agent's Claude Code (local runtime) |
| Versioning | `WorkflowVersion` snapshot per write | `RegistryItemRevision` (per registry primitive) |
| Marketplace | `WorkflowTemplate` (dedicated table) | `WorkflowTemplate.kind = 'dynamic_workflow'` (discriminator) |
| Audit | `activity_log` + `workflow_runs` thread | `activity_log` + `dynamic_workflow_runs.step_states` |
| Policy | Per-step `action_policies` | Per-script declared `capabilities[]` + per-call `action_policies` |
| Credentials | Service proxy (per step) | Service proxy (per SDK call inside script) |
| Replay | Run + `WorkflowVersion` content | Run + `RegistryItemRevision` content hash |

## Appendix B: event flow for a representative run

```
[1] User → POST /registry/dynamic_workflow/incident-triage/runs
    Body: { inputs: { severity: "high" } }
       │
       ▼
[2] WorkflowRunDispatcher.create_run
    - INSERT dynamic_workflow_runs (status='pending')
    - INSERT events (type='platform.dynamic_workflow.run.requested')
       │
       ▼
[3] Agent polls events/claims
    - Sees platform.dynamic_workflow.run.requested
    - POST /api/v1/agents/claims/dynamic_workflow { run_id }
       │
       ▼
[4] Server: atomic claim
    - UPDATE ... SET status='claimed' WHERE id=:run_id AND status='pending'
    - Return { script, inputs, run_id, capabilities, superpos_client }
       │
       ▼
[5] Agent's Claude Code runs the script
    - Script calls superpos.knowledge.read(...)
    - Script calls superpos.proxy.github.list_issues(...)  ← policy evaluated
    - Script calls superpos.workflows.dynamic.phase('started', 'fetch_issues')
    - Script completes
       │
       ▼
[6] Agent: POST /api/v1/agents/claims/dynamic_workflow/{run_id}/complete
    Body: { outputs: { recommended_action: 'triage_batch' } }
       │
       ▼
[7] Server: status='completed', outputs persisted
    - INSERT events (type='platform.dynamic_workflow.run.completed',
        payload={ run_id, slug, revision_id, status, duration_ms })
        ← identifiers/status only; cross-hive, so NO outputs (§12)
    - INSERT activity_log
    - Subscribers see the completion signal and, if authorized,
        fetch outputs via GET /registry/dynamic_workflow/runs/{run_id}
        (workflows:read, run's own hive) — outputs never ride the bus
```

Total round trips for a trivial script: 4. For a script with
N phases: 4 + 2N (each `phase` is an event + an activity_log
entry, batched into a single `complete` call).
