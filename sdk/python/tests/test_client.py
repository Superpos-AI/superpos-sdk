"""Tests for core client behaviour: envelope parsing, auth headers, error mapping."""

from __future__ import annotations

import httpx
import pytest

from superpos_sdk import AuthenticationError, SuperposClient, SuperposError, ValidationError
from superpos_sdk.exceptions import (
    ConflictError,
    NotFoundError,
)
from superpos_sdk.exceptions import (
    PermissionError as SuperposPermissionError,
)

from .conftest import BASE_URL, TOKEN, envelope

# ------------------------------------------------------------------
# Envelope & headers
# ------------------------------------------------------------------


class TestEnvelopeParsing:
    def test_success_unwraps_data(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            json=envelope({"id": "abc", "name": "bot"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.me()
        assert result == {"id": "abc", "name": "bot"}

    def test_204_returns_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/logout",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            assert c.logout() is None

    def test_bearer_token_sent(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            json=envelope({"id": "x"}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.me()
        request = httpx_mock.get_request()
        assert request.headers["authorization"] == f"Bearer {TOKEN}"

    def test_no_auth_header_when_no_token(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=201,
            json=envelope({"agent": {"id": "a"}, "token": "t"}),
        )
        with SuperposClient(BASE_URL) as c:
            c.register(name="x", hive_id="h" * 26, secret="s" * 16)
        request = httpx_mock.get_request()
        assert "authorization" not in request.headers


# ------------------------------------------------------------------
# Error mapping
# ------------------------------------------------------------------


class TestErrorMapping:
    def test_401_raises_authentication_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            status_code=401,
            json=envelope(errors=[{"message": "Unauthenticated.", "code": "auth_failed"}]),
        )
        with SuperposClient(BASE_URL, token="bad") as c:
            with pytest.raises(AuthenticationError) as exc_info:
                c.me()
        assert exc_info.value.status_code == 401
        assert exc_info.value.errors[0].code == "auth_failed"

    def test_403_raises_permission_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            status_code=403,
            json=envelope(errors=[{"message": "Forbidden.", "code": "forbidden"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposPermissionError) as exc_info:
                c.me()
        assert exc_info.value.status_code == 403

    def test_404_raises_not_found_error(self, httpx_mock):
        hive = "H" * 26
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{hive}/knowledge/NOTFOUND",
            status_code=404,
            json=envelope(errors=[{"message": "Not found.", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.get_knowledge(hive, "NOTFOUND")

    def test_409_raises_conflict_error(self, httpx_mock):
        hive = "H" * 26
        task = "T" * 26
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{hive}/tasks/{task}/claim",
            status_code=409,
            json=envelope(errors=[{"message": "Task is no longer available.", "code": "conflict"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(ConflictError) as exc_info:
                c.claim_task(hive, task)
        assert "no longer available" in str(exc_info.value)

    def test_422_raises_validation_error_with_field(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=422,
            json=envelope(
                errors=[
                    {
                        "message": "The name has already been taken.",
                        "code": "validation_error",
                        "field": "name",
                    }
                ]
            ),
        )
        with SuperposClient(BASE_URL) as c:
            with pytest.raises(ValidationError) as exc_info:
                c.register(name="dup", hive_id="h" * 26, secret="s" * 16)
        assert exc_info.value.errors[0].field == "name"

    def test_422_laravel_object_errors_parsed(self, httpx_mock):
        """Laravel validation returns errors as {field: [messages]} dict."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=422,
            json={
                "data": None,
                "meta": {},
                "errors": {
                    "name": ["The name field is required."],
                    "secret": [
                        "The secret must be at least 16 characters.",
                        "The secret field is required.",
                    ],
                },
            },
        )
        with SuperposClient(BASE_URL) as c:
            with pytest.raises(ValidationError) as exc_info:
                c.register(name="", hive_id="h" * 26, secret="")
        err = exc_info.value
        assert err.status_code == 422
        # Should have 3 ApiError entries total
        assert len(err.errors) == 3
        assert err.errors[0].field == "name"
        assert err.errors[0].message == "The name field is required."
        assert err.errors[0].code == "validation_error"
        secret_errors = [e for e in err.errors if e.field == "secret"]
        assert len(secret_errors) == 2

    def test_422_laravel_object_errors_single_string(self, httpx_mock):
        """Laravel may return a single string instead of a list for a field."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            status_code=422,
            json={
                "data": None,
                "meta": {},
                "errors": {
                    "email": "The email must be a valid email address.",
                },
            },
        )
        with SuperposClient(BASE_URL) as c:
            with pytest.raises(ValidationError) as exc_info:
                c.register(name="x", hive_id="h" * 26, secret="s" * 16)
        err = exc_info.value
        assert len(err.errors) == 1
        assert err.errors[0].field == "email"
        assert err.errors[0].message == "The email must be a valid email address."

    def test_500_raises_generic_superpos_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            status_code=500,
            json=envelope(errors=[{"message": "Internal error", "code": "server_error"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposError) as exc_info:
                c.me()
        assert exc_info.value.status_code == 500

    def test_non_json_error_response_raises_superpos_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            status_code=502,
            text="<html><body>Bad Gateway</body></html>",
            headers={"content-type": "text/html"},
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposError) as exc_info:
                c.me()
        assert exc_info.value.status_code == 502
        assert "Bad Gateway" in str(exc_info.value)

    def test_non_json_success_response_raises_superpos_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/me",
            status_code=200,
            text="OK",
            headers={"content-type": "text/plain"},
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposError) as exc_info:
                c.me()
        assert exc_info.value.status_code == 200
        assert "text/plain" in str(exc_info.value)


# ------------------------------------------------------------------
# Context manager
# ------------------------------------------------------------------


class TestLogoutTokenClearing:
    def test_logout_clears_token_on_success(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/logout",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.logout()
            assert c.token is None

    def test_logout_clears_token_on_api_error(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/logout",
            status_code=500,
            json=envelope(errors=[{"message": "Internal error", "code": "server_error"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(SuperposError):
                c.logout()
            assert c.token is None

    def test_logout_clears_token_on_transport_error(self, httpx_mock):
        httpx_mock.add_exception(
            httpx.ConnectError("connection refused"),
            url=f"{BASE_URL}/api/v1/agents/logout",
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(httpx.ConnectError):
                c.logout()
            assert c.token is None


# ------------------------------------------------------------------
# Context manager
# ------------------------------------------------------------------


class TestContextManager:
    def test_close_is_idempotent(self):
        c = SuperposClient(BASE_URL)
        c.close()
        c.close()  # should not raise
