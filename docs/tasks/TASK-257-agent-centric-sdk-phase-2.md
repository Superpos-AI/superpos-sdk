# TASK-257: Agent-centric SDK — Phase 2 (OOP resource wrappers)

**Status:** in-progress
**Branch:** `task/257-agent-centric-sdk-phase-2`
**PR:** —
**Depends on:** TASK-256 (Phase 1 — `AgentContext` + constants)
**Blocks:** Phase 3 (async variant + high-level skills like `discuss()` / `decide()` / `remember()`)
**Edition:** both
**Feature doc:** —

## Objective

Phase 1 (TASK-256) shipped a sync-only `AgentContext` facade that removes the
`hive_id=` boilerplate from agent code. Every method still returns a raw dict —
agents then have to thread those dicts back through `ctx.post_message(channel["id"], ...)`
style calls, and there's no natural place to hang "what can I do with this
resource?" style documentation.

Phase 2 adds **OOP wrappers** on top of Phase 1: `Channel`, `Task`, and
`KnowledgeEntry` classes that wrap a dict and expose bound methods. Instead of:

```python
ch = ctx.create_channel(title="...", channel_type="discussion")
ctx.post_message(ch["id"], "hello")
ctx.add_participant(ch["id"], "agent", "01HXYZ...", role="decider")
ctx.resolve_channel(ch["id"], outcome="shipped")
```

agents write:

```python
ch = ctx.create_channel_obj(title="...", channel_type="discussion")
ch.post("hello")
ch.invite("01HXYZ...", role="decider")
ch.resolve(outcome="shipped")
```

Phase 2 is **strictly additive** — no Phase 1 method is renamed or removed, no
return type is changed. Async variants and high-level skills remain deferred
to Phase 3.

## Requirements

### Functional

- [ ] FR-1: New `Channel` class in
  `sdk/python/src/superpos_sdk/resources/channel.py` wrapping a channel dict.
  Exposes attributes (`id`, `title`, `channel_type`, `status`, `topic`,
  `participants`, `resolution_policy`, `created_at`, `updated_at`) plus
  bound methods:
  - `refresh()` — re-fetch the channel and merge the result into the
    wrapper's local dict.
  - `post(content, *, message_type='discussion', mentions=None, metadata=None, reply_to=None)`
    — post a message (wraps `post_message` / `post_channel_message`).
  - `messages(*, since=None, after_id=None, page=None, per_page=None)` —
    list messages (wraps `list_messages`).
  - `invite(participant_id, *, participant_type='agent', role='contributor', mention_policy=None)`
    — add a participant (wraps `add_participant`).
  - `remove_participant(participant_id)` — wraps
    `SuperposClient.remove_channel_participant`.
  - `participants()` — returns the `participants` field from a fresh fetch.
  - `summary()` — wraps `SuperposClient.channel_summary`.
  - `mark_read()` — wraps `SuperposClient.mark_channel_read`.
  - `resolve(outcome, *, materialized_tasks=None)` — wraps `resolve_channel`
    and refreshes local state.
  - `reopen()` — wraps `SuperposClient.reopen_channel` and refreshes.
  - `archive()` — wraps `archive_channel` and refreshes.
  - `materialize(tasks)` — wraps `SuperposClient.materialize_channel`. Takes
    a list of task template dicts (each with `type` + optional
    `payload` / `target_capability` / `priority`) as per the existing
    client API.

- [ ] FR-2: New `Task` class in
  `sdk/python/src/superpos_sdk/resources/task.py` wrapping a task dict.
  Exposes attributes (`id`, `type`, `status`, `payload`, `result`,
  `priority`, `created_at`, `updated_at`, `progress`, `status_message`)
  plus bound methods:
  - `refresh()` — re-fetch via `get_task_trace` (see FR-7 gap note) and
    merge the task fields from the trace envelope. If the trace endpoint
    is unavailable the method raises.
  - `claim()` — wraps `claim_task` and refreshes local state.
  - `complete(result=None, *, status_message=None, delivery_mode=None, knowledge_entry_id=None)`
    — wraps `complete_task` and refreshes.
  - `fail(error=None, *, status_message=None)` — wraps `fail_task` and
    refreshes.
  - `update_progress(progress, *, status_message=None)` — wraps
    `update_progress` and refreshes.
  - `trace()` — wraps `get_task_trace`.
  - `replay(*, override_payload=None)` — wraps `replay_task`, returns
    a **new** `Task` wrapping the replayed task dict.

- [ ] FR-3: New `KnowledgeEntry` class in
  `sdk/python/src/superpos_sdk/resources/knowledge.py` wrapping a
  knowledge-entry dict. Exposes attributes (`id`, `key`, `value`, `scope`,
  `visibility`, `version`, `ttl`, `created_at`, `updated_at`) plus:
  - `refresh()` — re-fetch via `get_knowledge` and merge.
  - `update(value, *, visibility=None, ttl=None)` — wraps
    `update_knowledge` and refreshes.
  - `delete()` — wraps `delete_knowledge`. After a successful delete the
    wrapper marks itself as `deleted` (see FR-6) and subsequent mutating
    calls raise `RuntimeError`.
  - `links(*, target_type=None, limit=None)` — wraps
    `list_knowledge_links` with `source_id=self.id`.
  - `link_to(target_id, *, target_type='knowledge', link_type='relates_to', metadata=None)`
    — wraps `create_knowledge_link`.
  - `unlink(link_id)` — wraps `delete_knowledge_link`.

- [ ] FR-4: Extend `AgentContext` with factory methods that return wrapper
  instances, alongside (not replacing) the existing dict-returning methods:
  - `ctx.channel(channel_id)` → `Channel` (fetches by id).
  - `ctx.create_channel_obj(title, channel_type, **kwargs)` → `Channel`.
  - `ctx.list_channels_obj(**filters)` → `list[Channel]`.
  - `ctx.claim_next(*, capability=None)` → `Task | None` — polls for one
    task, claims it, returns a `Task` (or `None` if no tasks are
    available).
  - `ctx.knowledge(entry_id)` → `KnowledgeEntry`.
  - `ctx.create_knowledge_obj(key, value, *, scope=None, visibility=None, ttl=None)` → `KnowledgeEntry`.
  - `ctx.list_knowledge_obj(*, key=None, scope=None, limit=None)` → `list[KnowledgeEntry]`.

- [ ] FR-5: Every wrapper class implements:
  - `__repr__` in the form `Channel(id='...', title='...')` /
    `Task(id='...', type='...', status='...')` /
    `KnowledgeEntry(id='...', key='...', version=N)`.
  - `to_dict()` returning the underlying dict (shallow copy) so agents
    can cleanly serialise state when they want the raw shape back.
  - Equality (`__eq__`) by `(type(self), self.id)`. Hashing by `self.id`.

- [ ] FR-6: Every wrapper method that mutates remote state also refreshes
  the wrapper's local dict — either by merging the response body into
  `self._data` or by calling `self.refresh()` on endpoints whose response
  doesn't echo the full resource. After a successful mutation, reading
  attributes off the wrapper reflects the new state, not the pre-write
  state.

- [ ] FR-7: **SDK / backend gaps documented and skipped, not invented.**
  Specifically:
  - The Superpos REST API does **not** expose a single-task "show" endpoint
    at `GET /api/v1/hives/{hive}/tasks/{task}` (only a `/tasks/{task}/trace`
    endpoint exists, plus a cross-hive variant). Because of this:
    - `AgentContext.task(task_id)` is **not** implemented in this phase.
      Agents who need a `Task` wrapper from an ID must go through
      `ctx.claim_next()` or `ctx.create_task(...)` (which returns a dict
      — callers construct `Task(dict, ctx)` explicitly).
    - `Task.refresh()` uses `get_task_trace` and pulls the task fields
      from the trace envelope. If the trace envelope shape changes the
      wrapper falls back to a no-op refresh with a clear error.
  - The SDK also lacks `create_task_obj` — adding a factory wrapper
    without a corresponding `get_task` retrieval method would be
    asymmetrical. Deferring a full `Task` lifecycle wrapper (including
    `ctx.task(...)`) to a future phase once a `GET /tasks/{id}` endpoint
    lands.

- [ ] FR-8: Extend `sdk/python/README.md` with a new **"Working with
  resources (OOP wrappers)"** section showing one end-to-end snippet per
  wrapper (`Channel`, `Task`, `KnowledgeEntry`). Existing Phase 1 recipes
  are left unchanged.

### Non-Functional

- [ ] NFR-1: **Zero breaking changes to Phase 1.** Every `AgentContext`
  method that returned a dict before still returns a dict. Wrappers are
  exposed via new, explicitly named methods (`channel()`, `knowledge()`,
  `claim_next()`, `*_obj()`).
- [ ] NFR-2: Every public method, class, and attribute on a wrapper has a
  full type hint and a docstring.
- [ ] NFR-3: Wrappers are **testable without network** — they accept an
  `AgentContext` (or a stub) as a constructor argument and call through
  it. Tests substitute a `ContextStub` that records method calls the same
  way Phase 1's `ClientStub` does.
- [ ] NFR-4: Sync only. No async variants in this phase.
- [ ] NFR-5: No new runtime dependencies (`pydantic`, `attrs`, etc.).
  Wrappers are plain classes — stdlib only.
- [ ] NFR-6: Each wrapper file stays under ~200 lines of code. If a
  wrapper grows larger it's a signal we're pulling in skill logic that
  belongs in Phase 3.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `sdk/python/src/superpos_sdk/resources/__init__.py` | Package entry; exports `Channel`, `Task`, `KnowledgeEntry` |
| Create | `sdk/python/src/superpos_sdk/resources/channel.py` | `Channel` wrapper |
| Create | `sdk/python/src/superpos_sdk/resources/task.py` | `Task` wrapper |
| Create | `sdk/python/src/superpos_sdk/resources/knowledge.py` | `KnowledgeEntry` wrapper |
| Modify | `sdk/python/src/superpos_sdk/agent.py` | Add factory methods (FR-4) |
| Modify | `sdk/python/src/superpos_sdk/__init__.py` | Re-export wrapper classes |
| Modify | `sdk/python/README.md` | Add "Working with resources" section |
| Create | `sdk/python/tests/resources/__init__.py` | Test package marker |
| Create | `sdk/python/tests/resources/test_channel.py` | `Channel` tests |
| Create | `sdk/python/tests/resources/test_task.py` | `Task` tests |
| Create | `sdk/python/tests/resources/test_knowledge_entry.py` | `KnowledgeEntry` tests |
| Modify | `sdk/python/tests/test_agent_context.py` | Add factory-method tests |

### Key Design Decisions

- **Wrappers hold a context, not a client.** The constructor takes an
  `AgentContext` rather than an `SuperposClient` so the wrapper inherits
  Phase 1's `hive_id` binding automatically. No wrapper needs to know
  which hive it lives in.
- **Wrappers are thin.** They do not cache state beyond the initial dict
  and do not implement cross-wrapper logic (e.g. "post a message then
  vote" is not a wrapper method — that's Phase 3). If a method would
  need more than a few lines of logic, it belongs in Phase 3.
- **Mutation refresh policy: merge over re-fetch.** When the backend
  response already contains the full resource (e.g. `resolve_channel`
  returns the resolved channel), we merge it into `_data`. When the
  response is an action acknowledgement (e.g. `mark_channel_read`
  returns only `{channel_id, last_read_at}`), we patch the affected
  fields in place and skip a second HTTP call. Tests assert the merge
  behaviour.
- **Equality by id, not by dict contents.** Two `Channel` instances
  wrapping different snapshots of the same channel compare equal. This
  matches how agents reason about resources in practice.
- **`Task.refresh()` uses the trace endpoint.** See FR-7. This is the
  single compromise we're making; a future phase will replace it with a
  proper `get_task` once the backend exposes one.
- **Deleted knowledge entries are sticky-dead.** After `entry.delete()`
  any mutating call raises `RuntimeError("knowledge entry already deleted")`.
  Attribute reads still work so callers can log the final state.

## Test Plan

### Unit Tests — wrappers

- [ ] `Channel` construction from a dict exposes every documented attribute.
- [ ] `Channel.post()` calls `ctx.post_message(channel.id, ...)` with the
  expected kwargs.
- [ ] `Channel.invite()` maps to `ctx.add_participant` with
  `participant_type='agent'` by default.
- [ ] `Channel.resolve()` calls `ctx.resolve_channel` and merges the
  returned dict into the wrapper's local state.
- [ ] `Channel.refresh()` calls `ctx.get_channel` and merges.
- [ ] `Channel.to_dict()` returns a shallow copy (mutation of the returned
  dict does not leak into `_data`).
- [ ] `Channel` equality and hashing are id-based.
- [ ] `Channel.__repr__` includes the id and title.
- [ ] `Task` construction and attributes.
- [ ] `Task.claim()`, `complete()`, `fail()`, `update_progress()` call the
  matching context methods with `task.id` threaded through, and merge.
- [ ] `Task.replay()` returns a **new** `Task` instance, not the original.
- [ ] `Task.refresh()` pulls task fields from the trace envelope.
- [ ] `KnowledgeEntry` construction and attributes.
- [ ] `KnowledgeEntry.update()` bumps the local `version` after success.
- [ ] `KnowledgeEntry.delete()` marks the wrapper as deleted; subsequent
  mutations raise `RuntimeError`.
- [ ] `KnowledgeEntry.link_to()` calls `ctx.raw.create_knowledge_link` with
  `source_id=entry.id`.

### Unit Tests — `AgentContext` factory methods

- [ ] `ctx.channel(channel_id)` calls `get_channel` and returns a
  `Channel` wrapping the result.
- [ ] `ctx.create_channel_obj(...)` creates + returns a `Channel`.
- [ ] `ctx.list_channels_obj()` returns a list of `Channel` instances.
- [ ] `ctx.knowledge(entry_id)` returns a `KnowledgeEntry`.
- [ ] `ctx.create_knowledge_obj(...)` returns a `KnowledgeEntry`.
- [ ] `ctx.list_knowledge_obj()` returns a list of `KnowledgeEntry`.
- [ ] `ctx.claim_next()` polls + claims + returns a `Task`, or returns
  `None` when no tasks are available.

### Integration Tests

- [ ] Existing Phase 1 tests (`test_agent_context.py`, `test_constants.py`,
  `test_channels.py`, …) pass unchanged.
- [ ] `from superpos_sdk import Channel, Task, KnowledgeEntry` works.

## Validation Checklist

- [ ] `ruff check .` passes in `sdk/python`
- [ ] `ruff format --check .` passes in `sdk/python`
- [ ] `pytest` passes in `sdk/python`
- [ ] No changes to `SuperposClient` public API
- [ ] `Channel`, `Task`, `KnowledgeEntry` importable from the top-level
  `superpos_sdk` package
- [ ] README updated with a "Working with resources" section
- [ ] No PHP / backend changes
