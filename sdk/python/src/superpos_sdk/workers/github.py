"""GitHub service worker — interact with the GitHub REST API.

Install the optional dependency::

    pip install superpos-sdk[github]

Credential resolution (first match wins):

1. Per-request ``token`` key in the task payload
2. ``superpos-gh-token`` credential helper (mints short-lived GitHub App tokens)
3. ``GITHUB_TOKEN`` env var (**deprecated** — migrate to superpos-gh-token)
4. Unauthenticated (public endpoints only)

Task payload (``params``) schema varies by operation.  All operations accept
an optional ``token`` key that overrides automatic credential resolution.
An optional ``connection_id`` (or ``service_connection_id``) key binds
credential resolution to a specific GitHub App connection, ensuring
multi-connection workers resolve the correct installation token per request.

An optional ``api_base_url`` key targets a GitHub Enterprise Server (GHES)
REST API (e.g. ``https://github.acme.corp/api/v3``) so a connection's token
is sent to its own host rather than public GitHub.

Host resolution fails closed so a credential is never leaked off-host:

* For **connection-bound** requests the host must equal the bound connection's
  own API host (derived via ``superpos-gh-token --api-base-url``). If that host
  cannot be proven, the request is refused — it never degrades to public
  GitHub, and ``api.github.com`` / ``SUPERPOS_GHES_HOST`` are not accepted as
  substitutes for the connection's host.
* For **unbound** requests the host must be ``api.github.com`` (the default) or
  the configured ``SUPERPOS_GHES_HOST``; any other host is refused.

Supported operations
--------------------

``get_issue``
    ``{"owner": "...", "repo": "...", "number": 1}``

``create_issue``
    ``{"owner": "...", "repo": "...", "title": "...", "body": "...", "labels": [...]}``

``list_issues``
    ``{"owner": "...", "repo": "...", "state": "open", "per_page": 30, "page": 1}``

``get_pr``
    ``{"owner": "...", "repo": "...", "number": 1}``

``list_prs``
    ``{"owner": "...", "repo": "...", "state": "open", "per_page": 30, "page": 1}``

``create_pr``
    ``{"owner": "...", "repo": "...", "title": "...", "head": "...", "base": "...",
       "body": "...", "draft": false}``

``get_file``
    ``{"owner": "...", "repo": "...", "path": "README.md", "ref": "main"}``

``create_file``
    ``{"owner": "...", "repo": "...", "path": "...", "message": "...",
       "content": "<base64>", "branch": "main"}``

``update_file``
    ``{"owner": "...", "repo": "...", "path": "...", "message": "...",
       "content": "<base64>", "sha": "...", "branch": "main"}``

``list_commits``
    ``{"owner": "...", "repo": "...", "sha": "main", "per_page": 30, "page": 1}``

``get_commit``
    ``{"owner": "...", "repo": "...", "ref": "<sha>"}``
"""

from __future__ import annotations

import os
import subprocess
import warnings
from typing import Any
from urllib.parse import urlsplit

from superpos_sdk._github_host import normalize_host
from superpos_sdk.service_worker import ServiceWorker

_GITHUB_API = "https://api.github.com"

# REST API host for public GitHub. Note this is ``api.github.com``, not
# ``github.com`` — GitHub Enterprise Server instead serves its REST API from
# ``https://<ghes-host>/api/v3`` (same host as the web UI).
_PUBLIC_API_HOST = "api.github.com"


class GitHubWorker(ServiceWorker):
    """Service worker that proxies GitHub REST API calls.

    Credentials are resolved via a three-tier fallback:

    1. Per-request ``token`` in *params*
    2. ``superpos-gh-token`` credential helper (preferred)
    3. ``GITHUB_TOKEN`` env var (deprecated)
    """

    CAPABILITY = "data:github"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_token(params: dict[str, Any]) -> str:
        """Resolve a GitHub token using the three-tier fallback chain."""
        explicit = params.get("token")
        if explicit:
            return explicit

        # Build the superpos-gh-token command, optionally binding to a
        # specific service connection so that multi-connection workers
        # resolve the correct installation token per request.
        cmd = ["superpos-gh-token"]
        connection_id = params.get("connection_id") or params.get("service_connection_id")
        if connection_id:
            cmd.extend(["--connection", connection_id])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            # Helper ran but failed (non-zero exit or empty output).
            helper_failed = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Helper could not be invoked (missing) or timed out.
            helper_failed = True

        if helper_failed and connection_id:
            # Fail closed: an explicit per-request connection binding was
            # supplied, so we must NOT degrade to the ambient GITHUB_TOKEN —
            # doing so could send a request bound to connection A using an
            # unrelated global credential (wrong installation).
            raise RuntimeError(
                f"Failed to resolve a GitHub token for connection "
                f"{connection_id!r} via superpos-gh-token; refusing to fall "
                f"back to the ambient GITHUB_TOKEN (would risk using an "
                f"unrelated credential)."
            )

        env_token = os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            warnings.warn(
                "GITHUB_TOKEN env var is deprecated; migrate to superpos-gh-token helper",
                DeprecationWarning,
                stacklevel=2,
            )
            return env_token

        return ""

    @staticmethod
    def _connection_api_base_url(connection_id: str) -> str:
        """Derive a connection's API base URL via the superpos-gh-token helper.

        Shells out to ``superpos-gh-token --connection <id> --api-base-url``
        (the same subprocess pattern as :meth:`_resolve_token`). Returns the
        helper's output on success, or an empty string on any failure (helper
        missing, timeout, non-zero exit, empty output).

        It deliberately does NOT fall back to public GitHub: when a request is
        bound to a connection, the caller cannot prove the connection's host on
        failure, and silently defaulting to ``api.github.com`` would risk
        sending a connection-bound (possibly GHES) token to public GitHub. The
        caller is responsible for failing closed on an empty result.
        """
        cmd = ["superpos-gh-token", "--connection", connection_id, "--api-base-url"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""

    @staticmethod
    def _resolve_api_base_url(params: dict[str, Any]) -> str:
        """Resolve the GitHub REST API base URL for this request.

        Tokens are resolved per connection, so the request must be sent to the
        host that issued the token.

        **Connection-bound requests** (a ``connection_id`` /
        ``service_connection_id`` is present) resolve the bound connection's own
        API host via ``superpos-gh-token --api-base-url`` and fail closed:

        * If the connection's host cannot be proven (helper missing, timeout,
          non-zero exit, empty output) the request is refused — it never
          degrades to public GitHub, because doing so could send a
          connection-bound (possibly GHES) installation token to the wrong host.
        * The resolved host must *equal* the bound connection's host. An
          explicit ``api_base_url`` is honoured only when its host matches the
          connection; ``api.github.com`` and ``SUPERPOS_GHES_HOST`` are NOT
          unioned into the allowlist for bound requests, so a GHES-bound token
          can never be directed at public GitHub.

        **Unbound requests** (no connection) keep the legacy allowlist: an
        explicit ``api_base_url`` (or the public-GitHub default) whose host is
        ``api.github.com`` or the configured ``SUPERPOS_GHES_HOST``; any other
        host is refused.
        """
        connection_id = params.get("connection_id") or params.get("service_connection_id")
        explicit = params.get("api_base_url")

        if connection_id:
            # Fail closed: we must prove the bound connection's host before
            # sending it a token. An empty result means the helper could not
            # vouch for the host — refuse rather than fall back to public GitHub.
            connection_base = GitHubWorker._connection_api_base_url(connection_id)
            if not connection_base:
                raise RuntimeError(
                    f"Refusing to send GitHub credentials for connection "
                    f"{connection_id!r}: could not derive its API host via "
                    f"superpos-gh-token (helper missing, timed out, or failed). "
                    f"Failing closed instead of defaulting to public GitHub."
                )
            connection_host = normalize_host(urlsplit(connection_base).hostname or "")
            if not connection_host:
                raise RuntimeError(
                    f"Refusing to send GitHub credentials for connection "
                    f"{connection_id!r}: derived API base {connection_base!r} "
                    f"has no usable host."
                )

            base = (explicit or connection_base).rstrip("/")
            scheme = urlsplit(base).scheme
            if scheme != "https":
                raise RuntimeError(
                    f"Refusing to send GitHub credentials over non-HTTPS "
                    f"scheme {scheme!r} (resolved from {base!r}). Only "
                    f"https:// API URLs are permitted."
                )
            host = normalize_host(urlsplit(base).hostname or "")
            if host != connection_host:
                raise RuntimeError(
                    f"Refusing to send GitHub credentials to host {host!r} "
                    f"(resolved from {base!r}): it does not match the bound "
                    f"connection's host {connection_host!r}. A connection-bound "
                    f"token must only be sent to its own host."
                )
            return base

        # Unbound request: legacy allowlist (public GitHub + optional GHES env).
        base = explicit.rstrip("/") if explicit else _GITHUB_API
        scheme = urlsplit(base).scheme
        if scheme != "https":
            raise RuntimeError(
                f"Refusing to send GitHub credentials over non-HTTPS "
                f"scheme {scheme!r} (resolved from {base!r}). Only "
                f"https:// API URLs are permitted."
            )
        host = normalize_host(urlsplit(base).hostname or "")
        ghes_host = normalize_host(os.environ.get("SUPERPOS_GHES_HOST", ""))

        allowed = {_PUBLIC_API_HOST}
        if ghes_host:
            allowed.add(ghes_host)

        if host not in allowed:
            raise RuntimeError(
                f"Refusing to send GitHub credentials to disallowed host "
                f"{host!r} (resolved from {base!r}). Allowed API hosts: "
                f"{', '.join(sorted(allowed))}. Set SUPERPOS_GHES_HOST for a "
                f"GitHub Enterprise host, or target api.github.com."
            )

        return base

    def _client(self, params: dict[str, Any]):  # type: ignore[return]
        """Return an httpx.Client configured for the GitHub API."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "httpx is required for GitHubWorker. "
                "Install it with: pip install superpos-sdk[github]"
            ) from exc

        base_url = self._resolve_api_base_url(params)
        token = self._resolve_token(params)
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=base_url, headers=headers, timeout=30)

    def _get(self, params: dict[str, Any], path: str, **query: Any) -> Any:
        query = {k: v for k, v in query.items() if v is not None}
        with self._client(params) as c:
            r = c.get(path, params=query or None)
            r.raise_for_status()
            return r.json()

    def _post(self, params: dict[str, Any], path: str, body: dict[str, Any]) -> Any:
        with self._client(params) as c:
            r = c.post(path, json=body)
            r.raise_for_status()
            return r.json()

    def _put(self, params: dict[str, Any], path: str, body: dict[str, Any]) -> Any:
        with self._client(params) as c:
            r = c.put(path, json=body)
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _repo_path(params: dict[str, Any], *parts: str) -> str:
        owner = params["owner"]
        repo = params["repo"]
        base = f"/repos/{owner}/{repo}"
        if parts:
            base = base + "/" + "/".join(str(p) for p in parts)
        return base

    # ------------------------------------------------------------------
    # Issue operations
    # ------------------------------------------------------------------

    def get_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single issue by number."""
        return self._get(params, self._repo_path(params, "issues", params["number"]))

    def create_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new issue."""
        body: dict[str, Any] = {"title": params["title"]}
        if params.get("body"):
            body["body"] = params["body"]
        if params.get("labels"):
            body["labels"] = params["labels"]
        if params.get("assignees"):
            body["assignees"] = params["assignees"]
        return self._post(params, self._repo_path(params, "issues"), body)

    def list_issues(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """List issues for a repository."""
        return self._get(
            params,
            self._repo_path(params, "issues"),
            state=params.get("state", "open"),
            per_page=params.get("per_page", 30),
            page=params.get("page", 1),
            labels=params.get("labels"),
        )

    # ------------------------------------------------------------------
    # Pull request operations
    # ------------------------------------------------------------------

    def get_pr(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single pull request by number."""
        return self._get(params, self._repo_path(params, "pulls", params["number"]))

    def list_prs(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """List pull requests for a repository."""
        return self._get(
            params,
            self._repo_path(params, "pulls"),
            state=params.get("state", "open"),
            per_page=params.get("per_page", 30),
            page=params.get("page", 1),
        )

    def create_pr(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new pull request."""
        body: dict[str, Any] = {
            "title": params["title"],
            "head": params["head"],
            "base": params["base"],
        }
        if params.get("body"):
            body["body"] = params["body"]
        if "draft" in params:
            body["draft"] = bool(params["draft"])
        return self._post(params, self._repo_path(params, "pulls"), body)

    # ------------------------------------------------------------------
    # File / content operations
    # ------------------------------------------------------------------

    def get_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a file's metadata and base64-encoded content."""
        path = self._repo_path(params, "contents", params["path"])
        query: dict[str, Any] = {}
        if params.get("ref"):
            query["ref"] = params["ref"]
        with self._client(params) as c:
            r = c.get(path, params=query or None)
            r.raise_for_status()
            return r.json()

    def create_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new file via the Contents API."""
        body: dict[str, Any] = {
            "message": params["message"],
            "content": params["content"],
        }
        if params.get("branch"):
            body["branch"] = params["branch"]
        return self._put(params, self._repo_path(params, "contents", params["path"]), body)

    def update_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update an existing file via the Contents API."""
        body: dict[str, Any] = {
            "message": params["message"],
            "content": params["content"],
            "sha": params["sha"],
        }
        if params.get("branch"):
            body["branch"] = params["branch"]
        return self._put(params, self._repo_path(params, "contents", params["path"]), body)

    # ------------------------------------------------------------------
    # Commit operations
    # ------------------------------------------------------------------

    def list_commits(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """List commits for a repository."""
        return self._get(
            params,
            self._repo_path(params, "commits"),
            sha=params.get("sha"),
            per_page=params.get("per_page", 30),
            page=params.get("page", 1),
        )

    def get_commit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single commit by SHA."""
        return self._get(params, self._repo_path(params, "commits", params["ref"]))
