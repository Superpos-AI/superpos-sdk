"""OOP wrapper around a channel dict.

See :class:`Channel`. Constructed by
:meth:`superpos_sdk.agent.AgentContext.channel`,
:meth:`superpos_sdk.agent.AgentContext.create_channel_obj`, and
:meth:`superpos_sdk.agent.AgentContext.list_channels_obj`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.agent import AgentContext


class Channel:
    """Agent-facing wrapper around a channel dict.

    The wrapper holds two things: the channel dict returned by the API
    (``_data``) and the :class:`AgentContext` that fetched it. Attribute
    access reads from ``_data``; mutating methods call the context and
    merge the response back into ``_data`` so the wrapper never returns
    stale state after a write.
    """

    __slots__ = ("_ctx", "_data")

    def __init__(self, data: dict[str, Any], ctx: AgentContext) -> None:
        """Wrap *data* with a bound :class:`AgentContext`."""
        self._data: dict[str, Any] = dict(data)
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Attributes
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Channel ULID."""
        return self._data["id"]

    @property
    def title(self) -> str | None:
        """Channel title (may be absent on legacy responses)."""
        return self._data.get("title")

    @property
    def channel_type(self) -> str | None:
        """Channel type (``discussion``, ``review``, ``planning``, ``incident``)."""
        return self._data.get("channel_type") or self._data.get("type")

    @property
    def status(self) -> str | None:
        """Channel status (``open``, ``deliberating``, ``resolved``, ...)."""
        return self._data.get("status")

    @property
    def topic(self) -> str | None:
        """Optional topic / short description."""
        return self._data.get("topic")

    def participants(self) -> list[dict[str, Any]]:
        """Return participants from a fresh fetch.

        Refreshes the wrapper and returns the updated participants list.
        """
        self.refresh()
        return list(self._data.get("participants") or [])

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
        return f"Channel(id={self.id!r}, title={self.title!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Channel):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def refresh(self) -> Channel:
        """Re-fetch the channel and merge the result into local state.

        Returns ``self`` for fluent chaining.
        """
        fresh = self._ctx.get_channel(self.id)
        if isinstance(fresh, dict):
            self._data.update(fresh)
        return self

    def messages(
        self,
        *,
        since: str | None = None,
        after_id: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List messages in this channel (thin wrapper over the context)."""
        return self._ctx.list_messages(
            self.id,
            since=since,
            after_id=after_id,
            page=page,
            per_page=per_page,
        )

    def summary(self) -> dict[str, Any]:
        """Lightweight summary for the authenticated agent (unread, mentions, ...)."""
        return self._ctx.raw.channel_summary(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write — messages
    # ------------------------------------------------------------------

    def post(
        self,
        content: str,
        *,
        message_type: str = "discussion",
        mentions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to this channel. Returns the created message dict.

        After a successful write the wrapper calls :meth:`refresh` so that
        cached attributes (``updated_at``, etc.) reflect server-side changes.
        """
        result = self._ctx.post_message(
            self.id,
            content,
            message_type=message_type,
            mentions=mentions,
            metadata=metadata,
            reply_to=reply_to,
        )
        self.refresh()
        return result

    def mark_read(self) -> dict[str, Any]:
        """Mark the channel as read for the authenticated agent."""
        return self._ctx.raw.mark_channel_read(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write — participants
    # ------------------------------------------------------------------

    def invite(
        self,
        participant_id: str,
        *,
        participant_type: str = "agent",
        role: str = "contributor",
        mention_policy: str | None = None,
    ) -> dict[str, Any]:
        """Add a participant (defaults to ``participant_type='agent'``).

        After a successful write the wrapper calls :meth:`refresh` so that
        cached attributes (``participants``, ``updated_at``, etc.) reflect
        server-side changes.
        """
        result = self._ctx.add_participant(
            self.id,
            participant_type,
            participant_id,
            role=role,
            mention_policy=mention_policy,
        )
        self.refresh()
        return result

    def remove_participant(self, participant_id: str) -> None:
        """Remove a participant from this channel.

        After a successful write the wrapper calls :meth:`refresh` so that
        cached attributes (``participants``, ``updated_at``, etc.) reflect
        server-side changes.
        """
        self._ctx.raw.remove_channel_participant(self._ctx._require_hive(), self.id, participant_id)
        self.refresh()

    # ------------------------------------------------------------------
    # Write — lifecycle
    # ------------------------------------------------------------------

    def resolve(
        self,
        outcome: str,
        *,
        materialized_tasks: list[dict[str, Any]] | None = None,
    ) -> Channel:
        """Resolve the channel. Merges the server response back into local state."""
        updated = self._ctx.resolve_channel(
            self.id,
            outcome=outcome,
            materialized_tasks=materialized_tasks,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def reopen(self) -> Channel:
        """Reopen a resolved or stale channel. Refreshes local state."""
        updated = self._ctx.raw.reopen_channel(self._ctx._require_hive(), self.id)
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def archive(self) -> Channel:
        """Archive the channel (soft delete). Merges response back into local state."""
        updated = self._ctx.archive_channel(self.id)
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def materialize(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create tasks from a resolved channel's outcome. Returns the task dicts."""
        return self._ctx.raw.materialize_channel(self._ctx._require_hive(), self.id, tasks)


__all__ = ["Channel"]
