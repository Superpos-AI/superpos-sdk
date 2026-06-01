"""Async implementations of the high-level agent skills.

Parallel to :mod:`superpos_sdk.skills.sync_skills` — each function takes
an :class:`~superpos_sdk.async_agent.AsyncAgentContext` as its first
argument and is ``async def``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from superpos_sdk.skills.sync_skills import (
    _resolution_policy_for,
    _stale_after_from_deadline,
)

if TYPE_CHECKING:
    from superpos_sdk.async_agent import AsyncAgentContext
    from superpos_sdk.resources.async_resources import AsyncChannel, AsyncKnowledgeEntry


async def discuss(
    ctx: AsyncAgentContext,
    title: str,
    *,
    topic: str | None = None,
    participants: list[dict[str, Any]] | None = None,
    initial_message: str | None = None,
    channel_type: str = "discussion",
) -> AsyncChannel:
    """Async variant of :func:`superpos_sdk.skills.sync_skills.discuss`."""
    ch = await ctx.create_channel_obj(
        title=title,
        channel_type=channel_type,
        topic=topic,
        participants=participants,
    )
    if initial_message is not None:
        await ch.post(initial_message)
    return ch


async def decide(
    ctx: AsyncAgentContext,
    title: str,
    question: str,
    options: list[str] | list[dict[str, Any]],
    *,
    participants: list[dict[str, Any]] | None = None,
    policy: str = "agent_decision",
    threshold: float | None = None,
    deadline_seconds: int | None = None,
) -> AsyncChannel:
    """Async variant of :func:`superpos_sdk.skills.sync_skills.decide`."""
    resolution_policy = _resolution_policy_for(policy, threshold=threshold)
    stale_after = _stale_after_from_deadline(deadline_seconds)

    normalised_options: list[dict[str, Any]] = []
    for opt in options:
        if isinstance(opt, str):
            normalised_options.append({"key": opt, "label": opt})
        else:
            normalised_options.append(dict(opt))

    ch = await ctx.create_channel_obj(
        title=title,
        channel_type="discussion",
        topic=question,
        participants=participants,
        resolution_policy=resolution_policy,
        stale_after=stale_after,
    )
    await ch.post(
        question,
        message_type="proposal",
        metadata={"options": normalised_options},
    )
    return ch


async def remember(
    ctx: AsyncAgentContext,
    key: str,
    value: Any,
    *,
    scope: str = "hive",
    visibility: str = "public",
    ttl: str | None = None,
    tags: list[str] | None = None,
    format: str = "markdown",
    title: str | None = None,
    summary: str | None = None,
) -> AsyncKnowledgeEntry:
    """Async variant of :func:`superpos_sdk.skills.sync_skills.remember`."""
    if isinstance(value, str):
        wrapped: dict[str, Any] = {
            "title": title or key,
            "content": value,
            "format": format,
            "tags": list(tags or []),
        }
        if summary is not None:
            wrapped["summary"] = summary
        value_payload: Any = wrapped
    else:
        value_payload = value

    return await ctx.create_knowledge_obj(
        key=key,
        value=value_payload,
        scope=scope,
        visibility=visibility,
        ttl=ttl,
    )


async def recall(
    ctx: AsyncAgentContext,
    key: str | None = None,
    *,
    query: str | None = None,
    scope: str | None = None,
    limit: int = 10,
) -> list[AsyncKnowledgeEntry]:
    """Async variant of :func:`superpos_sdk.skills.sync_skills.recall`."""
    if key is None and query is None:
        raise ValueError("recall(): one of 'key' or 'query' must be provided.")
    if key is not None and query is not None:
        raise ValueError("recall(): pass only one of 'key' or 'query', not both.")

    from superpos_sdk.resources.async_resources import AsyncKnowledgeEntry  # noqa: PLC0415

    if key is not None:
        rows = await ctx.list_knowledge(key=key, scope=scope, limit=limit)
    else:
        rows = await ctx.search_knowledge(q=query, scope=scope, limit=limit)
    return [AsyncKnowledgeEntry(row, ctx) for row in rows or []]


__all__ = ["decide", "discuss", "recall", "remember"]
