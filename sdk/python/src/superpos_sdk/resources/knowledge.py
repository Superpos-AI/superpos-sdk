"""OOP wrapper around a knowledge-entry dict.

See :class:`KnowledgeEntry`. Constructed by
:meth:`superpos_sdk.agent.AgentContext.knowledge`,
:meth:`superpos_sdk.agent.AgentContext.create_knowledge_obj`, and
:meth:`superpos_sdk.agent.AgentContext.list_knowledge_obj`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.agent import AgentContext


class KnowledgeEntry:
    """Agent-facing wrapper around a knowledge-entry dict.

    After :meth:`delete` succeeds the wrapper is marked as deleted and
    subsequent mutating calls raise :class:`RuntimeError`. Attribute reads
    still work so callers can inspect the final state.
    """

    __slots__ = ("_ctx", "_data", "_deleted")

    def __init__(self, data: dict[str, Any], ctx: AgentContext) -> None:
        """Wrap *data* with a bound :class:`AgentContext`."""
        self._data: dict[str, Any] = dict(data)
        self._ctx = ctx
        self._deleted: bool = False

    # ------------------------------------------------------------------
    # Attributes
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Knowledge entry ULID."""
        return self._data["id"]

    @property
    def key(self) -> str | None:
        """Knowledge entry key."""
        return self._data.get("key")

    @property
    def value(self) -> Any:
        """Knowledge entry value (opaque JSON)."""
        return self._data.get("value")

    @property
    def scope(self) -> str | None:
        """Knowledge scope (``hive``, ``organization``, ``agent:<id>``).

        ``organization`` is the canonical organization-wide scope. The legacy
        value ``apiary`` is a deprecated alias: it is still accepted on writes
        (normalized to ``organization``) but new entries are stored and
        returned as ``organization``.
        """
        return self._data.get("scope")

    @property
    def visibility(self) -> str | None:
        """``public`` or ``private``."""
        return self._data.get("visibility")

    @property
    def version(self) -> int | None:
        """Entry version (bumps on every update)."""
        return self._data.get("version")

    @property
    def ttl(self) -> str | None:
        """TTL expression, if set."""
        return self._data.get("ttl")

    @property
    def created_at(self) -> str | None:
        """ISO-8601 creation timestamp."""
        return self._data.get("created_at")

    @property
    def updated_at(self) -> str | None:
        """ISO-8601 last-update timestamp."""
        return self._data.get("updated_at")

    @property
    def deleted(self) -> bool:
        """``True`` once :meth:`delete` has been called successfully."""
        return self._deleted

    # ------------------------------------------------------------------
    # Dict / equality / repr
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the underlying knowledge-entry dict."""
        return dict(self._data)

    def __repr__(self) -> str:
        return f"KnowledgeEntry(id={self.id!r}, key={self.key!r}, version={self.version!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KnowledgeEntry):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_alive(self) -> None:
        if self._deleted:
            raise RuntimeError("knowledge entry already deleted")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def refresh(self) -> KnowledgeEntry:
        """Re-fetch the entry and merge the result into local state."""
        self._check_alive()
        fresh = self._ctx.get_knowledge(self.id)
        if isinstance(fresh, dict):
            self._data.update(fresh)
        return self

    def links(
        self,
        *,
        target_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List knowledge links whose source is this entry."""
        self._check_alive()
        return self._ctx.raw.list_knowledge_links(
            self._ctx._require_hive(),
            source_id=self.id,
            target_type=target_type,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def update(
        self,
        value: Any,
        *,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> KnowledgeEntry:
        """Update the entry's value (bumps ``version``). Merges the response back."""
        self._check_alive()
        updated = self._ctx.update_knowledge(
            self.id,
            value=value,
            visibility=visibility,
            ttl=ttl,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def delete(self) -> None:
        """Delete the entry. After this returns, the wrapper is marked deleted."""
        self._check_alive()
        self._ctx.delete_knowledge(self.id)
        self._deleted = True

    def link_to(
        self,
        target: str,
        *,
        target_type: str = "knowledge",
        link_type: str = "relates_to",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a link from this entry to another entity. Returns the link dict."""
        self._check_alive()
        if target_type == "knowledge":
            return self._ctx.raw.create_knowledge_link(
                self._ctx._require_hive(),
                self.id,
                target_id=target,
                target_type=target_type,
                link_type=link_type,
                metadata=metadata,
            )
        return self._ctx.raw.create_knowledge_link(
            self._ctx._require_hive(),
            self.id,
            target_ref=target,
            target_type=target_type,
            link_type=link_type,
            metadata=metadata,
        )

    def unlink(self, link_id: str) -> None:
        """Delete a knowledge link by its ID."""
        self._check_alive()
        self._ctx.raw.delete_knowledge_link(self._ctx._require_hive(), link_id)


__all__ = ["KnowledgeEntry"]
