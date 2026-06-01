# TASK-258: Agent-centric SDK — Phase 3 (async variant + skills layer)

**Status:** in-progress
**Branch:** `task/258-agent-centric-sdk-phase-3`
**PR:** —
**Depends on:** TASK-256 (Phase 1 — `AgentContext` + constants), TASK-257 (Phase 2 — OOP wrappers)
**Blocks:** —
**Edition:** both
**Feature doc:** —

## Objective

Phases 1 and 2 delivered a sync agent-centric facade (`AgentContext`) and
OOP wrappers (`Channel` / `Task` / `KnowledgeEntry`). Phase 3 finishes the
refactor with two additive pieces:

1. **Async variant.** Agents that run inside `asyncio` event loops (web
   frameworks, WebSocket handlers, long-lived gateways) currently have to
   wrap every sync SDK call in `asyncio.to_thread()` — which both hides
   the call behind a thread boundary and defeats httpx's async pool. This
   phase adds a parallel async stack (`AsyncSuperposClient`,
   `AsyncAgentContext`, `AsyncChannel` / `AsyncTask` /
   `AsyncKnowledgeEntry`) with the same surface as the sync stack.
2. **Skills layer.** High-level goal-oriented verbs — `discuss`,
   `decide`, `remember`, `recall` — that compose multiple SDK calls into
   common agent patterns. Agents stop writing boilerplate like "create a
   channel, add participants, post the opener, set the resolution
   policy" and write `ctx.discuss(...)` instead.

Phase 3 is **strictly additive**. Sync `AgentContext`, sync wrappers, sync
API, top-level exports: all unchanged. Every new surface lives behind
explicit, separately-named imports (`AsyncAgentContext`,
`superpos_sdk.skills`).

## Non-Goals

- No async variant of `StreamingTask` / `ServiceWorker` — those keep
  their existing infrastructure.
- No skill that invents REST endpoints. If a skill needs something the
  SDK cannot express, the skill does not silently fallback — it either
  raises or documents the gap.
- No full method-by-method port of the 120-method `SuperposClient`. The
  async client mirrors only the methods `AsyncAgentContext` itself
  needs. Exotic / rarely-used methods (workflows, thread helpers, large
  result delivery, service catalog discovery, stream chunk helpers)
  remain sync-only for now — agents that need them can drop down to a
  sync `SuperposClient` from inside `asyncio.to_thread()`.

## Requirements

### Functional — async variant

- [ ] FR-1: New `AsyncSuperposClient` in
  `sdk/python/src/superpos_sdk/async_client.py`, backed by
  `httpx.AsyncClient`. Mirrors the sync client's surface for every method
  that `AgentContext` wraps, specifically:
  - **Auth & lifecycle:** `register`, `login`, `logout`, `me`,
    `heartbeat`, `close` / `__aenter__` / `__aexit__`.
  - **Tasks:** `create_task`, `poll_tasks`, `claim_task`,
    `update_progress`, `complete_task`, `fail_task`, `get_task_trace`,
    `replay_task`.
  - **Channels:** `list_channels`, `create_channel`, `get_channel`,
    `archive_channel`, `list_channel_messages`, `post_channel_message`,
    `add_channel_participant`, `remove_channel_participant`,
    `resolve_channel`, `reopen_channel`, `materialize_channel`,
    `channel_summary`, `mark_channel_read`.
  - **Knowledge:** `list_knowledge`, `search_knowledge`, `get_knowledge`,
    `create_knowledge`, `update_knowledge`, `delete_knowledge`,
    `list_knowledge_links`, `create_knowledge_link`,
    `delete_knowledge_link`.
  - **Events:** `poll_events`, `publish_event`, `reset_event_cursor`.
  - **Schedules:** `list_schedules`, `create_schedule`, `delete_schedule`.
  - **Persona memory:** `update_memory`.

  Response parsing, error handling, and the envelope contract match the
  sync client exactly (`_request` unwraps `data`, `_request_envelope`
  returns the full `{data, meta, errors}` shape, `raise_for_status` is
  reused unchanged).

- [ ] FR-2: New `AsyncAgentContext` in
  `sdk/python/src/superpos_sdk/async_agent.py`. Exposes the same public
  surface as `AgentContext` — identity properties (`base_url`, `token`,
  `hive_id`, `agent_id`, `raw`), the hive-bound methods listed in FR-1,
  and the `from_env` classmethod. Every public method is `async def`.
  Environment variable resolution is identical to the sync version
  (`SUPERPOS_BASE_URL` / `SUPERPOS_API_TOKEN` / `SUPERPOS_TOKEN` /
  `SUPERPOS_HIVE_ID` / `SUPERPOS_AGENT_ID`).

- [ ] FR-3: Async OOP wrappers under
  `sdk/python/src/superpos_sdk/resources/async_resources/`:
  - `AsyncChannel` — `post`, `messages`, `invite`, `remove_participant`,
    `resolve`, `reopen`, `archive`, `refresh`. (High-value subset —
    `summary`, `mark_read`, `materialize` skipped per Out-of-Scope.)
  - `AsyncTask` — `claim`, `update_progress`, `complete`, `fail`,
    `trace`, `refresh`, `replay`.
  - `AsyncKnowledgeEntry` — `update`, `delete`, `refresh`, `link_to`,
    `unlink`.

  All wrappers expose the same attributes as their sync counterparts
  (`id`, `title`, `status`, etc.) via synchronous property access.
  `to_dict()`, `__repr__`, and equality-by-id follow the sync pattern.
  Mutation methods that refresh local state are `async def` (since they
  issue HTTP calls).

- [ ] FR-4: `AsyncAgentContext` factory methods — async mirrors of Phase
  2's factories:
  - `async def channel(channel_id)` → `AsyncChannel`.
  - `async def create_channel_obj(...)` → `AsyncChannel`.
  - `async def list_channels_obj(**filters)` → `list[AsyncChannel]`.
  - `async def claim_next(*, capability=None)` → `AsyncTask | None`.
  - `async def knowledge(entry_id)` → `AsyncKnowledgeEntry`.
  - `async def create_knowledge_obj(...)` → `AsyncKnowledgeEntry`.
  - `async def list_knowledge_obj(**filters)` →
    `list[AsyncKnowledgeEntry]`.

- [ ] FR-5: Both `AsyncSuperposClient` and `AsyncAgentContext` implement
  `__aenter__` / `__aexit__` so agents can write::

      async with AsyncAgentContext.from_env() as ctx:
          tasks = await ctx.poll_tasks(capability="code")

  The `AsyncSuperposClient`'s underlying `httpx.AsyncClient` is closed on
  context-manager exit.

### Functional — skills

- [ ] FR-6: New `sdk/python/src/superpos_sdk/skills/` package exposing four
  high-level verbs, each with a sync and an async implementation:
  - `discuss(ctx, title, *, topic=None, participants=None, initial_message=None, channel_type='discussion')`
    — creates a channel and optionally posts an opener (when
    *initial_message* is given). Returns a `Channel` (sync ctx) or
    `AsyncChannel` (async ctx).
  - `decide(ctx, title, question, options, *, participants=None, policy='agent_decision', threshold=None, deadline_seconds=None)`
    — creates a channel with `channel_type='discussion'`, attaches a
    `resolution_policy` derived from *policy* (falls through to
    `RESOLUTION_POLICIES[policy]` when known) and posts a `proposal`
    message carrying *question* + *options* in metadata. Returns a
    `Channel` / `AsyncChannel`. Resolution is asynchronous — the
    function does **not** wait for a verdict.
  - `remember(ctx, key, value, *, scope='hive', visibility='public', ttl=None, tags=None, format='markdown', title=None, summary=None)`
    — writes a knowledge entry. When *value* is a `str`, the skill
    normalises it into the standard shape
    `{"title", "content", "format", "summary", "tags"}` (title defaults
    to *key*, tags default to `[]`). When *value* is a `dict`, it is
    passed through unchanged. Returns a `KnowledgeEntry` /
    `AsyncKnowledgeEntry`.
  - `recall(ctx, key=None, *, query=None, scope=None, limit=10)` —
    key-lookup mode (via `list_knowledge(key=...)`) when *key* is given,
    full-text search mode (via `search_knowledge(q=...)`) when *query*
    is given. Raises `ValueError` when neither is given or both are
    given. Returns a list of `KnowledgeEntry` / `AsyncKnowledgeEntry`.

- [ ] FR-7: Skills are exposed two ways:
  1. Functional: `from superpos_sdk.skills import discuss, decide, remember, recall`.
     Each takes `ctx: AgentContext | AsyncAgentContext` as the first
     positional arg.
  2. Method-bound: `AgentContext.discuss(...)` / `.decide(...)` /
     `.remember(...)` / `.recall(...)` and the matching
     `AsyncAgentContext` methods. These delegate to the functional
     form with `self` threaded as the first arg.

- [ ] FR-8: Skill implementations live in separate modules:
  - `sdk/python/src/superpos_sdk/skills/sync_skills.py` — sync
    implementations that take an `AgentContext`.
  - `sdk/python/src/superpos_sdk/skills/async_skills.py` — async
    implementations (`async def`) that take an `AsyncAgentContext`.
  - `sdk/python/src/superpos_sdk/skills/__init__.py` — public façade.
    Exports `discuss`, `decide`, `remember`, `recall` that dispatch to
    the sync or async implementation by inspecting
    `inspect.iscoroutinefunction(ctx.post_message)` (or, equivalently,
    by isinstance check on `AsyncAgentContext`). The dispatcher returns
    an awaitable when the ctx is async and a plain value when it is
    sync — exactly as a user of "one public symbol" would expect.

  **Design choice:** separate modules over a single-module
  `iscoroutinefunction` branch because (a) the type-checker has an
  easier time with two small single-purpose functions per skill, and
  (b) no user has asked for a runtime-polymorphic helper that returns
  "a `Channel` or `AsyncChannel` depending on ctx" — so we keep the
  surface simple, dispatch at the `__init__` level once, and let each
  implementation stay explicitly sync or async.

- [ ] FR-9: Extend `sdk/python/README.md` with two new sections:
  - **Async usage** — an `async with AsyncAgentContext.from_env()`
    example plus 2 recipes (poll/claim, post to a channel).
  - **Skills** — one block per verb showing a representative call.

### Non-Functional

- [ ] NFR-1: **Zero breaking changes.** Sync `AgentContext`, sync
  wrappers, all existing tests still pass unchanged.
- [ ] NFR-2: Every new public async method and every new skill function
  has a full type hint and a docstring.
- [ ] NFR-3: All async classes are **testable without network** — they
  accept a client / context via dependency injection so tests can stub
  `httpx.MockTransport` or a hand-rolled recorder. Async skill tests
  use a lightweight async stub, no real HTTP.
- [ ] NFR-4: **No new runtime dependencies.** `httpx` already ships
  `AsyncClient`. Dev-only: add `pytest-asyncio` to `[dev]` extras (a
  no-op for production installs). Mark new async tests with
  `@pytest.mark.asyncio`.
- [ ] NFR-5: Skills never invent endpoints. `discuss` uses
  `create_channel` + (optional) `post_message`. `decide` uses
  `create_channel` + `post_message` with `message_type='proposal'`.
  `remember` uses `create_knowledge`. `recall` uses `list_knowledge`
  or `search_knowledge`.
- [ ] NFR-6: Each async resource file stays under ~250 lines. The
  async client may exceed that (it mirrors a large surface) but stays
  under ~900 lines — roughly a third of the sync client, which is
  expected since it only mirrors the 30-ish methods AgentContext uses.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `sdk/python/src/superpos_sdk/async_client.py` | `AsyncSuperposClient` |
| Create | `sdk/python/src/superpos_sdk/async_agent.py` | `AsyncAgentContext` |
| Create | `sdk/python/src/superpos_sdk/resources/async_resources/__init__.py` | Async wrapper package |
| Create | `sdk/python/src/superpos_sdk/resources/async_resources/channel.py` | `AsyncChannel` |
| Create | `sdk/python/src/superpos_sdk/resources/async_resources/task.py` | `AsyncTask` |
| Create | `sdk/python/src/superpos_sdk/resources/async_resources/knowledge.py` | `AsyncKnowledgeEntry` |
| Create | `sdk/python/src/superpos_sdk/skills/__init__.py` | Skills façade with sync/async dispatch |
| Create | `sdk/python/src/superpos_sdk/skills/sync_skills.py` | Sync skill implementations |
| Create | `sdk/python/src/superpos_sdk/skills/async_skills.py` | Async skill implementations |
| Modify | `sdk/python/src/superpos_sdk/agent.py` | Bind `discuss` / `decide` / `remember` / `recall` methods |
| Modify | `sdk/python/src/superpos_sdk/__init__.py` | Re-export async stack + skills |
| Modify | `sdk/python/README.md` | Async + Skills sections |
| Modify | `sdk/python/pyproject.toml` | Add `pytest-asyncio` dev dep |
| Create | `sdk/python/tests/test_async_client.py` | `AsyncSuperposClient` smoke tests |
| Create | `sdk/python/tests/test_async_agent.py` | `AsyncAgentContext` env, methods, factories |
| Create | `sdk/python/tests/resources/test_async_channel.py` | `AsyncChannel` tests |
| Create | `sdk/python/tests/resources/test_async_task.py` | `AsyncTask` tests |
| Create | `sdk/python/tests/resources/test_async_knowledge_entry.py` | `AsyncKnowledgeEntry` tests |
| Create | `sdk/python/tests/skills/__init__.py` | Test package marker |
| Create | `sdk/python/tests/skills/test_discuss.py` | `discuss` (sync) |
| Create | `sdk/python/tests/skills/test_decide.py` | `decide` (sync) |
| Create | `sdk/python/tests/skills/test_remember.py` | `remember` (sync) |
| Create | `sdk/python/tests/skills/test_recall.py` | `recall` (sync) |
| Create | `sdk/python/tests/skills/test_async_skills.py` | Async skill variants |

### Key Design Decisions

- **Duplicate the client surface, don't extract shared helpers.** The
  sync and async clients have slightly different call styles (`self._http.request`
  vs `await self._http.request`) and `httpx.Client` vs
  `httpx.AsyncClient` don't share a transport-agnostic abstraction out
  of the box. Extracting URL / body builders into an internal
  `_RequestBuilder` saves little and adds indirection. We duplicate,
  accept the cost, and keep the two clients side by side.
- **Async context holds an `AsyncSuperposClient`, mirrors the sync
  factory pattern.** `AsyncAgentContext` construction, env loading, and
  `raw` escape-hatch parallel `AgentContext` one-for-one.
- **Async wrappers hold an async context.** Same pattern as Phase 2 —
  the wrapper inherits hive binding from the context. Attribute reads
  stay synchronous (they hit `self._data` only); only refresh-issuing
  or remote-mutating methods are `async def`.
- **Skills dispatch at import level, not at call time.** The single
  `discuss` symbol in `superpos_sdk.skills.__init__` is a thin dispatcher
  that picks between `sync_skills.discuss` and `async_skills.discuss`
  based on `isinstance(ctx, AsyncAgentContext)`. When the ctx is async
  the dispatcher returns an awaitable (the coroutine from
  `async_skills.discuss(...)`); when sync it returns the result
  directly. This matches user intuition (`await ctx.discuss(...)` for
  async, `ctx.discuss(...)` for sync) without forcing users to import
  different symbols.
- **Method binding on `AgentContext` / `AsyncAgentContext` is a
  one-line delegation.** Each of `discuss` / `decide` / `remember` /
  `recall` on the context class forwards to the matching skill
  function with `self` as the first argument. This keeps the skill
  implementations authoritative; the context class does not re-implement
  anything.
- **`decide` resolution policy via preset map.** The skill reads
  `superpos_sdk.constants.RESOLUTION_POLICIES` for named policies
  (`consensus`, `majority`, `agent_decision`). When the caller provides
  a `threshold` we merge it into the policy dict. When the caller
  provides `deadline_seconds` we translate it to `stale_after` minutes
  (rounded up). This is a minor convenience — the underlying
  `create_channel` API is unchanged.

## Test Plan

### Unit Tests — async client

- [ ] `AsyncSuperposClient` constructs with a base URL and stores auth.
- [ ] `register` stores the token and returns the full dict.
- [ ] `heartbeat` issues a POST with the expected body.
- [ ] `poll_tasks` / `claim_task` / `complete_task` / `fail_task` round
  trip correctly through `httpx.MockTransport`.
- [ ] `post_channel_message` posts with the default `message_type`.
- [ ] `list_knowledge` passes filters as query params.
- [ ] `poll_events` tracks the cursor across paginated calls.
- [ ] `__aenter__` / `__aexit__` close the underlying `AsyncClient`.

### Unit Tests — async agent

- [ ] `AsyncAgentContext.from_env` matches sync env precedence.
- [ ] `_require_hive` raises when no hive is bound.
- [ ] Every hive-bound method forwards `hive_id` to the client.
- [ ] Factory methods return the correct async wrapper type.
- [ ] `async with AsyncAgentContext.from_env()` closes the client.

### Unit Tests — async wrappers

- [ ] `AsyncChannel.post` calls `ctx.post_message(channel.id, ...)`.
- [ ] `AsyncChannel.refresh` merges the fresh dict.
- [ ] `AsyncTask.complete` / `fail` / `update_progress` merge state.
- [ ] `AsyncKnowledgeEntry.update` / `delete` / `link_to` work.
- [ ] Attribute reads stay synchronous.
- [ ] Equality by id.

### Unit Tests — skills

- [ ] `discuss` creates a channel and optionally posts an opener.
- [ ] `decide` creates a channel with a proposal message containing
  `options` metadata.
- [ ] `remember` accepts a string and normalises it to the standard
  shape; accepts a dict and passes it through.
- [ ] `recall` with `key` calls `list_knowledge(key=...)`.
- [ ] `recall` with `query` calls `search_knowledge(q=...)`.
- [ ] `recall` without either raises `ValueError`.
- [ ] Method-bound variants on `AgentContext` delegate.
- [ ] Async variants pass the same assertions with `await`.

### Integration Tests

- [ ] Every existing sync test (`test_client.py`, `test_agent_context.py`,
  Phase 2 wrapper tests, …) passes unchanged.
- [ ] `from superpos_sdk import AsyncAgentContext, AsyncSuperposClient` works.
- [ ] `from superpos_sdk.skills import discuss, decide, remember, recall`
  works.

## Validation Checklist

- [ ] `ruff check .` passes in `sdk/python`
- [ ] `ruff format --check .` passes in `sdk/python`
- [ ] `pytest` passes in `sdk/python`
- [ ] No changes to `SuperposClient` public API
- [ ] `AsyncSuperposClient`, `AsyncAgentContext`, `AsyncChannel`,
  `AsyncTask`, `AsyncKnowledgeEntry` importable from the top-level
  `superpos_sdk` package
- [ ] README updated with "Async usage" and "Skills" sections
- [ ] No PHP / backend changes

## Gaps & Out-of-Scope

- **Async `StreamingTask` / `ServiceWorker`** — deferred. The existing
  sync helpers stay authoritative; agents needing streaming from async
  code use `asyncio.to_thread(sync_helper, ...)` for now.
- **Full async port of `SuperposClient`** — only the methods
  `AgentContext` wraps are mirrored. Workflows, service catalog,
  persona versioning, thread helpers, and large-result delivery stay
  sync-only. A future task can expand the async surface when a concrete
  agent asks for it.
- **Channel voting / summary / mark-read on `AsyncChannel`** — the
  high-value mutation surface (`post` / `invite` / `resolve` / `archive`)
  is covered; the observability helpers (`summary`, `mark_read`,
  `materialize`) stay sync-only in this phase.
