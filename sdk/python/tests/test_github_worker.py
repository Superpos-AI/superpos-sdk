"""Tests for GitHubWorker — connection-aware credential resolution."""

from __future__ import annotations

import subprocess
import warnings
from unittest import mock

import pytest

from superpos_sdk.workers.github import GitHubWorker


class TestResolveTokenConnectionBinding:
    """_resolve_token must forward connection_id to superpos-gh-token --connection."""

    def test_connection_id_passed_via_flag(self):
        """When params contain connection_id, superpos-gh-token receives --connection."""
        params = {"owner": "acme", "repo": "backend", "connection_id": "conn-alpha"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="ghs_alpha\n")
            token = GitHubWorker._resolve_token(params)

        assert token == "ghs_alpha"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["superpos-gh-token", "--connection", "conn-alpha"]

    def test_service_connection_id_passed_via_flag(self):
        """service_connection_id is accepted as an alias for connection_id."""
        params = {"owner": "acme", "repo": "backend", "service_connection_id": "conn-beta"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="ghs_beta\n")
            token = GitHubWorker._resolve_token(params)

        assert token == "ghs_beta"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["superpos-gh-token", "--connection", "conn-beta"]

    def test_connection_id_takes_precedence_over_service_connection_id(self):
        """When both keys exist, connection_id wins (or short-circuits)."""
        params = {
            "owner": "acme",
            "repo": "backend",
            "connection_id": "conn-primary",
            "service_connection_id": "conn-fallback",
        }

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="ghs_primary\n")
            token = GitHubWorker._resolve_token(params)

        assert token == "ghs_primary"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["superpos-gh-token", "--connection", "conn-primary"]

    def test_no_connection_id_omits_flag(self):
        """Without a connection key, superpos-gh-token is called with no --connection."""
        params = {"owner": "acme", "repo": "backend"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="ghs_default\n")
            token = GitHubWorker._resolve_token(params)

        assert token == "ghs_default"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["superpos-gh-token"]

    def test_explicit_token_bypasses_helper(self):
        """An explicit token in params skips superpos-gh-token entirely."""
        params = {
            "owner": "acme",
            "repo": "backend",
            "token": "ghp_explicit",
            "connection_id": "conn-x",
        }

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            token = GitHubWorker._resolve_token(params)

        assert token == "ghp_explicit"
        mock_run.assert_not_called()

    def test_two_sequential_requests_resolve_different_connections(self):
        """Regression: two requests in the same process must resolve different connections.

        This verifies that _resolve_token does not cache or leak state between
        calls — each invocation builds its command from the current params.
        """
        params_a = {"owner": "acme", "repo": "frontend", "connection_id": "conn-111"}
        params_b = {"owner": "acme", "repo": "backend", "connection_id": "conn-222"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock.Mock(returncode=0, stdout="ghs_token_for_111\n"),
                mock.Mock(returncode=0, stdout="ghs_token_for_222\n"),
            ]

            token_a = GitHubWorker._resolve_token(params_a)
            token_b = GitHubWorker._resolve_token(params_b)

        assert token_a == "ghs_token_for_111"
        assert token_b == "ghs_token_for_222"

        assert mock_run.call_count == 2
        cmd_a = mock_run.call_args_list[0][0][0]
        cmd_b = mock_run.call_args_list[1][0][0]
        assert cmd_a == ["superpos-gh-token", "--connection", "conn-111"]
        assert cmd_b == ["superpos-gh-token", "--connection", "conn-222"]


class TestResolveTokenFailClosed:
    """When an explicit connection binding is supplied, helper failure must
    fail closed — never degrade to the ambient GITHUB_TOKEN."""

    def test_explicit_binding_failure_raises_and_does_not_fall_back(self, monkeypatch):
        """connection_id supplied + helper returns non-zero/empty → RuntimeError,
        and the GITHUB_TOKEN sentinel is never returned."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_ambient_sentinel")
        params = {"owner": "acme", "repo": "backend", "connection_id": "conn-alpha"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_token(params)

        assert "conn-alpha" in str(excinfo.value)
        assert "ghp_ambient_sentinel" not in str(excinfo.value)

    def test_explicit_binding_helper_missing_raises(self, monkeypatch):
        """connection_id supplied + helper missing (FileNotFoundError) → RuntimeError,
        no fallback to GITHUB_TOKEN."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_ambient_sentinel")
        params = {"owner": "acme", "repo": "backend", "connection_id": "conn-beta"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("superpos-gh-token not found")
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_token(params)

        assert "conn-beta" in str(excinfo.value)

    def test_explicit_binding_helper_timeout_raises(self, monkeypatch):
        """connection_id supplied + helper times out → RuntimeError, no fallback."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_ambient_sentinel")
        params = {"owner": "acme", "repo": "backend", "connection_id": "conn-gamma"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["superpos-gh-token", "--connection", "conn-gamma"], timeout=30
            )
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_token(params)

        assert "conn-gamma" in str(excinfo.value)

    def test_no_binding_helper_failure_falls_back_to_env(self, monkeypatch):
        """No connection_id + helper fails → preserve legacy behavior: fall back
        to GITHUB_TOKEN and emit the DeprecationWarning."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_ambient_sentinel")
        params = {"owner": "acme", "repo": "backend"}

        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                token = GitHubWorker._resolve_token(params)

        assert token == "ghp_ambient_sentinel"
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)


class TestResolveApiBaseUrl:
    """_resolve_api_base_url must default to public GitHub, honor a GHES base
    URL, and fail closed for any other host so credentials never leak off-host."""

    def test_default_is_public_github(self, monkeypatch):
        """No api_base_url and no GHES env → public GitHub REST API."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        assert (
            GitHubWorker._resolve_api_base_url({"owner": "acme", "repo": "backend"})
            == "https://api.github.com"
        )

    def test_explicit_public_api_passes_and_strips_trailing_slash(self, monkeypatch):
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        base = GitHubWorker._resolve_api_base_url(
            {"owner": "acme", "repo": "backend", "api_base_url": "https://api.github.com/"}
        )
        assert base == "https://api.github.com"

    def test_ghes_base_allowed_when_matches_bound_connection(self, monkeypatch):
        """An explicit GHES api_base_url is honored when its host matches the
        bound connection's own derived host (SUPERPOS_GHES_HOST is irrelevant
        for connection-bound requests)."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            base = GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "connection_id": "conn-ghes",
                    "api_base_url": "https://github.acme.corp/api/v3",
                }
            )
        assert base == "https://github.acme.corp/api/v3"

    def test_ghes_base_rejected_when_not_configured(self, monkeypatch):
        """A GHES api_base_url with no configured GHES host fails closed."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with pytest.raises(RuntimeError) as excinfo:
            GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "api_base_url": "https://github.acme.corp/api/v3",
                }
            )
        assert "github.acme.corp" in str(excinfo.value)

    def test_lookalike_host_rejected(self, monkeypatch):
        """A lookalike domain must never receive a token (exact-match host check)."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with pytest.raises(RuntimeError):
            GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "api_base_url": "https://api.github.com.evil.com",
                }
            )

    def test_unrelated_host_rejected_even_with_ghes_configured(self, monkeypatch):
        """Configuring one GHES host does not whitelist a different host."""
        monkeypatch.setenv("SUPERPOS_GHES_HOST", "github.acme.corp")
        with pytest.raises(RuntimeError):
            GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "api_base_url": "https://evil.example.com/api/v3",
                }
            )

    # --------------------------------------------------------------
    # Review fix: the connection's own API host is derived & allowed
    # automatically (no SUPERPOS_GHES_HOST needed on hosted runtimes).
    # --------------------------------------------------------------

    def test_default_is_public_github_with_no_connection(self, monkeypatch):
        """No api_base_url and no connection → public GitHub, no subprocess."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            base = GitHubWorker._resolve_api_base_url({"owner": "acme", "repo": "backend"})
        assert base == "https://api.github.com"
        # Without a connection binding the helper must not be invoked.
        mock_run.assert_not_called()

    def test_connection_ghes_base_is_derived_and_allowed_without_env(self, monkeypatch):
        """A connection whose base_url is a GHES API host is derived and allowed
        even when SUPERPOS_GHES_HOST is unset."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            base = GitHubWorker._resolve_api_base_url(
                {"owner": "acme", "repo": "backend", "connection_id": "conn-ghes"}
            )
        assert base == "https://github.acme.corp/api/v3"
        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "superpos-gh-token",
            "--connection",
            "conn-ghes",
            "--api-base-url",
        ]

    def test_service_connection_id_alias_is_derived(self, monkeypatch):
        """service_connection_id is accepted as an alias for connection_id."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            base = GitHubWorker._resolve_api_base_url(
                {"owner": "acme", "repo": "backend", "service_connection_id": "conn-ghes"}
            )
        assert base == "https://github.acme.corp/api/v3"

    def test_helper_failure_fails_closed_for_bound_connection(self, monkeypatch):
        """If the helper cannot prove a bound connection's host, the request must
        fail closed — NOT degrade to public GitHub. Otherwise a connection-bound
        (possibly GHES) token could be sent to api.github.com."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("superpos-gh-token not found")
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_api_base_url(
                    {"owner": "acme", "repo": "backend", "connection_id": "conn-x"}
                )
        assert "conn-x" in str(excinfo.value)

    def test_helper_nonzero_exit_fails_closed_for_bound_connection(self, monkeypatch):
        """A non-zero/empty helper result for a bound connection also fails closed."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            with pytest.raises(RuntimeError):
                GitHubWorker._resolve_api_base_url(
                    {"owner": "acme", "repo": "backend", "connection_id": "conn-x"}
                )

    def test_explicit_public_github_rejected_for_ghes_bound_connection(self, monkeypatch):
        """Explicitly targeting api.github.com for a GHES-bound connection must
        fail closed: the public host does not match the bound connection's host,
        so the GHES token is never sent to public GitHub even though
        api.github.com is otherwise an allowed host."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_api_base_url(
                    {
                        "owner": "acme",
                        "repo": "backend",
                        "connection_id": "conn-ghes",
                        "api_base_url": "https://api.github.com",
                    }
                )
        assert "github.acme.corp" in str(excinfo.value)

    def test_explicit_api_base_url_to_unrelated_host_still_raises(self, monkeypatch):
        """An explicit api_base_url to a host that matches neither the env GHES
        host nor the connection's own host must still fail closed."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            with pytest.raises(RuntimeError) as excinfo:
                GitHubWorker._resolve_api_base_url(
                    {
                        "owner": "acme",
                        "repo": "backend",
                        "connection_id": "conn-ghes",
                        "api_base_url": "https://evil.example.com/api/v3",
                    }
                )
        assert "evil.example.com" in str(excinfo.value)


class TestClientUsesResolvedBaseUrl:
    """_client must build the httpx.Client against the resolved base URL and
    refuse (before any HTTP call) when the host is disallowed."""

    def _worker(self) -> GitHubWorker:
        return GitHubWorker(
            "https://superpos.test",
            "01HXYZ00000000000000000001",
            name="gh-worker",
            secret="s3cr3t",
        )

    def test_public_default_base_url(self, monkeypatch):
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        worker = self._worker()
        with mock.patch("httpx.Client") as mock_client:
            worker._client({"owner": "acme", "repo": "backend", "token": "ghp_x"})
        assert mock_client.call_args.kwargs["base_url"] == "https://api.github.com"

    def test_ghes_base_url_threaded_to_client(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_GHES_HOST", "github.acme.corp")
        worker = self._worker()
        with mock.patch("httpx.Client") as mock_client:
            worker._client(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "token": "ghs_ghes",
                    "api_base_url": "https://github.acme.corp/api/v3",
                }
            )
        assert mock_client.call_args.kwargs["base_url"] == "https://github.acme.corp/api/v3"

    def test_disallowed_host_refuses_before_any_request(self, monkeypatch):
        """A request bound to a disallowed host must raise before httpx is touched."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        worker = self._worker()
        with mock.patch("httpx.Client") as mock_client:
            with pytest.raises(RuntimeError):
                worker.get_issue(
                    {
                        "owner": "acme",
                        "repo": "backend",
                        "number": 1,
                        "token": "ghs_ghes",
                        "api_base_url": "https://github.acme.corp/api/v3",
                    }
                )
        mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# Security — _resolve_api_base_url must reject non-HTTPS schemes
# ---------------------------------------------------------------------------


class TestResolveApiBaseUrlSchemeValidation:
    """_resolve_api_base_url must reject http:// and other non-https schemes."""

    def test_http_unbound_rejected(self, monkeypatch):
        """An unbound request with http:// base URL must be refused."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with pytest.raises(RuntimeError, match="non-HTTPS"):
            GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "api_base_url": "http://api.github.com",
                }
            )

    def test_http_connection_bound_rejected(self, monkeypatch):
        """A connection-bound request with http:// explicit URL must be refused."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            with pytest.raises(RuntimeError, match="non-HTTPS"):
                GitHubWorker._resolve_api_base_url(
                    {
                        "owner": "acme",
                        "repo": "backend",
                        "connection_id": "conn-ghes",
                        "api_base_url": "http://github.acme.corp/api/v3",
                    }
                )

    @pytest.mark.parametrize("scheme", ["http", "ftp", "git"])
    def test_non_https_schemes_rejected_unbound(self, scheme, monkeypatch):
        """Any non-https scheme must be rejected for unbound requests."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with pytest.raises(RuntimeError, match="non-HTTPS"):
            GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "api_base_url": f"{scheme}://api.github.com",
                }
            )

    def test_https_unbound_accepted(self, monkeypatch):
        """https:// must be accepted for unbound requests (sanity check)."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        base = GitHubWorker._resolve_api_base_url(
            {
                "owner": "acme",
                "repo": "backend",
                "api_base_url": "https://api.github.com",
            }
        )
        assert base == "https://api.github.com"

    def test_https_connection_bound_accepted(self, monkeypatch):
        """https:// must be accepted for connection-bound requests (sanity check)."""
        monkeypatch.delenv("SUPERPOS_GHES_HOST", raising=False)
        with mock.patch("superpos_sdk.workers.github.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout="https://github.acme.corp/api/v3\n"
            )
            base = GitHubWorker._resolve_api_base_url(
                {
                    "owner": "acme",
                    "repo": "backend",
                    "connection_id": "conn-ghes",
                    "api_base_url": "https://github.acme.corp/api/v3",
                }
            )
        assert base == "https://github.acme.corp/api/v3"
