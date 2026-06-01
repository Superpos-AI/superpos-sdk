"""Async OOP wrapper around a channel dict.

Async counterpart of :class:`superpos_sdk.resources.Channel`. Attribute
reads are synchronous (they hit ``self._data`` only); every method that
issues an HTTP call is ``async def``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.async_agent import AsyncAgentContext


class AsyncChannel:
    """Agent-facing async wrapper around a channel dict."""

    __slots__ = ("_ctx", "_data")

    def __init__(self, data: dict[str, Any], ctx: AsyncAgentContext) -> None:
        """Wrap *data* with a bound :class:`AsyncAgentContext`."""
        self._data: dict[str, Any] = dict(data)
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Attributes (synchronous)
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Channel ULID."""
        return self._data["id"]

    @property
    def title(self) -> str | None:
        """Channel title."""
        return self._data.get("title")

    @property
    def channel_type(self) -> str | None:
        """Channel type (``discussion``, ``review``, ``planning``, ``incident``)."""
        return self._data.get("channel_type") or self._data.get("type")

    @property
    def status(self) -> str | None:
        """Channel status."""
        return self._data.get("status")

    @property
    def topic(self) -> str | None:
        """Channel topic."""
        return self._data.get("topic")

    @property
    def resolution_policy(self) -> dict[str, Any] | None:
        """Resolution policy dict, if configured."""
        return self._data.get("resolution_policy")

    @property
    def created_at(self) -> str | None:
        """ISO-8601 creation timestamp."""
        return self._data.get("created_at")

    @property
    def updated_at(self) -> str | None:
        """ISO-8601 last-update timestamp."""
        return self._data.get("updated_at")

    # ------------------------------------------------------------------
    # Dict / equality / repr
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the underlying channel dict."""
        return dict(self._data)

    def __repr__(self) -> str:
        return f"AsyncChannel(id={self.id!r}, title={self.title!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AsyncChannel):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def refresh(self) -> AsyncChannel:
        """Re-fetch the channel and merge the result into local state."""
        fresh = await self._ctx.get_channel(self.id)
        if isinstance(fresh, dict):
            self._data.update(fresh)
        return self

    async def messages(
        self,
        *,
        since: str | None = None,
        after_id: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List messages in this channel."""
        return await self._ctx.list_messages(
            self.id,
            since=since,
            after_id=after_id,
            page=page,
            per_page=per_page,
        )

    async def participants(self) -> list[dict[str, Any]]:
        """Return participants from a fresh fetch."""
        await self.refresh()
        return list(self._data.get("participants") or [])

    async def summary(self) -> dict[str, Any]:
        """Lightweight summary for the authenticated agent (unread, mentions, ...)."""
        return await self._ctx.raw.channel_summary(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write — messages
    # ------------------------------------------------------------------

    async def post(
        self,
        content: str,
        *,
        message_type: str = "discussion",
        mentions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to this channel. Refreshes local state on success."""
        result = await self._ctx.post_message(
            self.id,
            content,
            message_type=message_type,
            mentions=mentions,
            metadata=metadata,
            reply_to=reply_to,
        )
        await self.refresh()
        return result

    async def mark_read(self) -> dict[str, Any]:
        """Mark the channel as read for the authenticated agent."""
        return await self._ctx.raw.mark_channel_read(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write — participants
    # ------------------------------------------------------------------

    async def invite(
        self,
        participant_id: str,
        *,
        participant_type: str = "agent",
        role: str = "contributor",
        mention_policy: str | None = None,
    ) -> dict[str, Any]:
        """Add a participant. Refreshes local state on success."""
        result = await self._ctx.add_participant(
            self.id,
            participant_type,
            participant_id,
            role=role,
            mention_policy=mention_policy,
        )
        await self.refresh()
        return result

    async def remove_participant(self, participant_id: str) -> None:
        """Remove a participant from this channel."""
        await self._ctx.raw.remove_channel_participant(
            self._ctx._require_hive(), self.id, participant_id
        )
        await self.refresh()

    # ------------------------------------------------------------------
    # Write — lifecycle
    # ------------------------------------------------------------------

    async def resolve(
        self,
        outcome: str,
        *,
        materialized_tasks: list[dict[str, Any]] | None = None,
    ) -> AsyncChannel:
        """Resolve the channel. Merges the server response back into local state."""
        updated = await self._ctx.resolve_channel(
            self.id,
            outcome=outcome,
            materialized_tasks=materialized_tasks,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def reopen(self) -> AsyncChannel:
        """Reopen a resolved or stale channel. Refreshes local state."""
        updated = await self._ctx.raw.reopen_channel(self._ctx._require_hive(), self.id)
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def archive(self) -> AsyncChannel:
        """Archive the channel (soft delete). Merges response back."""
        updated = await self._ctx.archive_channel(self.id)
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def materialize(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create tasks from a resolved channel's outcome. Returns the task dicts."""
        return await self._ctx.raw.materialize_channel(self._ctx._require_hive(), self.id, tasks)


__all__ = ["AsyncChannel"]
