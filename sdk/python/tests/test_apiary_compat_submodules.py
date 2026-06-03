"""Verify that ``apiary_sdk`` backward-compat shim supports dotted sub-module imports.

Every sub-module path that exists under ``superpos_sdk`` must also be
importable via ``apiary_sdk`` so that legacy code continues to work after
the package rename.
"""

from __future__ import annotations

import warnings

import pytest


@pytest.fixture(autouse=True)
def _suppress_deprecation():
    """Suppress the expected DeprecationWarning from apiary_sdk."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        yield


# ---- top-level module imports ------------------------------------------------


class TestTopLevelModuleImports:
    def test_import_constants(self):
        import apiary_sdk.constants  # noqa: F401

    def test_import_exceptions(self):
        import apiary_sdk.exceptions  # noqa: F401

    def test_import_models(self):
        import apiary_sdk.models  # noqa: F401

    def test_import_client(self):
        import apiary_sdk.client  # noqa: F401

    def test_import_async_client(self):
        import apiary_sdk.async_client  # noqa: F401

    def test_import_agent(self):
        import apiary_sdk.agent  # noqa: F401

    def test_import_async_agent(self):
        import apiary_sdk.async_agent  # noqa: F401

    def test_import_service_worker(self):
        import apiary_sdk.service_worker  # noqa: F401

    def test_import_streaming(self):
        import apiary_sdk.streaming  # noqa: F401

    def test_import_large_result(self):
        import apiary_sdk.large_result  # noqa: F401


# ---- sub-package imports -----------------------------------------------------


class TestSubPackageImports:
    def test_import_workers(self):
        import apiary_sdk.workers  # noqa: F401

    def test_import_resources(self):
        import apiary_sdk.resources  # noqa: F401

    def test_import_resources_async_resources(self):
        import apiary_sdk.resources.async_resources  # noqa: F401

    def test_import_skills(self):
        import apiary_sdk.skills  # noqa: F401


# ---- deep module imports -----------------------------------------------------


class TestDeepModuleImports:
    # workers
    def test_import_workers_github(self):
        import apiary_sdk.workers.github  # noqa: F401

    def test_import_workers_gmail(self):
        import apiary_sdk.workers.gmail  # noqa: F401

    def test_import_workers_http(self):
        import apiary_sdk.workers.http  # noqa: F401

    def test_import_workers_jira(self):
        import apiary_sdk.workers.jira  # noqa: F401

    def test_import_workers_sheets(self):
        import apiary_sdk.workers.sheets  # noqa: F401

    def test_import_workers_slack(self):
        import apiary_sdk.workers.slack  # noqa: F401

    def test_import_workers_sql(self):
        import apiary_sdk.workers.sql  # noqa: F401

    # resources
    def test_import_resources_channel(self):
        import apiary_sdk.resources.channel  # noqa: F401

    def test_import_resources_knowledge(self):
        import apiary_sdk.resources.knowledge  # noqa: F401

    def test_import_resources_task(self):
        import apiary_sdk.resources.task  # noqa: F401

    # resources.async_resources
    def test_import_resources_async_channel(self):
        import apiary_sdk.resources.async_resources.channel  # noqa: F401

    def test_import_resources_async_knowledge(self):
        import apiary_sdk.resources.async_resources.knowledge  # noqa: F401

    def test_import_resources_async_task(self):
        import apiary_sdk.resources.async_resources.task  # noqa: F401

    # skills
    def test_import_skills_sync(self):
        import apiary_sdk.skills.sync_skills  # noqa: F401

    def test_import_skills_async(self):
        import apiary_sdk.skills.async_skills  # noqa: F401


# ---- from ... import ... style -----------------------------------------------


class TestFromImports:
    def test_from_workers_import_github_worker(self):
        from apiary_sdk.workers import GitHubWorker  # noqa: F401

    def test_from_workers_import_slack_worker(self):
        from apiary_sdk.workers import SlackWorker  # noqa: F401

    def test_from_workers_import_http_worker(self):
        from apiary_sdk.workers import HttpWorker  # noqa: F401

    def test_from_resources_import_channel(self):
        from apiary_sdk.resources import Channel  # noqa: F401

    def test_from_resources_import_knowledge_entry(self):
        from apiary_sdk.resources import KnowledgeEntry  # noqa: F401

    def test_from_resources_import_task(self):
        from apiary_sdk.resources import Task  # noqa: F401

    def test_from_async_resources_import_async_channel(self):
        from apiary_sdk.resources.async_resources import AsyncChannel  # noqa: F401

    def test_from_async_resources_import_async_task(self):
        from apiary_sdk.resources.async_resources import AsyncTask  # noqa: F401

    def test_from_constants_import_task_statuses(self):
        from apiary_sdk.constants import TASK_STATUSES  # noqa: F401

    def test_from_exceptions_import_superpos_error(self):
        from apiary_sdk.exceptions import SuperposError  # noqa: F401

    # Legacy Apiary* aliases from submodule shims
    def test_from_client_import_apiary_client(self):
        from apiary_sdk.client import ApiaryClient  # noqa: F401

    def test_from_async_client_import_async_apiary_client(self):
        from apiary_sdk.async_client import AsyncApiaryClient  # noqa: F401

    def test_from_exceptions_import_apiary_error(self):
        from apiary_sdk.exceptions import ApiaryError  # noqa: F401

    def test_from_exceptions_import_apiary_permission_error(self):
        from apiary_sdk.exceptions import ApiaryPermissionError  # noqa: F401


# ---- identity checks (shim re-exports the *same* objects) --------------------


class TestIdentity:
    def test_workers_github_worker_is_same_object(self):
        import apiary_sdk.workers
        import superpos_sdk.workers

        assert apiary_sdk.workers.GitHubWorker is superpos_sdk.workers.GitHubWorker

    def test_workers_slack_worker_is_same_object(self):
        import apiary_sdk.workers
        import superpos_sdk.workers

        assert apiary_sdk.workers.SlackWorker is superpos_sdk.workers.SlackWorker

    def test_resources_task_is_same_object(self):
        import apiary_sdk.resources
        import superpos_sdk.resources

        assert apiary_sdk.resources.Task is superpos_sdk.resources.Task

    def test_resources_channel_is_same_object(self):
        import apiary_sdk.resources
        import superpos_sdk.resources

        assert apiary_sdk.resources.Channel is superpos_sdk.resources.Channel

    def test_resources_knowledge_entry_is_same_object(self):
        import apiary_sdk.resources
        import superpos_sdk.resources

        assert apiary_sdk.resources.KnowledgeEntry is superpos_sdk.resources.KnowledgeEntry

    def test_async_resources_async_channel_is_same_object(self):
        import apiary_sdk.resources.async_resources
        import superpos_sdk.resources.async_resources

        assert (
            apiary_sdk.resources.async_resources.AsyncChannel
            is superpos_sdk.resources.async_resources.AsyncChannel
        )

    def test_constants_task_statuses_is_same_object(self):
        import apiary_sdk.constants
        import superpos_sdk.constants

        assert apiary_sdk.constants.TASK_STATUSES is superpos_sdk.constants.TASK_STATUSES

    def test_client_superpos_client_is_same_object(self):
        import apiary_sdk.client
        import superpos_sdk.client

        assert apiary_sdk.client.SuperposClient is superpos_sdk.client.SuperposClient

    def test_client_apiary_client_alias_is_superpos_client(self):
        import apiary_sdk.client
        import superpos_sdk.client

        assert apiary_sdk.client.ApiaryClient is superpos_sdk.client.SuperposClient

    def test_async_client_async_apiary_client_alias_is_async_superpos_client(self):
        import apiary_sdk.async_client
        import superpos_sdk.async_client

        expected = superpos_sdk.async_client.AsyncSuperposClient
        assert apiary_sdk.async_client.AsyncApiaryClient is expected

    def test_exceptions_apiary_error_alias_is_superpos_error(self):
        import apiary_sdk.exceptions
        import superpos_sdk.exceptions

        assert apiary_sdk.exceptions.ApiaryError is superpos_sdk.exceptions.SuperposError

    def test_exceptions_apiary_permission_error_alias_is_permission_error(self):
        import apiary_sdk.exceptions
        import superpos_sdk.exceptions

        expected = superpos_sdk.exceptions.PermissionError
        assert apiary_sdk.exceptions.ApiaryPermissionError is expected
