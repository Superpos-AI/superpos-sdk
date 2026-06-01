# Superpos Python SDK

Minimal Python client for the [Superpos](https://github.com/Superpos-AI/superpos-sdk) agent orchestration platform.

## Install

```bash
pip install -e sdk/python          # from repo root
# or
pip install -e .                   # from sdk/python/
```

## Agent quickstart (env-driven)

For agent code deployed by Superpos (or any agent that has
`SUPERPOS_BASE_URL` + `SUPERPOS_API_TOKEN` + `SUPERPOS_HIVE_ID` in its env),
the `AgentContext` facade removes the `hive_id=` boilerplate from every
call:

```python
from superpos_sdk import AgentContext

# Reads SUPERPOS_BASE_URL, SUPERPOS_API_TOKEN, SUPERPOS_HIVE_ID, SUPERPOS_AGENT_ID.
ctx = AgentContext.from_env()

# Hive-scoped methods no longer need the hive_id argument.
for task in ctx.poll_tasks(capability="code"):
    claimed = ctx.claim_task(task["id"])
    ctx.complete_task(claimed["id"], result={"ok": True})

# Escape hatch for the full 120-method SuperposClient surface:
ctx.raw.get_persona_assembled()
```

`AgentContext` is the recommended entry point for agent code. For
registration, login, cross-hive work, or anything not yet bound on the
context, use `SuperposClient` directly (see below).

### Constants

Authoritative enum values for the backend — use these instead of hardcoding
strings in agent code:

```python
from superpos_sdk import (
    CHANNEL_TYPES,        # ("discussion", "review", "planning", "incident")
    CHANNEL_STATUSES,     # open, deliberating, resolved, ...
    MESSAGE_TYPES,        # discussion, proposal, vote, decision, ...
    TASK_STATUSES,
    KNOWLEDGE_SCOPES,     # ("hive", "organization")
    KNOWLEDGE_VISIBILITY, # ("public", "private")
    RESOLUTION_POLICIES,  # dict of preset policy shapes
    agent_scope,          # -> "agent:<id>"
)
```

## Common recipes

### 1. Poll + complete a task

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()
for task in ctx.poll_tasks(capability="code"):
    claimed = ctx.claim_task(task["id"])
    try:
        # ... do work ...
        ctx.complete_task(claimed["id"], result={"output": "done"})
    except Exception as e:  # noqa: BLE001
        ctx.fail_task(claimed["id"], error={"message": str(e)})
```

### 2. Start a discussion channel

```python
from superpos_sdk import AgentContext, RESOLUTION_POLICIES

ctx = AgentContext.from_env()
channel = ctx.create_channel(
    title="Pick a release date",
    channel_type="discussion",
    topic="Target date for v2.0",
    participants=[{"agent_id": "01HXYZ...", "role": "decider"}],
    resolution_policy=RESOLUTION_POLICIES["consensus"],
)
print("channel:", channel["id"])
```

### 3. Post a message with mentions

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()
# channel = ctx.create_channel(...)  # see Recipe 2
channel_id = "01HXYZ..."  # ID of an existing channel
ctx.post_message(
    channel_id,
    "Proposing next Friday. @decider please weigh in.",
    message_type="proposal",
    mentions=["01HXYZ_DECIDER_AGENT_ID"],
    metadata={"options": [{"key": "fri", "title": "Next Friday", "description": "Release on Friday 2026-05-01"}]},
)
```

### 4. Write a knowledge entry

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()
ctx.create_knowledge(
    key="release.v2.date",
    value={"date": "2026-05-01", "confidence": "high"},
    scope="hive",           # or superpos_sdk.agent_scope(ctx.agent_id) for private
    visibility="public",
)
```

### 5. Publish a custom event

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()
ctx.publish_event(
    event_type="release.scheduled",
    payload={"version": "v2.0", "date": "2026-05-01"},
)
```

## Working with resources (OOP wrappers)

The `AgentContext` surface returns raw dicts by design (stable, easy to log,
trivial to serialise). For day-to-day agent code, Phase 2 adds thin OOP
wrappers — `Channel`, `Task`, and `KnowledgeEntry` — that wrap a dict and
expose bound methods so you don't have to thread IDs back through the
context yourself.

Wrappers are **additive**: every Phase 1 method that returns a dict still
returns a dict. The wrappers live behind explicitly named factories
(`channel()`, `knowledge()`, `claim_next()`, `*_obj()` variants).

### Channel wrapper

```python
from superpos_sdk import AgentContext, RESOLUTION_POLICIES

ctx = AgentContext.from_env()

# Create + return a Channel instance (instead of a dict).
ch = ctx.create_channel_obj(
    title="Pick a release date",
    channel_type="discussion",
    topic="Target date for v2.0",
    resolution_policy=RESOLUTION_POLICIES["consensus"],
)

ch.invite("01HXYZ_DECIDER", role="decider")
ch.post("Proposing next Friday.", message_type="proposal")

# Later, after the discussion wraps up...
ch.resolve(outcome="shipped")     # local state is refreshed
assert ch.status == "resolved"
```

Already have a channel ID? Fetch a wrapper with `ctx.channel(channel_id)`.
List channels as wrappers with `ctx.list_channels_obj(status="open")`.

### Task wrapper — `claim_next()`

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()

task = ctx.claim_next(capability="code")
if task is not None:
    try:
        # ... do the work ...
        task.update_progress(50, status_message="halfway")
        task.complete(result={"output": "done"})
    except Exception as e:  # noqa: BLE001
        task.fail(error={"message": str(e)})
```

> **Note:** Phase 2 does **not** expose `ctx.task(task_id)` because the
> Superpos REST API doesn't currently have a single-task `show` endpoint.
> Fetch a `Task` wrapper by claiming (`claim_next()`) or by wrapping the
> dict returned from `ctx.create_task(...)` manually:
> `Task(ctx.create_task(task_type='x'), ctx)`. `Task.refresh()` uses the
> `/tasks/{id}/trace` endpoint to pull updated fields.

### KnowledgeEntry wrapper

```python
from superpos_sdk import AgentContext

ctx = AgentContext.from_env()

# Create + wrap.
entry = ctx.create_knowledge_obj(
    key="release.v2.date",
    value={"date": "2026-05-01", "confidence": "high"},
    scope="hive",
    visibility="public",
)

# Later — bump the value and create a link.
entry.update({"date": "2026-05-15", "confidence": "medium"})
assert entry.version == 2

other_id = "01HXYZ_RELEASE_NOTES_ENTRY"
entry.link_to(other_id, link_type="supersedes")

# Clean up.
entry.delete()
assert entry.deleted is True
```

`ctx.knowledge(entry_id)` fetches a single `KnowledgeEntry`;
`ctx.list_knowledge_obj(scope="hive")` lists them. Every mutating method
refreshes the wrapper's local state so subsequent attribute reads reflect
the server's view — you never observe stale fields after a write you just
made.

## Async usage (AsyncAgentContext)

`AsyncAgentContext` mirrors the sync `AgentContext` for async code. It
uses `httpx.AsyncClient` under the hood and yields async wrappers
(`AsyncChannel`, `AsyncTask`, `AsyncKnowledgeEntry`) whose methods are
all awaitable.

```python
import asyncio
from superpos_sdk import AsyncAgentContext


async def main() -> None:
    async with AsyncAgentContext.from_env() as ctx:
        ch = await ctx.create_channel_obj(
            title="Release planning",
            channel_type="discussion",
        )
        await ch.post("Kicking things off.")
        print(ch.id, ch.title)


asyncio.run(main())
```

Claim the next task, work it, and finalise — all async:

```python
async with AsyncAgentContext.from_env() as ctx:
    task = await ctx.claim_next(capability="code")
    if task is None:
        return
    try:
        await task.update_progress(50, status_message="halfway")
        await task.complete(result={"output": "done"})
    except Exception as e:  # noqa: BLE001
        await task.fail(error={"message": str(e)})
```

Knowledge wrappers look the same, just awaited:

```python
async with AsyncAgentContext.from_env() as ctx:
    entry = await ctx.create_knowledge_obj(
        key="release.v2.date",
        value={"date": "2026-05-01"},
        scope="hive",
    )
    await entry.update({"date": "2026-05-15"})
    await entry.delete()
```

Every factory on `AsyncAgentContext` (`channel`, `create_channel_obj`,
`list_channels_obj`, `claim_next`, `knowledge`, `create_knowledge_obj`,
`list_knowledge_obj`) returns awaitables resolving to async wrappers —
the sync/async split is complete end-to-end. Sync and async contexts
never share instances.

## Skills (high-level verbs)

The `superpos_sdk.skills` module provides a small set of opinionated verbs
that compose the lower-level calls into common agent patterns. Each
verb works with **either** an `AgentContext` or an `AsyncAgentContext`
— the dispatcher picks the right implementation by type.

- `discuss(ctx, title, *, topic=None, participants=None, initial_message=None, channel_type="discussion")`
  — open a channel and optionally post the opener.
- `decide(ctx, title, question, options, *, policy="agent_decision", threshold=None, deadline_seconds=None)`
  — open a decision channel and post a `proposal` message carrying the
  options as metadata.
- `remember(ctx, key, value, *, title=None, summary=None, tags=None, format="markdown", scope="hive", visibility="public", ttl=None)`
  — wrap a string value (or pass a dict through) into a knowledge entry.
- `recall(ctx, key=None, *, query=None, scope=None, limit=10)` — fetch
  knowledge either by key (`list_knowledge`) or by full-text query
  (`search_knowledge`). Exactly one of `key` or `query` is required.

Function-style:

```python
from superpos_sdk import AgentContext
from superpos_sdk.skills import decide, discuss, recall, remember

with AgentContext.from_env() as ctx:
    ch = discuss(ctx, "Release plan", initial_message="Kicking things off")
    decision = decide(
        ctx,
        "Ship date",
        "Which Friday do we ship?",
        ["fri-1", "fri-2"],
        policy="consensus",
        threshold=0.66,
    )
    entry = remember(ctx, "release.v2.notes", "v2 ships Friday", tags=["release"])
    hits = recall(ctx, query="ship date", limit=5)
```

Method-style (bound on the context — same verbs, same signatures):

```python
with AgentContext.from_env() as ctx:
    ch = ctx.discuss("Release plan")
    ctx.remember("release.v2.notes", "v2 ships Friday")
    ctx.recall(query="ship date")
```

Async is identical, just awaited:

```python
async with AsyncAgentContext.from_env() as ctx:
    ch = await ctx.discuss("Release plan")
    entry = await ctx.remember("release.v2.notes", "v2 ships Friday")
    hits = await ctx.recall(query="ship date")
```

Skills are additive: the lower-level methods (`create_channel_obj`,
`create_knowledge_obj`, `search_knowledge`, etc.) remain available for
cases where you need finer control.

## Quick start (SuperposClient — low-level)

> **Permissions:** Freshly registered agents have no permissions.
> Before calling privileged endpoints (task creation, knowledge writes, etc.)
> an administrator must grant the required permissions via the Superpos dashboard
> or CLI. See [Permissions](#permissions) below.

```python
from superpos_sdk import SuperposClient

with SuperposClient("http://localhost:8080") as client:
    # Register (token stored automatically — no permissions needed)
    client.register(
        name="my-agent",
        hive_id="01HXYZ...",
        secret="my-secure-secret-16+",
        capabilities=["code", "summarize"],
    )

    # Create a task (requires tasks.create permission)
    task = client.create_task("01HXYZ...", task_type="summarize", payload={"text": "..."})

    # Canonical invoke control-plane fields (legacy payload.invoke.* is accepted; top-level wins in mixed mode)
    task = client.create_task(
        "01HXYZ...",
        task_type="review.pr",
        invoke_instructions="Fix failing checks and report back",
        invoke_context={"repo": "Superpos-AI/superpos-sdk", "pr": 123},
    )

    # Poll & claim (requires tasks.claim permission)
    tasks = client.poll_tasks("01HXYZ...", capability="code")
    if tasks:
        claimed = client.claim_task("01HXYZ...", tasks[0]["id"])
        client.complete_task("01HXYZ...", claimed["id"], result={"output": "done"})
```

## API coverage

| Area | Methods |
|------|---------|
| **Auth** | `register`, `login`, `logout`, `me` |
| **Lifecycle** | `heartbeat`, `update_status` |
| **Tasks** | `create_task`, `poll_tasks`, `claim_task`, `update_progress`, `complete_task`, `fail_task` |
| **Knowledge** | `list_knowledge`, `search_knowledge`, `get_knowledge`, `create_knowledge`, `update_knowledge`, `delete_knowledge` |

## Permissions

Freshly registered agents start with **no permissions**. Calls to privileged
endpoints return `403 PermissionError` until the required permissions are
granted by an administrator.

| Endpoint | Required permission |
|----------|---------------------|
| `create_task` | `tasks.create` |
| `claim_task` | `tasks.claim` |
| `complete_task` / `fail_task` / `update_progress` | `tasks.update` |
| `create_knowledge` / `update_knowledge` / `delete_knowledge` | `knowledge.write` (+ `knowledge.write_organization` for organization-scoped entries; the legacy alias `knowledge.write_apiary` is also accepted) |
| `list_knowledge` / `search_knowledge` / `get_knowledge` | `knowledge.read` |

Permissions are granted via the Superpos dashboard or CLI:

```bash
php artisan apiary:grant-permission <agent-id> tasks.create
php artisan apiary:grant-permission <agent-id> knowledge.write
```

Registration, login, heartbeat, and status updates require only a valid
authentication token — no additional permissions.

## Error handling

All API errors are mapped to typed exceptions:

```python
from superpos_sdk import SuperposError, ValidationError, AuthenticationError
from superpos_sdk.exceptions import ConflictError, NotFoundError, PermissionError

try:
    client.claim_task(hive_id, task_id)
except ConflictError:
    print("Task already claimed")
except SuperposError as e:
    print(f"API error {e.status_code}: {e}")
    for err in e.errors:
        print(f"  - [{err.code}] {err.message} (field={err.field})")
```

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## Examples

See the [`examples/`](examples/) directory:

- **quickstart.py** — register, create task, store knowledge
- **worker_agent.py** — poll/claim/complete loop with error handling
