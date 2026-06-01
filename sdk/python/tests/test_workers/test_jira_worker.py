"""Tests for JiraWorker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.jira import JiraWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"

JIRA_PARAMS = {
    "jira_url": "https://acme.atlassian.net",
    "jira_email": "bot@acme.com",
    "jira_api_token": "ATATt3xFfGF0test",
}


def _worker() -> JiraWorker:
    return JiraWorker(BASE_URL, HIVE_ID, name="jira-worker", secret="s3cr3t")


def _mock_client(json_data: dict, *, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = resp
    mock_client.post.return_value = resp
    mock_client.put.return_value = resp
    return mock_client


class TestJiraWorkerCredentials:
    def test_missing_url_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="Jira URL"):
            worker.get_issue({"issue_key": "PROJ-1"})

    def test_missing_credentials_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="credentials"):
            worker.get_issue({"jira_url": "https://x.atlassian.net", "issue_key": "PROJ-1"})

    def test_env_vars_used_as_fallback(self, monkeypatch):
        monkeypatch.setenv("JIRA_URL", "https://acme.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "bot@acme.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "token123")

        worker = _worker()
        issue = {"id": "10001", "key": "PROJ-1", "fields": {}}

        with patch("httpx.Client", return_value=_mock_client(issue)):
            result = worker.get_issue({"issue_key": "PROJ-1"})

        assert result["key"] == "PROJ-1"


class TestJiraWorkerGetIssue:
    def test_get_issue_returns_issue(self):
        worker = _worker()
        issue = {"id": "10001", "key": "PROJ-42", "fields": {"summary": "Bug"}}

        with patch("httpx.Client", return_value=_mock_client(issue)):
            result = worker.get_issue({**JIRA_PARAMS, "issue_key": "PROJ-42"})

        assert result["key"] == "PROJ-42"


class TestJiraWorkerCreateIssue:
    def test_create_issue_minimal(self):
        worker = _worker()
        created = {"id": "10002", "key": "PROJ-43", "self": "https://..."}

        with patch("httpx.Client", return_value=_mock_client(created, status_code=201)):
            result = worker.create_issue(
                {**JIRA_PARAMS, "project_key": "PROJ", "summary": "New task"}
            )

        assert result["key"] == "PROJ-43"

    def test_create_issue_with_all_fields(self):
        worker = _worker()
        created = {"id": "10003", "key": "PROJ-44", "self": "https://..."}

        with patch("httpx.Client", return_value=_mock_client(created, status_code=201)) as mc:
            worker.create_issue(
                {
                    **JIRA_PARAMS,
                    "project_key": "PROJ",
                    "summary": "Full task",
                    "issue_type": "Bug",
                    "description": "Detailed desc",
                    "priority": "High",
                    "labels": ["backend"],
                    "assignee": "acc123",
                }
            )
            call_kwargs = mc.return_value.__enter__.return_value.post.call_args[1]

        fields = call_kwargs["json"]["fields"]
        assert fields["issuetype"]["name"] == "Bug"
        assert fields["priority"]["name"] == "High"
        assert fields["labels"] == ["backend"]
        assert fields["assignee"]["accountId"] == "acc123"


class TestJiraWorkerUpdateIssue:
    def test_update_issue_returns_success(self):
        worker = _worker()
        no_content = MagicMock()
        no_content.status_code = 204
        no_content.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.put.return_value = no_content

        with patch("httpx.Client", return_value=mock_client):
            result = worker.update_issue(
                {**JIRA_PARAMS, "issue_key": "PROJ-42", "summary": "Updated"}
            )

        assert result["updated"] is True
        assert result["issue_key"] == "PROJ-42"


class TestJiraWorkerListIssues:
    def test_list_issues_returns_shape(self):
        worker = _worker()
        data = {
            "issues": [{"key": "PROJ-1"}, {"key": "PROJ-2"}],
            "total": 2,
            "startAt": 0,
            "maxResults": 50,
        }

        with patch("httpx.Client", return_value=_mock_client(data)):
            result = worker.list_issues({**JIRA_PARAMS, "jql": "project = PROJ", "max_results": 50})

        assert len(result["issues"]) == 2
        assert result["total"] == 2
        assert result["start_at"] == 0
        assert result["max_results"] == 50


class TestJiraWorkerAddComment:
    def test_add_comment_returns_comment(self):
        worker = _worker()
        comment = {"id": "10100", "body": {}}

        with patch("httpx.Client", return_value=_mock_client(comment, status_code=201)):
            result = worker.add_comment(
                {**JIRA_PARAMS, "issue_key": "PROJ-42", "body": "Looks good!"}
            )

        assert result["id"] == "10100"
