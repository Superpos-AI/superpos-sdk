"""Sync implementations of the high-level agent skills.

See :mod:`superpos_sdk.skills` for the public façade.

Every function takes a sync :class:`~superpos_sdk.agent.AgentContext` as
its first positional argument and composes existing SDK calls — no new
REST endpoints, no silent invention.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from superpos_sdk.constants import RESOLUTION_POLICIES

if TYPE_CHECKING:
    from superpos_sdk.agent import AgentContext
    from superpos_sdk.resources import Channel, KnowledgeEntry


def _resolution_policy_for(
    policy: str,
    *,
    threshold: float | None,
) -> dict[str, Any]:
    """Resolve a named policy to a full dict, applying *threshold* when given."""
    base = RESOLUTION_POLICIES.get(policy)
    if base is None:
        # Unknown label — pass through as an opaque ``type``.
        resolved: dict[str, Any] = {"type": policy}
    else:
        resolved = copy.deepcopy(base)
    if threshold is not None:
        resolved["threshold"] = threshold
    return resolved


def _stale_after_from_deadline(deadline_seconds: int | None) -> int | None:
    """Convert a deadline in seconds to ``stale_after`` minutes (rounded up)."""
    if deadline_seconds is None:
        return None
    minutes, rem = divmod(max(0, int(deadline_seconds)), 60)
    if rem:
        minutes += 1
    return minutes


def discuss(
    ctx: AgentContext,
    title: str,
    *,
    topic: str | None = None,
    participants: list[dict[str, Any]] | None = None,
    initial_message: str | None = None,
    channel_type: str = "discussion",
) -> Channel:
    """Create a channel and optionally post an opener.

    Args:
        ctx: Sync agent context.
        title: Channel title.
        topic: Optional short description of the discussion.
        participants: Initial participant list (``agent_id``/``user_id`` + ``role``).
        initial_message: When given, this is posted after channel creation
            as a ``discussion`` message.
        channel_type: Channel type (default ``"discussion"``).

    Returns:
        A :class:`Channel` wrapper around the created channel. When
        *initial_message* is posted, the wrapper's local state is
        refreshed so ``ch.updated_at`` reflects the post.
    """
    ch = ctx.create_channel_obj(
        title=title,
        channel_type=channel_type,
        topic=topic,
        participants=participants,
    )
    if initial_message is not None:
        ch.post(initial_message)
    return ch


def decide(
    ctx: AgentContext,
    title: str,
    question: str,
    options: list[str] | list[dict[str, Any]],
    *,
    participants: list[dict[str, Any]] | None = None,
    policy: str = "agent_decision",
    threshold: float | None = None,
    deadline_seconds: int | None = None,
) -> Channel:
    """Open a decision channel carrying a proposal.

    Creates a channel (``channel_type='discussion'``) with a
    ``resolution_policy`` derived from *policy*, then posts a
    ``proposal`` message carrying *question* and *options* in metadata.

    This function **does not wait** for a verdict — resolution happens
    asynchronously as agents vote. Use the returned channel wrapper to
    observe state (``ch.refresh()``; ``ch.status``).

    Args:
        ctx: Sync agent context.
        title: Channel title.
        question: Human-readable decision question (posted as message body).
        options: Proposal options. Strings are normalised to
            ``{"key": "<str>", "label": "<str>"}`` dicts; callers may
            pass full option dicts directly.
        participants: Initial participant list.
        policy: Resolution policy label — one of
            :data:`~superpos_sdk.constants.RESOLUTION_POLICIES` keys, or a
            custom label that is passed through as ``{"type": policy}``.
        threshold: Optional threshold merged into the resolution policy.
        deadline_seconds: Optional deadline expressed in seconds; converted
            to ``stale_after`` minutes (rounded up).

    Returns:
        A :class:`Channel` wrapper with the proposal already posted.
    """
    resolution_policy = _resolution_policy_for(policy, threshold=threshold)
    stale_after = _stale_after_from_deadline(deadline_seconds)

    normalised_options: list[dict[str, Any]] = []
    for opt in options:
        if isinstance(opt, str):
            normalised_options.append({"key": opt, "label": opt})
        else:
            normalised_options.append(dict(opt))

    ch = ctx.create_channel_obj(
        title=title,
        channel_type="discussion",
        topic=question,
        participants=participants,
        resolution_policy=resolution_policy,
        stale_after=stale_after,
    )
    ch.post(
        question,
        message_type="proposal",
        metadata={"options": normalised_options},
    )
    return ch


def remember(
    ctx: AgentContext,
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
) -> KnowledgeEntry:
    """Write a knowledge entry.

    If *value* is a :class:`str` it is wrapped into the canonical shape
    ``{"title", "content", "format", "summary", "tags"}``. If *value* is
    a :class:`dict` it is passed through unchanged — callers who need a
    bespoke value shape take full control.

    Args:
        ctx: Sync agent context.
        key: Knowledge entry key.
        value: Entry value (``str`` or ``dict``; other shapes passed through).
        scope: Knowledge scope (default ``"hive"``).
        visibility: ``"public"`` or ``"private"``.
        ttl: Optional TTL expression.
        tags: Tags merged into the wrapped value when *value* is a string.
        format: Format label for the wrapped value (default ``"markdown"``).
        title: Title for the wrapped value; defaults to *key*.
        summary: Optional summary stored alongside a wrapped value.

    Returns:
        A :class:`KnowledgeEntry` wrapper around the created entry.
    """
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

    return ctx.create_knowledge_obj(
        key=key,
        value=value_payload,
        scope=scope,
        visibility=visibility,
        ttl=ttl,
    )


def recall(
    ctx: AgentContext,
    key: str | None = None,
    *,
    query: str | None = None,
    scope: str | None = None,
    limit: int = 10,
) -> list[KnowledgeEntry]:
    """Look up knowledge by key or full-text query.

    Exactly one of *key* / *query* must be provided. *key* triggers a
    direct key lookup via :meth:`AgentContext.list_knowledge`; *query*
    triggers a full-text search via :meth:`AgentContext.search_knowledge`.

    Args:
        ctx: Sync agent context.
        key: Knowledge entry key (exact match).
        query: Free-text search query.
        scope: Optional scope filter.
        limit: Maximum entries to return (default 10).

    Returns:
        List of :class:`KnowledgeEntry` wrappers (possibly empty).
    """
    if key is None and query is None:
        raise ValueError("recall(): one of 'key' or 'query' must be provided.")
    if key is not None and query is not None:
        raise ValueError("recall(): pass only one of 'key' or 'query', not both.")

    from superpos_sdk.resources import KnowledgeEntry  # noqa: PLC0415

    if key is not None:
        rows = ctx.list_knowledge(key=key, scope=scope, limit=limit)
    else:
        rows = ctx.search_knowledge(q=query, scope=scope, limit=limit)
    return [KnowledgeEntry(row, ctx) for row in rows or []]


__all__ = ["decide", "discuss", "recall", "remember"]
