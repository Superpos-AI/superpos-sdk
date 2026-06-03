"""OOP wrapper around a task dict.

See :class:`Task`. Usually obtained from
:meth:`superpos_sdk.agent.AgentContext.claim_next`,
:meth:`superpos_sdk.agent.AgentContext.task`, or by wrapping a dict
returned from :meth:`AgentContext.create_task` manually:
``Task(ctx.create_task(task_type='x'), ctx)``.

``Task.refresh()`` re-fetches the task via
``GET /api/v1/hives/{hive}/tasks/{task}``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.agent import AgentContext


class Task:
    """Agent-facing wrapper around a task dict.

    Holds the task dict returned by the API plus the :class:`AgentContext`
    that fetched it. Mutating methods refresh the local state from the
    response so the wrapper never exposes stale fields after a write.
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
        """Task ULID."""
        return self._data["id"]

    @property
    def type(self) -> str | None:
        """Task type (``task_type`` on the server)."""
        return self._data.get("type") or self._data.get("task_type")

    @property
    def status(self) -> str | None:
        """Task status (``pending``, ``in_progress``, ``completed``, ...)."""
        return self._data.get("status")

    @property
    def payload(self) -> Any:
        """Task payload — opaque JSON blob owned by the task type."""
        return self._data.get("payload")

    @property
    def result(self) -> Any:
        """Task result once completed, otherwise ``None``."""
        return self._data.get("result")

    @property
    def priority(self) -> int | None:
        """Scheduling priority (server-defined scale)."""
        return self._data.get("priority")

    @property
    def progress(self) -> int | None:
        """Last reported progress (0-100), if any."""
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
        return f"Task(id={self.id!r}, type={self.type!r}, status={self.status!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def refresh(self) -> Task:
        """Re-fetch task state from the server.

        Issues ``GET /api/v1/hives/{hive}/tasks/{task}`` and merges the
        response back into local state. Requires ``tasks.read`` on the
        bound agent.

        Raises :class:`ValueError` if the response is not a dict —
        callers should never silently work with stale data.
        """
        fresh = self._ctx.raw.get_task(self._ctx._require_hive(), self.id)
        if not isinstance(fresh, dict):
            raise ValueError(
                f"Task.refresh(): get_task returned {type(fresh).__name__}, expected dict"
            )
        self._data.update(fresh)
        return self

    def trace(self) -> dict[str, Any]:
        """Return the full execution trace for this task."""
        return self._ctx.raw.get_task_trace(self._ctx._require_hive(), self.id)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def claim(self) -> Task:
        """Atomically claim a pending task. Merges the response back into state."""
        claimed = self._ctx.claim_task(self.id)
        if isinstance(claimed, dict):
            self._data.update(claimed)
        return self

    def update_progress(
        self,
        progress: int,
        *,
        status_message: str | None = None,
    ) -> Task:
        """Report progress (0-100). Merges the response back into state."""
        updated = self._ctx.update_progress(
            self.id,
            progress=progress,
            status_message=status_message,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def complete(
        self,
        result: dict[str, Any] | list | None = None,
        *,
        status_message: str | None = None,
        delivery_mode: str | None = None,
        knowledge_entry_id: str | None = None,
    ) -> Task:
        """Mark the task completed. Merges the response back into state."""
        updated = self._ctx.complete_task(
            self.id,
            result=result,
            status_message=status_message,
            delivery_mode=delivery_mode,
            knowledge_entry_id=knowledge_entry_id,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def fail(
        self,
        error: dict[str, Any] | None = None,
        *,
        status_message: str | None = None,
    ) -> Task:
        """Mark the task failed. Merges the response back into state."""
        updated = self._ctx.fail_task(
            self.id,
            error=error,
            status_message=status_message,
        )
        if isinstance(updated, dict):
            self._data.update(updated)
        return self

    def replay(
        self,
        *,
        override_payload: dict[str, Any] | None = None,
    ) -> Task:
        """Replay this task. Returns a **new** :class:`Task` wrapping the replay."""
        replayed = self._ctx.raw.replay_task(
            self._ctx._require_hive(),
            self.id,
            override_payload=override_payload,
        )
        return Task(replayed, self._ctx)


__all__ = ["Task"]
