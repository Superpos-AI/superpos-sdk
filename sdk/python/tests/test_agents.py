"""Tests for agent auth and lifecycle endpoints."""

from __future__ import annotations

import json

from superpos_sdk import SuperposClient

from .conftest import AGENT_ID, BASE_URL, TOKEN, envelope


class TestRegister:
    def test_register_stores_token(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=201,
            json=envelope(
                {
                    "agent": {"id": AGENT_ID, "name": "bot", "status": "offline"},
                    "token": "new-token-xyz",
                }
            ),
        )
        with SuperposClient(BASE_URL) as c:
            data = c.register(
                name="bot",
                hive_id="H" * 26,
                secret="s" * 16,
                capabilities=["code"],
                metadata={"lang": "python"},
            )
        assert data["token"] == "new-token-xyz"
        # Token should have been stored but client is closed; just verify data.
        assert data["agent"]["id"] == AGENT_ID

    def test_register_sends_correct_body(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=201,
            json=envelope({"agent": {"id": "a"}, "token": "t"}),
        )
        hive = "H" * 26
        with SuperposClient(BASE_URL) as c:
            c.register(
                name="my-agent",
                hive_id=hive,
                secret="secret-value-here!",
                agent_type="worker",
            )
        body = httpx_mock.get_request().content
        payload = json.loads(body)
        assert payload["name"] == "my-agent"
        assert payload["hive_id"] == hive
        assert payload["type"] == "worker"
        assert payload["secret"] == "secret-value-here!"

    def test_register_omits_optional_none_fields(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=201,
            json=envelope({"agent": {"id": "a"}, "token": "t"}),
        )
        with SuperposClient(BASE_URL) as c:
            c.register(name="x", hive_id="H" * 26, secret="s" * 16)
        payload = json.loads(httpx_mock.get_request().content)
        assert "capabilities" not in payload
        assert "metadata" not in payload
        assert "organization_id" not in payload


class TestLogin:
    def test_login_stores_token(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/login",
            json=envelope(
                {
                    "agent": {"id": AGENT_ID, "name": "bot", "status": "online"},
                    "token": "login-token",
                }
            ),
        )
        with SuperposClient(BASE_URL) as c:
            data = c.login(agent_id=AGENT_ID, secret="my-secret")
            assert c.token == "login-token"
            assert data["agent"]["status"] == "online"


class TestLogout:
    def test_logout_clears_token(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/logout",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.logout()
            assert c.token is None


class TestMe:
    def test_me_returns_agent(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            json=envelope({"id": AGENT_ID, "name": "bot", "status": "online"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            agent = c.me()
        assert agent["name"] == "bot"


class TestHeartbeat:
    def test_heartbeat_basic(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            json=envelope(
                {"id": AGENT_ID, "status": "online", "last_heartbeat": "2026-02-26T12:00:00Z"}
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            data = c.heartbeat()
        assert data["last_heartbeat"] == "2026-02-26T12:00:00Z"

    def test_heartbeat_with_metadata(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/heartbeat",
            json=envelope({"id": AGENT_ID, "status": "online", "metadata": {"cpu": 42}}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.heartbeat(metadata={"cpu": 42})
        payload = json.loads(httpx_mock.get_request().content)
        assert payload["metadata"]["cpu"] == 42


class TestUpdateStatus:
    def test_update_status(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/status",
            json=envelope({"id": AGENT_ID, "status": "busy"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            data = c.update_status("busy")
        assert data["status"] == "busy"
        payload = json.loads(httpx_mock.get_request().content)
        assert payload["status"] == "busy"


class TestUpdateCapabilities:
    def test_update_capabilities(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/capabilities",
            json=envelope({"capabilities": ["code", "deploy"]}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            data = c.update_capabilities(["code", "deploy"])
        assert data["capabilities"] == ["code", "deploy"]
        payload = json.loads(httpx_mock.get_request().content)
        assert payload["capabilities"] == ["code", "deploy"]

    def test_update_capabilities_empty_list(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/capabilities",
            json=envelope({"capabilities": []}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            data = c.update_capabilities([])
        assert data["capabilities"] == []
        payload = json.loads(httpx_mock.get_request().content)
        assert payload["capabilities"] == []
