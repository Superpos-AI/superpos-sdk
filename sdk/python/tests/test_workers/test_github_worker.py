"""Tests for GitHubWorker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.github import GitHubWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"

OWNER = "acme"
REPO = "backend"
BASE_PARAMS = {"owner": OWNER, "repo": REPO, "token": "ghp_test"}


def _worker() -> GitHubWorker:
    return GitHubWorker(BASE_URL, HIVE_ID, name="gh-worker", secret="s3cr3t")


def _mock_client(json_data, *, status_code: int = 200) -> MagicMock:
    """Return a patched httpx.Client context manager with preset response."""
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


class TestGitHubWorkerIssues:
    def test_get_issue(self):
        worker = _worker()
        issue = {"id": 1, "number": 42, "title": "Bug report"}

        with patch("httpx.Client", return_value=_mock_client(issue)):
            result = worker.get_issue({**BASE_PARAMS, "number": 42})

        assert result["number"] == 42
        assert result["title"] == "Bug report"

    def test_create_issue(self):
        worker = _worker()
        created = {"id": 10, "number": 1, "title": "New issue"}

        with patch("httpx.Client", return_value=_mock_client(created)):
            result = worker.create_issue({**BASE_PARAMS, "title": "New issue", "body": "Details"})

        assert result["title"] == "New issue"

    def test_list_issues(self):
        worker = _worker()
        issues = [{"id": 1, "number": 1}, {"id": 2, "number": 2}]

        with patch("httpx.Client", return_value=_mock_client(issues)):
            result = worker.list_issues(BASE_PARAMS)

        assert len(result) == 2


class TestGitHubWorkerPRs:
    def test_get_pr(self):
        worker = _worker()
        pr = {"id": 5, "number": 10, "title": "Fix: auth bug"}

        with patch("httpx.Client", return_value=_mock_client(pr)):
            result = worker.get_pr({**BASE_PARAMS, "number": 10})

        assert result["number"] == 10

    def test_list_prs(self):
        worker = _worker()
        prs = [{"id": 1}, {"id": 2}]

        with patch("httpx.Client", return_value=_mock_client(prs)):
            result = worker.list_prs(BASE_PARAMS)

        assert len(result) == 2

    def test_create_pr(self):
        worker = _worker()
        pr = {"id": 99, "number": 50, "title": "Add feature"}

        with patch("httpx.Client", return_value=_mock_client(pr)):
            result = worker.create_pr(
                {
                    **BASE_PARAMS,
                    "title": "Add feature",
                    "head": "feat/branch",
                    "base": "main",
                    "body": "Description",
                    "draft": False,
                }
            )

        assert result["number"] == 50


class TestGitHubWorkerFiles:
    def test_get_file(self):
        worker = _worker()
        file_data = {"name": "README.md", "content": "aGVsbG8=", "sha": "abc123"}

        with patch("httpx.Client", return_value=_mock_client(file_data)):
            result = worker.get_file({**BASE_PARAMS, "path": "README.md"})

        assert result["name"] == "README.md"

    def test_create_file(self):
        worker = _worker()
        response = {"content": {"name": "file.txt", "sha": "def456"}}

        with patch("httpx.Client", return_value=_mock_client(response)):
            result = worker.create_file(
                {
                    **BASE_PARAMS,
                    "path": "file.txt",
                    "message": "Add file",
                    "content": "aGVsbG8=",
                }
            )

        assert "content" in result

    def test_update_file(self):
        worker = _worker()
        response = {"content": {"name": "file.txt", "sha": "ghi789"}}

        with patch("httpx.Client", return_value=_mock_client(response)):
            result = worker.update_file(
                {
                    **BASE_PARAMS,
                    "path": "file.txt",
                    "message": "Update file",
                    "content": "d29ybGQ=",
                    "sha": "def456",
                }
            )

        assert "content" in result


class TestGitHubWorkerCommits:
    def test_list_commits(self):
        worker = _worker()
        commits = [{"sha": "abc"}, {"sha": "def"}]

        with patch("httpx.Client", return_value=_mock_client(commits)):
            result = worker.list_commits(BASE_PARAMS)

        assert len(result) == 2

    def test_get_commit(self):
        worker = _worker()
        commit = {"sha": "abc123", "commit": {"message": "Initial"}}

        with patch("httpx.Client", return_value=_mock_client(commit)):
            result = worker.get_commit({**BASE_PARAMS, "ref": "abc123"})

        assert result["sha"] == "abc123"


class TestGitHubWorkerRepoPaths:
    def test_repo_path_no_parts(self):
        assert GitHubWorker._repo_path(BASE_PARAMS) == f"/repos/{OWNER}/{REPO}"

    def test_repo_path_with_parts(self):
        assert (
            GitHubWorker._repo_path(BASE_PARAMS, "issues", 42) == f"/repos/{OWNER}/{REPO}/issues/42"
        )

    def test_missing_owner_raises(self):
        worker = _worker()
        with pytest.raises(KeyError):
            worker.get_issue({"repo": REPO, "number": 1})
