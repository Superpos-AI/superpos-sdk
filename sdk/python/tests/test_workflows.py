"""Tests for workflow CRUD, run management, and versioning endpoints."""

from __future__ import annotations

import json

from superpos_sdk import SuperposClient

from .conftest import BASE_URL, HIVE_ID, TOKEN, envelope

WORKFLOW_ID = "01HXYZ00000000000000000020"
RUN_ID = "01HXYZ00000000000000000021"


def _workflow_data(**overrides):
    base = {
        "id": WORKFLOW_ID,
        "organization_id": "01HXYZ00000000000000000001",
        "hive_id": HIVE_ID,
        "name": "deploy-pipeline",
        "slug": "deploy-pipeline",
        "description": "Deployment workflow",
        "version": 1,
        "is_active": True,
        "trigger_config": {},
        "steps": {},
        "settings": {},
        "created_by": "01HXYZ00000000000000000099",
        "created_at": "2026-03-01T12:00:00+00:00",
        "updated_at": "2026-03-01T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def _run_data(**overrides):
    base = {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "status": "running",
        "payload": {"env": "staging"},
        "started_at": "2026-03-01T12:00:00Z",
    }
    base.update(overrides)
    return base


class TestListWorkflows:
    def test_list_returns_workflows(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=15"),
            json=envelope([_workflow_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID)
        assert len(result) == 1
        assert result[0]["name"] == "deploy-pipeline"

    def test_list_with_pagination(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=2&per_page=10"),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID, page=2, per_page=10)
        assert result == []

    def test_list_clamps_per_page(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=100"),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_workflows(HIVE_ID, per_page=500)
        req = httpx_mock.get_request()
        assert "per_page=100" in str(req.url)

    def test_list_with_is_active_filter(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=15&is_active=true"),
            json=envelope([_workflow_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID, is_active=True)
        assert len(result) == 1
        req = httpx_mock.get_request()
        assert "is_active=true" in str(req.url)

    def test_list_with_is_active_false(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=15&is_active=false"),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID, is_active=False)
        assert result == []
        req = httpx_mock.get_request()
        assert "is_active=false" in str(req.url)

    def test_list_with_search_filter(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=15&search=deploy"),
            json=envelope([_workflow_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID, search="deploy")
        assert len(result) == 1
        req = httpx_mock.get_request()
        assert "search=deploy" in str(req.url)

    def test_list_with_all_filters(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows"
                "?page=2&per_page=10&is_active=true&search=pipe"
            ),
            json=envelope([_workflow_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflows(HIVE_ID, page=2, per_page=10, is_active=True, search="pipe")
        assert len(result) == 1
        req = httpx_mock.get_request()
        assert "page=2" in str(req.url)
        assert "per_page=10" in str(req.url)
        assert "is_active=true" in str(req.url)
        assert "search=pipe" in str(req.url)

    def test_list_omits_none_filters(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows?page=1&per_page=15"),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_workflows(HIVE_ID, is_active=None, search=None)
        req = httpx_mock.get_request()
        assert "is_active" not in str(req.url)
        assert "search" not in str(req.url)


class TestGetWorkflow:
    def test_get_workflow(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}"),
            json=envelope(_workflow_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.get_workflow(HIVE_ID, WORKFLOW_ID)
        assert result["id"] == WORKFLOW_ID
        assert result["name"] == "deploy-pipeline"


class TestCreateWorkflow:
    def test_create_workflow(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows"),
            status_code=201,
            json=envelope(_workflow_data()),
        )
        steps = {"build": {"type": "task"}}
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.create_workflow(
                HIVE_ID,
                slug="deploy-pipeline",
                name="deploy-pipeline",
                steps=steps,
            )
        assert result["name"] == "deploy-pipeline"
        body = json.loads(httpx_mock.get_request().content)
        assert body["name"] == "deploy-pipeline"
        assert body["slug"] == "deploy-pipeline"
        assert body["steps"] == steps
        assert "trigger_type" not in body

    def test_create_with_all_options(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows"),
            status_code=201,
            json=envelope(
                _workflow_data(
                    description="Full options",
                )
            ),
        )
        steps = {"build": {"type": "task"}}
        config = {"type": "webhook", "url": "https://example.com/hook"}
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.create_workflow(
                HIVE_ID,
                slug="deploy-pipeline",
                name="deploy-pipeline",
                steps=steps,
                trigger_config=config,
                description="Full options",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert "trigger_type" not in body
        assert body["trigger_config"] == config
        assert body["description"] == "Full options"

    def test_create_with_is_active_and_settings(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows"),
            status_code=201,
            json=envelope(_workflow_data(is_active=False, settings={"timeout": 300})),
        )
        steps = {"build": {"type": "task"}}
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.create_workflow(
                HIVE_ID,
                slug="deploy-pipeline",
                name="deploy-pipeline",
                steps=steps,
                is_active=False,
                settings={"timeout": 300},
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["is_active"] is False
        assert body["settings"] == {"timeout": 300}
        assert result["is_active"] is False
        assert result["settings"] == {"timeout": 300}


class TestUpdateWorkflow:
    def test_update_workflow(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}"),
            json=envelope(_workflow_data(name="renamed-pipeline")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.update_workflow(
                HIVE_ID,
                WORKFLOW_ID,
                name="renamed-pipeline",
            )
        assert result["name"] == "renamed-pipeline"
        body = json.loads(httpx_mock.get_request().content)
        assert body["name"] == "renamed-pipeline"
        req = httpx_mock.get_request()
        assert req.method == "PUT"


class TestUpdateWorkflowFields:
    def test_update_with_is_active_and_settings(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}"),
            json=envelope(
                _workflow_data(
                    is_active=False,
                    settings={"retry_count": 5},
                )
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.update_workflow(
                HIVE_ID,
                WORKFLOW_ID,
                is_active=False,
                settings={"retry_count": 5},
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["is_active"] is False
        assert body["settings"] == {"retry_count": 5}
        assert result["is_active"] is False
        assert result["settings"] == {"retry_count": 5}
        req = httpx_mock.get_request()
        assert req.method == "PUT"

    def test_update_omits_none_fields(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}"),
            json=envelope(_workflow_data(name="renamed-pipeline")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.update_workflow(
                HIVE_ID,
                WORKFLOW_ID,
                name="renamed-pipeline",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body == {"name": "renamed-pipeline"}


class TestDeleteWorkflow:
    def test_delete_returns_none(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}"),
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.delete_workflow(HIVE_ID, WORKFLOW_ID)
        assert result is None


class TestRunWorkflow:
    def test_run_workflow(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs"),
            status_code=201,
            json=envelope(_run_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.run_workflow(HIVE_ID, WORKFLOW_ID)
        assert result["status"] == "running"
        req = httpx_mock.get_request()
        assert req.method == "POST"

    def test_run_workflow_with_payload(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs"),
            status_code=201,
            json=envelope(_run_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.run_workflow(
                HIVE_ID,
                WORKFLOW_ID,
                payload={"env": "staging"},
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["payload"] == {"env": "staging"}


class TestListWorkflowRuns:
    def test_list_runs(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs?page=1&per_page=15"
            ),
            json=envelope([_run_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflow_runs(HIVE_ID, WORKFLOW_ID)
        assert len(result) == 1
        assert result[0]["status"] == "running"

    def test_list_runs_with_status_filter(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs"
                "?page=1&per_page=15&status=completed"
            ),
            json=envelope([_run_data(status="completed")]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflow_runs(HIVE_ID, WORKFLOW_ID, status="completed")
        assert len(result) == 1
        assert result[0]["status"] == "completed"
        req = httpx_mock.get_request()
        assert "status=completed" in str(req.url)

    def test_list_runs_omits_none_status(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs?page=1&per_page=15"
            ),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_workflow_runs(HIVE_ID, WORKFLOW_ID, status=None)
        req = httpx_mock.get_request()
        assert "status" not in str(req.url)

    def test_list_runs_with_status_and_pagination(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs"
                "?page=2&per_page=10&status=failed"
            ),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflow_runs(
                HIVE_ID, WORKFLOW_ID, page=2, per_page=10, status="failed"
            )
        assert result == []
        req = httpx_mock.get_request()
        assert "page=2" in str(req.url)
        assert "per_page=10" in str(req.url)
        assert "status=failed" in str(req.url)


class TestGetWorkflowRun:
    def test_get_run(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs/{RUN_ID}"),
            json=envelope(_run_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.get_workflow_run(HIVE_ID, WORKFLOW_ID, RUN_ID)
        assert result["id"] == RUN_ID


class TestCancelWorkflowRun:
    def test_cancel_run(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs/{RUN_ID}/cancel"),
            json=envelope(_run_data(status="cancelled")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.cancel_workflow_run(HIVE_ID, WORKFLOW_ID, RUN_ID)
        assert result["status"] == "cancelled"
        req = httpx_mock.get_request()
        assert req.method == "POST"


class TestRetryWorkflowRun:
    def test_retry_run(self, httpx_mock):
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/runs/{RUN_ID}/retry"),
            json=envelope(_run_data(status="running")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.retry_workflow_run(HIVE_ID, WORKFLOW_ID, RUN_ID)
        assert result["status"] == "running"
        req = httpx_mock.get_request()
        assert req.method == "POST"


class TestListWorkflowVersions:
    def test_list_versions(self, httpx_mock):
        versions = [
            {"version": 1, "created_at": "2026-03-01T12:00:00Z"},
            {"version": 2, "created_at": "2026-03-02T12:00:00Z"},
        ]
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions?page=1&per_page=15"
            ),
            json=envelope(versions),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflow_versions(HIVE_ID, WORKFLOW_ID)
        assert len(result) == 2
        assert result[0]["version"] == 1

    def test_list_versions_with_pagination(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions?page=2&per_page=10"
            ),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_workflow_versions(HIVE_ID, WORKFLOW_ID, page=2, per_page=10)
        assert result == []

    def test_list_versions_clamps_per_page(self, httpx_mock):
        httpx_mock.add_response(
            url=(
                f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions?page=1&per_page=100"
            ),
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_workflow_versions(HIVE_ID, WORKFLOW_ID, per_page=500)
        req = httpx_mock.get_request()
        assert "per_page=100" in str(req.url)


class TestGetWorkflowVersion:
    def test_get_version(self, httpx_mock):
        version_data = {
            "version": 2,
            "steps": {"build": {"type": "task"}},
        }
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions/2"),
            json=envelope(version_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.get_workflow_version(HIVE_ID, WORKFLOW_ID, 2)
        assert result["version"] == 2


class TestDiffWorkflowVersions:
    def test_diff_versions(self, httpx_mock):
        diff_data = {
            "from_version": 1,
            "to_version": 3,
            "steps": {
                "added": ["deploy"],
                "removed": [],
                "changed": ["build"],
            },
            "trigger_config_changed": False,
            "settings_changed": True,
            "from": {
                "id": "01HXYZ00000000000000000030",
                "workflow_id": WORKFLOW_ID,
                "version": 1,
                "steps": {},
                "trigger_config": {},
                "settings": {},
                "created_by": "01HXYZ00000000000000000099",
                "created_at": "2026-03-01T12:00:00+00:00",
            },
            "to": {
                "id": "01HXYZ00000000000000000031",
                "workflow_id": WORKFLOW_ID,
                "version": 3,
                "steps": {},
                "trigger_config": {},
                "settings": {},
                "created_by": "01HXYZ00000000000000000099",
                "created_at": "2026-03-03T12:00:00+00:00",
            },
        }
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions/1/diff/3"),
            json=envelope(diff_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.diff_workflow_versions(HIVE_ID, WORKFLOW_ID, 1, 3)
        assert result["from_version"] == 1
        assert result["to_version"] == 3
        assert result["steps"]["added"] == ["deploy"]
        assert result["steps"]["changed"] == ["build"]
        assert result["trigger_config_changed"] is False
        assert result["settings_changed"] is True
        assert result["from"]["version"] == 1
        assert result["to"]["version"] == 3


class TestRollbackWorkflowVersion:
    def test_rollback_version(self, httpx_mock):
        rollback_data = {
            "workflow": _workflow_data(version=3),
            "restored_from_version": 1,
            "new_version": 3,
        }
        httpx_mock.add_response(
            url=(f"{BASE_URL}/api/v1/hives/{HIVE_ID}/workflows/{WORKFLOW_ID}/versions/1/rollback"),
            json=envelope(rollback_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.rollback_workflow_version(HIVE_ID, WORKFLOW_ID, 1)
        assert result["new_version"] == 3
        assert result["restored_from_version"] == 1
        assert result["workflow"]["version"] == 3
        req = httpx_mock.get_request()
        assert req.method == "POST"
