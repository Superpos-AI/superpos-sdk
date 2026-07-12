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
    def type(self) -> str | None:
        """Typed-page kind (e.g. ``proposal``, ``note``)."""
        return self._data.get("type")

    @property
    def slug(self) -> str | None:
        """Typed-page slug."""
        return self._data.get("slug")

    @property
    def title(self) -> str | None:
        """Typed-page title."""
        return self._data.get("title")

    @property
    def body(self) -> str | None:
        """Typed-page body (full content)."""
        return self._data.get("body")

    @property
    def summary(self) -> str | None:
        """Typed-page summary / excerpt."""
        return self._data.get("summary")

    @property
    def frontmatter(self) -> dict[str, Any]:
        """Typed-page frontmatter mapping (defaults to ``{}``)."""
        return self._data.get("frontmatter") or {}

    @property
    def tags(self) -> list[str]:
        """Typed-page tags (defaults to ``[]``)."""
        return self._data.get("tags") or []

    @property
    def source_ids(self) -> list[str]:
        """IDs of the entry's source references (defaults to ``[]``)."""
        return self._data.get("source_ids") or []

    @property
    def value(self) -> Any:
        """Deprecated legacy ``value`` field (removed from the API response).

        Retained only as a backward-compatibility alias; it returns whatever
        ``value`` is present in the underlying dict (``None`` for modern typed
        responses). Use the typed accessors (``body``/``title``/…) instead.
        """
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
        value: Any = None,
        *,
        type: str | None = None,
        slug: str | None = None,
        title: str | None = None,
        body: str | None = None,
        summary: str | None = None,
        frontmatter: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> KnowledgeEntry:
        """Update the entry (bumps ``version``). Merges the response back.

        Prefer the typed fields (``body``/``title``/…). The positional
        ``value`` argument is deprecated; it is converted to the typed ``body``
        field before sending.
        """
        self._check_alive()
        updated = self._ctx.update_knowledge(
            self.id,
            type=type,
            slug=slug,
            title=title,
            body=body,
            summary=summary,
            frontmatter=frontmatter,
            tags=tags,
            visibility=visibility,
            ttl=ttl,
            value=value,
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
