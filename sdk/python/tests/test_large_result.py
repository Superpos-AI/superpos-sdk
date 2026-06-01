"""Tests for LargeResultDelivery and SuperposClient.complete_task_large()."""

from __future__ import annotations

import json

from superpos_sdk import LargeResultDelivery, SuperposClient
from superpos_sdk.large_result import LARGE_RESULT_THRESHOLD_BYTES

from .conftest import BASE_URL, ENTRY_ID, HIVE_ID, TASK_ID, TOKEN, envelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SMALL_RESULT = {"output": "hello world"}
LARGE_RESULT = {"data": "x" * (LARGE_RESULT_THRESHOLD_BYTES + 1)}

_ENTRY_DATA = {
    "id": ENTRY_ID,
    "organization_id": "A" * 26,
    "hive_id": HIVE_ID,
    "key": f"task-result:{TASK_ID}",
    "value": LARGE_RESULT,
    "scope": "hive",
    "visibility": "public",
    "created_by": "01AGENT00000000000000000001",
    "version": 1,
    "ttl": None,
    "created_at": "2026-02-26T12:00:00Z",
    "updated_at": "2026-02-26T12:00:00Z",
}

_COMPLETED_TASK = {
    "id": TASK_ID,
    "hive_id": HIVE_ID,
    "status": "completed",
    "knowledge_entry_id": ENTRY_ID,
    "result": None,
}

_COMPLETED_TASK_INLINE = {
    "id": TASK_ID,
    "hive_id": HIVE_ID,
    "status": "completed",
    "knowledge_entry_id": None,
    "result": SMALL_RESULT,
}


# ---------------------------------------------------------------------------
# LargeResultDelivery.deliver()
# ---------------------------------------------------------------------------


class TestLargeResultDeliveryDeliver:
    """Unit tests for LargeResultDelivery.deliver() sizing logic."""

    def test_small_result_returns_inline(self, httpx_mock):
        """Results below the threshold are returned inline with no HTTP calls."""
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, SMALL_RESULT)

        assert result == {"result": SMALL_RESULT}

    def test_large_result_stores_in_knowledge(self, httpx_mock):
        """Results above the threshold are stored in the knowledge store."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, LARGE_RESULT)

        assert result == {
            "delivery_mode": "knowledge",
            "knowledge_entry_id": ENTRY_ID,
        }
        assert "result" not in result

    def test_large_result_uses_task_id_as_key(self, httpx_mock):
        """The generated knowledge entry key includes the task ID."""
        captured: list[dict] = []

        def capture(request, response):  # noqa: ANN001
            captured.append(json.loads(request.content))

        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            delivery.deliver(TASK_ID, HIVE_ID, LARGE_RESULT)

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["key"] == f"task-result:{TASK_ID}"

    def test_custom_key_is_used(self, httpx_mock):
        """A custom key overrides the default ``task-result:<id>`` pattern."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope({**_ENTRY_DATA, "key": "my-custom-key"}),
            status_code=201,
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            delivery.deliver(TASK_ID, HIVE_ID, LARGE_RESULT, key="my-custom-key")

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["key"] == "my-custom-key"

    def test_threshold_override_respected(self, httpx_mock):
        """A custom threshold triggers offloading at a lower byte count."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )

        tiny_result = {"x": "y"}  # well below default 1 MB
        encoded = len(json.dumps(tiny_result, separators=(",", ":")).encode("utf-8"))

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client, threshold_bytes=encoded - 1)
            result = delivery.deliver(TASK_ID, HIVE_ID, tiny_result)

        # Should have offloaded despite being tiny because threshold was lowered
        assert result["delivery_mode"] == "knowledge"
        assert result["knowledge_entry_id"] == ENTRY_ID

    def test_exactly_at_threshold_is_inline(self, httpx_mock):
        """A payload exactly at the threshold (not over) is returned inline."""
        # Build a dict whose JSON encoding is exactly THRESHOLD_BYTES bytes
        threshold = 20  # small threshold for test isolation
        content = "a" * (threshold - len('{"x":""}'))
        tiny_result = {"x": content}
        encoded = json.dumps(tiny_result, separators=(",", ":")).encode("utf-8")
        assert len(encoded) == threshold

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client, threshold_bytes=threshold)
            result = delivery.deliver(TASK_ID, HIVE_ID, tiny_result)

        assert "result" in result
        assert "delivery_mode" not in result


# ---------------------------------------------------------------------------
# SuperposClient.complete_task() with knowledge fields
# ---------------------------------------------------------------------------


class TestCompleteTaskKnowledge:
    """Tests for the knowledge delivery kwargs on complete_task()."""

    def test_complete_task_sends_knowledge_fields(self, httpx_mock):
        """complete_task() passes delivery_mode and knowledge_entry_id to the API."""
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            result = client.complete_task(
                HIVE_ID,
                TASK_ID,
                delivery_mode="knowledge",
                knowledge_entry_id=ENTRY_ID,
            )

        assert result["knowledge_entry_id"] == ENTRY_ID
        assert result["result"] is None

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["delivery_mode"] == "knowledge"
        assert body["knowledge_entry_id"] == ENTRY_ID

    def test_complete_task_inline_omits_knowledge_fields(self, httpx_mock):
        """complete_task() without knowledge kwargs omits those fields from the body."""
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK_INLINE),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            client.complete_task(HIVE_ID, TASK_ID, result=SMALL_RESULT)

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert "delivery_mode" not in body
        assert "knowledge_entry_id" not in body


# ---------------------------------------------------------------------------
# SuperposClient.complete_task_large()
# ---------------------------------------------------------------------------


class TestCompleteTaskLarge:
    def test_small_result_completes_inline(self, httpx_mock):
        """Small results go through the normal inline completion path."""
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK_INLINE),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            result = client.complete_task_large(HIVE_ID, TASK_ID, SMALL_RESULT)

        assert result["status"] == "completed"

        requests = httpx_mock.get_requests()
        assert len(requests) == 1  # only the complete call
        body = json.loads(requests[0].content)
        assert body["result"] == SMALL_RESULT
        assert "delivery_mode" not in body

    def test_large_result_stores_then_completes_knowledge(self, httpx_mock):
        """Large results are stored in knowledge then completed with a reference."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            result = client.complete_task_large(HIVE_ID, TASK_ID, LARGE_RESULT)

        assert result["status"] == "completed"
        assert result["knowledge_entry_id"] == ENTRY_ID

        requests = httpx_mock.get_requests()
        assert len(requests) == 2  # POST /knowledge + PATCH /complete

        complete_body = json.loads(requests[1].content)
        assert complete_body["delivery_mode"] == "knowledge"
        assert complete_body["knowledge_entry_id"] == ENTRY_ID
        assert "result" not in complete_body

    def test_status_message_forwarded(self, httpx_mock):
        """status_message is forwarded to the complete call."""
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK_INLINE),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            client.complete_task_large(HIVE_ID, TASK_ID, SMALL_RESULT, status_message="done")

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["status_message"] == "done"

    def test_threshold_bytes_override_respected(self, httpx_mock):
        """A custom threshold_bytes causes tiny results to be offloaded."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK),
        )

        tiny = {"x": 1}

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            client.complete_task_large(HIVE_ID, TASK_ID, tiny, threshold_bytes=1)

        requests = httpx_mock.get_requests()
        assert len(requests) == 2  # knowledge store + complete


# ---------------------------------------------------------------------------
# Scalar result wrapping — consistent contract regardless of payload size
# ---------------------------------------------------------------------------


class TestScalarResultWrapping:
    """Scalars (str, int, bool, None) must be wrapped as {"__value": scalar}
    on BOTH the small-payload inline path and the large-payload knowledge path
    so the API always receives a valid JSON object.
    """

    def test_string_scalar_small_payload_wrapped_inline(self):
        """A string result below the threshold is wrapped as {"__value": str} inline."""
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, "ok")

        assert result == {"result": {"__value": "ok"}}

    def test_int_scalar_small_payload_wrapped_inline(self, httpx_mock):
        """An integer result below the threshold is wrapped as {"__value": int} inline."""
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, 42)

        assert result == {"result": {"__value": 42}}

    def test_bool_scalar_small_payload_wrapped_inline(self, httpx_mock):
        """A bool result below the threshold is wrapped as {"__value": bool} inline."""
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, True)

        assert result == {"result": {"__value": True}}

    def test_string_scalar_large_payload_wrapped_in_knowledge(self, httpx_mock):
        """A string result above the threshold is wrapped as {"__value": str} in the knowledge
        store."""
        captured: list[dict] = []

        def capture(request, response):  # noqa: ANN001
            captured.append(json.loads(request.content))

        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )

        # Use a threshold of 1 so the string definitely exceeds it.
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client, threshold_bytes=1)
            result = delivery.deliver(TASK_ID, HIVE_ID, "a large string result")

        assert result["delivery_mode"] == "knowledge"
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["value"] == {"__value": "a large string result"}

    def test_int_scalar_large_payload_wrapped_in_knowledge(self, httpx_mock):
        """An integer result above the threshold is wrapped as {"__value": int} in the knowledge
        store."""
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope(_ENTRY_DATA),
            status_code=201,
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client, threshold_bytes=1)
            result = delivery.deliver(TASK_ID, HIVE_ID, 99)

        assert result["delivery_mode"] == "knowledge"
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["value"] == {"__value": 99}

    def test_complete_task_large_string_scalar_inline_is_wrapped(self, httpx_mock):
        """complete_task_large() wraps a string scalar in {"__value": ...} for the inline path."""
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            json=envelope(_COMPLETED_TASK_INLINE),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as client:
            client.complete_task_large(HIVE_ID, TASK_ID, "ok")

        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content)
        assert body["result"] == {"__value": "ok"}
        assert "delivery_mode" not in body

    def test_list_result_is_not_wrapped(self):
        """A list result (already a valid JSON array) is passed through unchanged."""
        list_result = [1, 2, 3]
        with SuperposClient(BASE_URL, token=TOKEN) as client:
            delivery = LargeResultDelivery(client)
            result = delivery.deliver(TASK_ID, HIVE_ID, list_result)

        assert result == {"result": [1, 2, 3]}
