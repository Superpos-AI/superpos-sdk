"""Smoke tests for :class:`superpos_sdk.async_client.AsyncSuperposClient`."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from superpos_sdk import AsyncSuperposClient


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _envelope(data: Any, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return body


class TestConstruction:
    def test_strips_trailing_slash(self):
        c = AsyncSuperposClient("https://superpos.test/")
        assert c.base_url == "https://superpos.test"

    def test_initial_token_and_cursors(self):
        c = AsyncSuperposClient("https://superpos.test", token="tok-1")
        assert c.token == "tok-1"
        assert c._event_cursors == {}


class TestAuth:
    async def test_register_stores_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/agents/register"
            body = json.loads(request.content)
            assert body["name"] == "worker"
            assert body["hive_id"] == "hive-1"
            return httpx.Response(
                200,
                json=_envelope({"agent": {"id": "a1", "name": "worker"}, "token": "newtok"}),
            )

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        data = await client.register(name="worker", hive_id="hive-1", secret="s" * 16)
        assert data["token"] == "newtok"
        assert client.token == "newtok"
        await client.aclose()

    async def test_register_resets_event_cursors(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_envelope({"agent": {"id": "a1"}, "token": "newtok"}),
            )

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        client._event_cursors["some_channel"] = "cursor_123"
        await client.register(name="worker", hive_id="hive-1", secret="s" * 16)
        assert client._event_cursors == {}
        await client.aclose()

    async def test_login_resets_event_cursors(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_envelope({"agent": {"id": "a1"}, "token": "newtok"}),
            )

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        client._event_cursors["some_channel"] = "cursor_123"
        await client.login(agent_id="a1", secret="s" * 16)
        assert client._event_cursors == {}
        await client.aclose()

    async def test_heartbeat_attaches_bearer(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer tok-1"
            assert request.url.path == "/api/v1/agents/heartbeat"
            return httpx.Response(200, json=_envelope({"ok": True}))

        client = AsyncSuperposClient(
            "https://superpos.test", token="tok-1", transport=_mock_transport(handler)
        )
        data = await client.heartbeat()
        assert data == {"ok": True}
        await client.aclose()


class TestTasks:
    async def test_poll_and_claim_and_complete(self):
        steps: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            steps.append(path)
            if path == "/api/v1/hives/hive-1/tasks/poll":
                assert request.url.params.get("capability") == "code"
                return httpx.Response(200, json=_envelope([{"id": "t1"}]))
            if path == "/api/v1/hives/hive-1/tasks/t1/claim":
                assert request.method == "PATCH"
                return httpx.Response(200, json=_envelope({"id": "t1", "status": "in_progress"}))
            if path == "/api/v1/hives/hive-1/tasks/t1/complete":
                body = json.loads(request.content)
                assert body["result"] == {"out": 1}
                return httpx.Response(
                    200, json=_envelope({"id": "t1", "status": "completed", "result": {"out": 1}})
                )
            return httpx.Response(404, json={"errors": ["not found"]})

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        tasks = await client.poll_tasks("hive-1", capability="code")
        assert tasks == [{"id": "t1"}]
        claimed = await client.claim_task("hive-1", "t1")
        assert claimed["status"] == "in_progress"
        completed = await client.complete_task("hive-1", "t1", result={"out": 1})
        assert completed["status"] == "completed"
        assert steps == [
            "/api/v1/hives/hive-1/tasks/poll",
            "/api/v1/hives/hive-1/tasks/t1/claim",
            "/api/v1/hives/hive-1/tasks/t1/complete",
        ]
        await client.aclose()

    async def test_get_task(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/hives/hive-1/tasks/t1"
            return httpx.Response(
                200,
                json=_envelope({"id": "t1", "status": "completed", "result": {"ok": True}}),
            )

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        task = await client.get_task("hive-1", "t1")
        assert task["status"] == "completed"
        assert task["result"] == {"ok": True}
        await client.aclose()

    async def test_fail_task_body(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_envelope({"id": "t1", "status": "failed"}))

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        await client.fail_task("hive-1", "t1", error={"message": "boom"})
        assert seen["body"] == {"error": {"message": "boom"}}
        await client.aclose()


class TestChannelsAndKnowledge:
    async def test_post_channel_message_defaults(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_envelope({"id": "m1"}))

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        await client.post_channel_message("hive-1", "ch-1", "hi")
        assert seen["body"] == {"content": "hi", "message_type": "discussion"}
        await client.aclose()

    async def test_list_knowledge_filters_go_to_query(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=_envelope([]))

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        await client.list_knowledge("hive-1", key="release.v2", scope="hive", limit=5)
        assert seen["params"] == {"key": "release.v2", "scope": "hive", "limit": "5"}
        await client.aclose()


class TestEvents:
    async def test_poll_events_tracks_cursor_and_pages(self):
        calls: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            calls.append(params)
            if "last_event_id" not in params:
                return httpx.Response(
                    200,
                    json={
                        "data": [{"id": "e1", "type": "t.c"}],
                        "meta": {"next_cursor": "e1", "has_more": True},
                    },
                )
            assert params["last_event_id"] == "e1"
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "e2", "type": "t.c"}],
                    "meta": {"next_cursor": "e2", "has_more": False},
                },
            )

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        events = await client.poll_events("hive-1")
        assert [e.id for e in events] == ["e1", "e2"]
        assert client._event_cursors["hive-1"] == "e2"
        assert len(calls) == 2
        await client.aclose()


class TestLifecycle:
    async def test_async_context_manager_closes(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope({"ok": True}))

        async with AsyncSuperposClient(
            "https://superpos.test", transport=_mock_transport(handler)
        ) as c:
            await c.heartbeat()
            http = c._http
        assert http.is_closed

    async def test_error_status_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"errors": [{"message": "nope"}]})

        client = AsyncSuperposClient("https://superpos.test", transport=_mock_transport(handler))
        with pytest.raises(Exception):
            await client.get_knowledge("hive-1", "missing")
        await client.aclose()
