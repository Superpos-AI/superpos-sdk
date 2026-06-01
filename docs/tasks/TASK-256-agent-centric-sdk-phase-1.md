# TASK-256: Agent-centric SDK — Phase 1 (AgentContext + constants)

**Status:** in-progress
**Branch:** `task/256-agent-centric-sdk-phase-1`
**PR:** —
**Depends on:** —
**Blocks:** Phase 2 (OOP wrappers — Channel, Task, KnowledgeEntry classes)
**Edition:** both
**Feature doc:** —

## Objective

The Superpos Python SDK (`sdk/python/`) is technically complete (120 methods) but
ergonomically flat — a 1:1 mirror of REST endpoints. Agents using it have to
thread `hive_id` through every call, pass credentials manually, deal with
undocumented dict shapes, and don't get IDE autocomplete on enum values.

This task delivers **Phase 1** of an agent-centric refactor: a thin, typed
`AgentContext` facade that auto-reads the agent's identity from env vars,
binds `hive_id` implicitly, and exposes authoritative enum constants for the
most common API fields. No breaking changes, no async, no OOP wrappers —
those are explicitly Phase 2 and Phase 3.

## Requirements

### Functional

- [ ] FR-1: New `AgentContext` class in
  `sdk/python/src/superpos_sdk/agent.py` auto-reads `SUPERPOS_BASE_URL`,
  `SUPERPOS_API_TOKEN`, `SUPERPOS_HIVE_ID`, and `SUPERPOS_AGENT_ID` from the
  process environment, and falls back to explicit keyword arguments on
  `__init__`.
- [ ] FR-2: `AgentContext.from_env()` class method raises a clear
  `ValueError` if `SUPERPOS_BASE_URL` or `SUPERPOS_API_TOKEN` is missing. A
  missing `SUPERPOS_HIVE_ID` or `SUPERPOS_AGENT_ID` is tolerated at
  construction time — methods that need a hive ID raise a
  `ValueError` at call time if none is bound.
- [ ] FR-3: `AgentContext` wraps an underlying `SuperposClient` and exposes a
  **pre-bound** surface where `hive_id` is implicit. Methods covered at
  minimum:
  - Tasks: `poll_tasks`, `create_task`, `claim_task`, `complete_task`,
    `fail_task`, `update_progress`.
  - Channels: `create_channel`, `list_channels`, `get_channel`,
    `post_message`, `list_messages`, `add_participant`,
    `resolve_channel`, `archive_channel`.
  - Knowledge: `list_knowledge`, `create_knowledge`, `get_knowledge`,
    `update_knowledge`, `delete_knowledge`, `search_knowledge`.
  - Events: `poll_events`, `publish_event`.
  - Schedules: `create_schedule`, `list_schedules`, `delete_schedule`.
  - Persona memory: `update_memory`.
  - Heartbeat: `heartbeat`.
- [ ] FR-4: `AgentContext` exposes `agent_id` and `hive_id` as read-only
  properties, plus a `raw` property that returns the underlying
  `SuperposClient` for escape-hatch access to methods not yet bound.
- [ ] FR-5: New `sdk/python/src/superpos_sdk/constants.py` module exporting:
  - `MESSAGE_TYPES` (channel message types — authoritative list from
    `App\Models\ChannelMessage::TYPES`).
  - `CHANNEL_STATUSES` (from `App\Models\Channel::STATUSES`).
  - `RESOLUTION_POLICIES` — dict of preset resolution-policy shapes
    (keys: `manual`, `agent_decision`, `consensus`, `human_approval`,
    `staged`) pulled from `App\Services\ResolutionEngine`.
  - `TASK_STATUSES` (from `App\Models\Task::STATUSES`).
  - `KNOWLEDGE_SCOPES` — `("hive", "apiary", "agent")` from
    `CompleteTaskRequest` / `KnowledgeDashboardController`.
  - `KNOWLEDGE_VISIBILITY` — `("public", "private")` from
    `CreateKnowledgeRequest`.
  All exported from the top-level `superpos_sdk` namespace.
- [ ] FR-6: The existing `CHANNEL_TYPES` list is moved into `constants.py`
  and re-exported from `superpos_sdk.client` and `superpos_sdk.__init__` so
  existing imports continue to work.
- [ ] FR-7: `AgentContext` is **sync-only** — it wraps the existing sync
  `SuperposClient`. An async variant (`AsyncAgentContext`) is explicitly
  deferred to Phase 3.
- [ ] FR-8: `sdk/python/README.md` is updated with:
  - A new "Agent quickstart (env-driven)" section showing
    `AgentContext.from_env()` usage.
  - A "Common recipes" section with five copy-paste snippets:
    1. Poll + complete a task.
    2. Start a discussion channel.
    3. Post a message with mentions.
    4. Write a knowledge entry.
    5. Publish a custom event.

### Non-Functional

- [ ] NFR-1: **No breaking changes to `SuperposClient`.** All existing public
  methods keep their signatures. Existing tests pass untouched.
- [ ] NFR-2: Every public method and property on `AgentContext` has a full
  type hint and a docstring that states what it returns and what
  permission it requires (where relevant).
- [ ] NFR-3: `from_env()` never reads the token twice — it's captured once
  and cached on the instance. Re-reads of `os.environ` between
  construction and method calls must not mutate behaviour.
- [ ] NFR-4: Sync only. No `asyncio`, no `httpx.AsyncClient` in this phase.
- [ ] NFR-5: `AgentContext` must be testable without network — accept an
  injected `SuperposClient` via the `client=` kwarg on `__init__` so tests
  can pass a stub.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `sdk/python/src/superpos_sdk/agent.py` | `AgentContext` class |
| Create | `sdk/python/src/superpos_sdk/constants.py` | Enum/constant module |
| Modify | `sdk/python/src/superpos_sdk/__init__.py` | Export new names; preserve existing |
| Modify | `sdk/python/src/superpos_sdk/client.py` | Re-export `CHANNEL_TYPES` from `constants` |
| Modify | `sdk/python/README.md` | Agent quickstart + recipes |
| Create | `sdk/python/tests/test_agent_context.py` | Unit tests |
| Create | `sdk/python/tests/test_constants.py` | Constant module tests |

### Key Design Decisions

- **`AgentContext` is a facade, not a subclass.** It *holds* an
  `SuperposClient` rather than inheriting from it. This keeps the escape
  hatch (`ctx.raw`) honest and prevents accidental leaking of unbound
  methods onto the agent surface.
- **Hive ID binding is read-once at construction.** Methods do not re-read
  env vars on every call. Agents that need to operate across hives keep
  using `ctx.raw` directly or construct a second context.
- **Constants are plain `tuple[str, ...]`, not Enums.** The backend
  validates strings and the SDK deliberately avoids forcing users to
  import an Enum just to pass a known string. Autocomplete in modern
  editors covers literal types via `Literal[*CHANNEL_TYPES]` if users
  want stricter typing, but the canonical constant form is a tuple.
- **`RESOLUTION_POLICIES` is a dict of *example shapes*, not just names.**
  Agents frequently forget the exact JSON structure for staged policies.
  Providing a copy-and-edit template is more useful than just a list of
  names.
- **Environment variable names match what the hosted-agents runtime
  injects** (TASK-231): `SUPERPOS_BASE_URL`, `SUPERPOS_API_TOKEN`,
  `SUPERPOS_HIVE_ID`, `SUPERPOS_AGENT_ID`. Note: TASK-231 injects the token
  as `SUPERPOS_TOKEN`; this phase reads **both** `SUPERPOS_API_TOKEN`
  (canonical) and `SUPERPOS_TOKEN` (runtime compat) with the former
  winning if both are set.

## Test Plan

### Unit Tests

- [ ] `from_env()` reads all four env vars into the context.
- [ ] `from_env()` raises `ValueError` when `SUPERPOS_BASE_URL` is missing.
- [ ] `from_env()` raises `ValueError` when neither `SUPERPOS_API_TOKEN`
  nor `SUPERPOS_TOKEN` is set.
- [ ] `from_env()` prefers `SUPERPOS_API_TOKEN` over `SUPERPOS_TOKEN` when
  both are present.
- [ ] Explicit kwargs override env vars.
- [ ] `agent_id`, `hive_id` properties return the values bound at
  construction.
- [ ] `raw` returns the underlying `SuperposClient` instance.
- [ ] Hive-bound methods call the correct underlying client method with
  `hive_id` threaded through (asserted via a `ClientStub` that captures
  calls).
- [ ] `post_message` and other renamed methods map to the correct
  underlying method (e.g. `post_channel_message`).
- [ ] Hive-bound methods raise `ValueError` if the context was
  constructed without a `hive_id`.
- [ ] `heartbeat()` works without a `hive_id`.

### Integration Tests

- [ ] `test_constants.py`: importing every new constant succeeds, and
  expected keys / values are present (e.g. `"discussion"` in
  `MESSAGE_TYPES`, `"hive"` in `KNOWLEDGE_SCOPES`).
- [ ] `CHANNEL_TYPES` remains importable from both `superpos_sdk` and
  `superpos_sdk.client` (backward compat).
- [ ] The existing SDK test suite passes unchanged.

## Validation Checklist

- [ ] `ruff check .` passes in `sdk/python`
- [ ] `pytest` passes in `sdk/python` (existing + new tests)
- [ ] No changes to `SuperposClient` public API
- [ ] `AgentContext` importable from top-level `superpos_sdk` package
- [ ] README updated with agent quickstart + five recipes
- [ ] No PHP / backend changes
