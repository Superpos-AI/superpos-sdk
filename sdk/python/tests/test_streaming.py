"""Tests for StreamingTask and ServiceWorker streaming integration."""

from __future__ import annotations

import pytest

from superpos_sdk import ServiceWorker, StreamingTask, SuperposClient, SuperposError

from .conftest import BASE_URL, HIVE_ID, TASK_ID, TOKEN, envelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STREAM_TASK_DATA = {
    "id": TASK_ID,
    "organization_id": "A" * 26,
    "hive_id": HIVE_ID,
    "type": "stream_test",
    "delivery_mode": "stream",
    "status": "in_progress",
    "priority": 2,
    "payload": {"operation": "generate", "params": {}},
    "stream_sequence": None,
    "stream_parent_id": None,
    "stream_complete": False,
    "progress": 0,
    "claimed_by": "01AGENT00000000000000000001",
    "created_at": "2026-04-01T10:00:00Z",
}

CHUNK_TASK_DATA = {
    "id": "01CHUNK0000000000000000001",
    "type": "stream_chunk",
    "delivery_mode": "default",
    "stream_sequence": 0,
    "stream_parent_id": TASK_ID,
    "stream_complete": False,
    "status": "completed",
    "payload": {"text": "hello"},
}

CHUNK_RESPONSE = {
    "chunk": CHUNK_TASK_DATA,
    "parent": STREAM_TASK_DATA,
}

FINAL_CHUNK_RESPONSE = {
    "chunk": {**CHUNK_TASK_DATA, "stream_complete": True},
    "parent": {**STREAM_TASK_DATA, "status": "completed"},
}

AGENT_DATA = {
    "id": "01AGENT00000000000000000001",
    "token": TOKEN,
}


def _stream_chunk_url(task_id: str = TASK_ID) -> str:
    return f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{task_id}/stream-chunk"


# ---------------------------------------------------------------------------
# StreamingTask.send_chunk()
# ---------------------------------------------------------------------------


class TestStreamingTaskSendChunk:
    def _stream(self, client: SuperposClient) -> StreamingTask:
        return StreamingTask(client, HIVE_ID, TASK_ID)

    def test_send_chunk_posts_to_stream_chunk_endpoint(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        result = stream.send_chunk({"text": "hello"}, sequence=0)
        assert result["chunk"]["stream_sequence"] == 0

    def test_send_chunk_includes_sequence_in_body(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.send_chunk({"x": 1}, sequence=5)
        req = httpx_mock.get_requests()[0]
        import json

        body = json.loads(req.content)
        assert body["sequence"] == 5
        assert body["is_final"] is False

    def test_send_chunk_auto_increments_sequence(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.send_chunk({"x": 1})
        stream.send_chunk({"x": 2})

        import json

        requests = httpx_mock.get_requests()
        assert json.loads(requests[0].content)["sequence"] == 0
        assert json.loads(requests[1].content)["sequence"] == 1

    def test_send_chunk_raises_after_finalize(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.complete()
        with pytest.raises(RuntimeError, match="already finalized"):
            stream.send_chunk({"x": 1})


# ---------------------------------------------------------------------------
# StreamingTask.complete()
# ---------------------------------------------------------------------------


class TestStreamingTaskComplete:
    def _stream(self, client: SuperposClient) -> StreamingTask:
        return StreamingTask(client, HIVE_ID, TASK_ID)

    def test_complete_sends_is_final_true(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.complete(final_data={"summary": "done"})

        import json

        req = httpx_mock.get_requests()[0]
        body = json.loads(req.content)
        assert body["is_final"] is True
        assert body["data"] == {"summary": "done"}

    def test_complete_marks_stream_finalized(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.complete()
        assert stream._finalized is True

    def test_complete_raises_if_called_twice(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.complete()
        with pytest.raises(RuntimeError, match="already finalized"):
            stream.complete()

    def test_complete_sends_empty_data_when_none(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        stream = self._stream(authed_client)
        stream.complete()

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["data"] == {}


# ---------------------------------------------------------------------------
# StreamingTask context manager
# ---------------------------------------------------------------------------


class TestStreamingTaskContextManager:
    def test_context_manager_auto_completes_on_clean_exit(self, authed_client, httpx_mock):
        # send_chunk call
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        # complete() call from __exit__
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        with StreamingTask(authed_client, HIVE_ID, TASK_ID) as stream:
            stream.send_chunk({"x": 1}, sequence=0)

        assert stream._finalized is True
        assert len(httpx_mock.get_requests()) == 2

    def test_context_manager_does_not_complete_if_already_finalized(
        self, authed_client, httpx_mock
    ):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        with StreamingTask(authed_client, HIVE_ID, TASK_ID) as stream:
            stream.complete()

        # Only one request (the explicit complete()), not two.
        assert len(httpx_mock.get_requests()) == 1

    def test_context_manager_does_not_suppress_exceptions(self, authed_client, httpx_mock):
        with pytest.raises(ValueError, match="boom"):
            with StreamingTask(authed_client, HIVE_ID, TASK_ID):
                raise ValueError("boom")


# ---------------------------------------------------------------------------
# SuperposClient.send_stream_chunk()
# ---------------------------------------------------------------------------


class TestClientSendStreamChunk:
    def test_send_stream_chunk_method_exists(self, authed_client):
        assert callable(getattr(authed_client, "send_stream_chunk", None))

    def test_send_stream_chunk_posts_correctly(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        result = authed_client.send_stream_chunk(HIVE_ID, TASK_ID, data={"text": "hi"}, sequence=3)
        assert result["chunk"]["stream_sequence"] == 0  # from mock

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["sequence"] == 3
        assert body["is_final"] is False

    def test_send_stream_chunk_final(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )
        authed_client.send_stream_chunk(HIVE_ID, TASK_ID, data={}, is_final=True)

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["is_final"] is True


# ---------------------------------------------------------------------------
# ServiceWorker streaming integration
# ---------------------------------------------------------------------------


class StreamWorker(ServiceWorker):
    """Worker that exposes stream_process() for testing."""

    CAPABILITY = "data:stream"

    def __init__(self, *args, stream_results=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_results = stream_results or ["chunk1", "chunk2"]
        self._stream_call_count = 0

    def stream_process(self, task, stream):
        self._stream_call_count += 1
        for i, text in enumerate(self._stream_results):
            stream.send_chunk({"text": text}, sequence=i)


STREAM_CHUNKS_RESPONSE = {
    "data": [
        {
            "id": "01CHUNK0000000000000000001",
            "result": {"text": "hello"},
            "stream_sequence": 0,
            "created_at": "2026-04-01T10:00:00Z",
        },
        {
            "id": "01CHUNK0000000000000000002",
            "result": {"text": "world"},
            "stream_sequence": 1,
            "created_at": "2026-04-01T10:00:01Z",
        },
    ],
    "meta": {"parent_task_id": TASK_ID, "stream_complete": True, "count": 2},
}


def _stream_chunks_url(task_id: str = TASK_ID) -> str:
    return f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{task_id}/stream-chunks"


# ---------------------------------------------------------------------------
# SuperposClient.get_stream_chunks()
# ---------------------------------------------------------------------------


class TestClientGetStreamChunks:
    def test_get_stream_chunks_method_exists(self, authed_client):
        assert callable(getattr(authed_client, "get_stream_chunks", None))

    def test_get_stream_chunks_calls_correct_endpoint(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunks_url(),
            method="GET",
            status_code=200,
            json=STREAM_CHUNKS_RESPONSE,
        )
        result = authed_client.get_stream_chunks(HIVE_ID, TASK_ID)
        assert len(result["data"]) == 2
        assert result["meta"]["count"] == 2

    def test_get_stream_chunks_returns_ordered_chunks(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunks_url(),
            method="GET",
            status_code=200,
            json=STREAM_CHUNKS_RESPONSE,
        )
        result = authed_client.get_stream_chunks(HIVE_ID, TASK_ID)
        sequences = [c["stream_sequence"] for c in result["data"]]
        assert sequences == sorted(sequences)

    def test_get_stream_chunks_includes_parent_meta(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_stream_chunks_url(),
            method="GET",
            status_code=200,
            json=STREAM_CHUNKS_RESPONSE,
        )
        result = authed_client.get_stream_chunks(HIVE_ID, TASK_ID)
        assert result["meta"]["parent_task_id"] == TASK_ID
        assert result["meta"]["stream_complete"] is True


# ---------------------------------------------------------------------------
# ServiceWorker double-completion bug fix
# ---------------------------------------------------------------------------


class TestServiceWorkerNoDoubleComplete:
    """Bug #1: _process() must NOT call complete_task() after stream_process().

    The stream is already finalised by send_stream_chunk(is_final=True) inside
    the StreamingTask context manager / stream.complete().  Calling
    complete_task() afterward would cause a 409 double-completion.
    """

    def _worker(self) -> StreamWorker:
        return StreamWorker(BASE_URL, HIVE_ID, token=TOKEN, claim_type="data_request")

    def test_stream_process_does_not_double_complete(self, httpx_mock):
        """complete_task() must NOT be called after stream_process() returns."""
        w = self._worker()

        # claim response
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            method="PATCH",
            status_code=200,
            json=envelope(STREAM_TASK_DATA),
        )
        # two send_chunk calls from StreamWorker.stream_process()
        for _ in range(2):
            httpx_mock.add_response(
                url=_stream_chunk_url(),
                method="POST",
                status_code=200,
                json=envelope(CHUNK_RESPONSE),
            )
        # final complete() called automatically by _process() when not finalized
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )

        w._process({"id": TASK_ID, "type": "data_request"})

        # Verify complete_task() (PATCH .../complete) was never called.
        complete_reqs = [r for r in httpx_mock.get_requests() if r.url.path.endswith("/complete")]
        assert complete_reqs == [], (
            f"complete_task() was called {len(complete_reqs)} time(s) after "
            "stream_process() — this causes a 409 double-completion"
        )

    def test_stream_process_only_uses_stream_chunk_endpoint(self, httpx_mock):
        """All HTTP calls must go to the stream-chunk endpoint, not complete."""
        w = self._worker()

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            method="PATCH",
            status_code=200,
            json=envelope(STREAM_TASK_DATA),
        )
        for _ in range(2):
            httpx_mock.add_response(
                url=_stream_chunk_url(),
                method="POST",
                status_code=200,
                json=envelope(CHUNK_RESPONSE),
            )
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )

        w._process({"id": TASK_ID, "type": "data_request"})

        # Only claim + 3 stream-chunk requests — no complete/fail endpoints.
        non_stream_non_claim = [
            r
            for r in httpx_mock.get_requests()
            if "stream-chunk" not in str(r.url) and "claim" not in str(r.url)
        ]
        assert non_stream_non_claim == [], "Unexpected requests to non-stream endpoints: " + str(
            [str(r.url) for r in non_stream_non_claim]
        )


class TestServiceWorkerStreamingIntegration:
    def _worker(self) -> StreamWorker:
        return StreamWorker(BASE_URL, HIVE_ID, token=TOKEN, claim_type="data_request")

    def test_open_stream_returns_streaming_task(self):
        w = self._worker()
        stream = w.open_stream(TASK_ID)
        assert isinstance(stream, StreamingTask)
        assert stream._task_id == TASK_ID
        assert stream._hive_id == HIVE_ID

    def test_stream_process_not_implemented_in_base_class(self):
        w = ServiceWorker(BASE_URL, HIVE_ID, token=TOKEN)
        with pytest.raises(NotImplementedError, match="stream_process"):
            w.stream_process({}, StreamingTask(w.client, HIVE_ID, TASK_ID))

    def test_process_routes_stream_task_to_stream_process(self, httpx_mock):
        w = self._worker()

        # claim response
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            method="PATCH",
            status_code=200,
            json=envelope(STREAM_TASK_DATA),
        )
        # two send_chunk calls
        for _ in range(2):
            httpx_mock.add_response(
                url=_stream_chunk_url(),
                method="POST",
                status_code=200,
                json=envelope(CHUNK_RESPONSE),
            )
        # auto-complete call from __exit__ / stream finalization
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json=envelope(FINAL_CHUNK_RESPONSE),
        )

        w._process({"id": TASK_ID, "type": "data_request"})

        assert w._stream_call_count == 1
        # 3 HTTP calls: 2 send_chunk + 1 complete
        stream_chunk_reqs = [r for r in httpx_mock.get_requests() if "stream-chunk" in str(r.url)]
        assert len(stream_chunk_reqs) == 3


# ---------------------------------------------------------------------------
# create_task delivery_mode wiring
# ---------------------------------------------------------------------------


_TASKS_URL = f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks"


class TestCreateTaskDeliveryMode:
    """create_task() must forward delivery_mode in the request body."""

    def test_create_task_default_delivery_mode(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_TASKS_URL,
            method="POST",
            status_code=201,
            json=envelope({**STREAM_TASK_DATA, "delivery_mode": "default", "status": "pending"}),
        )
        authed_client.create_task(HIVE_ID, task_type="stream_test")

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["delivery_mode"] == "default"

    def test_create_task_stream_delivery_mode(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_TASKS_URL,
            method="POST",
            status_code=201,
            json=envelope(STREAM_TASK_DATA),
        )
        authed_client.create_task(HIVE_ID, task_type="stream_test", delivery_mode="stream")

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["delivery_mode"] == "stream"


# ---------------------------------------------------------------------------
# data_request() uses default delivery_mode
# ---------------------------------------------------------------------------


class TestDataRequestDeliveryMode:
    """data_request() must create tasks with the default delivery mode.

    Forcing delivery_mode='stream' on every data_request() broke the normal
    service-worker pattern where an operation handler just returns a dict.
    The stream path ignored that return value and never called complete_task(),
    leaving the parent task stuck in_progress.  The fix is to omit
    delivery_mode (server defaults to 'default') unless the caller explicitly
    passes it.
    """

    def test_data_request_sends_default_delivery_mode(self, authed_client, httpx_mock):
        httpx_mock.add_response(
            url=_TASKS_URL,
            method="POST",
            status_code=201,
            json=envelope(STREAM_TASK_DATA),
        )
        authed_client.data_request(
            HIVE_ID,
            capability="data:search",
            operation="fetch",
        )

        import json

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body.get("delivery_mode", "default") == "default", (
            f"data_request() sent delivery_mode={body.get('delivery_mode')!r}, expected 'default'"
        )


# ---------------------------------------------------------------------------
# End-to-end: create stream task then send_stream_chunk()
# ---------------------------------------------------------------------------


class TestCreateStreamTaskAndChunk:
    """Creating a stream-mode task and immediately sending a chunk must work."""

    def test_create_stream_task_then_send_chunk(self, authed_client, httpx_mock):
        # Step 1: create the parent task with delivery_mode='stream'
        httpx_mock.add_response(
            url=_TASKS_URL,
            method="POST",
            status_code=201,
            json=envelope(STREAM_TASK_DATA),
        )
        task = authed_client.create_task(
            HIVE_ID,
            task_type="stream_test",
            delivery_mode="stream",
        )

        import json

        create_body = json.loads(httpx_mock.get_requests()[0].content)
        assert create_body["delivery_mode"] == "stream"
        assert task["delivery_mode"] == "stream"

        # Step 2: send a chunk — must use the stream-chunk endpoint, not /complete
        httpx_mock.add_response(
            url=_stream_chunk_url(task["id"]),
            method="POST",
            status_code=200,
            json=envelope(CHUNK_RESPONSE),
        )
        result = authed_client.send_stream_chunk(
            HIVE_ID,
            task["id"],
            data={"text": "hello"},
            sequence=0,
        )

        assert result["chunk"]["stream_sequence"] == 0
        chunk_req = httpx_mock.get_requests()[1]
        assert "stream-chunk" in str(chunk_req.url)
        chunk_body = json.loads(chunk_req.content)
        assert chunk_body["sequence"] == 0
        assert chunk_body["is_final"] is False


# ---------------------------------------------------------------------------
# Regression: StreamingTask finalization errors must propagate (not be swallowed)
# ---------------------------------------------------------------------------


class TestStreamingTaskFinalizationErrorPropagation:
    """Finalization errors from the final POST /stream-chunk must not be swallowed.

    Previously __exit__ caught SuperposError during the implicit complete() call
    and silently discarded it, leaving the parent task stuck in_progress on the
    server while the handler appeared to have succeeded locally.
    """

    def test_context_manager_exit_propagates_superpos_error_from_complete(
        self, authed_client, httpx_mock
    ):
        """SuperposError from the final stream-chunk POST must propagate out of the `with` block."""
        error_body = {
            "data": None,
            "meta": {},
            "errors": [{"message": "Service unavailable", "code": "server_error"}],
        }
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=503,
            json=error_body,
        )

        with pytest.raises(SuperposError):
            with StreamingTask(authed_client, HIVE_ID, TASK_ID):
                pass  # __exit__ triggers implicit complete(), which should raise

    def test_context_manager_exit_propagates_error_even_after_send_chunk(
        self, authed_client, httpx_mock
    ):
        """Finalization error propagates even when prior chunks succeeded."""
        # First chunk succeeds
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json={"data": CHUNK_RESPONSE, "meta": {}, "errors": None},
        )
        # Final implicit complete() fails with 5xx
        error_body = {
            "data": None,
            "meta": {},
            "errors": [{"message": "Service unavailable", "code": "server_error"}],
        }
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=503,
            json=error_body,
        )

        with pytest.raises(SuperposError):
            with StreamingTask(authed_client, HIVE_ID, TASK_ID) as stream:
                stream.send_chunk({"text": "hello"}, sequence=0)
            # __exit__ triggers complete(), which fails


# ---------------------------------------------------------------------------
# Regression: service_worker._process() must call fail_task() on finalization error
# ---------------------------------------------------------------------------


class HandleStreamWorker(ServiceWorker):
    """Worker that uses open_stream() inside an operation handler."""

    CAPABILITY = "data:stream_handle"

    def __init__(self, *args, fail_on_complete=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_on_complete = fail_on_complete

    def generate(self, params):  # noqa: ARG002
        with self.open_stream(self._current_task_id) as stream:
            stream.send_chunk({"text": "hello"}, sequence=0)
        # __exit__ sends the final complete() — if that fails, it should propagate


class TestServiceWorkerStreamFinalizationFailure:
    """_process() must call fail_task() when stream finalization raises SuperposError."""

    def _worker(self) -> HandleStreamWorker:
        return HandleStreamWorker(BASE_URL, HIVE_ID, token=TOKEN, claim_type="data_request")

    def _stream_task_data(self):
        return {**STREAM_TASK_DATA, "payload": {"operation": "generate", "params": {}}}

    def test_process_calls_fail_task_when_stream_finalisation_raises(self, httpx_mock):
        """When the final stream-chunk POST fails, _process() must call fail_task()."""
        w = self._worker()

        # claim response
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            method="PATCH",
            status_code=200,
            json={"data": self._stream_task_data(), "meta": {}, "errors": None},
        )
        # send_chunk succeeds
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json={"data": CHUNK_RESPONSE, "meta": {}, "errors": None},
        )
        # final complete() fails with transient 5xx
        finalize_error = {
            "data": None,
            "meta": {},
            "errors": [{"message": "Service unavailable", "code": "server_error"}],
        }
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=503,
            json=finalize_error,
        )
        # fail_task() call
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/fail",
            method="PATCH",
            status_code=200,
            json={"data": {**STREAM_TASK_DATA, "status": "failed"}, "meta": {}, "errors": None},
        )

        w._process({"id": TASK_ID, "type": "data_request"})

        # Verify fail_task() was called
        fail_reqs = [r for r in httpx_mock.get_requests() if r.url.path.endswith("/fail")]
        assert len(fail_reqs) == 1, (
            "fail_task() must be called exactly once when stream finalization fails"
        )

    def test_process_does_not_log_success_when_stream_finalisation_raises(self, httpx_mock):
        """Task must not be silently logged as completed when finalization fails."""
        w = self._worker()

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            method="PATCH",
            status_code=200,
            json={"data": self._stream_task_data(), "meta": {}, "errors": None},
        )
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=200,
            json={"data": CHUNK_RESPONSE, "meta": {}, "errors": None},
        )
        # Final complete() fails
        finalize_error = {
            "data": None,
            "meta": {},
            "errors": [{"message": "Service unavailable", "code": "server_error"}],
        }
        httpx_mock.add_response(
            url=_stream_chunk_url(),
            method="POST",
            status_code=503,
            json=finalize_error,
        )
        # fail_task() response
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/fail",
            method="PATCH",
            status_code=200,
            json={"data": {**STREAM_TASK_DATA, "status": "failed"}, "meta": {}, "errors": None},
        )

        w._process({"id": TASK_ID, "type": "data_request"})

        # complete_task() (PATCH .../complete) must NOT have been called
        complete_reqs = [r for r in httpx_mock.get_requests() if r.url.path.endswith("/complete")]
        assert complete_reqs == [], (
            "complete_task() must not be called when stream finalization fails"
        )
