"""Stream delivery helpers for incremental task result delivery.

Stream delivery mode allows a task to deliver results as a sequence of
child tasks (chunks) rather than one final result.  The parent task stays
``in_progress`` while chunks are delivered one by one; the consumer polls
for ``stream_chunk`` child tasks to read the stream incrementally.

Usage inside a :class:`~superpos_sdk.service_worker.ServiceWorker`::

    class SearchWorker(ServiceWorker):
        CAPABILITY = "data:search"

        def search(self, params):
            task_id = self._current_task_id  # set during _process()
            with self.open_stream(task_id) as stream:
                for i, result in enumerate(fetch_results(params)):
                    stream.send_chunk({"result": result}, sequence=i)
            # is_final=True is sent automatically on context-manager exit.
            return {}  # parent will be completed by the stream

Or directly via :class:`StreamingTask`::

    stream = StreamingTask(client, hive_id, task_id)
    stream.send_chunk({"text": "Hello"}, sequence=0)
    stream.send_chunk({"text": " world"}, sequence=1)
    stream.complete(final_data={"text": "Hello world"})
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpos_sdk.client import SuperposClient


class StreamingTask:
    """Helper for delivering task results as a stream of chunks.

    Each call to :meth:`send_chunk` creates one ``stream_chunk`` child task
    via ``POST /api/v1/hives/{hive}/tasks/{task}/stream-chunk``.

    Calling :meth:`complete` (or exiting the context manager without an
    exception) sends a final chunk with ``is_final=True``, which marks the
    parent task as completed on the server.

    Args:
        client: Authenticated :class:`~superpos_sdk.client.SuperposClient`.
        hive_id: The hive that owns the parent task.
        task_id: ID of the ``in_progress`` parent task with
            ``delivery_mode='stream'``.
        auto_sequence: When *True* (default), the sequence number is
            auto-incremented locally.  Pass *False* to supply explicit
            sequence numbers to :meth:`send_chunk`.
    """

    def __init__(
        self,
        client: SuperposClient,
        hive_id: str,
        task_id: str,
        *,
        auto_sequence: bool = True,
    ) -> None:
        self._client = client
        self._hive_id = hive_id
        self._task_id = task_id
        self._auto_sequence = auto_sequence
        self._next_sequence: int = 0
        self._finalized: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_chunk(
        self,
        data: dict[str, Any],
        *,
        sequence: int | None = None,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Deliver one chunk to the stream.

        Args:
            data: Chunk payload — any JSON-serialisable dict.
            sequence: Explicit sequence number.  When *auto_sequence* is
                enabled and *sequence* is ``None``, the next local counter
                value is used.
            status_message: Optional human-readable message stored on the
                chunk task.

        Returns:
            The API response dict containing ``chunk`` and ``parent`` keys.

        Raises:
            RuntimeError: If :meth:`complete` has already been called.
            :class:`~superpos_sdk.exceptions.SuperposError`: On API errors.
        """
        if self._finalized:
            raise RuntimeError("StreamingTask is already finalized — cannot send more chunks.")

        seq = self._resolve_sequence(sequence)

        return self._send(data=data, sequence=seq, is_final=False, status_message=status_message)

    def complete(
        self,
        final_data: dict[str, Any] | None = None,
        *,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Mark the stream as complete.

        Sends a final chunk with ``is_final=True``, which causes the server
        to mark the parent task as *completed*.

        Args:
            final_data: Optional data payload for the final chunk.  Defaults
                to ``{}`` when not supplied.
            status_message: Optional human-readable message.

        Returns:
            The API response dict containing ``chunk`` and ``parent`` keys.

        Raises:
            RuntimeError: If :meth:`complete` has already been called.
            :class:`~superpos_sdk.exceptions.SuperposError`: On API errors.
        """
        if self._finalized:
            raise RuntimeError("StreamingTask is already finalized.")

        seq = self._resolve_sequence(None)
        data = final_data if final_data is not None else {}

        try:
            return self._send(data=data, sequence=seq, is_final=True, status_message=status_message)
        finally:
            self._finalized = True

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> StreamingTask:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        """Complete the stream on clean exit; suppress nothing on error."""
        if exc_type is None and not self._finalized:
            self.complete()
        return False  # Never suppress exceptions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_sequence(self, explicit: int | None) -> int:
        if explicit is not None:
            if self._auto_sequence:
                # Keep local counter in sync when explicit values are supplied.
                self._next_sequence = explicit + 1
            return explicit
        seq = self._next_sequence
        self._next_sequence += 1
        return seq

    def _send(
        self,
        *,
        data: dict[str, Any],
        sequence: int,
        is_final: bool,
        status_message: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "data": data,
            "sequence": sequence,
            "is_final": is_final,
        }
        if status_message is not None:
            body["status_message"] = status_message
        return self._client._request(  # noqa: SLF001
            "POST",
            f"/api/v1/hives/{self._hive_id}/tasks/{self._task_id}/stream-chunk",
            json=body,
        )
