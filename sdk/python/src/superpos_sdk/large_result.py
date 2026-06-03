"""Large result delivery helper for the Superpos SDK.

When a task result exceeds the size threshold (default 1 MB), the worker
stores it in the Knowledge Store and returns a reference ID instead of
embedding the full payload in the completion request.  Consumers retrieve
the content separately via ``GET /knowledge/{entry_id}``.

Usage::

    from superpos_sdk import SuperposClient
    from superpos_sdk.large_result import LargeResultDelivery

    client = SuperposClient("https://superpos.example.com", token="...")
    delivery = LargeResultDelivery(client)

    # Automatically stores large payloads in the knowledge store.
    completion = delivery.deliver(task_id, hive_id, big_data)
    client.complete_task(
        hive_id,
        task_id,
        **completion,
    )
"""

from __future__ import annotations

import json
from typing import Any

from superpos_sdk.client import SuperposClient

#: Result payloads larger than this threshold (in bytes) are stored in the
#: Knowledge Store rather than inlined in the completion request.
LARGE_RESULT_THRESHOLD_BYTES: int = 1_000_000  # 1 MB


class LargeResultDelivery:
    """Helper that transparently offloads large task results to the Knowledge Store.

    When the serialised result exceeds :attr:`THRESHOLD_BYTES`, the payload is
    written to a new ``hive``-scoped knowledge entry (key
    ``task-result:<task_id>``).  The completion call then uses
    ``delivery_mode="knowledge"`` and carries the entry ID rather than the
    full result.

    For results below the threshold the helper returns the data inline so the
    caller can use the same code path regardless of size.

    Args:
        client: An authenticated :class:`~superpos_sdk.client.SuperposClient`.
        threshold_bytes: Override the default 1 MB threshold.
    """

    THRESHOLD_BYTES: int = LARGE_RESULT_THRESHOLD_BYTES

    def __init__(
        self,
        client: SuperposClient,
        *,
        threshold_bytes: int = LARGE_RESULT_THRESHOLD_BYTES,
    ) -> None:
        self._client = client
        self.threshold_bytes = threshold_bytes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deliver(
        self,
        task_id: str,
        hive_id: str,
        data: Any,
        *,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Prepare a task completion payload, offloading to Knowledge Store if needed.

        If the JSON-serialised *data* exceeds :attr:`threshold_bytes` the
        content is written to a new knowledge entry and the method returns a
        ``knowledge`` delivery descriptor.  Otherwise the data is returned
        inline.

        Args:
            task_id: ID of the task being completed (used to generate the
                knowledge entry key when *key* is not supplied).
            hive_id: Hive that owns both the task and knowledge entry.
            data: Result data (must be JSON-serialisable).
            key: Optional knowledge entry key override.  Defaults to
                ``"task-result:<task_id>"``.

        Returns:
            A dict suitable for passing as ``**kwargs`` to
            :meth:`~superpos_sdk.client.SuperposClient.complete_task`::

                # inline (small result):
                {"result": {...}}

                # knowledge (large result):
                {"delivery_mode": "knowledge", "knowledge_entry_id": "01ABC..."}
        """
        # Normalise scalars to a dict so both paths send a valid JSON object to
        # the API (which only accepts array/object payloads for `result`).
        normalised = data if isinstance(data, (dict, list)) else {"__value": data}

        serialized = json.dumps(normalised, separators=(",", ":"))
        encoded_bytes = len(serialized.encode("utf-8"))

        if encoded_bytes <= self.threshold_bytes:
            return {"result": normalised}

        entry_id = self._store_in_knowledge(hive_id, task_id, normalised, key=key)
        return {"delivery_mode": "knowledge", "knowledge_entry_id": entry_id}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_in_knowledge(
        self,
        hive_id: str,
        task_id: str,
        data: Any,
        *,
        key: str | None = None,
    ) -> str:
        """Write *data* to the Knowledge Store and return the entry ID."""
        entry_key = key or f"task-result:{task_id}"

        entry = self._client.create_knowledge(
            hive_id,
            key=entry_key,
            value=data,
            scope="hive",
            visibility="public",
        )

        return entry["id"]
