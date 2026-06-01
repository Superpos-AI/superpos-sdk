# Proposal: Registry (Subagents, Skills, Modules as first-class artifacts)

Status: Draft for review
Owner: Taras
Scope: Adds a Registry subsystem with three sibling primitives (Subagent, Skill, Module) and a shared attachment model. Subsumes the in-flight sub-agent runtime-bundle work and extends it to skills and modules.

---

## 1. Problem

Today Superpos models Agents and Tasks well, but the **artifacts that
determine what an agent can actually do at runtime** are only partially
represented:

- **Subagents** — half-modeled. The recent `GET /api/v1/sub-agents/runtime-bundle`
  endpoint pulls definitions for runtime, but the entity itself is thin and
  has no clean attachment story beyond "this agent owns it."
- **Skills** — not modeled at all. They exist only as files inside each agent
  container (`.claude/skills/`). The hive has no visibility, no way to share
  them, no way to pin a skill to a single task.
- **Modules** — not modeled at all. Six are currently baked into the agent
  image (`github-pr`, `superpos-issues`, `superpos-knowledge`,
  `superpos-sdk`, `superpos-workflows`, plus one more). Adding or removing a
  module requires a container rebuild.

Symptoms:

- No shared vocabulary for "things you pin to an agent or task that change
  its capabilities."
- Subagent sync is a one-off mechanism that won't generalize.
- Skills and modules cannot be hive-scoped, audited, or task-overridden.
- The agent image grows monotonically because there's no way to opt out of a
  bundled module at the hive level.

## 2. Goals / Non-goals

**Goals**

- Introduce **Registry** as the single subsystem that owns Subagent, Skill,
  and Module definitions.
- Keep them as **three distinct primitives** — their lifecycles differ enough
  that merging into one polymorphic type would leak abstractions.
- Provide a **shared attachment model**: pin items to a hive, an agent, or a
  task, with deterministic resolution precedence.
- Make Superpos the **source of truth**. Agent runtime pulls; it does not
  push.
- Generalize the existing `sub-agents/runtime-bundle` endpoint into
  `/registry/resolved`, which returns the merged kit for any
  `(agent, task)` pair.

**Non-goals (v1)**

- Semantic versioning / pinning (`my-skill@1.2.0`). Mutable "latest" + audit
  log only. Note: *revision pinning* (pointing an attachment at a specific
  `RegistryItemRevision.id`) **is** in scope — it's the existing contract
  (today's `sub_agent_definition_id` in tasks and workflow snapshots).
  Semver is what's deferred.
- Cross-hive sharing or a marketplace.
- Dependency graphs between registry items.
- A full editing UI. API-first; UI is a separate workstream.

## 3. Naming

"Registry" — not "Inventory" (implies fungible stock) and not "Capabilities"
(already used for agent pool capability tags). The three things being
registered are versioned, addressable, runtime-effecting definitions —
"registry" fits.

## 4. Primitives

Three sibling resources. They share metadata shape and the attachment
mechanism, but stay distinct because their install semantics differ.

| | Subagent | Skill | Module |
|---|---|---|---|
| What it is | Persona / delegate config | Invocable capability | Bundled package (scripts + env + skill) |
| Install cost | None — read into config | Low — write files under `.claude/skills/` | Real — may run pip/npm, set PATH, inject env |
| Side effects | None outside parent session | Agent working directory | Persistent in runtime env |
| Typical size | Single markdown file | Markdown + a few scripts | Medium-to-large |
| Surfaced via | `Agent` tool | `Skill` tool / `/skill-name` | Scripts on PATH + bundled SKILL.md |

## 5. Data model

Shared envelope across all three primitives:

```
RegistryItem
  id               ulid
  hive_id          ulid                    # FK hives.id — every item is owned by exactly one hive
  kind             enum { subagent, skill, module }
  slug             string                  # stable, immutable lookup key; unique within (hive_id, kind);
                                           #   set once at creation, never changes even if display name is
                                           #   updated; used by authoring paths (task creation, workflow
                                           #   snapshot) to resolve bindings — analogous to today's
                                           #   SubAgentDefinition.slug
  name             string                  # human-readable display name; mutable; does NOT participate
                                           #   in binding resolution or uniqueness constraints
  description      text
  visibility       enum { hive, private }  # hive    = any agent in the hive can list / attach
                                           # private = only owner_agent_id can list / attach;
                                           #           additionally constrained at attach time
                                           #           to scope=agent / scope_id=owner_agent_id
                                           #           (see §6 "Private visibility constraint")
                                           #           so the "only owner sees it" contract holds
                                           #           under task/hive scoping too
  owner_agent_id   ulid | null             # null = hive-authored; required (NOT NULL) when
                                           #   visibility = private; when set, must satisfy
                                           #   agents.hive_id = RegistryItem.hive_id
  payload          jsonb                   # kind-specific (see below)
  created_at       timestamp
  updated_at       timestamp               # bumped on every payload change
  is_active        boolean default true     # whether the item is available for resolution;
                                           #   false = invisible to resolution queries and
                                           #   list APIs (unless ?include_inactive=true),
                                           #   but the record is preserved and can be
                                           #   reactivated. Distinct from deleted_at: a
                                           #   deactivated item is "paused" (reversible),
                                           #   a tombstoned item is "retired" (permanent in
                                           #   v1). See "Deactivation semantics" below.
  deleted_at       timestamp | null        # soft delete (tombstone); see §7 "Delete semantics"
                                           #   for resolver / list / attach behavior. Live
                                           #   RegistryAttachment rows continue to resolve
                                           #   tombstoned items so pinned historical work
                                           #   (retry, replay) stays deterministic.

RegistryItemRevision        # audit log, append-only — no deleted_at column;
                            # revisions are never independently deleted in v1
                            # (they tombstone with their parent item via §7)
  id               ulid
  item_id          ulid                    # FK registry_items.id (hive_id inherited via item)
  version          int                     # immutable, monotonic per item_id (1, 2, 3, ...);
                                           #   assigned at revision-create time and never mutated,
                                           #   even on rollback. This is the source of truth for
                                           #   the legacy SubAgentDefinition.version field —
                                           #   see "Per-item revision version" note below.
  payload          jsonb
  message          text         # what changed
  author_agent_id  ulid | null             # if set, must belong to the same hive as the item
  created_at       timestamp

  UNIQUE (item_id, id)                     # required for the composite FK in §6
  UNIQUE (item_id, version)                # monotonic version sequence per item
```

**Per-item revision version.** The `version` column is an integer scoped per
`item_id` and assigned at revision-create time as `MAX(version) + 1` within
the item (starting at `1` for the first revision). It is **immutable** once
written — neither `update`, `rollback`, nor any maintenance job ever mutates
it. This is what gives the runtime-bundle adapter (§7) and the task API
compatibility helpers (§9 "Task API payload compatibility") a stable,
deterministic source for the legacy `sub_agent.version` field, which today
is served by the monotonic `SubAgentDefinition.version` column. ULID order
and `created_at` are explicitly **not** a substitute: they describe
insertion order but neither is the field that current SDK consumers read on
`task.sub_agent.version` or `definitions[].version`, and both would diverge
from the legacy semantics after a rollback (see §9 "Write-path cutover for
SubAgentDefinitionService" — rollback repoints `RegistryItem.payload` at an
older revision **without** creating a new revision, so the `version`
exposed by `latest` after rollback is the older revision's original
`version` integer, exactly matching the legacy `SubAgentDefinition`
rollback semantic).

**Tenancy invariants** (enforced at write time and asserted by integration tests):

- `RegistryItem.hive_id` is **required** and immutable. Every item — including
  hive-authored items where `owner_agent_id IS NULL` — is owned by exactly one
  hive.
- `owner_agent_id`, when set, **must** point to an agent in the same hive
  (`agents.hive_id = RegistryItem.hive_id`). Reassigning an agent across
  hives is not a supported operation; if it ever becomes one, the agent's
  private items go with it or are reset.
- `RegistryItemRevision` has no `hive_id` column — it inherits hive ownership
  from its parent `RegistryItem` via FK. Cross-hive revision reads are
  forbidden at the API layer.
- `RegistryAttachment.scope_id` **must** resolve to an entity in the same hive
  as `RegistryAttachment.item_id`:
  - `scope=hive`     → `hive_id = item.hive_id`
  - `scope=agent`    → `agents.find(scope_id).hive_id = item.hive_id`
  - `scope=task`     → `tasks.find(scope_id).hive_id = item.hive_id`
  This invariant is what enforces "no cross-hive sharing" — there is simply no
  way to attach a foreign-hive item to a local scope.
- **Private-visibility attachment invariant**: when
  `RegistryItem.visibility = 'private'`, every `RegistryAttachment` for that
  item **must** be one of:
  - `scope = 'agent'` AND `scope_id = RegistryItem.owner_agent_id`, or
  - `scope = 'task'` AND `role = 'executor'` AND
    `tasks.find(scope_id).agent_id = RegistryItem.owner_agent_id`
    (the **owner-executor exception**, see §6).

  Any other combination (`scope = 'hive'`, `scope = 'agent'` with a
  different agent, or `scope = 'task'` violating the owner-executor
  exception) is rejected at write time. This is what makes "only
  `owner_agent_id` sees it" hold even though attachments are decoupled
  from the owning agent — by construction no foreign agent can have a
  live private attachment (the executor exception keeps the task on the
  owner agent), so the resolver does not need an extra owner filter at
  read time. Full delete / authoring rules in §6 ("Private visibility
  constraint") and §7 ("Visibility-change guard").
- The unique index is `(hive_id, kind, slug)` (partial: `WHERE deleted_at IS NULL`).
  `name` (display name) has no uniqueness constraint — two items may share a
  display name as long as their slugs differ.
- **Slug-reuse guard**: a `POST /registry/{kind}` that would create an item
  with a slug matching a **tombstoned** item in the same `(hive_id, kind)`
  is rejected with HTTP 409 `error.code = "slug_tombstone_has_live_attachments"`
  **if** any live `RegistryAttachment` still references the tombstoned item.
  Once all attachments to the tombstoned item have been detached (hard-deleted),
  the slug is free for reuse. If the tombstoned item has **no** remaining live
  attachments, creation succeeds normally — the partial unique index permits it
  and there is no collision risk. This invariant closes the "same-scope
  duplicate slug" gap described in the next paragraph.
- List/read APIs scope every query to the caller's hive via the
  `BelongsToHive` trait; there is no admin path that bypasses this in v1.
- **Revision-belongs-to-item invariant**: whenever
  `RegistryAttachment.revision_id IS NOT NULL`, the pinned revision **must**
  belong to the attachment's item — i.e.
  `RegistryItemRevision.item_id == RegistryAttachment.item_id`. Pairing item
  A with a revision row from item B is rejected at write time so resolution
  is never ambiguous. Enforcement is two-layered:
  - **Service / model layer**: `RegistryAttachment` validates on create and
    update that the loaded `RegistryItemRevision`'s `item_id` matches.
    Mismatch returns HTTP 422 with `error.code = "revision_item_mismatch"`.
  - **Database layer**: a composite foreign key
    `(item_id, revision_id) REFERENCES registry_item_revisions(item_id, id)`
    on the attachments table, backed by the
    `UNIQUE (item_id, id)` index on `registry_item_revisions` shown above.
    The composite FK is the standard fix and the preferred enforcement
    mechanism; a CHECK trigger is the fallback if a future schema change
    makes the composite FK impractical.

**Why slug reuse under live attachments is forbidden.** Soft-deleting an
item tombstones it but does **not** detach existing `RegistryAttachment`
rows — live attachments continue to resolve the tombstoned item so pinned
historical work stays deterministic (§7). Meanwhile, the partial unique
index (`WHERE deleted_at IS NULL`) would allow a fresh item with the same
`(hive_id, kind, slug)` to be created. If that fresh item is then attached
at the same scope as the tombstoned item's surviving attachment, the scope
would contain **two** live bindings for the same `(kind, slug)` — one via
the old attachment (pointing at the tombstone) and one via the new
attachment (pointing at the new item). Because the resolver and runtime
install paths are keyed by `(kind, slug)` within a scope (§8), the
resolver can only surface one of them, leaving the other silently
shadowed. This is an undefined-precedence collision that breaks the
determinism guarantee.

The slug-reuse guard (previous bullet) prevents this by construction:
a slug cannot be reissued while any live attachment still reaches the
tombstoned item, so the two-binding collision can never arise. Operators
who want to reclaim a tombstoned slug must first detach all remaining
references (`DELETE /registry/attachments/{id}`) and then create the new
item. This is a deliberate, auditable workflow — not an accident.

Mutable "latest" lives in `RegistryItem.payload`; history lives in
`RegistryItemRevision`. No semver — defer until a concrete need surfaces.

`RegistryItemRevision.id` serves as the immutable identifier for pinning.
This is directly analogous to today's `sub_agent_definition_id` — a concrete,
content-addressed pointer that tasks and workflow snapshots use for
deterministic retry and replay. When an attachment carries a `revision_id`,
the runtime resolves that exact revision instead of reading the mutable
latest from `RegistryItem.payload`.

Kind-specific payload shapes:

```
subagent.payload = {
  frontmatter: { name, description, tools[], model },
                                # frontmatter.name is the display name (matches
                                # RegistryItem.name); the stable lookup key is
                                # RegistryItem.slug on the envelope, not here
  body: string                  # markdown
}

skill.payload = {
  instructions: string,         # SKILL.md body
  files: [{ path, content, mode }]   # optional helper scripts
}

module.payload = {
  manifest: { name, version, env_keys[], scripts[] },
  install:  { steps: [...] },   # idempotent install recipe
  skill:    string | null       # bundled SKILL.md if any
}
```

**Deactivation semantics.** Setting `is_active = false` on a `RegistryItem`
makes the item invisible to resolution queries (`/registry/resolved`) and
default list endpoints (`GET /registry/{kind}`). The record itself is
preserved — all revisions, attachments, and metadata remain intact. The
item can be reactivated at any time by setting `is_active = true`, at which
point it immediately becomes resolvable again. Key distinctions from
`deleted_at`:

- **Deactivation (`is_active = false`)** — reversible; the item is "paused."
  Existing pinned attachments (those carrying a `revision_id`) continue to
  resolve deterministically (pinned replay is unaffected). Unpinned
  ("latest") attachments skip the item during resolution — if a consumer
  depends on the item being resolvable via latest, that binding breaks
  until reactivation. List APIs omit deactivated items by default but
  accept `?include_inactive=true` for admin/audit views.
- **Soft delete (`deleted_at IS NOT NULL`)** — permanent in v1 (no
  un-tombstone path). Existing pinned attachments still resolve (§7), but
  new attachments and new revisions are rejected. The slug is locked until
  all live attachments are detached (slug-reuse guard above).

**Resolver carve-out for pinned attachments.** Pinned attachments (those
carrying a non-null `revision_id`) resolve their target item/revision
regardless of `is_active` state, analogous to the tombstone resolution
behavior in §7. Only unpinned ("latest") resolution skips inactive items.
This ensures that consumers holding a deterministic pin are never broken by
a deactivation — they explicitly opted into a specific revision and that
contract is honoured until the attachment is detached.

The `deactivate` operation on a `RegistryItem` sets `is_active = false`
and is exposed as `PATCH /registry/{kind}/{slug}` with body
`{ "is_active": false }`. Reactivation uses the same endpoint with
`{ "is_active": true }`. Both operations log a revision-less activity
entry (no payload change, so no `RegistryItemRevision` is created).

## 6. Attachment model

One join table covers all three scopes:

```
RegistryAttachment
  id           ulid
  item_id      ulid                 # FK registry_items.id
  revision_id  ulid | null          # null → resolve to latest; set → pin to
                                    #   this exact RegistryItemRevision.
                                    # When non-null, must satisfy
                                    #   RegistryItemRevision.item_id == item_id
                                    # (see "revision-belongs-to-item" invariant
                                    #  in §5). Enforced by a composite FK
                                    #  (item_id, revision_id) →
                                    #  registry_item_revisions(item_id, id),
                                    #  plus a service-layer check that returns
                                    #  HTTP 422 revision_item_mismatch.
  scope        enum { hive, agent, task }
  scope_id     ulid                 # hive_id | agent_id | task_id
                                    # must resolve to entity in item.hive_id
                                    # (see tenancy invariants in §5)
  role         string | null        # optional stable selector for callers that
                                    #   need to pick one attachment out of
                                    #   several sharing the same (scope, kind).
                                    #   The role name `executor` is **reserved
                                    #   globally** for task-scoped subagent
                                    #   attachments: it names the single
                                    #   attachment that backs the legacy
                                    #   `task.sub_agent` field (see §9 "Task
                                    #   API payload compatibility"). Attaching
                                    #   with `role='executor'` is rejected at
                                    #   write time (HTTP 422
                                    #   `executor_role_reserved`) unless both
                                    #   `scope='task'` AND `item.kind='subagent'`.
                                    #   This role reservation lets the
                                    #   at-most-one-per-task invariant be a
                                    #   plain partial unique index on the
                                    #   attachment table alone:
                                    #     UNIQUE (scope_id)
                                    #     WHERE scope='task' AND role='executor'
                                    #   No join to `registry_items.kind` is
                                    #   needed (PostgreSQL partial unique
                                    #   indexes cannot reference columns from
                                    #   joined tables), because the
                                    #   reservation rule guarantees every row
                                    #   matching the predicate is already a
                                    #   `kind=subagent` attachment. Other
                                    #   roles are unconstrained in v1.
  pinned_by    ulid                 # agent_id that attached (must be same hive)
  created_at   timestamp
```

**Resolution precedence at runtime** (highest wins on slug collision within a
kind):

```
task  >  agent  >  hive
```

This lets a task override an agent's default kit without mutating the agent.
Detachment is a hard delete of the attachment row; the item itself is
untouched.

### Private visibility constraint

`visibility=private` means "only `owner_agent_id` can list or attach this
item." Once attachments are decoupled from the owning agent (an item can in
principle be attached at hive, agent, or task scope), that contract is only
well-defined if we also constrain the **shape of allowed attachments** for
private items. The rule is:

- When `RegistryItem.visibility = 'private'`, a new `RegistryAttachment` is
  accepted only if **either**:
  - `scope = 'agent'` AND `scope_id = RegistryItem.owner_agent_id`, **or**
  - `scope = 'task'` AND `role = 'executor'` AND
    `tasks.find(scope_id).agent_id = RegistryItem.owner_agent_id`
    (the **owner-executor exception**, see below).
- Any other combination — `scope = 'hive'`, `scope = 'agent'` with a
  different agent id, `scope = 'task'` without `role = 'executor'`, or
  `scope = 'task'` with `role = 'executor'` but a task owned by a
  different agent — returns HTTP 422 with
  `error.code = "private_item_scope_violation"`.

This is enforced at `POST /registry/attachments` time (and at any other
code path that creates attachments, including the legacy-pin bridge, the
task-producer dual-write, the workflow snapshot's `createStepTask()`
attachment write, and the replay-time attachment copy — see §9).

**Owner-executor exception — rationale.** A private subagent must still
be runnable as the executor of its owner agent's tasks, otherwise
`role=executor` (the single source of truth for "the subagent this task
runs as", §6 attachment model and §9 task-producer cutover) would have
no legal way to pin a private subagent and would silently degrade to a
mutable `latest` resolution chain, breaking deterministic replay. The
exception is deliberately narrow: it permits **only**
`role = 'executor'`, **only** for subagents (`item.kind = 'subagent'`,
already required by the `executor`-role reservation rule on the field
above), and **only** when the task's `agent_id` equals the item's
`owner_agent_id` — i.e. the task is already running as the owner
agent. Under that constraint the attachment is invisible to every
other agent (no foreign agent ever sees the task as its own), so the
resolver-skips-owner-filter argument from the "Load-bearing because"
paragraph below still holds without a per-caller check.

**Replay implication of the exception.** Because the replay path copies
the source task's task-scoped `RegistryAttachment` rows verbatim onto
the child task (see §9 "Replay path: copying registry attachments")
and replay already preserves the original task's `agent_id` (see §11
"Out of scope"), the owner-executor invariant transfers automatically:
the child task has the same `agent_id` as the source, so
`tasks.find(child_task_id).agent_id = item.owner_agent_id` continues
to hold for any private-subagent executor attachment carried across.
Replay determinism is preserved — the pinned `revision_id` rides with
the attachment, the resolver sees an identical task-scoped pin, and
the owner filter is still unnecessary.

Load-bearing because: this attach-time invariant is what lets
`/registry/resolved` skip an owner filter entirely. The resolver does not
need to check "is the caller `item.owner_agent_id`?" — by construction,
every live attachment for a private item is either at the owner agent's
own agent scope or at a task scope whose `task.agent_id` already equals
the owner agent, so the resolver only ever surfaces private items to
their owner. The runtime contract stays simple: "task attachments are
the runtime source of truth, full stop." There is no per-caller filter
on top.

**Re-targeted replay non-goal.** Today replay re-uses the original
task's `agent_id` context, so the owner-executor exception transfers
verbatim (see "Replay implication of the exception" above). If a future
replay path is ever re-targeted to a **different** agent (out of scope
for v1), the re-targeted task would either have to drop the
private-subagent executor attachment (because the new task's `agent_id`
no longer equals `item.owner_agent_id`) or be rejected at re-target
time — call this out as an explicit non-goal, not a bug.

**Rejected alternatives.**
- *Allow arbitrary task-scope private with a resolver-time owner
  filter.* Rejected: `/registry/resolved` would have to return
  different items for different agents claiming the **same** task,
  which breaks the "task attachments are the runtime source of truth"
  invariant the rest of this proposal depends on (Phase 2 sync, replay
  determinism, the runtime-bundle adapter).
- *Ban private items from being task executors outright.* Rejected:
  this would force every private-executor pin to fall back to the
  agent-scoped attachment chain at resolve time, which carries no
  `revision_id` — replay would then resolve the mutable `latest`
  revision instead of the pinned one, silently breaking determinism
  for any private subagent used as a workflow step or fan-out child.
  The narrow owner-executor exception above gives private subagents a
  deterministic executor binding without weakening the resolver's
  "no per-caller filter" guarantee.

## 7. API surface

REST under `/api/v1/registry/`:

```
GET    /registry/{kind}                  list (filter by visibility, owner;
                                              hides tombstoned items unless
                                              ?include_deleted=true — see
                                              "Delete semantics" below)
POST   /registry/{kind}                  create; rejects with HTTP 409
                                              slug_tombstone_has_live_attachments
                                              if slug matches a tombstoned item
                                              in the same (hive_id, kind) that
                                              still has live RegistryAttachment
                                              rows (see "Slug-reuse guard" in §5)
GET    /registry/{kind}/{id}             read (tombstoned items remain
                                              readable by id so admin /
                                              audit / replay paths can
                                              introspect them; deleted_at
                                              is surfaced on the response)
PATCH  /registry/{kind}/{id}             update payload (creates revision;
                                              rejected on tombstoned items
                                              with HTTP 422
                                              registry_item_deleted)
DELETE /registry/{kind}/{id}             soft delete (tombstone) — see
                                              "Delete semantics" below
GET    /registry/{kind}/{id}/revisions   audit log

POST   /registry/attachments             attach (kind+id, scope, scope_id);
                                              rejected on tombstoned target
                                              (HTTP 422 registry_item_deleted
                                              / registry_revision_deleted)
                                              and on private-visibility
                                              scope violation (HTTP 422
                                              private_item_scope_violation)
DELETE /registry/attachments/{id}        detach
GET    /registry/attachments?scope=...   list attachments for a scope

GET    /registry/resolved?agent_id=...&task_id=...
       returns the merged, deduplicated set of items the runtime should load,
       with resolution precedence already applied. When an attachment carries
       a revision_id, the response includes that exact revision's payload
       rather than the item's mutable latest.

       Response envelope:
       {
         "items": [
           {
             kind,
             slug,
             name,
             revision_id,
             payload,
             resolved_from_scope:         "task" | "agent" | "hive",
             resolved_from_attachment_id: ulid,
             deleted_at:                  timestamp | null,
                                          # non-null iff the item (or its
                                          #   pinned revision's parent item)
                                          #   is tombstoned. Live attachments
                                          #   continue to resolve tombstoned
                                          #   items so pinned historical work
                                          #   stays deterministic; the runtime
                                          #   uses this field to warn / log
                                          #   without changing the binding.
                                          # See "Delete semantics" below.
             ...
           },
           ...
         ],
         "agent_context": {
           "agent_memory":    string | null,   # current persona MEMORY document
           "persona_version": int | null       # active persona rollout version
         }
       }
```

Each item in `items[]` carries **per-item provenance**:
`resolved_from_scope` records which scope's attachment won the precedence
contest (`task` > `agent` > `hive`), and `resolved_from_attachment_id` points
at the specific `RegistryAttachment` row that produced it. The server does the
precedence resolution once and bakes the result into the response, so the
runtime never has to re-derive scope from the desired set — it can trust the
provenance field directly when deciding what to install where (see Phase 2 in
§8: task-scoped items go into `/tmp/registry/<task_id>/`, everything else
lives in the shared install root).

**Slug uniqueness in the resolved set.** Within the `items[]` array
returned by `/registry/resolved`, every `(kind, slug)` pair appears **at
most once** — that's what "precedence resolution" means. The slug-reuse
guard in §5 guarantees that a scope can never contain two live bindings
for the same `(kind, slug)`: new attachments cannot reference tombstoned
items (attach-time rejection), and new items cannot reuse a tombstoned
slug while any live attachment still points at the tombstone
(creation-time rejection). Together, these two constraints make the
resolver's "pick highest-precedence scope, one winner per slug"
algorithm well-defined in all cases.

`/registry/resolved` is the hot endpoint — agents call it on startup and on
each task claim. Resolving server-side keeps clients dumb and consistent.

For tasks and workflow snapshots that pre-date this proposal — i.e. rows
that today carry a `sub_agent_definition_id` directly on the task or in
`WorkflowVersion.steps` — `/registry/resolved` does **not** read those
columns. It reads task-scoped `RegistryAttachment` rows. The bridge that
turns legacy pins into task-scoped attachments so the resolver sees them
is specified in §9 ("Compatibility bridge for legacy pins"); the
invariant that follows from that bridge is repeated here:
post-migration, no task / workflow execution path reads
`sub_agent_definitions` (or any legacy pin column) directly — every
runtime read goes through `/registry/resolved`.

The `agent_context` block exists so `/registry/resolved` is a true superset of
the existing `sub-agents/runtime-bundle` contract; see the migration note
below for why this matters.

**Relationship to `sub-agents/runtime-bundle`**: the existing endpoint
currently returns more than sub-agent definitions — it also returns
`agent_memory` (the resolved persona MEMORY document) and `persona_version`
(see `SubAgentApiController::runtimeBundle`). The current top-level response
shape is, literally:

```
{
  "definitions":     [ {id, slug, name, description, model, version,
                        documents, config, allowed_tools, prompt}, ... ],
  "agent_memory":    string | null,
  "persona_version": int | null
}
```

A naive "alias that filters `kind=subagent`" would drop `agent_memory` /
`persona_version` and break the runtime contract.

To preserve compatibility we do **both** of the following:

1. `/registry/resolved` returns persona context in its top-level
   `agent_context` block (shown above), so a single call still replaces the
   N+1 of "list sub-agents + fetch persona/memory" that `runtime-bundle` was
   built to eliminate.
2. The legacy `GET /api/v1/sub-agents/runtime-bundle` endpoint is **kept**
   during migration and reimplemented as a server-side adapter over
   `/registry/resolved`. The adapter is **bit-compatible** with today's
   response — same top-level keys, same nested object shapes, same field
   types — only the underlying storage/source changes. Concretely it:

   - Keeps the top-level field named **`definitions`** (not `sub_agents`).
     The legacy key must not be renamed.
   - Preserves the exact per-definition fields the controller emits today:
     `id`, `slug`, `name`, `description`, `model`, `version`, `documents`,
     `config`, `allowed_tools`, `prompt`. The `slug` field is mapped from
     `RegistryItem.slug` (the stable lookup key), `name` from
     `RegistryItem.name` (the display name), and `version` from
     `RegistryItemRevision.version` (the immutable per-item monotonic
     integer defined in §5). Sourcing `version` from the revision row —
     rather than recomputing it from ULID / `created_at` order — is what
     keeps the adapter bit-compatible across rollback: a rollback repoints
     `RegistryItem.payload` at an older revision without creating a new
     revision (see §9), so `latest.version` after rollback is the older
     revision's original integer, matching the existing
     `SubAgentDefinition.version` rollback semantic.
   - Copies `agent_context.agent_memory` and `agent_context.persona_version`
     into the existing top-level `agent_memory` / `persona_version` fields
     that current clients already read.

   The endpoint stays bit-compatible until every runtime is on the new
   contract; only then is it deprecated and removed.

### Delete semantics

`DELETE /registry/{kind}/{id}` is a **soft delete (tombstone)** that sets
`RegistryItem.deleted_at`. It is explicitly **not** a hard delete in v1
(see §11). The rule set is split across three surfaces — list / authoring,
attach, and resolve — so that pinned historical work keeps resolving
deterministically while new authoring stops referencing the retired item:

- **List / authoring flows hide tombstones by default.**
  - `GET /registry/{kind}` omits items where `deleted_at IS NOT NULL`.
    Passing `?include_deleted=true` surfaces them for admin / audit
    callers; the unique index `(hive_id, kind, slug)` remains partial on
    `WHERE deleted_at IS NULL` so the slug **may** be re-used by a fresh
    item — but only after all live `RegistryAttachment` rows referencing
    the tombstoned item have been detached. See "Slug-reuse guard" in §5
    for the invariant and rationale; `POST /registry/{kind}` enforces it
    at creation time.
  - `GET /registry/{kind}/{id}` still returns tombstoned items by id so
    admin / audit / replay paths can introspect them. The response
    surfaces `deleted_at` so callers can see the tombstone.
  - `PATCH /registry/{kind}/{id}` on a tombstoned item is rejected with
    HTTP 422 `error.code = "registry_item_deleted"`. Tombstoned items
    cannot grow new revisions; restoration is a separate admin path
    (not specified in v1 — the safe action is "create a new item with
    the desired payload").

- **`POST /registry/attachments` against a tombstoned target is rejected.**
  - If `item_id` points at a tombstoned `RegistryItem`, HTTP 422
    `error.code = "registry_item_deleted"`.
  - If `revision_id` is supplied and its parent item is tombstoned
    (revisions tombstone with their parent — there is no independent
    revision-level delete in v1; see the `RegistryItemRevision` struct
    in §5), HTTP 422 `error.code = "registry_revision_deleted"`.

  This is what prevents tombstones from leaking into newly authored
  bindings — operators see the rejection and pick a live item instead.

- **`/registry/resolved` continues to resolve tombstoned items when a
  live attachment points at them.** This is the load-bearing rule for
  determinism. Concretely:
  - If a live `RegistryAttachment` (task / agent / hive scope) references
    a tombstoned `item_id` — or a `(item_id, revision_id)` whose parent
    item is tombstoned — the resolver still returns the item / pinned
    revision in `items[]`, with `deleted_at` populated on the resolved
    entry. The runtime is expected to log a warning (`registry.resolved.
    tombstoned_binding`) but **must not** drop the binding; doing so
    would silently demote a pinned task to "latest from hive default,"
    which is exactly the determinism failure the revision pin exists to
    prevent.
  - The resolver does not invent attachments for tombstoned items.
    Items only ever become tombstone-resolvable when an attachment was
    already created against them while they were live — which, combined
    with the attach-time rejection above, gives the closed system "old
    attachments keep resolving, new attachments cannot reference
    tombstones."

- **Slug reuse is blocked while live attachments reference the tombstone.**
  `POST /registry/{kind}` rejects creation of an item whose
  `(hive_id, kind, slug)` matches a tombstoned item that still has at
  least one live `RegistryAttachment` row (HTTP 409,
  `error.code = "slug_tombstone_has_live_attachments"`). This prevents
  the same-scope duplicate-slug collision described in §5: without this
  guard, a newly created item could be attached at a scope where the
  tombstoned item's surviving attachment already resolves, producing two
  live bindings for the same `(kind, slug)` within one scope — an
  undefined state for the resolver. Detaching all remaining references
  to the tombstoned item (`DELETE /registry/attachments/{id}` for each)
  clears the guard and allows the slug to be reissued. The error
  response includes the list of blocking attachment ids so the operator
  knows exactly what to detach.

- **Replay path is unaffected by deletion.** `TaskReplayService` (and
  the workflow-step task-creation paths covered in §9) re-uses or
  re-materializes the original task's `RegistryAttachment` rows, which
  already pin `item_id` (+ optional `revision_id`). Because
  `/registry/resolved` honors tombstones for live attachments, a replay
  of a task whose pinned subagent has since been retired resolves the
  same revision the original execution used — with `deleted_at`
  surfaced for visibility but the binding itself stable. No special
  replay-time fallback is needed.

- **Rejected alternative — "block delete while any attachment or
  replayable history depends on the item."** This was considered and
  rejected: in practice every completed task pins the subagent it ran
  with, so any item attached to a long-running workflow would become
  un-deletable forever. The cost of refusing deletes scales with the
  size of the task history; the cost of honoring tombstones for live
  attachments is one extra index condition on the resolver query.
  Honoring tombstones is the strictly more workable rule. The
  slug-reuse guard (above) complements this design: it does **not**
  block deletion — only slug **reissue** — and only while at least one
  live attachment still references the tombstone. Once those attachments
  are cleaned up, the slug is free. This keeps the delete path
  unblocked while closing the duplicate-slug collision gap.

### Visibility-change guard

Mutating `RegistryItem.visibility` from `hive` to `private` is gated by
the private-visibility attachment invariant from §5 / §6. If any live
`RegistryAttachment` for the item violates the post-change shape, the
`PATCH /registry/{kind}/{id}` request is rejected with HTTP 422
`error.code = "private_visibility_conflict"`. A valid post-change shape
is one of:

1. `scope = 'agent'` AND `scope_id = item.owner_agent_id` (the standard
   owner-scoped attachment), OR
2. `scope = 'task'` AND `role = 'executor'` AND `task.agent_id =
   item.owner_agent_id` (the owner-executor exception defined in §5/§6 —
   the item remains accessible because the executing agent is itself the
   owner).

Any live attachment that satisfies neither condition is considered in
violation. The error payload lists the offending attachment ids so the
operator can detach them (or re-target them through the owner agent)
before re-attempting the visibility change. Going the other way —
`private` → `hive` — is always safe and has no equivalent guard.

## 8. Runtime sync

Superpos is the source of truth. Agents pull on:

1. **Startup** — full resolve for the agent's scope.
2. **Task claim** — re-resolve including the task scope (in case the task
   pinned overrides).
3. **Explicit refresh signal** — optional, for hot updates without restart.

### Isolation model

Agents can run multiple tasks concurrently (`concurrency_limit`, default 3).
Naively installing and uninstalling items per task claim would cause task B to
tear down items that task A is still using. To avoid this the sync algorithm
operates in two scopes:

- **Agent-scoped installs** (from hive + agent attachments): installed once at
  agent startup into the shared runtime environment. These are stable across
  tasks and are only re-synced on startup or on an explicit refresh signal.
  Because the set of hive/agent attachments changes infrequently, this avoids
  churn during normal task processing.

- **Task-scoped overrides** (from task attachments): installed into per-task
  sandboxed directories (e.g. `/tmp/registry/<task_id>/`). These are
  ephemeral — created when the task is claimed, cleaned up when the task
  completes. They never mutate the shared environment, so concurrent tasks
  cannot interfere with each other. No filesystem locks or reference counting
  are needed.

  **v1 restriction — task scope is file-only**: in v1, only `kind=subagent`
  and `kind=skill` attachments may use `scope=task`. The API rejects
  `POST /registry/attachments` with `scope=task` and `kind=module` (HTTP 422,
  `error.code = "module_task_scope_unsupported"`), and `/registry/resolved`
  will never include a task-scoped module in its `items` array. The reason is
  that modules have shared-state side effects — pip/npm installs, PATH
  mutation, env var injection, and system-prompt / module-doc updates — that
  cannot be made invisible to a single concurrently running task using
  filesystem sandboxing alone. The runtime indirection required to make those
  effects task-local (per-task subprocess with its own PATH/env, dynamically
  re-rendered system prompt per task, separate Python/Node virtualenv per
  task) is real engineering work and is explicitly out of scope for v1.

  Subagents and skills are safe under file-only sandboxing because their
  "install" is a pure file write under a known directory, and the Agent and
  Skill tools read from that directory by path — pointing those reads at
  `/tmp/registry/<task_id>/` for the duration of a task is straightforward.

  Module task-scope is tracked as a v2 follow-up (see Open Questions).

### Lookup contract (overlay semantics)

The runtime is **not** told "task sandbox is the only source"; it is told
"task sandbox overlays the shared root." The lookup order for every file-
backed primitive is a strict ordered overlay:

```
1. /tmp/registry/<task_id>/<kind>/<slug>   # task scope (Phase 2 sandbox)
2. <shared_root>/<kind>/<slug>             # agent + hive scopes (Phase 1)
```

Where `<shared_root>` is the per-kind agent-scoped install directory
(`.claude/subagents/` for subagents, `.claude/skills/` for skills, etc. —
exact paths owned by `superpos-agent-core`).

Read semantics, per primitive:

- **Subagent definitions** — when the Agent tool resolves a subagent by
  slug, it first checks the task sandbox; if absent, it falls through to
  the shared root. A task-scoped attachment for an item with the same slug
  as an agent-scoped item therefore replaces it for that task only; an
  agent-scoped item with no task override remains visible.
- **Skills** — same overlay, applied at skill discovery time (`Skill` tool
  / `/skill-name` resolution). The skill directory listing the runtime
  exposes is the **union** of slugs from the two layers, with the task
  layer winning on slug collision.

Two consequences worth stating explicitly:

- **Non-overridden items are still visible inside a task.** A task that
  pins one skill does not lose access to the agent's other skills; only the
  overridden slug is replaced. Equally, the runtime never reads only the
  shared root for a task that has overrides — that would make the overrides
  invisible.
- **`/registry/resolved` is the source of truth for set membership.** The
  resolved response already lists every item that should be visible at each
  scope (with `resolved_from_scope` provenance per item). The runtime uses
  that list to decide what to write where; filesystem scans (the
  `current` in the Phase 1 diff) are only used to compute install /
  uninstall deltas, never to answer "does this slug exist for this task."
  The overlay above is the read-time view of the same set the resolver
  returned, not an independent filesystem-derived view.

Copy-on-write staging of the full resolved set into the task sandbox was
considered and rejected: it would duplicate every non-overridden file on
each task claim (adding I/O and disk pressure proportional to agent kit
size × concurrency) without changing the observable contract. The ordered
overlay gives the same semantics with O(overrides-only) work at claim
time.

### Sync algorithm

**Phase 1 — Agent startup (agent-scoped)**

```
desired = GET /registry/resolved?agent_id=X          # hive + agent scopes only
current = scan shared install directory for installed items
for item in desired - current:    install  (write files, run module installer)
for item in current - desired:    uninstall (rm files, revert env)
for item in desired ∩ current:    if revision differs → reinstall
```

This phase also runs on explicit refresh signals.

**Phase 2 — Task claim (task-scoped)**

```
desired = GET /registry/resolved?agent_id=X&task_id=Y
task_overrides = [item for item in desired
                  if item.resolved_from_scope == "task"]
if task_overrides is empty:  nothing to do — use agent-scoped items
else:
  sandbox = mkdir /tmp/registry/<task_id>
  for item in task_overrides:    install into sandbox
  # on task completion / failure:
  rm -rf /tmp/registry/<task_id>
```

Precedence has already been resolved server-side, so the runtime simply
trusts `item.resolved_from_scope` rather than walking back through desired
attachments to figure out which scope a name came from. Items with
`resolved_from_scope == "task"` go into the per-task sandbox; everything
else is part of the agent-scoped set installed in Phase 1. At read time
the runtime uses the ordered overlay defined in "Lookup contract" above
(`/tmp/registry/<task_id>/` then shared root) so non-overridden agent /
hive items remain visible inside the task while task overrides win on slug
collision.

Modules need an idempotent installer; skills and subagents are file writes.
The module installer logic already exists in `superpos-agent-core` — we wrap
it with the two-phase diff logic above.

## 9. Migration

- **Subagents**: existing `runtime-bundle` consumer becomes a thin client of
  `/registry/resolved` filtered to `kind=subagent`. Migration imports from the
  existing `sub_agent_definitions` table — **not** from local agent files.
  For each unique `(hive_id, slug)` group, migration creates one
  `RegistryItem` with `kind=subagent`, `visibility=hive`, and
  `RegistryItem.slug` set to the legacy `SubAgentDefinition.slug` value —
  preserving the exact lookup key that authoring paths already use (matching
  the current hive-scoped semantics). **Every** `sub_agent_definitions` row in
  that group — including the currently-active one — becomes a
  `RegistryItemRevision`. The active row additionally seeds the
  corresponding `RegistryItem.payload` and acts as the "latest" pointer.
  This invariant is load-bearing: the compatibility bridge (below) assumes
  that every `sub_agent_definition_id` pinned by a task or workflow step
  maps 1:1 to a `RegistryItemRevision` row. If the active definition were
  only materialized as the `RegistryItem` and not also as a revision, any
  task pinning the active definition's ID would have no revision to resolve
  — breaking deterministic retry. The migration therefore guarantees:
  *one `RegistryItemRevision` per legacy `sub_agent_definitions` row, no
  exceptions.*

  Existing `sub_agent_definition_id` references in `tasks` and
  `WorkflowVersion.steps` must be mapped to the new `RegistryItem` +
  `RegistryItemRevision` IDs via a lookup table, or — preferably — the
  original ULIDs are preserved as the new `RegistryItemRevision` IDs so that
  foreign keys remain valid without a data rewrite. Preserving referential
  integrity for in-flight workflow runs and incomplete tasks is a hard
  requirement.
- **Skills**: import current built-in skills as hive-scoped items, attached
  to the hive by default so behavior is unchanged.
- **Modules**: import the six currently bundled modules as hive-scoped
  items, hive-attached by default.

End state: the agent image ships with **no** baked-in skills or modules —
everything is pulled from the registry. This is the long-term direction;
phased rollout is fine.

### Compatibility bridge for legacy pins

Today, `tasks.sub_agent_definition_id` and the equivalent pins inside
`WorkflowVersion.steps` are the only thing that makes a retry or replay
deterministic — they point at a concrete `sub_agent_definitions` row, not
"latest." The attachment-based resolver does not see those columns. If
migration only preserves or remaps the old IDs and stops there, a migrated
task that gets retried after a definition has been edited will resolve the
**latest** revision via the hive / agent attachment chain instead of the
revision its original execution pinned — silently losing determinism. To
prevent that, migration writes an explicit bridge:

- **Tasks with a legacy pin** — for every `tasks` row where
  `sub_agent_definition_id IS NOT NULL`, migration creates a task-scoped
  `RegistryAttachment` with:
  - `item_id` = the `RegistryItem` imported from that definition's parent,
  - `revision_id` = the `RegistryItemRevision` imported from the exact
    `sub_agent_definitions` row the task pinned (1:1 with the preserved
    ULID — see §9 bullet 1),
  - `scope = task`, `scope_id` = the task's id,
  - `role = executor` (this is the attachment the task-API compat
    helper resolves `task.sub_agent` from — see "Task API payload
    compatibility" below; the legacy pin is by definition the
    task's executor),
  - `pinned_by` = a migration system agent id, recorded in the audit log.

  **Private-item owner-executor check.** When the imported `RegistryItem`
  has `visibility = 'private'`, the bridge writes the attachment only if
  the source task's `agent_id` equals `item.owner_agent_id` (the
  owner-executor exception, §6 "Private visibility constraint"). The
  check holds by construction for legitimate legacy pins — a private
  `sub_agent_definition` could only ever have been pinned by its owner
  agent's own tasks under the pre-registry rules — so this is a
  defensive assertion, not an expected branch. Any mismatch is logged
  as `migration.private_executor_owner_mismatch` against the source
  task and the bridge is skipped for that row (the task will fall
  through to the agent-scoped attachment chain, matching the
  visibility intent); the migration does not abort.

  Materialization happens **at migration time** for all
  non-terminal tasks (status not in `completed`, `failed`, `cancelled`) so
  the resolver is correct the first time a migrated task is polled.

  **Replayable terminal tasks** — completed and failed tasks ARE eligible
  for replay today (`TaskReplayService` copies `sub_agent_definition_id`
  from the original task to the replayed child task). If terminal tasks
  are skipped entirely, a post-migration replay of a pre-migration
  terminal task would find no task-scoped attachment on the source task to
  copy, breaking determinism for the replayed child. To handle this, the
  replay path includes a **replay-time bridge**: when `TaskReplayService`
  creates a child task from a source task that has a legacy
  `sub_agent_definition_id` but **no** task-scoped `RegistryAttachment`,
  it materializes the attachment on-the-fly for both the source task and
  the newly created child task (using the same migration mapping table).
  This avoids the cost of backfilling millions of dead terminal tasks
  while preserving determinism for the small subset that actually get
  replayed. Cancelled tasks remain excluded — they are not replayable.

- **Workflow snapshots with legacy pins** — `WorkflowVersion.steps` is
  immutable per version, so we do **not** rewrite step JSON. Instead,
  whenever the runtime claims a task created from a workflow step that
  carries a legacy `sub_agent_definition_id`, the claim path materializes a
  task-scoped `RegistryAttachment` for that task (same shape as above) using
  the mapping table built during migration.

  Critically, the bridge covers **all** legacy sub-agent pin fields in
  `WorkflowVersion.steps`, not just the primary step agent. Today the
  workflow snapshot system pins both `sub_agent_definition_id` (the step's
  primary agent) and `evaluator_sub_agent_definition_id` (the evaluator
  agent used in generate-evaluate loops — see `Workflow::createVersion()`
  and `WorkflowExecutionService::handleLoopStepCompletion()`). Both fields
  follow the same slug → ID resolution at snapshot time and the same
  fail-open propagation at step-task creation time. However, they are
  materialized at **different points** in the execution lifecycle:

  - `sub_agent_definition_id` → attachment materialized **at claim time**
    on the generator step-task, with `item_id` / `revision_id` resolved
    from the primary definition's migration mapping.
  - `evaluator_sub_agent_definition_id` → attachment materialized **when
    the evaluator child task is created** (inside
    `WorkflowExecutionService::handleLoopStepCompletion()`), NOT on the
    originally claimed generator task.

  The reason for deferred evaluator materialization: in the actual
  execution model, the evaluator pin is consumed only when
  `handleLoopStepCompletion()` spawns a separate evaluator child task
  after the generator completes an iteration. The generator task itself
  never resolves the evaluator definition — it only uses the primary pin.
  Creating the evaluator attachment on the generator task at claim time
  would be semantically incorrect (wrong `scope_id`) and would not
  propagate to the evaluator child task without additional copy logic.
  Instead, when `handleLoopStepCompletion()` calls `createStepTask()` for
  the evaluator, the bridge intercepts the step's
  `evaluator_sub_agent_definition_id`, resolves it via the migration
  mapping table, and creates the task-scoped `RegistryAttachment` on the
  **evaluator child task** with:
  - `item_id` / `revision_id` from the evaluator definition's migration
    mapping,
  - `scope = task`, `scope_id` = the evaluator child task's ID,
  - `role = executor` (on the evaluator child task itself, the
    evaluator pin IS the executor — the child task runs as the
    evaluator subagent),
  - `pinned_by` = the migration system agent.

  For the primary attachment on the generator step-task: `scope = task`,
  `scope_id` = the generator step-task's ID, `role = executor`,
  `pinned_by` = the migration system agent. If the primary and evaluator pins resolve to revisions of
  the **same** `RegistryItem`, both attachments point at that item but
  carry different `revision_id` values (one per pinned version). If they
  resolve to different items, each attachment points at its own item.

  This is a **claim-time materialization** because workflow versions can
  spawn new tasks indefinitely after the migration runs; doing it once at
  migration time would miss every task spawned later from a pre-migration
  workflow version. The mapping table (`legacy_sub_agent_definition_id →
  registry_item_revision_id`) is part of the migration output and is kept
  for the lifetime of any workflow version that still references legacy
  pins.

- **Retry and replay must go through the same path.** Retrying a task does
  not regenerate its attachments; it re-uses them. Replay re-claims the
  task and re-runs Phase 2 sync against the existing task-scoped
  attachment, so it resolves the pinned `revision_id` rather than latest.
  Any code path that creates a child / retry task from a pre-migration
  parent copies the parent's task-scoped registry attachments (with new
  `scope_id` pointing at the child task) so the determinism guarantee
  follows the work. Critically, this path is unaffected by soft delete:
  `/registry/resolved` honors tombstoned items for live attachments
  (see §7 "Delete semantics"), so a replay of a task whose pinned
  subagent / skill / module has since been retired still resolves the
  same `revision_id` the original execution pinned. The resolved entry
  surfaces `deleted_at` so the runtime can log the tombstone, but the
  binding itself does not change. No replay-time fallback or "find a
  live equivalent" logic is needed.

- **Post-migration invariant.** No task or workflow execution path reads
  `sub_agent_definitions` (or any other legacy pin column) directly. All
  runtime reads of subagent / skill / module state go through
  `/registry/resolved`. The legacy `sub_agent_definitions` table is kept
  read-only as a migration artifact until the `runtime-bundle` adapter is
  retired (see §7), at which point it can be dropped along with the
  adapter.

### Write-path cutover for SubAgentDefinitionService

The one-time import (§9 bullet 1) seeds the registry with existing data,
but `SubAgentDefinitionService` continues to accept `create`, `update`,
`rollback`, and `deactivate` mutations against the legacy
`sub_agent_definitions` table. Without redirecting these write paths, the
registry becomes stale after the first post-migration edit. The cutover
proceeds in three ordered phases:

1. **Dual-write phase (immediately after backfill completes).** Each
   mutation in `SubAgentDefinitionService` writes to **both** the legacy
   table and the registry:
   - `create` → inserts a `sub_agent_definitions` row **and** creates a
     new `RegistryItemRevision` under the corresponding `RegistryItem`
     (or creates a new `RegistryItem` if the slug is new). The new
     revision's ID matches the new legacy row's ULID (preserving the 1:1
     invariant from §9).
   - `update` → deactivates the old legacy row, creates a new legacy row,
     **and** creates a new `RegistryItemRevision` linked to the same
     `RegistryItem`. Updates `RegistryItem.payload` to reflect the new
     active state.
   - `rollback` → activates the target legacy row **and** updates
     `RegistryItem.payload` to point at the target
     `RegistryItemRevision`. No new revision is created (the historical
     revision already exists from the original import), and the target
     revision's `version` integer (§5) is **not** mutated. The `version`
     surfaced by `/registry/resolved` and the runtime-bundle adapter
     after rollback is therefore the target revision's original
     `version` — the same number it had when first written. This is the
     same semantic as today's `SubAgentDefinition` rollback, which
     re-activates an older row without renumbering it.
   - `deactivate` → deactivates the legacy row **and** sets
     `is_active = false` on the corresponding `RegistryItem` (see §5
     "Deactivation semantics"). The item becomes invisible to resolution
     queries while preserving the record and allowing reactivation.

   During this phase both stores are consistent. The legacy table remains
   the source-of-truth for any code that has not yet migrated to registry
   reads.

2. **Registry-primary phase (after all read paths use `/registry/resolved`
   and the dual-write has been stable for one release cycle).**
   `SubAgentDefinitionService` mutations switch to writing **only** to
   `RegistryItem` / `RegistryItemRevision`. The legacy table receives no
   further writes and becomes effectively read-only. A background job can
   optionally back-sync registry state to the legacy table for
   observability during the transition, but this is non-authoritative.

3. **Legacy table retirement (after the `runtime-bundle` adapter is
   retired per §7).** The `sub_agent_definitions` table and its dual-write
   code are dropped. `SubAgentDefinitionService` (or its successor) is a
   pure registry client.

   The table MUST NOT be dropped until every direct query against
   `sub_agent_definitions` (or its Eloquent model `SubAgentDefinition`)
   has been replaced with a Registry-backed equivalent. The list below is
   a known inventory at time of writing — a grep for `SubAgentDefinition`
   usages must return zero hits outside of the dual-write service before
   retirement proceeds.

   **Dashboard selector consumers** (read active definitions to populate
   UI dropdowns):

   - **`TaskDashboardController`** (`app/Http/Controllers/Dashboard/TaskDashboardController.php:210-216`) —
     queries active `SubAgentDefinition` rows to populate the sub-agent
     selector on the task creation form.
   - **`WorkflowDashboardController`** (`app/Http/Controllers/Dashboard/WorkflowDashboardController.php:125, 1275-1291`) —
     calls `getActiveSubAgentDefinitions()` to populate the sub-agent
     selector dropdown in the workflow builder.
   - **`WebhookRouteDashboardController`** (`app/Http/Controllers/Dashboard/WebhookRouteDashboardController.php:51-57`) —
     queries active `SubAgentDefinition` rows to populate the sub-agent
     selector on the webhook route form.

   **API controllers** (public endpoints that resolve sub-agents by slug
   or ID):

   - **`SubAgentApiController`** (`app/Http/Controllers/Api/SubAgentApiController.php`) —
     four endpoints read `SubAgentDefinition` directly. They split into
     two migration surfaces:
     - *Active-only selectors:* `show()` and `assembled()` resolve by
       slug with `is_active=true` — these migrate to `RegistryItem`
       filtered by `kind=subagent`, in-scope visibility, `is_active=true`.
     - *Revision-stable fetches:* `showById()` and `assembledById()`
       fetch the exact row by ULID regardless of active state (used when
       an agent re-fetches a pinned definition from a task). These must
       migrate to `RegistryItemRevision` lookup by ID, returning the
       revision even if `is_active=false` on the parent `RegistryItem`.
       Filtering by `is_active=true` here would break the pinned-version
       contract that agents depend on.

   **Authoring UI flows** (dashboard read/write paths for sub-agent
   management):

   - **`SubAgentDashboardController`** (`app/Http/Controllers/Dashboard/SubAgentDashboardController.php`) —
     multiple methods read the legacy table directly. They split into
     three migration surfaces:

     - *Active-with-fallback reads:* `show()` and `export()` query by
       slug ordered by `is_active` desc then `version` desc, falling back
       to the latest inactive version so that deactivated definitions
       don't 404. These migrate to `RegistryItem` lookup by slug with a
       fallback to the latest `RegistryItemRevision` when
       `is_active=false`.
     - *Version-history reads:* `versions()` lists **all** versions for a
       slug regardless of active state (to render the version history
       page). This migrates to listing all `RegistryItemRevision` rows
       for the `RegistryItem` — filtering by `is_active=true` would break
       the version history view. `rollback()` reads a single row by slug
       to validate the rollback target.
     - *Active-only mutation reads:* `update()` and `destroy()` query by
       slug with `is_active=true` to resolve the current active row
       before delegating to `SubAgentDefinitionService`. These migrate to
       `RegistryItem` filtered by `is_active=true`, then delegate to the
       registry-aware service successor.

   **Template validation** (workflow template fork-time checks):

   - **`WorkflowTemplateDashboardController`** (`app/Http/Controllers/Dashboard/WorkflowTemplateDashboardController.php`) —
     `findMissingSubAgentSlugs()` and `stripUnresolvedSubAgentSlugs()`
     check active sub-agent slugs against `SubAgentDefinition` to detect
     and handle missing bindings when forking a template into a hive.

   **Marketplace & template producers** (write paths that create
   `SubAgentDefinition` rows directly, bypassing
   `SubAgentDefinitionService`):

   - **`MarketplaceBundleInstaller`** (`app/Services/Marketplace/MarketplaceBundleInstaller.php:175-211`) —
     **write path.** Reads existing rows to check for duplicates
     (`is_active=true` existence check), then creates new
     `SubAgentDefinition` rows directly via `::create()` during
     marketplace persona install. Because this bypasses
     `SubAgentDefinitionService`, the dual-write bridge does not
     intercept it — the write lands only in the legacy table.
   - **`HiveTemplateApplyEngine`** (`app/Cloud/Services/HiveTemplateApplyEngine.php:1398-1427`) —
     **write path.** Creates `SubAgentDefinition` rows directly via
     `forceFill()->save()` during hive template application. Same bypass
     concern as `MarketplaceBundleInstaller`.

   Both of these producers MUST be migrated to route through either (a)
   `SubAgentDefinitionService` (so they are covered by the dual-write
   bridge) or (b) a registry-aware successor service that writes directly
   to `RegistryItem` / `RegistryItemRevision`. Option (a) is preferred
   for the dual-write phase because it keeps write-path migration
   centralized in one service; option (b) is the target for the
   registry-primary phase. Until one of these is done, any marketplace
   install or template application will create legacy rows with no
   corresponding registry entry, causing the newly created definitions to
   be invisible to `/registry/resolved`.

   **Marketplace & template read-only consumers** (read during install
   preflight and eligibility checks):

   - **`WorkflowDependencyResolver`** (`app/Services/Marketplace/WorkflowDependencyResolver.php:72-148`) —
     reads active definitions for marketplace workflow preflight/install
     (read).
   - **`HiveTemplateEligibility`** (`app/Cloud/Services/HiveTemplateEligibility.php:157-159`) —
     counts `sub_agent_definitions` directly for template eligibility
     checks (read).

   **Migration contract by surface.** The consumers above do not all
   share the same migration target. During the registry-primary phase:

   - *Selector / list views* (dashboard selector consumers, template
     validation, marketplace read-only consumers) migrate to query
     `RegistryItem` filtered by `kind=subagent`, in-scope visibility,
     `is_active=true`.
   - *Revision-stable by-ID fetches* (`SubAgentApiController::showById()`,
     `assembledById()`) migrate to `RegistryItemRevision` lookup by ID,
     returning the row regardless of the parent item's active state.
   - *Version-history and fallback reads*
     (`SubAgentDashboardController::show()`, `export()`, `versions()`)
     migrate to `RegistryItem` + all `RegistryItemRevision` rows for the
     item, without an `is_active=true` filter.
   - *Active-only mutation reads*
     (`SubAgentDashboardController::update()`, `destroy()`) migrate to
     `RegistryItem` filtered by `is_active=true`, then delegate to the
     registry-aware service.
   - *Write-path producers* (`MarketplaceBundleInstaller`,
     `HiveTemplateApplyEngine`) migrate to route through
     `SubAgentDefinitionService` (dual-write phase) or its registry-aware
     successor (registry-primary phase), so that every new definition
     appears in both stores during transition and in the registry alone
     afterward.

   The legacy table has no remaining consumers when all of the above have
   been migrated.

The dual-write phase is gated behind a feature flag
(`registry.subagent_dual_write`) so it can be enabled per-hive during
rollout and disabled instantly if regression is detected. The flag
defaults to `true` once backfill completes successfully for all hives.

### Write-path cutover for task producers

The `SubAgentDefinitionService` cutover above covers mutations to
definitions themselves. A separate set of code paths **create tasks** with
`sub_agent_definition_id` written directly onto the task row. These are
the ordinary task-creation producers — they do not go through
`SubAgentDefinitionService` and are not covered by the bridge logic for
historical tasks or workflow snapshots. If these paths are not cut over,
any task created post-migration through them will have a legacy
`sub_agent_definition_id` but **no** task-scoped `RegistryAttachment`,
causing `/registry/resolved` to miss the task's requested subagent
binding and fall back to the hive/agent attachment chain.

The affected producers are:

1. **`TaskController::store()`** (`app/Http/Controllers/Api/TaskController.php:1523-1537`) —
   resolves `sub_agent_definition_slug` → `sub_agent_definition_id` via
   a direct `SubAgentDefinition` query against the target hive.

2. **`TaskDashboardController::store()`** (`app/Http/Controllers/Dashboard/TaskDashboardController.php:423-428`) —
   accepts a `sub_agent_definition_id` from the dashboard form and writes
   it directly onto the task row.

3. **`WebhookRouteEvaluator`** (`app/Services/WebhookRouteEvaluator.php:243-246`) —
   copies a pre-resolved `sub_agent_definition_id` from the webhook route
   configuration onto each spawned task.

4. **`FanOutService`** (`app/Services/FanOutService.php:142-168`) —
   resolves `sub_agent_definition_slug` per fan-out child (batch-resolved
   in a single query), or accepts a literal `sub_agent_definition_id`.

5. **`TaskController::storeFanOut()`** (`app/Http/Controllers/Api/TaskController.php:1293-1350`) —
   resolves `sub_agent_definition_slug` → `sub_agent_definition_id` via
   a direct `SubAgentDefinition` query against the target hive and writes
   `sub_agent_definition_id` onto the parent fan-out task row
   (lines 1331-1340). This is the same slug-resolution pattern as
   `TaskController::store()` but applied to the fan-out parent path.

These paths must be cut over in three ordered phases that mirror the
`SubAgentDefinitionService` cutover:

1. **Dual-write phase (runs concurrently with the SubAgentDefinitionService
   dual-write).** Each task-creation path that today writes
   `sub_agent_definition_id` onto a task row is updated to **also** create
   a task-scoped `RegistryAttachment` in the same database transaction:

   - Resolve the slug (or accept the literal ID) against the registry
     migration mapping table to obtain `item_id` and `revision_id`.
     Concretely: lookup `RegistryItem` by `(hive_id, kind=subagent, slug)`,
     then resolve the active `RegistryItemRevision` (whose ULID matches
     the legacy `sub_agent_definition_id` per the 1:1 invariant from §9).
   - Create a `RegistryAttachment` with `scope=task`,
     `scope_id=<new task id>`, `item_id`, `revision_id`,
     `role=executor` (the legacy `sub_agent_definition_id` IS the
     task's executor binding — see §6 attachment model and the
     "Task API payload compatibility" subsection below — so the
     attachment that replaces it gets the same role), and
     `pinned_by=<creating agent id>`.
   - Continue writing `sub_agent_definition_id` on the task row so that
     any code still reading the legacy column sees the correct value
     during the transition.
   - If the resolved `RegistryItem` has `visibility = 'private'`, the
     attachment write enforces the owner-executor exception from §6:
     the new task's `agent_id` must equal `item.owner_agent_id`.
     Violations return HTTP 422 `private_item_scope_violation` from
     the task-creation endpoint, surfacing the misconfiguration to
     the caller at authoring time rather than at claim time. This is
     symmetric with the new task-creation contract: a private
     subagent can only be the executor of its owner agent's tasks.

   Fail-open semantics are preserved: if the slug does not resolve in
   the registry (just as it might not resolve in the legacy table today),
   neither the legacy column nor the attachment is written, and the task
   is created without a subagent binding. The existing activity-log
   warnings (`task.sub_agent_slug_unresolved`,
   `task.fanout_sub_agent_slug_unresolved`) remain unchanged.

   For `TaskDashboardController` and `WebhookRouteEvaluator`, which
   accept a pre-resolved `sub_agent_definition_id` rather than a slug:
   the dual-write path looks up the corresponding `RegistryItemRevision`
   by its ULID (which equals the legacy ID) and creates the attachment
   from that. If the ULID lookup fails (e.g. the ID predates migration
   and was not mapped), the attachment is skipped and the legacy column
   alone is written — the existing bridge for historical tasks will
   handle it at claim time.

2. **Registry-primary phase (after all read paths use
   `/registry/resolved`).** Task-creation paths stop writing
   `sub_agent_definition_id` and write **only** the task-scoped
   `RegistryAttachment`. Slug resolution switches from querying
   `SubAgentDefinition` to querying `RegistryItem` by
   `(hive_id, kind=subagent, slug)` and reading the latest
   `RegistryItemRevision`. The legacy column is left NULL on new tasks.

3. **Legacy column retirement (after all consumers — including the
   compatibility bridge, replay service, and runtime-bundle adapter —
   have been confirmed to never read `tasks.sub_agent_definition_id`
   directly).** The column is dropped from the `tasks` table schema.
   Task-creation paths are now pure registry clients.

This cutover is gated behind the same `registry.subagent_dual_write`
feature flag used for the `SubAgentDefinitionService` cutover, so both
write paths transition in lockstep. When the flag is disabled, task
producers fall back to legacy-only writes (no attachment created).

### Write-path cutover for workflow snapshots and step tasks

The task-producer cutover above covers ad-hoc task creation. Workflow
snapshots are a second, distinct producer: `Workflow::snapshotVersion()`
freezes the chosen subagent revision into `WorkflowVersion.steps` JSON,
and `WorkflowExecutionService` then propagates that pin onto every
step-task it creates from that snapshot. Both paths today resolve and
store the legacy `sub_agent_definition_id`. If they are not cut over,
workflows published **after** the registry-primary switch will still
embed legacy IDs — pointing at rows the dual-write phase has stopped
maintaining — and will either dereference stale state or write NULL
onto step tasks (`WorkflowExecutionService::createStepTask()` fail-opens
to NULL when `SubAgentDefinition::exists()` returns false).

The cutover is anchored on a single new field rather than a parallel
column rename, to keep the snapshot format forward-compatible with
registry-only resolution:

- **New snapshot fields.** Each step in `WorkflowVersion.steps` gains
  `sub_agent_registry_revision_id` (and
  `evaluator_sub_agent_registry_revision_id` for loop steps) alongside
  the existing `sub_agent_definition_id` /
  `evaluator_sub_agent_definition_id`. The new fields hold the
  `RegistryItemRevision.id` resolved at snapshot time. Because §9
  preserves the legacy ULID as the new revision ID, in the dual-write
  phase the two columns carry the same value; the separation exists so
  later phases can drop the legacy fields without rewriting the
  snapshot schema.

- **Ingress hardening / carry-forward extension.** The existing
  workflow ingress today strips caller-supplied
  `sub_agent_definition_id` / `evaluator_sub_agent_definition_id` from
  inbound request payloads and then re-injects trusted values from the
  stored workflow on unchanged slugless steps, so callers cannot bypass
  slug resolution by posting arbitrary definition IDs and unchanged
  steps preserve their server-resolved pins across edits. The five
  ingress paths that implement (or should implement) this are:

  - `app/Http/Requests/StoreWorkflowRequest.php` (lines 19-30) — strip
    on API create. **Current asymmetry:** unsets only
    `sub_agent_definition_id`; does not strip
    `evaluator_sub_agent_definition_id`.
  - `app/Http/Requests/UpdateWorkflowRequest.php` (lines 19-30) —
    strip on API update. **Current asymmetry:** same gap — strips only
    the primary, not the evaluator.
  - `app/Http/Controllers/Dashboard/WorkflowDashboardController.php`
    (lines 152-158) — strip on dashboard create. Already strips both
    `sub_agent_definition_id` and
    `evaluator_sub_agent_definition_id`.
  - `app/Http/Controllers/Api/WorkflowController.php` (lines 210-253) —
    carry-forward for unchanged slugless steps on the API update path.
    **Current asymmetry:** carries forward only
    `sub_agent_definition_id`; the evaluator pin is not preserved
    across edits.
  - `app/Http/Controllers/Dashboard/WorkflowDashboardController.php`
    (lines 295-385) — strip + carry-forward for unchanged slugless
    steps on the dashboard update path. Already handles both the
    primary and the evaluator (strip at 295-302, carry-forward at
    351-388).

  **Current evaluator gap — must be closed as part of the cutover.**
  Three of those five paths today treat the evaluator field as
  unguarded: `StoreWorkflowRequest` and `UpdateWorkflowRequest` leave
  caller-supplied `evaluator_sub_agent_definition_id` intact through
  validation, and `WorkflowController` never carries it forward on
  unchanged steps so a slugless evaluator pin silently drops on any
  API edit. The dashboard paths already do the right thing on both
  fields; the cutover is the right moment to close the API-side gap.
  Concretely, before any new-field work begins, the dual-write change
  also: (a) extends the `prepareForValidation()` strip in
  `StoreWorkflowRequest` and `UpdateWorkflowRequest` to unset
  `evaluator_sub_agent_definition_id` alongside the primary, and (b)
  adds an evaluator carry-forward loop in `WorkflowController` mirroring
  the primary one at 234-256 (and the dashboard's at 380-386). Without
  this, extending only the new registry fields would lock the existing
  asymmetry in place.

  With that gap closed, every one of those five paths is extended in
  the dual-write phase to apply the same strip-and-carry-forward
  treatment to the two new fields:

  - **Strip on ingress.**
    `sub_agent_registry_revision_id` and
    `evaluator_sub_agent_registry_revision_id` are removed from the
    inbound payload before validation in `StoreWorkflowRequest`,
    `UpdateWorkflowRequest`, and the dashboard create path in
    `WorkflowDashboardController` (152-158) — all three strip sites
    that today guard the legacy fields. Callers cannot post arbitrary
    `RegistryItemRevision` IDs and have them land in a snapshot — the
    same defense that today blocks caller-supplied
    `sub_agent_definition_id`. Treating only the legacy field as
    sensitive would leave the registry pin as an unguarded back-door
    to the same outcome.
  - **Re-inject trusted values from server resolution.** When the
    snapshot writer (`Workflow::snapshotVersion()`) resolves a step's
    slug against the registry in the dual-write phase, it writes
    **both** the legacy `sub_agent_definition_id` and the new
    `sub_agent_registry_revision_id` (and the evaluator pair) from
    its own resolution, ignoring anything that might have leaked
    through ingress.
  - **Carry-forward on unchanged slugless steps.** Both update paths
    — `WorkflowController` (API, 210-253) and
    `WorkflowDashboardController` (dashboard, 295-385) — carry
    forward the new fields from the stored workflow onto unchanged
    slugless steps. After the evaluator gap above is closed, each
    controller copies all four pins —
    `sub_agent_definition_id`, `evaluator_sub_agent_definition_id`,
    `sub_agent_registry_revision_id`, and
    `evaluator_sub_agent_registry_revision_id` — in the same loop,
    from the same stored step. This preserves the pinned registry
    revision (and the legacy pin, and both evaluator pins) across
    edits for unchanged steps, so a workflow edited in the
    dual-write phase does not silently drift to "latest" on steps
    the operator did not touch.

  In the registry-primary phase the legacy strip/carry-forward
  becomes a no-op (the legacy fields are no longer written) but the
  registry-field strip/carry-forward continues to run. In the
  legacy-field retirement phase the legacy clauses are removed from
  all five ingress paths in the same release that drops the legacy
  snapshot fields; the registry-field clauses remain as the sole
  ingress guard going forward.

The phasing mirrors the task-producer cutover and runs under the same
`registry.subagent_dual_write` flag:

  **Task-side storage.** The new
  `sub_agent_registry_revision_id` /
  `evaluator_sub_agent_registry_revision_id` fields live on the
  **snapshot** (`WorkflowVersion.steps` JSON) only. They are
  deliberately **not** mirrored onto the `tasks` row: no new
  `tasks.sub_agent_registry_revision_id` column is added, and no
  parallel payload key is introduced. The single task-side source of
  truth for a step task's pinned subagent revision is the task-scoped
  `RegistryAttachment` created in the same transaction as the step
  task itself (see "Dual-write phase" below). Executors and the
  task-API compat layer read the pin via
  `task.registryAttachments` → filter `kind=subagent` →
  `role=executor` (see §6 attachment model and the §9 "Task API
  payload compatibility" subsection), never from a column on `tasks`.
  This keeps the schema change contained to the snapshot side and
  consistent with the attachment-centric direction of the rest of the
  proposal: the legacy `tasks.sub_agent_definition_id` column is on a
  retirement path (see "Write-path cutover for task producers"), and
  introducing a sibling registry column would only create a second
  column to retire later.

1. **Dual-write phase.** `Workflow::snapshotVersion()` resolves slugs
   against the registry (`RegistryItem` by `(hive_id, kind=subagent,
   slug)` → active `RegistryItemRevision`) **in addition to** the
   existing `SubAgentDefinition` lookup, and writes both
   `sub_agent_definition_id` and `sub_agent_registry_revision_id` (same
   for the evaluator pair) into the snapshot.
   `WorkflowExecutionService::createStepTask()` continues to write
   `sub_agent_definition_id` onto the new step task row (the legacy
   column, in lockstep with the task-producer dual-write) and, in the
   same transaction, reads the new
   `sub_agent_registry_revision_id` from the snapshot step and
   creates a task-scoped `RegistryAttachment` from it
   (`scope=task`, `scope_id=<step task id>`,
   `item_id`/`revision_id` from the registry pin,
   `role=executor`, `pinned_by=<workflow run owner agent>`). It does
   **not** copy the registry revision ID onto the step task row —
   the attachment is the sole task-side carrier. The evaluator
   attachment is materialized at evaluator-child creation time
   inside `handleLoopStepCompletion()` (also with
   `role=executor`, since the evaluator child is itself a distinct
   task whose own executor pin comes from
   `evaluator_sub_agent_registry_revision_id`) — same split as the
   migration bridge in §9, but driven by the new
   `evaluator_sub_agent_registry_revision_id` field instead of the
   bridge's mapping table.

   For private-visibility executors, both `createStepTask()` and the
   evaluator-child materialization in `handleLoopStepCompletion()`
   enforce the owner-executor exception from §6 — the step task's (or
   evaluator child's) `agent_id` must equal `item.owner_agent_id`. The
   check is also pulled forward into `snapshotVersion()` itself as an
   authoring-time gate: if the workflow snapshot would pin a private
   subagent revision whose `owner_agent_id` does not match the
   resolved step `agent_id`, snapshot publication is rejected with
   HTTP 422 `private_item_scope_violation`, so the failure surfaces
   to the workflow author rather than to a runtime claim that bombs
   mid-execution. This applies symmetrically to the evaluator pin.

2. **Registry-primary phase.** `snapshotVersion()` stops resolving via
   `SubAgentDefinition` and stops writing the legacy fields; new
   snapshots carry only `sub_agent_registry_revision_id` /
   `evaluator_sub_agent_registry_revision_id`. `createStepTask()` reads
   the new snapshot field, creates the task-scoped
   `RegistryAttachment` (still the only task-side carrier), and stops
   writing `sub_agent_definition_id` onto the step task row (the
   `SubAgentDefinition::exists()` fail-open check is replaced with a
   `RegistryItemRevision::exists()` check against the snapshot field).
   Snapshots that predate this phase still carry the legacy fields and
   are handled by the §9 claim-time compatibility bridge — both paths
   coexist for as long as any pre-migration `WorkflowVersion` is still
   referenced by an active workflow.

3. **Legacy field retirement.** Once no live `WorkflowVersion` row
   carries the legacy `sub_agent_definition_id` /
   `evaluator_sub_agent_definition_id` fields (verified by a one-shot
   audit query), the bridge and the legacy fields are removed from the
   snapshot schema in the same release that drops
   `tasks.sub_agent_definition_id`.

This keeps newly published workflows on the registry from the moment the
flag flips, while existing snapshots continue resolving through the
bridge until they age out.

### Replay path: copying registry attachments

§9 ("Compatibility bridge for legacy pins") covers replays whose **source
task predates migration** — the replay-time bridge materializes a
task-scoped `RegistryAttachment` from the legacy
`sub_agent_definition_id` on demand. That mechanism is insufficient for
tasks created **after** the task-producer cutover: those tasks carry no
`sub_agent_definition_id` (the legacy column is left NULL per the
registry-primary phase), so `TaskReplayService::replay()` — which today
only copies `sub_agent_definition_id` from the source task onto the
replayed child — would produce a child task with no subagent binding
and fall through to the hive/agent attachment chain, silently dropping
the pinned revision.

The replay path therefore has its own cutover, running in lockstep with
the task-producer cutover under the same `registry.subagent_dual_write`
flag:

1. **Dual-write phase.** `TaskReplayService::replay()` continues to copy
   `sub_agent_definition_id` onto the child task and **also** copies
   every task-scoped `RegistryAttachment` row from the source task to
   the new child (cloning each row with a new `id`, `scope=task`,
   `scope_id=<child task id>`, same `item_id` / `revision_id` /
   `role` / `pinned_by`). The copy happens inside the existing
   `DB::transaction()` in `TaskReplayService::replay()` so the child
   task and its attachments are atomic with the dependency-row rehoming
   already in that transaction.

2. **Registry-primary phase.** `TaskReplayService::replay()` stops
   copying `sub_agent_definition_id` (it is NULL on registry-primary
   tasks anyway) and relies solely on the attachment copy. The
   pre-migration replay-time bridge from §9 remains in place to handle
   source tasks whose only binding is still the legacy column — the
   two code paths are mutually exclusive on a per-task basis (attachment
   present → copy attachment; attachment absent + legacy ID present →
   materialize attachment from bridge).

3. **Retirement.** Once `tasks.sub_agent_definition_id` is dropped (§9
   post-migration invariant + the legacy column retirement step in
   the task-producer cutover), the bridge branch is removed and replay
   is a pure attachment copy.

The replayed child's `agent_id` context is unchanged (today's behavior
already preserves the original task's `agent_id` — see §11 "Out of
scope"), so any agent-scoped or private attachments on the source's
agent that were resolved into the source's task scope continue to
resolve identically for the replay.

### Task API payload compatibility

The agent-facing task API today serializes a `sub_agent` block on poll,
claim, show, cross-hive, and replay responses (`TaskController::
formatSubAgentRef()` / `formatSubAgentFull()`,
`CrossHiveTaskController::formatSubAgentRef()`,
`TaskReplayController::formatSubAgentRef()`). All five helpers gate on
`task.sub_agent_definition_id` and read the `subAgentDefinition` Eloquent
relation to build the payload. Once the task-producer cutover stops
writing `sub_agent_definition_id` on new tasks, those helpers would
return `null` for every registry-primary task, silently dropping the
`sub_agent` field from existing agent SDK responses — a breaking change
for any poll/claim consumer that reads `task.sub_agent.slug` or
`task.sub_agent.prompt`.

To preserve the contract, the helpers are rewritten to resolve from the
task-scoped `RegistryAttachment` (with `kind=subagent` AND
`role=executor`) and materialize the same shape from the registry
rather than from `SubAgentDefinition`. The shared attachment model
allows multiple task-scoped `kind=subagent` attachments on a single
task (the workflow step task plus, for loop steps, the evaluator
child's attachment, plus any caller- or operator-attached extras), so a
naive "the task-scoped subagent attachment" filter is ambiguous.
`role=executor` is the stable selector — its at-most-one-per-task
invariant (see §6 attachment model) guarantees the
`task.sub_agent` block resolves deterministically to the single
attachment that represents "the subagent this task runs as." Any
additional `kind=subagent` attachments on the same task (other roles,
or no role) are not surfaced through the singular `task.sub_agent`
field; they remain reachable through `/registry/resolved` and the
generic attachments listing. The migration is again three-phased and
flag-gated:

1. **Dual-source phase (runs with the task-producer dual-write).** Each
   helper first looks for a task-scoped `RegistryAttachment` with
   `kind=subagent` and `role=executor` on the task; if found, the
   payload is built from the attached `RegistryItem` +
   `RegistryItemRevision` (slug from the item,
   `version` from `RegistryItemRevision.version` — the immutable per-item
   monotonic integer defined in §5, **not** a recomputation from ULID or
   `created_at` order — prompt/config/allowed_tools from the revision
   payload). The same column also sources `version` after rollback, where
   `RegistryItem.payload` is repointed at an older revision without
   creating a new one (see §9 "Write-path cutover for
   SubAgentDefinitionService"). If absent, it falls back to the existing
   `sub_agent_definition_id` + `subAgentDefinition` path. In the
   dual-write phase both sources are present and the registry source
   wins — this validates the new code path on production traffic
   before the legacy column goes NULL.

2. **Registry-primary phase.** The fallback to `subAgentDefinition` is
   retained for any task that still has only the legacy column (pre-
   cutover tasks that have not been migrated by the §9 bridge yet),
   but new tasks are served entirely from the registry source. The
   eager-load on the poll query (`->with('subAgentDefinition')`) is
   replaced with an eager-load of the task's registry attachments
   (`->with(['registryAttachments.item', 'registryAttachments.revision'])`)
   to keep the response a single-query operation.

3. **Legacy fallback retirement.** When `tasks.sub_agent_definition_id`
   is dropped, the `subAgentDefinition` relation and the fallback branch
   are removed. The wire format of the `sub_agent` block is unchanged
   end-to-end (same keys: `id`, `slug`, `version`, and for claim/full:
   `name`, `model`, `prompt`, `config`, `allowed_tools`) — `id` is
   sourced from the `RegistryItemRevision.id` (which equals the legacy
   `sub_agent_definition_id` for pre-cutover tasks per the §9 ULID
   preservation invariant), so existing SDK consumers that key off
   `task.sub_agent.id` keep working without an SDK update. The
   `subAgentService->assemble()` call used by `formatSubAgentFull()`
   is replaced with the equivalent prompt assembly over the revision
   payload — same input shape, same output.

This compatibility layer is the API-side counterpart to the §7
`runtime-bundle` adapter: both keep an existing agent-facing contract
serving the registry without an SDK-coordinated cutover.

## 10. Open questions

- **Secrets in module env**: modules declare `env_keys`; values must come
  from the hive's secret store. Binding mechanism spec'd separately.
- **Module install failures**: refuse to start, run degraded, or retry?
  Lean toward degraded mode + telemetry so a single bad module doesn't
  brick an agent.
- **Subagent vs. Skill overlap**: subagents look increasingly skill-like.
  Worth a v2 follow-up to decide if they should merge once the boundaries
  are clearer in practice.
- **Task-scoped modules (v2)**: v1 rejects task-scope for `kind=module`
  (see §8). Lifting that restriction needs a per-task process/env model —
  per-task subprocess with its own PATH, a per-task virtualenv (or
  equivalent for npm), and a re-rendered system prompt for that task only.
  Worth doing once a real use case appears; not worth speculating now.

## 11. Out of scope (v1)

- Semantic versioning (e.g. `my-skill@1.2.0`). Revision pinning via
  `revision_id` is in scope — semver is not.
- Marketplace / cross-hive publishing.
- Dependency graphs between registry items.
- Editing UI (API-first; UI is a separate workstream).
- **Hard delete of registry items.** v1 ships soft delete only (see §7
  "Delete semantics"). A real hard delete would need (a) GC of every
  attachment that references the item, (b) rewriting `WorkflowVersion.
  steps` JSON to drop the binding, and (c) rewriting replay history so
  re-runs of old tasks do not try to resolve a freed id. None of those
  ship in v1; tombstones are sufficient for the "retire an item" use
  case and preserve replay determinism by construction.
- **Re-targeting replay to a different agent.** Today
  `TaskReplayService` re-uses the original task's `agent_id` context, so
  agent-scoped private items remain visible to the replayed child. A
  hypothetical "replay this task as a different agent" feature would
  drop the original owner's private attachments by design (see §6
  "Private visibility constraint" → replay implication). Not a v1
  feature; called out so the private-visibility contract is closed.
