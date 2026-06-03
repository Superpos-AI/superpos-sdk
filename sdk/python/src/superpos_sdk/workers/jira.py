"""Jira service worker — interact with the Jira Cloud REST API v3.

Install the optional dependency::

    pip install superpos-sdk[jira]

Credentials (env-first, payload fallback):

- ``JIRA_URL``        — e.g. ``https://yourorg.atlassian.net``
- ``JIRA_EMAIL``      — Atlassian account email
- ``JIRA_API_TOKEN``  — API token (not password)

All three can also be provided as keys in the task *params* dict.

Supported operations
--------------------

``get_issue``
    ``{"issue_key": "PROJ-123"}``

``create_issue``
    ``{"project_key": "PROJ", "summary": "...", "issue_type": "Task",
       "description": "...", "priority": "Medium", "labels": [...],
       "assignee": "account-id"}``

``update_issue``
    ``{"issue_key": "PROJ-123", "summary": "...", "description": "...",
       "priority": "High", "labels": [...], "assignee": "account-id"}``

``list_issues``
    ``{"jql": "project = PROJ AND status = Open", "max_results": 50,
       "start_at": 0, "fields": ["summary", "status", "assignee"]}``

``add_comment``
    ``{"issue_key": "PROJ-123", "body": "..."}``
"""

from __future__ import annotations

import os
from typing import Any

from superpos_sdk.service_worker import ServiceWorker


class JiraWorker(ServiceWorker):
    """Service worker that proxies Jira Cloud REST API v3 calls.

    Credentials are read from ``JIRA_URL``, ``JIRA_EMAIL``, and
    ``JIRA_API_TOKEN`` environment variables.  Per-request keys in *params*
    (``jira_url``, ``jira_email``, ``jira_api_token``) override the env vars.
    """

    CAPABILITY = "data:jira"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _creds(self, params: dict[str, Any]) -> tuple[str, str, str]:
        """Return (base_url, email, api_token) resolving env → params."""
        url = params.get("jira_url") or os.environ.get("JIRA_URL", "")
        email = params.get("jira_email") or os.environ.get("JIRA_EMAIL", "")
        token = params.get("jira_api_token") or os.environ.get("JIRA_API_TOKEN", "")

        if not url:
            raise ValueError("Jira URL not found. Set JIRA_URL env var or pass jira_url in params.")
        if not email or not token:
            raise ValueError(
                "Jira credentials not found. "
                "Set JIRA_EMAIL and JIRA_API_TOKEN env vars or pass them in params."
            )
        return url.rstrip("/"), email, token

    def _client(self, params: dict[str, Any]):  # type: ignore[return]
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "httpx is required for JiraWorker. Install it with: pip install superpos-sdk[jira]"
            ) from exc

        base_url, email, token = self._creds(params)
        return httpx.Client(
            base_url=f"{base_url}/rest/api/3",
            auth=(email, token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def get_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a Jira issue by key.

        Args:
            params: Must include ``issue_key`` (e.g. ``PROJ-123``).

        Returns:
            Jira issue resource dict.
        """
        with self._client(params) as c:
            r = c.get(f"/issue/{params['issue_key']}")
            r.raise_for_status()
            return r.json()

    def create_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new Jira issue.

        Args:
            params: Must include ``project_key`` and ``summary``.  Optional:
                ``issue_type`` (default Task), ``description``, ``priority``,
                ``labels``, ``assignee``.

        Returns:
            Dict with ``id``, ``key``, and ``self`` (URL).
        """
        fields: dict[str, Any] = {
            "project": {"key": params["project_key"]},
            "summary": params["summary"],
            "issuetype": {"name": params.get("issue_type", "Task")},
        }
        if params.get("description"):
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": params["description"]}],
                    }
                ],
            }
        if params.get("priority"):
            fields["priority"] = {"name": params["priority"]}
        if params.get("labels"):
            fields["labels"] = params["labels"]
        if params.get("assignee"):
            fields["assignee"] = {"accountId": params["assignee"]}

        with self._client(params) as c:
            r = c.post("/issue", json={"fields": fields})
            r.raise_for_status()
            return r.json()

    def update_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update fields on an existing Jira issue.

        Args:
            params: Must include ``issue_key``.  At least one of: ``summary``,
                ``description``, ``priority``, ``labels``, ``assignee``.

        Returns:
            ``{"updated": true, "issue_key": "PROJ-123"}``
        """
        fields: dict[str, Any] = {}
        if params.get("summary"):
            fields["summary"] = params["summary"]
        if params.get("description"):
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": params["description"]}],
                    }
                ],
            }
        if params.get("priority"):
            fields["priority"] = {"name": params["priority"]}
        if params.get("labels"):
            fields["labels"] = params["labels"]
        if params.get("assignee"):
            fields["assignee"] = {"accountId": params["assignee"]}

        with self._client(params) as c:
            r = c.put(f"/issue/{params['issue_key']}", json={"fields": fields})
            r.raise_for_status()  # 204 No Content on success

        return {"updated": True, "issue_key": params["issue_key"]}

    def list_issues(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search for issues using JQL.

        Args:
            params: Optional ``jql`` (default: empty), ``max_results``
                (default 50), ``start_at`` (default 0), ``fields`` (list of
                field names, default all).

        Returns:
            Dict with ``issues``, ``total``, ``start_at``, ``max_results``.
        """
        body: dict[str, Any] = {
            "jql": params.get("jql", ""),
            "maxResults": params.get("max_results", 50),
            "startAt": params.get("start_at", 0),
        }
        if params.get("fields"):
            body["fields"] = params["fields"]

        with self._client(params) as c:
            r = c.post("/issue/search", json=body)
            r.raise_for_status()
            data = r.json()

        return {
            "issues": data.get("issues", []),
            "total": data.get("total", 0),
            "start_at": data.get("startAt", 0),
            "max_results": data.get("maxResults", 0),
        }

    def add_comment(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add a comment to a Jira issue.

        Args:
            params: Must include ``issue_key`` and ``body`` (plain text).

        Returns:
            Jira comment resource dict.
        """
        comment_body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": params["body"]}],
                    }
                ],
            }
        }
        with self._client(params) as c:
            r = c.post(f"/issue/{params['issue_key']}/comment", json=comment_body)
            r.raise_for_status()
            return r.json()
