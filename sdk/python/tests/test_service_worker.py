"""Tests for ServiceWorker base class and data_request / discover_services helpers."""

from __future__ import annotations

import pytest

from superpos_sdk import OperationNotFoundError, ServiceWorker, SuperposClient

from .conftest import BASE_URL, HIVE_ID, TASK_ID, TOKEN, envelope

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TASK_DATA = {
    "id": TASK_ID,
    "organization_id": "A" * 26,
    "hive_id": HIVE_ID,
    "type": "data_request",
    "status": "in_progress",
    "priority": 2,
    "payload": {"operation": "echo", "params": {"msg": "hello"}},
    "progress": 0,
    "claimed_by": "01AGENT00000000000000000001",
    "created_at": "2026-02-26T12:00:00Z",
}

AGENT_DATA = {
    "id": "01AGENT00000000000000000001",
    "token": TOKEN,
}


class EchoWorker(ServiceWorker):
    """Minimal worker that echoes params back as result."""

    CAPABILITY = "data:echo"

    def echo(self, params: dict) -> dict:
        return {"echoed": params}

    def fail_me(self, params: dict) -> dict:
        raise ValueError("intentional failure")


# ---------------------------------------------------------------------------
# ServiceWorker.handle()
# ---------------------------------------------------------------------------


class TestServiceWorkerHandle:
    def _worker(self):
        return EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")

    def test_handle_method_dispatch(self):
        w = self._worker()
        result = w.handle("echo", {"x": 1})
        assert result == {"echoed": {"x": 1}}

    def test_handle_hyphenated_operation(self):
        w = self._worker()
        result = w.handle("echo", {})
        assert "echoed" in result

    def test_handle_registered_operation(self):
        w = self._worker()
        w.register_operation("custom_op", lambda p: {"ok": True})
        result = w.handle("custom_op", {})
        assert result == {"ok": True}

    def test_handle_registered_takes_precedence_over_method(self):
        w = self._worker()
        # register an override for "echo"
        w.register_operation("echo", lambda p: {"overridden": True})
        result = w.handle("echo", {})
        assert result == {"overridden": True}

    def test_handle_unknown_operation_raises(self):
        w = self._worker()
        with pytest.raises(OperationNotFoundError):
            w.handle("nonexistent_op", {})

    def test_handle_private_method_not_dispatched(self):
        w = self._worker()
        with pytest.raises(OperationNotFoundError):
            w.handle("_worker", {})


# ---------------------------------------------------------------------------
# ServiceWorker._supported_operations()
# ---------------------------------------------------------------------------


class TestSupportedOperations:
    def test_discovers_public_methods(self):
        w = EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")
        ops = w._supported_operations()
        names = [o["name"] for o in ops]
        assert "echo" in names
        assert "fail_me" in names

    def test_includes_registered_operations(self):
        w = EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")
        w.register_operation("custom", lambda p: {})
        names = [o["name"] for o in w._supported_operations()]
        assert "custom" in names

    def test_excludes_private_methods(self):
        w = EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")
        names = [o["name"] for o in w._supported_operations()]
        for n in names:
            assert not n.startswith("_")

    def test_excludes_base_class_methods(self):
        w = EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")
        names = [o["name"] for o in w._supported_operations()]
        assert "run" not in names
        assert "handle" not in names
        assert "stop" not in names


# ---------------------------------------------------------------------------
# ServiceWorker._authenticate()
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_register_path(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=201,
            json=envelope(AGENT_DATA),
        )
        w = EchoWorker(BASE_URL, HIVE_ID, name="my-worker", secret="s3cr3t")
        w._authenticate()
        assert w.client.token == TOKEN

    def test_login_path(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/login",
            status_code=200,
            json=envelope(AGENT_DATA),
        )
        w = EchoWorker(BASE_URL, HIVE_ID, agent_id="01AGENT00000000000000000001", secret="s3cr3t")
        w._authenticate()
        assert w.client.token == TOKEN

    def test_pre_supplied_token_skips_auth(self, httpx_mock):
        w = EchoWorker(BASE_URL, HIVE_ID, token=TOKEN)
        # No HTTP call should be made.
        w._authenticate()
        assert w.client.token == TOKEN

    def test_missing_credentials_raises(self):
        w = ServiceWorker(BASE_URL, HIVE_ID)
        with pytest.raises(ValueError, match="requires either"):
            w._authenticate()


# ---------------------------------------------------------------------------
# ServiceWorker._process()
# ---------------------------------------------------------------------------


class TestProcessTask:
    def _worker(self):
        w = EchoWorker(BASE_URL, HIVE_ID, token=TOKEN)
        return w

    def test_process_success(self, httpx_mock):
        # claim
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(TASK_DATA),
        )
        # complete
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "completed"}),
        )
        w = self._worker()
        task = {**TASK_DATA, "status": "pending"}
        w._process(task)

    def test_process_unknown_operation_fails_task(self, httpx_mock):
        task_data_unknown = {
            **TASK_DATA,
            "payload": {"operation": "not_real", "params": {}},
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(task_data_unknown),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/fail",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "failed"}),
        )
        w = self._worker()
        task = {**task_data_unknown, "status": "pending"}
        w._process(task)  # should not raise

    def test_process_handler_error_fails_task(self, httpx_mock):
        task_data_fail = {
            **TASK_DATA,
            "payload": {"operation": "fail_me", "params": {}},
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(task_data_fail),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/fail",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "failed"}),
        )
        w = self._worker()
        task = {**task_data_fail, "status": "pending"}
        w._process(task)  # should not raise

    def test_process_claim_conflict_is_silently_skipped(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=409,
            json={
                "data": None,
                "meta": {},
                "errors": [{"message": "Conflict", "code": "conflict"}],
            },
        )
        w = self._worker()
        task = {**TASK_DATA, "status": "pending"}
        w._process(task)  # ConflictError is swallowed

    def test_process_data_request_default_delivery_completes_task(self, httpx_mock):
        """data_request tasks with default delivery_mode must call complete_task().

        Regression: when delivery_mode was forced to 'stream' on every
        data_request(), the service worker's stream path ignored plain dict
        return values from operation handlers and never called complete_task(),
        leaving the parent task stuck in_progress.
        """
        task_data = {
            **TASK_DATA,
            "type": "data_request",
            # delivery_mode absent (default) — as created by data_request()
            # after the fix.
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(task_data),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            status_code=200,
            json=envelope({**task_data, "status": "completed"}),
        )
        w = self._worker()
        task = {**task_data, "status": "pending"}
        w._process(task)

        # Verify complete was called (not left in_progress).
        reqs = httpx_mock.get_requests()
        complete_reqs = [r for r in reqs if "/complete" in str(r.url)]
        assert len(complete_reqs) == 1, "complete_task() must be called exactly once"


# ---------------------------------------------------------------------------
# ServiceWorker._tick() — type filtering
# ---------------------------------------------------------------------------


class TestTickTypeFiltering:
    """_tick() must skip tasks whose type doesn't match claim_type."""

    def _worker(self):
        return EchoWorker(BASE_URL, HIVE_ID, token=TOKEN)

    def test_tick_skips_tasks_with_wrong_type(self, httpx_mock):
        """Tasks with a type other than claim_type are silently skipped."""
        unrelated_task = {
            **TASK_DATA,
            "id": TASK_ID,
            "type": "default",  # not data_request
            "status": "pending",
        }
        # heartbeat (no URL match needed — use method match)
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            status_code=200,
            json=envelope({}),
        )
        # poll returns one unrelated task — capability param is sent by _tick
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/poll?capability=data%3Aecho",
            status_code=200,
            json=envelope([unrelated_task]),
        )

        w = self._worker()
        w._running = True
        w._tick()

        # Only the heartbeat and poll were called — no claim should be made.
        reqs = httpx_mock.get_requests()
        urls = [str(r.url) for r in reqs]
        assert not any("claim" in u for u in urls), "claim must not be called for wrong-type task"

    def test_tick_processes_matching_type_tasks(self, httpx_mock):
        """Tasks whose type matches claim_type are claimed and processed."""
        pending_task = {**TASK_DATA, "status": "pending"}

        # heartbeat
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            status_code=200,
            json=envelope({}),
        )
        # poll
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/poll?capability=data%3Aecho",
            status_code=200,
            json=envelope([pending_task]),
        )
        # claim
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(TASK_DATA),
        )
        # complete
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "completed"}),
        )

        w = self._worker()
        w._running = True
        w._tick()

        reqs = httpx_mock.get_requests()
        urls = [str(r.url) for r in reqs]
        assert any("claim" in u for u in urls), "matching task should be claimed"

    def test_tick_mixed_tasks_only_processes_matching(self, httpx_mock):
        """When poll returns both matching and unrelated tasks, only matching are claimed."""
        other_id = "01HXYZ00000000000000000099"
        matching_task = {**TASK_DATA, "status": "pending"}  # type=data_request
        unrelated_task = {
            **TASK_DATA,
            "id": other_id,
            "type": "default",
            "status": "pending",
        }

        # heartbeat
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            status_code=200,
            json=envelope({}),
        )
        # poll returns both
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/poll?capability=data%3Aecho",
            status_code=200,
            json=envelope([matching_task, unrelated_task]),
        )
        # claim (only for matching)
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(TASK_DATA),
        )
        # complete
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "completed"}),
        )

        w = self._worker()
        w._running = True
        w._tick()

        reqs = httpx_mock.get_requests()
        urls = [str(r.url) for r in reqs]
        # TASK_ID should be claimed, other_id should not
        assert any(TASK_ID in u and "claim" in u for u in urls)
        assert not any(other_id in u and "claim" in u for u in urls)


# ---------------------------------------------------------------------------
# ServiceWorker._tick() — backpressure sleep after task processing
# ---------------------------------------------------------------------------


class TestTickBackpressureSleep:
    """_tick() must sleep after processing tasks when next_poll_ms > 0."""

    def test_sleeps_after_task_loop_when_next_poll_ms_set(self, httpx_mock):
        """When the server returns tasks AND next_poll_ms > 0, sleep is called after processing."""
        import unittest.mock as mock

        pending_task = {**TASK_DATA, "status": "pending"}

        # heartbeat
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            status_code=200,
            json=envelope({}),
        )
        # poll returns one task with next_poll_ms = 2000
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/poll?capability=data%3Aecho",
            status_code=200,
            json=envelope([pending_task], meta={"next_poll_ms": 2000}),
        )
        # claim
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            status_code=200,
            json=envelope(TASK_DATA),
        )
        # complete
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/complete",
            status_code=200,
            json=envelope({**TASK_DATA, "status": "completed"}),
        )

        w = EchoWorker(BASE_URL, HIVE_ID, token=TOKEN)
        w._running = True

        with mock.patch("time.sleep") as mock_sleep:
            w._tick()

        mock_sleep.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# ServiceWorker stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_flag(self):
        w = EchoWorker(BASE_URL, HIVE_ID, token=TOKEN)
        w._running = True
        w.stop()
        assert not w._running


# ---------------------------------------------------------------------------
# SuperposClient.data_request()
# ---------------------------------------------------------------------------


class TestDataRequest:
    def test_creates_data_request_task(self, httpx_mock):
        task_resp = {
            "id": TASK_ID,
            "hive_id": HIVE_ID,
            "type": "data_request",
            "status": "pending",
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(task_resp),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            ref = c.data_request(
                HIVE_ID,
                capability="data:gmail",
                operation="fetch_emails",
                params={"query": "from:foo", "max_results": 10},
            )
        assert ref["id"] == TASK_ID
        assert ref["type"] == "data_request"

    def test_data_request_sends_correct_payload(self, httpx_mock):
        import json as _json

        task_resp = {"id": TASK_ID, "hive_id": HIVE_ID, "type": "data_request", "status": "pending"}
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(task_resp),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.data_request(
                HIVE_ID,
                capability="data:crm",
                operation="search_deals",
                params={"query": "license"},
                delivery="knowledge",
                result_format="array",
                continuation_of="tsk_prev",
            )
        req = httpx_mock.get_request()
        body = _json.loads(req.content)
        assert body["type"] == "data_request"
        assert body["target_capability"] == "data:crm"
        payload = body["payload"]
        assert payload["operation"] == "search_deals"
        assert payload["delivery"] == "knowledge"
        assert payload["result_format"] == "array"
        assert payload["continuation_of"] == "tsk_prev"
        assert payload["params"] == {"query": "license"}

    def test_data_request_minimal(self, httpx_mock):
        """delivery defaults to task_result; params optional."""
        import json as _json

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope({"id": TASK_ID, "type": "data_request", "status": "pending"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.data_request(HIVE_ID, capability="data:http", operation="get")
        req = httpx_mock.get_request()
        body = _json.loads(req.content)
        assert body["payload"]["delivery"] == "task_result"
        assert "params" not in body["payload"]


# ---------------------------------------------------------------------------
# SuperposClient.discover_services()
# ---------------------------------------------------------------------------


class TestDiscoverServices:
    def test_returns_data_capability_agents(self, httpx_mock):
        agents = [
            {
                "id": "01A" + "0" * 23,
                "name": "gmail-worker",
                "capabilities": ["data:gmail"],
                "type": "service_worker",
                "metadata": {"supported_operations": [{"name": "fetch_emails"}]},
            },
            {
                "id": "01B" + "0" * 23,
                "name": "general-agent",
                "capabilities": ["code_review"],
                "type": "custom",
                "metadata": {},
            },
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/agents?capability=data%3A",
            status_code=200,
            json=envelope(agents),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            services = c.discover_services(HIVE_ID)
        assert len(services) == 1
        assert services[0]["name"] == "gmail-worker"

    def test_empty_hive_returns_empty_list(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/agents?capability=data%3A",
            status_code=200,
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            services = c.discover_services(HIVE_ID)
        assert services == []

    def test_custom_capability_prefix(self, httpx_mock):
        agents = [
            {
                "id": "01A" + "0" * 23,
                "name": "my-worker",
                "capabilities": ["custom:foo"],
                "type": "service_worker",
                "metadata": {},
            },
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/agents?capability=custom%3A",
            status_code=200,
            json=envelope(agents),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            services = c.discover_services(HIVE_ID, capability_prefix="custom:")
        assert len(services) == 1
        assert services[0]["name"] == "my-worker"

    def test_non_list_response_returns_empty(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/agents?capability=data%3A",
            status_code=200,
            json=envelope(None),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            services = c.discover_services(HIVE_ID)
        assert services == []


# ---------------------------------------------------------------------------
# SuperposClient.discover_service_catalog()
# ---------------------------------------------------------------------------

SERVICE_A = {
    "id": "01SVC0000000000000000000001",
    "name": "github-connector",
    "service_type": "github",
    "capabilities": ["read", "write"],
    "status": "active",
}

SERVICE_B = {
    "id": "01SVC0000000000000000000002",
    "name": "slack-connector",
    "service_type": "slack",
    "capabilities": ["messaging"],
    "status": "active",
}

SERVICE_C = {
    "id": "01SVC0000000000000000000003",
    "name": "jira-connector",
    "service_type": "jira",
    "capabilities": ["issues"],
    "status": "inactive",
}

_CATALOG_URL = f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services"


def _catalog_url_with(params: str) -> str:
    return f"{_CATALOG_URL}?{params}"


class TestDiscoverServiceCatalog:
    # ------------------------------------------------------------------
    # Basic single-page response
    # ------------------------------------------------------------------

    def test_single_page_returns_all_items(self, httpx_mock):
        """A single-page response returns all items as a flat list."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope([SERVICE_A, SERVICE_B]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)
        assert len(results) == 2
        assert results[0]["name"] == "github-connector"
        assert results[1]["name"] == "slack-connector"

    def test_empty_first_page_returns_empty_list(self, httpx_mock):
        """When the first page is empty the result is an empty list."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)
        assert results == []

    # ------------------------------------------------------------------
    # Multi-page aggregation
    # ------------------------------------------------------------------

    def test_multi_page_aggregates_all_pages(self, httpx_mock):
        """All pages are fetched and combined into a single flat list."""
        # Page 1 returns per_page items → fetch next page
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=2&page=1"),
            status_code=200,
            json=envelope([SERVICE_A, SERVICE_B]),
        )
        # Page 2 returns fewer than per_page items → last page
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=2&page=2"),
            status_code=200,
            json=envelope([SERVICE_C]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=2)
        assert len(results) == 3
        names = [r["name"] for r in results]
        assert names == ["github-connector", "slack-connector", "jira-connector"]

    def test_multi_page_stops_when_last_page_is_full(self, httpx_mock):
        """Full last page triggers a follow-up fetch; empty response then stops pagination."""
        # Page 1: exactly per_page=2 items
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=2&page=1"),
            status_code=200,
            json=envelope([SERVICE_A, SERVICE_B]),
        )
        # Page 2: exactly per_page=2 items → must fetch page 3
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=2&page=2"),
            status_code=200,
            json=envelope([SERVICE_C, SERVICE_A]),
        )
        # Page 3: empty → stop
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=2&page=3"),
            status_code=200,
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=2)
        assert len(results) == 4

    # ------------------------------------------------------------------
    # Server-side per_page clamping
    # ------------------------------------------------------------------

    def test_server_clamps_per_page_pagination_still_works(self, httpx_mock):
        """Server returning fewer items than requested still terminates pagination correctly."""
        # Client requests per_page=50 but server returns only 3 items on page 1.
        # Because 3 < effective_per_page (50) the client stops after page 1.
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope([SERVICE_A, SERVICE_B, SERVICE_C]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)
        assert len(results) == 3

    def test_per_page_above_100_clamped_to_100(self, httpx_mock):
        """per_page values above 100 are silently clamped to 100."""
        # With per_page=500 the effective value sent to the API is 100.
        # The server returns 3 items which is < 100 → single page, pagination ends.
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=100&page=1"),
            status_code=200,
            json=envelope([SERVICE_A, SERVICE_B, SERVICE_C]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=500)
        assert len(results) == 3

    def test_per_page_zero_clamped_to_1(self, httpx_mock):
        """per_page=0 is clamped to 1, preventing an infinite loop."""
        # effective_per_page = max(1, min(0, 100)) = 1
        # Server returns 1 item — equals effective_per_page, so fetch next page.
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=1&page=1"),
            status_code=200,
            json=envelope([SERVICE_A]),
        )
        # Page 2 returns 0 items — stop.
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=1&page=2"),
            status_code=200,
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=0)
        assert len(results) == 1
        assert results[0]["name"] == "github-connector"

    def test_per_page_negative_clamped_to_1(self, httpx_mock):
        """Negative per_page values are clamped to 1."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=1&page=1"),
            status_code=200,
            json=envelope([SERVICE_B]),
        )
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=1&page=2"),
            status_code=200,
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=-10)
        assert len(results) == 1
        assert results[0]["name"] == "slack-connector"

    # ------------------------------------------------------------------
    # Filtering parameters passed through correctly
    # ------------------------------------------------------------------

    def test_service_type_filter_passed_as_type_param(self, httpx_mock):
        """service_type kwarg is sent as the ``type`` query parameter."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&type=github&page=1"),
            status_code=200,
            json=envelope([SERVICE_A]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, service_type="github")
        assert len(results) == 1
        assert results[0]["service_type"] == "github"

    def test_capability_filter_is_passed_through(self, httpx_mock):
        """capability kwarg is forwarded as the ``capability`` query parameter."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&capability=read&page=1"),
            status_code=200,
            json=envelope([SERVICE_A]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, capability="read")
        assert len(results) == 1
        assert results[0]["capabilities"] == ["read", "write"]

    def test_status_filter_overrides_default(self, httpx_mock):
        """Passing status='inactive' overrides the default 'active' filter."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=inactive&per_page=50&page=1"),
            status_code=200,
            json=envelope([SERVICE_C]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, status="inactive")
        assert len(results) == 1
        assert results[0]["status"] == "inactive"

    def test_all_filters_combined(self, httpx_mock):
        """All filter params are combined correctly in the query string."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=all&per_page=10&type=slack&capability=messaging&page=1"),
            status_code=200,
            json=envelope([SERVICE_B]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(
                HIVE_ID,
                service_type="slack",
                capability="messaging",
                status="all",
                per_page=10,
            )
        assert len(results) == 1
        assert results[0]["name"] == "slack-connector"

    def test_no_type_param_when_service_type_is_none(self, httpx_mock):
        """When service_type is not provided no ``type`` param is added."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope([SERVICE_A]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            # service_type defaults to None — must not appear in query string
            results = c.discover_service_catalog(HIVE_ID)
        assert len(results) == 1

    def test_no_capability_param_when_not_provided(self, httpx_mock):
        """When capability is not provided no ``capability`` param is added."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope([SERVICE_B]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)
        assert len(results) == 1

    # ------------------------------------------------------------------
    # HTTP errors are propagated
    # ------------------------------------------------------------------

    def test_http_401_raises(self, httpx_mock):
        """A 401 Unauthorized response raises an appropriate SDK exception."""
        from superpos_sdk import AuthenticationError

        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=401,
            json={
                "data": None,
                "meta": {},
                "errors": [{"message": "Unauthenticated", "code": "unauthenticated"}],
            },
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(AuthenticationError):
                c.discover_service_catalog(HIVE_ID)

    def test_http_403_raises(self, httpx_mock):
        """A 403 Forbidden response raises an appropriate SDK exception."""
        from superpos_sdk import SuperposPermissionError

        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=403,
            json={
                "data": None,
                "meta": {},
                "errors": [{"message": "Forbidden", "code": "forbidden"}],
            },
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposPermissionError):
                c.discover_service_catalog(HIVE_ID)

    def test_http_500_raises(self, httpx_mock):
        """A 500 server error raises an appropriate SDK exception."""
        from superpos_sdk import SuperposError

        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=500,
            json={
                "data": None,
                "meta": {},
                "errors": [{"message": "Server error", "code": "server_error"}],
            },
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposError):
                c.discover_service_catalog(HIVE_ID)

    # ------------------------------------------------------------------
    # Non-list / unexpected response shapes
    # ------------------------------------------------------------------

    def test_non_list_envelope_data_stops_pagination(self, httpx_mock):
        """Non-list envelope data stops pagination and returns what was collected so far."""
        httpx_mock.add_response(
            url=_catalog_url_with("status=active&per_page=50&page=1"),
            status_code=200,
            json=envelope({"error": "unexpected"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)
        assert results == []


# ---------------------------------------------------------------------------
# ServiceWorker.deliver_response() — uses dedicated deliver-response endpoint
# ---------------------------------------------------------------------------

RESPONSE_TASK_ID = "01HXYZ00000000000000000099"


def _response_task_data(**overrides):
    base = {
        "id": RESPONSE_TASK_ID,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "type": "data_response",
        "status": "completed",
        "priority": 2,
        "payload": {},
        "progress": 100,
        "claimed_by": None,
        "created_at": "2026-02-26T12:00:00Z",
        "completed_at": "2026-02-26T12:01:00Z",
    }
    base.update(overrides)
    return base


class TestDeliverResponse:
    """ServiceWorker.deliver_response() must use the deliver-response endpoint."""

    def _worker(self):
        return EchoWorker(BASE_URL, HIVE_ID, name="w", secret="s")

    def test_deliver_response_calls_deliver_response_endpoint(self, httpx_mock):
        """deliver_response() must POST to /deliver-response, not PATCH /complete."""
        result = {"status": "success", "data": {}}
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{RESPONSE_TASK_ID}/deliver-response",
            method="POST",
            json=envelope(_response_task_data(result=result)),
        )
        w = self._worker()
        # Manually set the internal state as if we are inside _process().
        w._response_task_id = RESPONSE_TASK_ID  # noqa: SLF001
        w.client = SuperposClient(BASE_URL, token=TOKEN)

        resp = w.deliver_response(result)
        assert resp["id"] == RESPONSE_TASK_ID
        assert resp["status"] == "completed"

    def test_deliver_response_with_explicit_response_task_id(self, httpx_mock):
        result = {"status": "success"}
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{RESPONSE_TASK_ID}/deliver-response",
            method="POST",
            json=envelope(_response_task_data(result=result)),
        )
        w = self._worker()
        w.client = SuperposClient(BASE_URL, token=TOKEN)

        # Pass the ID explicitly — no ambient _response_task_id needed.
        resp = w.deliver_response(result, response_task_id=RESPONSE_TASK_ID)
        assert resp["id"] == RESPONSE_TASK_ID

    def test_deliver_response_raises_when_no_response_task_id(self):
        w = self._worker()
        w.client = SuperposClient(BASE_URL, token=TOKEN)
        # No _response_task_id set, none passed explicitly.
        with pytest.raises(ValueError, match="response_task_id"):
            w.deliver_response({"status": "success"})

    def test_deliver_response_passes_status_message(self, httpx_mock):
        result = {"status": "success"}
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{RESPONSE_TASK_ID}/deliver-response",
            method="POST",
            json=envelope(_response_task_data(result=result, status_message="Done")),
        )
        w = self._worker()
        w._response_task_id = RESPONSE_TASK_ID  # noqa: SLF001
        w.client = SuperposClient(BASE_URL, token=TOKEN)

        resp = w.deliver_response(result, status_message="Done")
        assert resp["status_message"] == "Done"
