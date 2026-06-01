"""Async OOP wrapper around a task dict.

Async counterpart of :class:`superpos_sdk.resources.Task`. Attribute reads
are synchronous; every method that issues an HTTP call is ``async def``.
``refresh()`` re-fetches the task via
``GET /api/v1/hives/{hive}/tasks/{task}``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.async_agent import AsyncAgentContext


class AsyncTask:
    """Agent-facing async wrapper around a task dict."""

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
        """Task ULID."""
        return self._data["id"]

    @property
    def type(self) -> str | None:
        """Task type."""
        return self._data.get("type") or self._data.get("task_type")

    @property
    def status(self) -> str | None:
        """Task status."""
        return self._data.get("status")

    @property
    def payload(self) -> Any:
        """Task payload — opaque JSON."""
        return self._data.get("payload")

    @property
    def result(self) -> Any:
        """Task result once completed, otherwise ``None``."""
        return self._data.get("result")

    @property
    def priority(self) -> int | None:
        """Scheduling priority."""
        return self._data.get("priority")

    @property
    def progress(self) -> int | None:
        """Last reported progress (0-100)."""
        return self._data.get("progress")

    @property
    def status_message(self) -> str | None:
        """Human-readable status message, if set."""
        return self._data.get("status_message")

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
        """Return a shallow copy of the underlying task dict."""
        return dict(self._data)

    def __repr__(self) -> str:
        return f"AsyncTask(id={self.id!r}, type={self.type!r}, status={self.status!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AsyncTask):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def refresh(self) -> AsyncTask:
        """Re-fetch task state from the server.

        Issues ``GET /api/v1/hives/{hive}/tasks/{task}`` and merges the
        response back into local state. Requires ``tasks.read`` on the
        bound agent.
        """
        fresh = await self._ctx.raw.get_task(self._ctx._require_hive(), self.id)
        if not isinstance(fresh, dict):
            raise ValueError(
                f"AsyncTask.refresh(): get_task returned {type(fresh).__name__}, expected dict"
            )
        self._data.update(fresh)
        return self

    async def trace(self) -> dict[str, Any]:
        """Return the full execution trace for this task."""
        return await self._ctx.raw.get_task_trace(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def claim(self) -> AsyncTask:
        """Atomically claim a pending task. Merges the response back into state."""
        claimed = await self._ctx.claim_task(self.id)
        if isinstance(claimed, dict):
            self._data.update(claimed)
        return self

    async def update_progress(
        self,
        progress: int,
        *,
        status_message: str | None = None,
    ) -> AsyncTask:
        """Report progress (0-100). Merges the response back into state."""
        updated = await self._ctx.update_progress(
            self.id,
            progress=progress,
            status_message=status_message,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def complete(
        self,
        result: dict[str, Any] | list | None = None,
        *,
        status_message: str | None = None,
        delivery_mode: str | None = None,
        knowledge_entry_id: str | None = None,
    ) -> AsyncTask:
        """Mark the task completed. Merges the response back into state."""
        updated = await self._ctx.complete_task(
            self.id,
            result=result,
            status_message=status_message,
            delivery_mode=delivery_mode,
            knowledge_entry_id=knowledge_entry_id,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def fail(
        self,
        error: dict[str, Any] | None = None,
        *,
        status_message: str | None = None,
    ) -> AsyncTask:
        """Mark the task failed. Merges the response back into state."""
        updated = await self._ctx.fail_task(
            self.id,
            error=error,
            status_message=status_message,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    async def replay(
        self,
        *,
        override_payload: dict[str, Any] | None = None,
    ) -> AsyncTask:
        """Replay this task. Returns a **new** :class:`AsyncTask` wrapping the replay."""
        replayed = await self._ctx.raw.replay_task(
            self._ctx._require_hive(),
            self.id,
            override_payload=override_payload,
        )
        return AsyncTask(replayed, self._ctx)


__all__ = ["AsyncTask"]
