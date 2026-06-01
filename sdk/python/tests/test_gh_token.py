"""Tests for gh_token credential helper — regression tests for review findings."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest import mock

import pytest

from superpos_sdk.gh_token import (
    _cmd_api_base_url,
    _cmd_git_credential,
    _cmd_list_connections,
    _connection_api_base_url,
    _connection_base_url,
    _connection_host,
    _connection_id,
    _fetch_persona,
    _find_persona_connection,
    _is_broker_compatible,
    _persona_default_connection,
    _read_cache,
    main,
    mint_token,
    resolve_connection,
)

# ---------------------------------------------------------------------------
# Bug 1 — Credential helper must only respond to github.com or GHES host
# ---------------------------------------------------------------------------


class TestHostFiltering:
    """Credential helper should exit(0) for unrelated hosts."""

    @staticmethod
    def _make_args(**overrides):
        """Minimal argparse.Namespace for _cmd_git_credential."""
        defaults = {"connection": None, "refresh": False}
        defaults.update(overrides)
        return type("Args", (), defaults)()

    def test_exits_for_non_github_host(self):
        """gitlab.com must be rejected for a public github.com connection."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            # Public github.com connection: present in persona, no base_url.
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()

    def test_accepts_github_com(self):
        """github.com must be accepted for a public github.com connection."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_abc"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            # Should have printed credential fields (not exited)
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_abc" in c for c in calls)

    def test_accepts_github_com_with_api_base_url(self):
        """github.com must be accepted when the persona emits the real backend
        shape: base_url='https://api.github.com'. The API host (api.github.com)
        must be recognized as the public GitHub git host (github.com)."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "conn-1",
                    "base_url": "https://api.github.com",
                },
            ),
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_real"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_real" in c for c in calls)

    def test_accepts_host_matching_connection_base_url(self):
        """A GHES host that matches the connection's own base_url is accepted,
        regardless of SUPERPOS_GHES_HOST (the connection is authoritative)."""
        stdin = StringIO("protocol=https\nhost=github.acme.corp\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,  # SUPERPOS_GHES_HOST intentionally unset — irrelevant now
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_xyz"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_xyz" in c for c in calls)

    def test_rejects_github_com_for_ghes_bound_connection(self):
        """A GHES-bound connection must NOT mint a token for github.com, even
        though github.com is otherwise an 'allowed' host. This is the off-host
        disclosure the connection-host check prevents."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()

    def test_rejects_unrelated_host_for_ghes_connection(self):
        """A host that matches neither github.com nor the connection's base_url
        host (gitlab.com) must be rejected for a GHES connection."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()

    def test_exits_when_connection_absent_from_persona(self):
        """A connection that resolves but is NOT advertised by the persona has an
        unprovable host. Its absence is NOT proof of a public github.com
        connection, so the helper must fail closed even for host=github.com."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            # Connection not present in persona -> _connection_host() is None.
            mock.patch("superpos_sdk.gh_token._find_persona_connection", return_value=None),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()

    @pytest.mark.parametrize("host", ["notgithub.com", "github.com.evil.com", "evilgithub.com"])
    def test_rejects_lookalike_hosts(self, host):
        """Substring lookalikes (notgithub.com, github.com.evil.com) must NOT leak a
        public github.com connection's token."""
        stdin = StringIO(f"protocol=https\nhost={host}\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()

    def test_accepts_github_com_with_explicit_port(self):
        """An explicit port on github.com must still be accepted."""
        stdin = StringIO("protocol=https\nhost=github.com:443\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_port"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_port" in c for c in calls)


# ---------------------------------------------------------------------------
# Bug — CLI must work as a git credential helper (accept get/store/erase)
# ---------------------------------------------------------------------------


class TestGitCredentialOperationArg:
    """`git` invokes the helper as `superpos-gh-token --git-credential <op>`."""

    def test_get_operation_is_accepted_and_returns_credentials(self):
        """`--git-credential get` must parse and emit credentials (no argparse error)."""
        argv = ["superpos-gh-token", "--git-credential", "get"]
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_get"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            main()  # must not raise SystemExit(2) from argparse
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_get" in c for c in calls)

    @pytest.mark.parametrize("operation", ["store", "erase"])
    def test_store_and_erase_are_noops(self, operation):
        """store/erase must not mint or print anything."""
        argv = ["superpos-gh-token", "--git-credential", operation]
        stdin = StringIO("protocol=https\nhost=github.com\nusername=x\npassword=y\n\n")
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection") as mock_resolve,
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            main()
            mock_mint.assert_not_called()
            mock_resolve.assert_not_called()
            mock_print.assert_not_called()


# ---------------------------------------------------------------------------
# Bug 2 — Persona API endpoint must be /api/v1/persona (not /agent/persona)
# ---------------------------------------------------------------------------


class TestPersonaEndpoint:
    """_fetch_persona must call the correct URL."""

    def test_fetch_persona_uses_correct_url(self, httpx_mock):
        """The request must go to /api/v1/persona, not /api/v1/agent/persona."""
        httpx_mock.add_response(
            url="https://superpos.test/api/v1/persona",
            json={"data": {"github": {"connections": []}}},
        )
        with mock.patch.dict(
            os.environ,
            {
                "SUPERPOS_BASE_URL": "https://superpos.test",
                "SUPERPOS_API_TOKEN": "tok",
            },
        ):
            result = _fetch_persona()

        assert result == {"github": {"connections": []}}
        req = httpx_mock.get_request()
        assert "/api/v1/persona" in str(req.url)
        assert "/api/v1/agent/persona" not in str(req.url)


# ---------------------------------------------------------------------------
# Bug 3 — _read_cache must handle null expires_at without crashing
# ---------------------------------------------------------------------------


class TestReadCacheNullExpiry:
    """_read_cache must handle expires_at=None gracefully."""

    def test_null_expires_at_bypasses_cache(self, tmp_path):
        """PATs (expires_at=None) must never be served from cache to honour rotation."""
        cache_data = {"token": "ghs_cached", "expires_at": None}
        cache_file = tmp_path / "superpos-gh-token-conn-1.json"
        cache_file.write_text(json.dumps(cache_data))

        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=cache_file):
            result = _read_cache("conn-1")

        assert result is None

    def test_valid_future_expires_at_returns_cached_data(self, tmp_path):
        """Normal case: future expiry returns cached data."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cache_data = {"token": "ghs_valid", "expires_at": future}
        cache_file = tmp_path / "superpos-gh-token-conn-2.json"
        cache_file.write_text(json.dumps(cache_data))

        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=cache_file):
            result = _read_cache("conn-2")

        assert result is not None
        assert result["token"] == "ghs_valid"

    def test_expired_entry_returns_none(self, tmp_path):
        """Expired token must not be returned."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cache_data = {"token": "ghs_old", "expires_at": past}
        cache_file = tmp_path / "superpos-gh-token-conn-3.json"
        cache_file.write_text(json.dumps(cache_data))

        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=cache_file):
            result = _read_cache("conn-3")

        assert result is None

    def test_missing_cache_file_returns_none(self, tmp_path):
        """No cache file means no cached data."""
        missing = tmp_path / "superpos-gh-token-conn-none.json"
        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=missing):
            result = _read_cache("conn-none")

        assert result is None

    def test_corrupt_json_returns_none(self, tmp_path):
        """Corrupt cache file must not crash."""
        cache_file = tmp_path / "superpos-gh-token-conn-bad.json"
        cache_file.write_text("NOT JSON {{{")

        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=cache_file):
            result = _read_cache("conn-bad")

        assert result is None


# ---------------------------------------------------------------------------
# Bug 4 — Persona github.connections[] must be parsed per the documented
# contract, which identifies each connection by `service_connection_id`
# (docs/proposals/github-app-integration.md), NOT by `id`/`name`.
# ---------------------------------------------------------------------------


# Connection shapes mirror the documented persona contract exactly.
_CONN_A = {
    "service_connection_id": "01HQA",
    "auth_type": "github_app",
    "broker_compatible": True,
    "target_type": "Organization",
    "target_login": "Superpos-AI",
    "repository_selection": "selected",
    "actor_login": "superpos-agent[bot]",
}
_CONN_B = {
    "service_connection_id": "01HQB",
    "auth_type": "github_app",
    "broker_compatible": True,
    "target_type": "User",
    "target_login": "octocat",
    "repository_selection": "all",
    "actor_login": "superpos-agent[bot]",
}


class TestConnectionIdHelper:
    """_connection_id reads the documented key, with a legacy fallback."""

    def test_prefers_service_connection_id(self):
        assert _connection_id(_CONN_A) == "01HQA"

    def test_falls_back_to_legacy_id(self):
        assert _connection_id({"id": "legacy-1"}) == "legacy-1"

    def test_missing_both_returns_none(self):
        assert _connection_id({"target_login": "x"}) is None


class TestPersonaDefaultConnection:
    """_persona_default_connection must use the documented contract keys."""

    def test_explicit_default_connection_id_wins(self):
        persona = {
            "github": {"default_connection_id": "01HQDEF", "connections": [_CONN_A, _CONN_B]}
        }
        with mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona):
            assert _persona_default_connection() == "01HQDEF"

    def test_single_connection_returns_service_connection_id(self):
        """Regression: previously read `id` and returned None for a usable connection."""
        persona = {"github": {"connections": [_CONN_A]}}
        with mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona):
            assert _persona_default_connection() == "01HQA"

    def test_multiple_connections_returns_none(self):
        persona = {"github": {"connections": [_CONN_A, _CONN_B]}}
        with mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona):
            assert _persona_default_connection() is None

    def test_no_github_block_returns_none(self):
        with mock.patch("superpos_sdk.gh_token._fetch_persona", return_value={}):
            assert _persona_default_connection() is None


class TestResolveConnectionAmbiguity:
    """The ambiguity error must print real service_connection_ids, not `?`."""

    def test_ambiguity_lists_service_connection_ids(self, capsys):
        persona = {"github": {"connections": [_CONN_A, _CONN_B]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            with pytest.raises(SystemExit) as exc_info:
                resolve_connection()
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "01HQA" in err
        assert "01HQB" in err
        assert "Superpos-AI" in err  # target_login is shown
        assert "superpos-agent[bot]" in err  # actor_login is shown
        assert "?" not in err  # regression: used to print `?` for the id


class TestListConnections:
    """--list-connections must emit the service_connection_id."""

    def test_lists_service_connection_ids(self, capsys):
        connections = [_CONN_A, _CONN_B]
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=connections):
            _cmd_list_connections(object())

        out = capsys.readouterr().out
        assert "01HQA" in out
        assert "01HQB" in out
        assert "Superpos-AI" in out  # target_login is shown
        assert "superpos-agent[bot]" in out  # actor_login is shown
        assert "?" not in out  # regression: used to print `?` for the id

    def test_no_connections_exits_nonzero(self, capsys):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[]):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_list_connections(object())
            assert exc_info.value.code == 1
        assert "No GitHub connections found." in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Bug — mint_token() must parse the REAL API error envelope:
#   {"data": null, "meta": {"install_url": ...}, "errors": [{"code": ...}]}
# It previously read body["error"]["code"] / body["error"]["install_url"],
# keys the API never returns, so the install hint was never surfaced.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stand-in for mint_token() error paths."""

    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class TestMintTokenErrorEnvelope:
    """Regression: mint_token() parses errors[0].code and meta.install_url."""

    @staticmethod
    def _env():
        return {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"}

    def test_not_installed_403_surfaces_install_url(self, capsys):
        """The real envelope shape must yield the install hint + message."""
        body = {
            "data": None,
            "meta": {"install_url": "https://github.com/apps/superpos/installations/new"},
            "errors": [
                {
                    "message": "GitHub App installation not found.",
                    "code": "github_app_not_installed",
                }
            ],
        }
        resp = _FakeResponse(403, json_body=body)

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-1")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "GitHub App is not installed on the target account." in err
        assert "https://github.com/apps/superpos/installations/new" in err

    def test_not_installed_403_without_meta_still_reports_message(self, capsys):
        """Missing meta must not crash; the not-installed message still shows."""
        body = {
            "data": None,
            "meta": {},
            "errors": [{"message": "not found", "code": "github_app_not_installed"}],
        }
        resp = _FakeResponse(403, json_body=body)

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-1")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "GitHub App is not installed on the target account." in err
        # No install URL available, so no "Install it here" line.
        assert "Install it here" not in err

    def test_generic_403_falls_through_to_broker_error(self, capsys):
        """A 403 without the not-installed code must produce a generic error."""
        body = {
            "data": None,
            "meta": {},
            "errors": [
                {"message": "Access to this service connection denied.", "code": "forbidden"},
            ],
        }
        resp = _FakeResponse(403, json_body=body, text=json.dumps(body))

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-1")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "Token broker error:" in err
        # Must NOT claim the App is not installed.
        assert "GitHub App is not installed" not in err

    def test_403_with_unparseable_body_does_not_crash(self, capsys):
        """A 403 with a non-JSON body must fall through without crashing."""
        resp = _FakeResponse(403, json_body=None, text="upstream gateway error")

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-1")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "Token broker error:" in err


# ---------------------------------------------------------------------------
# Bug — _read_cache must handle Z-suffix timestamps (Python 3.10 compat)
# ---------------------------------------------------------------------------


class TestReadCacheZSuffix:
    """_read_cache must handle Z-suffix timestamps (Python 3.10 compat)."""

    def test_z_suffix_expires_at_is_parsed(self, tmp_path):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache_data = {"token": "ghs_zsuffix", "expires_at": future}
        cache_file = tmp_path / "superpos-gh-token-conn-z.json"
        cache_file.write_text(json.dumps(cache_data))

        with mock.patch("superpos_sdk.gh_token._cache_path", return_value=cache_file):
            result = _read_cache("conn-z")

        assert result is not None
        assert result["token"] == "ghs_zsuffix"


# ---------------------------------------------------------------------------
# PAT cache bypass — PATs (expires_at=null) must never be cached
# ---------------------------------------------------------------------------


class TestPATCacheBypass:
    """PAT tokens must not be written to or served from the local cache."""

    @staticmethod
    def _env():
        return {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"}

    def test_mint_token_does_not_cache_pat_response(self):
        """When the broker returns expires_at=None, _write_cache must not be called."""
        pat_response = {
            "data": {
                "token": "ghp_rotatable_pat",
                "token_type": "pat",
                "expires_at": None,
                "permissions": None,
            }
        }
        resp = _FakeResponse(200, json_body=pat_response)

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
            mock.patch("superpos_sdk.gh_token._write_cache") as mock_write,
        ):
            result = mint_token("conn-pat")

        mock_write.assert_not_called()
        assert result["token"] == "ghp_rotatable_pat"

    def test_mint_token_caches_installation_token_response(self):
        """When the broker returns a real expires_at, _write_cache must be called."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        app_response = {
            "data": {
                "token": "ghs_installation_tok",
                "token_type": "installation",
                "expires_at": future,
                "permissions": {"contents": "read"},
            }
        }
        resp = _FakeResponse(200, json_body=app_response)

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
            mock.patch("superpos_sdk.gh_token._write_cache") as mock_write,
        ):
            result = mint_token("conn-app")

        mock_write.assert_called_once()
        assert result["token"] == "ghs_installation_tok"


# ---------------------------------------------------------------------------
# PAT connection exclusion from broker discovery (review fix)
# ---------------------------------------------------------------------------

_CONN_APP = {
    "service_connection_id": "01APP",
    "auth_type": "github_app",
    "broker_compatible": True,
    "target_type": "Organization",
    "target_login": "Superpos-AI",
    "repository_selection": "selected",
    "actor_login": "superpos-agent[bot]",
}
_CONN_PAT = {
    "service_connection_id": "01PAT",
    "auth_type": "token",
    "broker_compatible": False,
    "target_type": "User",
    "target_login": "octocat",
    "repository_selection": "all",
    "actor_login": "octocat",
}


class TestBrokerCompatibility:
    """_is_broker_compatible identifies PAT vs App connections."""

    def test_github_app_is_compatible(self):
        assert _is_broker_compatible(_CONN_APP) is True

    def test_pat_is_not_compatible(self):
        assert _is_broker_compatible(_CONN_PAT) is False

    def test_missing_auth_type_is_not_compatible(self):
        assert _is_broker_compatible({"service_connection_id": "01X"}) is False

    def test_unknown_auth_type_is_not_compatible(self):
        assert _is_broker_compatible({"auth_type": "oauth2"}) is False

    def test_explicit_broker_compatible_true_overrides_auth_type(self):
        assert _is_broker_compatible({"broker_compatible": True, "auth_type": "token"}) is True

    def test_explicit_broker_compatible_false_overrides_auth_type(self):
        conn = {"broker_compatible": False, "auth_type": "github_app"}
        assert _is_broker_compatible(conn) is False

    def test_fallback_to_auth_type_when_no_marker(self):
        assert _is_broker_compatible({"auth_type": "github_app"}) is True
        assert _is_broker_compatible({"auth_type": "token"}) is False


class TestResolveConnectionPATFiltering:
    """resolve_connection must filter out PAT connections from persona fallback."""

    def test_sole_app_among_mixed_is_auto_selected(self):
        """When persona has 1 App + 1 PAT, the App should be auto-selected."""
        persona = {"github": {"connections": [_CONN_APP, _CONN_PAT]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            result = resolve_connection()
        assert result == "01APP"

    def test_pat_only_org_dies_with_clear_message(self, capsys):
        """When all connections are PAT-backed, the helper must fail with guidance."""
        persona = {"github": {"connections": [_CONN_PAT]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            with pytest.raises(SystemExit) as exc_info:
                resolve_connection()
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "PAT-backed" in err
        assert "GITHUB_TOKEN" in err

    def test_multiple_apps_still_ambiguous(self, capsys):
        """Multiple App connections (no PAT) should still trigger ambiguity error."""
        conn_app2 = {**_CONN_APP, "service_connection_id": "01APP2", "target_login": "other-org"}
        persona = {"github": {"connections": [_CONN_APP, conn_app2, _CONN_PAT]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            with pytest.raises(SystemExit) as exc_info:
                resolve_connection()
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "01APP" in err
        assert "01APP2" in err
        # PAT connection should NOT appear in candidate list
        assert "01PAT" not in err

    def test_explicit_connection_bypasses_filtering(self):
        """--connection flag bypasses all filtering (user knows what they're doing)."""
        result = resolve_connection(explicit="01PAT")
        assert result == "01PAT"

    def test_env_var_bypasses_filtering(self):
        """GH_CONNECTION_ID bypasses filtering."""
        with mock.patch.dict(os.environ, {"GH_CONNECTION_ID": "01PAT"}, clear=True):
            result = resolve_connection()
        assert result == "01PAT"


class TestListConnectionsPATMarking:
    """--list-connections must mark PAT connections as broker-incompatible."""

    def test_pat_connection_marked_incompatible(self, capsys):
        connections = [_CONN_APP, _CONN_PAT]
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=connections):
            _cmd_list_connections(object())

        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert len(lines) == 2
        # App connection line should NOT have the incompatible marker
        assert "broker incompatible" not in lines[0]
        # PAT connection line should have it
        assert "broker incompatible" in lines[1]

    def test_all_app_connections_no_marker(self, capsys):
        connections = [_CONN_APP]
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=connections):
            _cmd_list_connections(object())

        out = capsys.readouterr().out
        assert "broker incompatible" not in out


class TestMintTokenPATBrokerError:
    """mint_token must surface a clear error when broker rejects a PAT connection."""

    @staticmethod
    def _env():
        return {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"}

    def test_pat_brokering_unsupported_gives_clear_error(self, capsys):
        """The broker's pat_brokering_unsupported must produce a user-friendly message."""
        body = {
            "data": None,
            "meta": {},
            "errors": [
                {
                    "message": "PAT brokering unsupported.",
                    "code": "pat_brokering_unsupported",
                }
            ],
        }
        resp = _FakeResponse(400, json_body=body, text=json.dumps(body))

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-pat")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "PAT-backed" in err
        assert "GITHUB_TOKEN" in err
        assert "GitHub App installation" in err

    def test_other_400_falls_through_to_generic_error(self, capsys):
        """A non-PAT 400 must still produce a generic broker error."""
        body = {
            "data": None,
            "meta": {},
            "errors": [{"message": "Bad request.", "code": "validation_error"}],
        }
        resp = _FakeResponse(400, json_body=body, text=json.dumps(body))

        with (
            mock.patch.dict(os.environ, self._env(), clear=True),
            mock.patch("superpos_sdk.gh_token._read_cache", return_value=None),
            mock.patch("superpos_sdk.gh_token._require_httpx"),
            mock.patch("superpos_sdk.gh_token.httpx.post", return_value=resp),
        ):
            with pytest.raises(SystemExit) as exc_info:
                mint_token("conn-x")
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "Token broker error:" in err
        assert "PAT-backed" not in err


# ---------------------------------------------------------------------------
# Server contract alignment — persona payload shape must match helper
# ---------------------------------------------------------------------------


class TestPersonaContractAlignment:
    """Verify the helper works with the real persona payload shape (broker_compatible field)."""

    def test_app_connection_with_broker_compatible_marker(self):
        conn = {
            "service_connection_id": "01APP",
            "name": "My App",
            "auth_type": "github_app",
            "broker_compatible": True,
            "target_type": "Organization",
            "target_login": "Superpos-AI",
            "repository_selection": "selected",
            "actor_login": "superpos-agent[bot]",
        }
        assert _is_broker_compatible(conn) is True

    def test_pat_connection_with_broker_compatible_marker(self):
        conn = {
            "service_connection_id": "01PAT",
            "name": "My PAT",
            "auth_type": "token",
            "broker_compatible": False,
            "target_type": "User",
            "target_login": "octocat",
            "repository_selection": None,
            "actor_login": "",
        }
        assert _is_broker_compatible(conn) is False

    def test_pat_only_persona_triggers_migration_guidance(self, capsys):
        """A persona with only PAT connections (broker_compatible=False) shows migration help."""
        pat_conn = {
            "service_connection_id": "01PAT",
            "auth_type": "token",
            "broker_compatible": False,
            "target_login": "octocat",
            "actor_login": "octocat",
        }
        persona = {"github": {"connections": [pat_conn]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            with pytest.raises(SystemExit) as exc_info:
                resolve_connection()
            assert exc_info.value.code == 1

        err = capsys.readouterr().err
        assert "PAT-backed" in err
        assert "GITHUB_TOKEN" in err

    def test_mixed_persona_auto_selects_app(self):
        """A persona with 1 App + 1 PAT must auto-select the App connection."""
        app_conn = {
            "service_connection_id": "01APP",
            "auth_type": "github_app",
            "broker_compatible": True,
            "target_login": "Superpos-AI",
            "actor_login": "superpos-agent[bot]",
        }
        pat_conn = {
            "service_connection_id": "01PAT",
            "auth_type": "token",
            "broker_compatible": False,
            "target_login": "octocat",
            "actor_login": "octocat",
        }
        persona = {"github": {"connections": [app_conn, pat_conn]}}
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token._discover_toml", return_value=None),
            mock.patch("superpos_sdk.gh_token._fetch_persona", return_value=persona),
        ):
            result = resolve_connection()
        assert result == "01APP"

    def test_list_connections_shows_pat_with_incompatible_marker(self, capsys):
        """--list-connections must show PAT connections with the incompatible marker."""
        app_conn = {
            "service_connection_id": "01APP",
            "auth_type": "github_app",
            "broker_compatible": True,
            "target_login": "Superpos-AI",
            "actor_login": "superpos-agent[bot]",
        }
        pat_conn = {
            "service_connection_id": "01PAT",
            "auth_type": "token",
            "broker_compatible": False,
            "target_login": "octocat",
            "actor_login": "octocat",
        }
        with mock.patch(
            "superpos_sdk.gh_token._persona_connections", return_value=[app_conn, pat_conn]
        ):
            _cmd_list_connections(object())

        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert len(lines) == 2
        assert "broker incompatible" not in lines[0]
        assert "broker incompatible" in lines[1]


# ---------------------------------------------------------------------------
# Review fix — GHES host must be derivable from the resolved connection's
# base_url so the GHES path works on hosted runtimes (no SUPERPOS_GHES_HOST).
# ---------------------------------------------------------------------------

# A GHES github_app connection advertising its own enterprise API base_url.
_CONN_GHES = {
    "service_connection_id": "01GHES",
    "auth_type": "github_app",
    "broker_compatible": True,
    "base_url": "https://github.acme.corp/api/v3",
    "target_type": "Organization",
    "target_login": "acme",
    "repository_selection": "all",
    "actor_login": "superpos-agent[bot]",
}


_CONN_PUBLIC_WITH_API_BASE = {
    "service_connection_id": "01PUB_API",
    "auth_type": "github_app",
    "broker_compatible": True,
    "base_url": "https://api.github.com",
    "target_type": "Organization",
    "target_login": "Superpos-AI",
    "repository_selection": "selected",
    "actor_login": "superpos-agent[bot]",
}


class TestConnectionBaseUrlHelper:
    """_connection_base_url returns the persona-advertised base_url."""

    def test_returns_base_url_for_matching_connection(self):
        with mock.patch(
            "superpos_sdk.gh_token._persona_connections",
            return_value=[_CONN_GHES, _CONN_APP],
        ):
            assert _connection_base_url("01GHES") == "https://github.acme.corp/api/v3"

    def test_returns_empty_for_unknown_connection(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            assert _connection_base_url("does-not-exist") == ""

    def test_returns_empty_when_base_url_missing(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            # _CONN_APP carries no base_url key.
            assert _connection_base_url("01APP") == ""


class TestConnectionHostResolvers:
    """_connection_host / _connection_api_base_url must distinguish a connection
    that is ABSENT from the persona (host unprovable -> None) from one that is
    present but carries no base_url (genuine public GitHub)."""

    def test_host_for_present_connection_without_base_url(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            # Present, no base_url -> public github.com.
            assert _connection_host("01APP") == "github.com"

    def test_host_for_present_connection_with_public_api_base_url(self):
        with mock.patch(
            "superpos_sdk.gh_token._persona_connections",
            return_value=[_CONN_PUBLIC_WITH_API_BASE],
        ):
            assert _connection_host("01PUB_API") == "github.com"

    def test_host_for_present_ghes_connection(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_GHES]):
            assert _connection_host("01GHES") == "github.acme.corp"

    def test_host_none_for_absent_connection(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            # Absent from persona -> unprovable host -> None (fail closed).
            assert _connection_host("does-not-exist") is None

    def test_host_none_for_unparseable_base_url(self):
        bad = {"service_connection_id": "01BAD", "base_url": "not-a-url"}
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[bad]):
            assert _connection_host("01BAD") is None

    def test_api_base_url_for_present_connection_without_base_url(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            assert _connection_api_base_url("01APP") == "https://api.github.com"

    def test_api_base_url_for_present_ghes_connection(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_GHES]):
            assert _connection_api_base_url("01GHES") == "https://github.acme.corp/api/v3"

    def test_api_base_url_none_for_absent_connection(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            assert _connection_api_base_url("does-not-exist") is None

    def test_find_persona_connection_returns_none_when_absent(self):
        with mock.patch("superpos_sdk.gh_token._persona_connections", return_value=[_CONN_APP]):
            assert _find_persona_connection("does-not-exist") is None
            assert _find_persona_connection("01APP") == _CONN_APP


class TestGitCredentialGhesDerivation:
    """git-credential validates the requested host against the issuing
    connection's own base_url for every host — including github.com."""

    @staticmethod
    def _make_args(**overrides):
        defaults = {"connection": None, "refresh": False}
        defaults.update(overrides)
        return type("Args", (), defaults)()

    def test_github_com_verified_against_connection_base_url(self):
        """github.com is NOT trusted on a blind fast path: the connection is
        looked up in the persona, and a public github.com connection (present,
        no base_url) is what authorizes minting a github.com token."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_pub"}),
            # The persona connection MUST be consulted even for github.com so a
            # GHES-bound connection can never silently issue a github.com token.
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ) as mock_lookup,
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_pub" in c for c in calls)
            mock_lookup.assert_called_once_with("conn-1")

    def test_allows_ghes_host_derived_from_connection_without_env(self):
        """A GHES host matching the connection base_url is allowed with no env."""
        stdin = StringIO("protocol=https\nhost=github.acme.corp\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,  # SUPERPOS_GHES_HOST intentionally unset
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_ent"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_ent" in c for c in calls)

    def test_fails_closed_for_unrelated_host(self):
        """A host that matches neither github.com nor the connection base_url
        must fail closed (exit 0) and never mint a token."""
        stdin = StringIO("protocol=https\nhost=gitlab.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_mint.assert_not_called()


class TestApiBaseUrlMode:
    """--api-base-url prints the connection's API base URL."""

    @staticmethod
    def _make_args(**overrides):
        defaults = {"connection": None, "refresh": False}
        defaults.update(overrides)
        return type("Args", (), defaults)()

    def test_prints_connection_base_url(self, capsys):
        with (
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
        ):
            _cmd_api_base_url(self._make_args())

        out = capsys.readouterr().out.strip()
        assert out == "https://github.acme.corp/api/v3"

    def test_public_github_when_present_without_base_url(self, capsys):
        """A connection present in the persona with no base_url is public GitHub
        and resolves to api.github.com."""
        with (
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01APP"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "01APP"},
            ),
        ):
            _cmd_api_base_url(self._make_args())

        out = capsys.readouterr().out.strip()
        assert out == "https://api.github.com"

    def test_fails_closed_when_connection_absent_from_persona(self, capsys):
        """A connection the persona does NOT advertise must NOT default to public
        GitHub: its host is unprovable, so the helper exits non-zero with no
        stdout (the worker treats that as a hard refusal)."""
        with (
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch("superpos_sdk.gh_token._find_persona_connection", return_value=None),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_api_base_url(self._make_args())
        assert exc_info.value.code != 0
        # Must not have printed a base URL to stdout.
        assert capsys.readouterr().out.strip() == ""

    def test_main_wires_api_base_url_flag(self, capsys):
        """`superpos-gh-token --api-base-url` must route to _cmd_api_base_url."""
        argv = ["superpos-gh-token", "--api-base-url"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="01GHES"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={
                    "service_connection_id": "01GHES",
                    "base_url": "https://github.acme.corp/api/v3",
                },
            ),
        ):
            main()

        out = capsys.readouterr().out.strip()
        assert out == "https://github.acme.corp/api/v3"


# ---------------------------------------------------------------------------
# Security — Credential helper must reject non-HTTPS protocols
# ---------------------------------------------------------------------------


class TestProtocolSchemeValidation:
    """Credential helper must reject protocol=http to prevent cleartext leaks."""

    @staticmethod
    def _make_args(**overrides):
        defaults = {"connection": None, "refresh": False}
        defaults.update(overrides)
        return type("Args", (), defaults)()

    def test_http_protocol_exits_without_credentials(self):
        """protocol=http must cause exit(0) without minting or printing anything."""
        stdin = StringIO("protocol=http\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token.resolve_connection") as mock_resolve,
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_resolve.assert_not_called()
            mock_mint.assert_not_called()
            mock_print.assert_not_called()

    @pytest.mark.parametrize("protocol", ["http", "ftp", "git", "ssh"])
    def test_non_https_protocols_rejected(self, protocol):
        """Any non-https protocol must be rejected."""
        stdin = StringIO(f"protocol={protocol}\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("superpos_sdk.gh_token.resolve_connection") as mock_resolve,
            mock.patch("superpos_sdk.gh_token.mint_token") as mock_mint,
        ):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_git_credential(self._make_args())
            assert exc_info.value.code == 0
            mock_resolve.assert_not_called()
            mock_mint.assert_not_called()

    def test_https_protocol_proceeds_normally(self):
        """protocol=https must NOT be rejected — credentials are emitted."""
        stdin = StringIO("protocol=https\nhost=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_ok"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_ok" in c for c in calls)

    def test_absent_protocol_proceeds_normally(self):
        """Missing protocol field defaults to https — must NOT be rejected."""
        stdin = StringIO("host=github.com\n\n")
        with (
            mock.patch("superpos_sdk.gh_token.sys.stdin", stdin),
            mock.patch.dict(
                os.environ,
                {"SUPERPOS_BASE_URL": "https://superpos.test", "SUPERPOS_API_TOKEN": "tok"},
                clear=True,
            ),
            mock.patch("superpos_sdk.gh_token.resolve_connection", return_value="conn-1"),
            mock.patch(
                "superpos_sdk.gh_token._find_persona_connection",
                return_value={"service_connection_id": "conn-1"},
            ),
            mock.patch("superpos_sdk.gh_token.mint_token", return_value={"token": "ghs_nopr"}),
            mock.patch("superpos_sdk.gh_token.print") as mock_print,
        ):
            _cmd_git_credential(self._make_args())
            calls = [str(c) for c in mock_print.call_args_list]
            assert any("password=ghs_nopr" in c for c in calls)
