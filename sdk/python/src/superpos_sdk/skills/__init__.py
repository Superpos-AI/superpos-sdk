"""High-level goal-oriented skills — Phase 3 of the agent-centric SDK.

Skills compose multiple SDK calls into common agent patterns:

- :func:`discuss` — create a channel and (optionally) post an opener.
- :func:`decide` — create a decision channel with a proposal message.
- :func:`remember` — persist a fact as a knowledge entry.
- :func:`recall` — look up knowledge by key or full-text query.

Each verb comes in sync and async flavors. The top-level symbols here
dispatch based on the context type — pass a sync
:class:`~superpos_sdk.agent.AgentContext` and you get a synchronous call
(result is a :class:`~superpos_sdk.resources.Channel` or
:class:`~superpos_sdk.resources.KnowledgeEntry`); pass an
:class:`~superpos_sdk.async_agent.AsyncAgentContext` and you get a
coroutine to ``await`` (result is an ``Async*`` wrapper).

Example (sync)::

    from superpos_sdk import AgentContext
    from superpos_sdk.skills import discuss, decide, remember, recall

    ctx = AgentContext.from_env()
    ch = discuss(ctx, title="Release schedule", topic="Pick a date")

Example (async)::

    from superpos_sdk import AsyncAgentContext
    from superpos_sdk.skills import discuss

    async with AsyncAgentContext.from_env() as ctx:
        ch = await discuss(ctx, title="Release schedule", topic="Pick a date")

The same verbs are also bound as methods on both context classes —
``ctx.discuss(...)`` / ``ctx.decide(...)`` / ``ctx.remember(...)`` /
``ctx.recall(...)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from superpos_sdk.skills import async_skills, sync_skills

if TYPE_CHECKING:  # pragma: no cover — typing only.
    from superpos_sdk.agent import AgentContext
    from superpos_sdk.async_agent import AsyncAgentContext


def _is_async(ctx: Any) -> bool:
    """Return ``True`` when *ctx* is an :class:`AsyncAgentContext`.

    We do an :class:`isinstance` check so the dispatcher is cheap and
    doesn't depend on accidental duck-typing (e.g. a test stub that
    exposes an unrelated ``async def post_message``).
    """
    # Local import to avoid import cycles at module load.
    from superpos_sdk.async_agent import AsyncAgentContext  # noqa: PLC0415

    return isinstance(ctx, AsyncAgentContext)


def discuss(ctx: AgentContext | AsyncAgentContext, *args: Any, **kwargs: Any) -> Any:
    """Dispatch :func:`sync_skills.discuss` / :func:`async_skills.discuss` by ctx type."""
    if _is_async(ctx):
        return async_skills.discuss(ctx, *args, **kwargs)
    return sync_skills.discuss(ctx, *args, **kwargs)


def decide(ctx: AgentContext | AsyncAgentContext, *args: Any, **kwargs: Any) -> Any:
    """Dispatch :func:`sync_skills.decide` / :func:`async_skills.decide` by ctx type."""
    if _is_async(ctx):
        return async_skills.decide(ctx, *args, **kwargs)
    return sync_skills.decide(ctx, *args, **kwargs)


def remember(ctx: AgentContext | AsyncAgentContext, *args: Any, **kwargs: Any) -> Any:
    """Dispatch :func:`sync_skills.remember` / :func:`async_skills.remember` by ctx type."""
    if _is_async(ctx):
        return async_skills.remember(ctx, *args, **kwargs)
    return sync_skills.remember(ctx, *args, **kwargs)


def recall(ctx: AgentContext | AsyncAgentContext, *args: Any, **kwargs: Any) -> Any:
    """Dispatch :func:`sync_skills.recall` / :func:`async_skills.recall` by ctx type."""
    if _is_async(ctx):
        return async_skills.recall(ctx, *args, **kwargs)
    return sync_skills.recall(ctx, *args, **kwargs)


__all__ = [
    "async_skills",
    "decide",
    "discuss",
    "recall",
    "remember",
    "sync_skills",
]
