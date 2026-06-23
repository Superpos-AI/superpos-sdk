"""Tests for the gl_token GitLab credential helper.

Mirrors the security-critical coverage of test_gh_token.py: the git-credential
mode must only ever hand a connection-bound token to the host that connection
vouches for, and must fail closed for unprovable hosts.
"""

from __future__ import annotations

import os
from io import StringIO
from unittest import mock

import pytest

from superpos_sdk.gl_token import (
    _cmd_git_credential,
    _connection_api_base_url,
    _connection_host,
    _connection_id,
    _is_broker_compatible,
    main,
    mint_token,
    resolve_connection,
)


def _args(**overrides):
    defaults = {"connection": None, "refresh": False}
    defaults.update(overrides)
    return type("Args", (), defaults)()


# ---------------------------------------------------------------------------
# git-credential host binding
# ---------------------------------------------------------------------------


class TestHostFiltering:
    def test_exits_for_non_gitlab_host(self):
        """github.com must be rejected for a public gitlab.com connection."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gl_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gl_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc:
                _cmd_git_credential(_args())
            assert exc.value.code == 0
            mock_mint.assert_not_called()

    def test_accepts_gitlab_com(self):
        """gitlab.com is accepted; username is oauth2 and the token is served."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch(
                "superpos_sdk.gl_token._find_persona_connection",
                return_value={
                    "service_connection_id": "conn-1",
                    "base_url": "https://gitlab.com/api/v4",
                },
            ),
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gl_token.mint_token", return_value={"token": "glpat_abc"}),
            mock.patch("superpos_sdk.gl_token.print") as mock_print,
        ):
            _cmd_git_credential(_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("username=oauth2" in c for c in calls)
            assert any("password=glpat_abc" in c for c in calls)

    def test_accepts_self_managed_host_matching_base_url(self):
        """A self-managed host matching the connection base_url is accepted."""
        stdin = StringIO("protocol=https\nhost=gitlab.acme.corp\n\n")
        with (
            mock.patch(
                "superpos_sdk.gl_token._find_persona_connection",
                return_value={
                    "service_connection_id": "conn-1",
                    "base_url": "https://gitlab.acme.corp/api/v4",
                },
            ),
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gl_token.mint_token", return_value={"token": "glpat_ent"}),
            mock.patch("superpos_sdk.gl_token.print") as mock_print,
        ):
            _cmd_git_credential(_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=glpat_ent" in c for c in calls)

    def test_self_managed_token_not_served_to_gitlab_com(self):
        """A token bound to a self-managed connection must not reach gitlab.com."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch(
                "superpos_sdk.gl_token._find_persona_connection",
                return_value={
                    "service_connection_id": "conn-1",
                    "base_url": "https://gitlab.acme.corp/api/v4",
                },
            ),
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gl_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc:
                _cmd_git_credential(_args())
            assert exc.value.code == 0
            mock_mint.assert_not_called()

    def test_fails_closed_when_connection_absent_from_persona(self):
        """An unprovable host (connection absent) must never mint."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch("superpos_sdk.gl_token._find_persona_connection", return_value=None),
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="conn-x"),
            mock.patch("superpos_sdk.gl_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc:
                _cmd_git_credential(_args())
            assert exc.value.code == 0
            mock_mint.assert_not_called()

    def test_rejects_non_https_protocol(self):
        stdin = StringIO("protocol=http\nhost=gitlab.com\n\n")
        with (
            mock.patch("superpos_sdk.gl_token.sys.stdin", stdin),
            mock.patch("superpos_sdk.gl_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc:
                _cmd_git_credential(_args())
            assert exc.value.code == 0
            mock_mint.assert_not_called()


# ---------------------------------------------------------------------------
# Connection host / base_url derivation
# ---------------------------------------------------------------------------


class TestConnectionHost:
    def test_no_base_url_is_public_gitlab(self):
        with mock.patch(
            "superpos_sdk.gl_token._find_persona_connection",
            return_value={"service_connection_id": "c"},
        ):
            assert _connection_host("c") == "gitlab.com"
            assert _connection_api_base_url("c") == "https://gitlab.com/api/v4"

    def test_base_url_host_is_extracted(self):
        with mock.patch(
            "superpos_sdk.gl_token._find_persona_connection",
            return_value={
                "service_connection_id": "c",
                "base_url": "https://gitlab.acme.corp/api/v4",
            },
        ):
            assert _connection_host("c") == "gitlab.acme.corp"
            assert _connection_api_base_url("c") == "https://gitlab.acme.corp/api/v4"

    def test_absent_connection_fails_closed(self):
        with mock.patch("superpos_sdk.gl_token._find_persona_connection", return_value=None):
            assert _connection_host("c") is None
            assert _connection_api_base_url("c") is None


# ---------------------------------------------------------------------------
# Resolution + compatibility
# ---------------------------------------------------------------------------


class TestResolution:
    def test_explicit_wins(self):
        assert resolve_connection("explicit-id") == "explicit-id"

    def test_env_var_used(self):
        with (
            mock.patch.dict(os.environ, {"GL_CONNECTION_ID": "env-id"}, clear=True),
            mock.patch("superpos_sdk.gl_token._discover_toml", return_value=None),
        ):
            assert resolve_connection() == "env-id"

    def test_connection_id_prefers_service_connection_id(self):
        assert _connection_id({"service_connection_id": "a", "id": "b"}) == "a"
        assert _connection_id({"id": "b"}) == "b"

    def test_gitlab_oauth_is_broker_compatible(self):
        assert _is_broker_compatible({"auth_type": "gitlab_oauth"}) is True
        assert _is_broker_compatible({"broker_compatible": True}) is True
        assert _is_broker_compatible({"broker_compatible": False}) is False
        assert _is_broker_compatible({"auth_type": "token"}) is False


# ---------------------------------------------------------------------------
# mint_token
# ---------------------------------------------------------------------------


class TestMint:
    def test_mint_posts_and_returns_data(self):
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {"data": {"token": "glpat_xyz", "expires_at": None}}
        with (
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gl_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gl_token.httpx.post", return_value=resp) as mock_post,
        ):
            data = mint_token("conn-1")
            assert data["token"] == "glpat_xyz"
            url = mock_post.call_args[0][0]
            assert url.endswith("/api/v1/gitlab/access-token")

    def test_mint_surfaces_api_error(self):
        resp = mock.Mock()
        resp.status_code = 400
        resp.json.return_value = {
            "errors": [{"message": "no token", "code": "no_access_token"}],
        }
        with (
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gl_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gl_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc:
                mint_token("conn-1")
            assert exc.value.code == 1


def test_main_dispatches_print_token():
    with (
        mock.patch("sys.argv", ["superpos-gl-token", "--connection", "c"]),
        mock.patch("superpos_sdk.gl_token.resolve_connection", return_value="c"),
        mock.patch("superpos_sdk.gl_token.mint_token", return_value={"token": "glpat_m"}),
        mock.patch("superpos_sdk.gl_token.print") as mock_print,
    ):
        main()
        assert any("glpat_m" in str(c) for c in mock_print.call_args_list)
