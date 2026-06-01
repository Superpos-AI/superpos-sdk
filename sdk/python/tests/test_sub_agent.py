"""Tests for sub-agent SDK methods (TASK-267).

Covers:
- ``GET /api/v1/sub-agents`` and the by-slug / by-id variants
- Task claim / poll / get parsing of the ``sub_agent`` block
- ``create_task`` forwarding of ``sub_agent_definition_slug``
- Async counterparts of all of the above
- ``AgentContext`` and ``AsyncAgentContext`` forwarding
"""

from __future__ import annotations

import json

import pytest

from superpos_sdk import (
    AgentContext,
    AsyncAgentContext,
    AsyncSuperposClient,
    SubAgent,
    SubAgentDefinition,
    SubAgentSummary,
    SuperposClient,
)
from superpos_sdk.exceptions import NotFoundError

from .conftest import BASE_URL, HIVE_ID, TASK_ID, TOKEN, envelope

SUB_AGENT_ID = "01HXYZ00000000000000000050"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _summary(**overrides):
    base = {
        "id": SUB_AGENT_ID,
        "slug": "coder",
        "name": "Coding Agent",
        "description": "Focused coding agent",
        "model": "claude-opus-4-7",
        "version": 1,
        "document_count": 3,
    }
    base.update(overrides)
    return base


def _full(**overrides):
    base = {
        "id": SUB_AGENT_ID,
        "slug": "coder",
        "name": "Coding Agent",
        "description": "Focused coding agent",
        "model": "claude-opus-4-7",
        "version": 1,
        "documents": {
            "SOUL": "You are a focused coding agent.",
            "RULES": "Never commit directly to main.",
        },
        "config": {"temperature": 0.2},
        "allowed_tools": ["Bash", "Read", "Write"],
    }
    base.update(overrides)
    return base


def _assembled(**overrides):
    base = {
        "slug": "coder",
        "version": 1,
        "prompt": (
            "# SOUL\nYou are a focused coding agent.\n\n# RULES\nNever commit directly to main.\n"
        ),
        "document_count": 2,
    }
    base.update(overrides)
    return base


def _task_data(**overrides):
    base = {
        "id": TASK_ID,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "type": "process",
        "status": "pending",
        "priority": 2,
        "payload": {},
        "progress": 0,
        "claimed_by": None,
        "created_at": "2026-02-26T12:00:00Z",
        "sub_agent": None,
    }
    base.update(overrides)
    return base


def _claim_sub_agent_block():
    return {
        "id": SUB_AGENT_ID,
        "slug": "coder",
        "name": "Coding Agent",
        "model": "claude-opus-4-7",
        "version": 1,
        "prompt": (
            "# SOUL\nYou are a focused coding agent.\n\n# RULES\nNever commit directly to main.\n"
        ),
        "config": {"temperature": 0.2},
        "allowed_tools": ["Bash", "Read", "Write"],
    }


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_sub_agent_summary_from_dict(self):
        s = SubAgentSummary.from_dict(_summary())
        assert s.id == SUB_AGENT_ID
        assert s.slug == "coder"
        assert s.name == "Coding Agent"
        assert s.description == "Focused coding agent"
        assert s.model == "claude-opus-4-7"
        assert s.version == 1
        assert s.document_count == 3

    def test_sub_agent_summary_optional_fields(self):
        s = SubAgentSummary.from_dict({"id": SUB_AGENT_ID, "slug": "x", "name": "X"})
        assert s.description is None
        assert s.model is None
        assert s.version == 1
        assert s.document_count == 0

    def test_sub_agent_definition_from_dict(self):
        d = SubAgentDefinition.from_dict(_full())
        assert d.id == SUB_AGENT_ID
        assert d.slug == "coder"
        assert d.name == "Coding Agent"
        assert d.version == 1
        assert d.model == "claude-opus-4-7"
        assert d.documents == {
            "SOUL": "You are a focused coding agent.",
            "RULES": "Never commit directly to main.",
        }
        assert d.config == {"temperature": 0.2}
        assert d.allowed_tools == ["Bash", "Read", "Write"]

    def test_sub_agent_definition_handles_null_collections(self):
        d = SubAgentDefinition.from_dict(
            {
                "id": SUB_AGENT_ID,
                "slug": "x",
                "name": "X",
                "version": 2,
                "documents": None,
                "config": None,
                "allowed_tools": None,
            }
        )
        assert d.documents == {}
        assert d.config == {}
        assert d.allowed_tools is None

    def test_sub_agent_from_full_claim_block(self):
        sa = SubAgent.from_dict(_claim_sub_agent_block())
        assert sa.id == SUB_AGENT_ID
        assert sa.slug == "coder"
        assert sa.name == "Coding Agent"
        assert sa.model == "claude-opus-4-7"
        assert sa.version == 1
        assert sa.prompt.startswith("# SOUL")
        assert sa.config == {"temperature": 0.2}
        assert sa.allowed_tools == ["Bash", "Read", "Write"]

    def test_sub_agent_from_lightweight_ref(self):
        # Poll / show responses include only the lightweight ref.
        sa = SubAgent.from_dict({"id": SUB_AGENT_ID, "slug": "coder", "version": 2})
        assert sa.id == SUB_AGENT_ID
        assert sa.slug == "coder"
        assert sa.version == 2
        assert sa.name is None
        assert sa.model is None
        assert sa.prompt is None
        assert sa.config is None
        assert sa.allowed_tools is None


# ---------------------------------------------------------------------------
# Sync client — sub-agent definition endpoints
# ---------------------------------------------------------------------------


class TestGetSubAgentDefinitions:
    def test_returns_list_of_summaries(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents",
            json=envelope([_summary(), _summary(id="B" * 26, slug="reviewer", name="Reviewer")]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            defs = c.get_sub_agent_definitions()
        assert len(defs) == 2
        assert all(isinstance(d, SubAgentSummary) for d in defs)
        assert defs[0].slug == "coder"
        assert defs[1].slug == "reviewer"

    def test_empty_list(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents",
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            assert c.get_sub_agent_definitions() == []


class TestGetSubAgentDefinition:
    def test_by_slug_returns_full_definition(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/coder",
            json=envelope(_full()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            d = c.get_sub_agent_definition("coder")
        assert isinstance(d, SubAgentDefinition)
        assert d.slug == "coder"
        assert "SOUL" in d.documents
        assert d.allowed_tools == ["Bash", "Read", "Write"]

    def test_by_slug_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/missing",
            status_code=404,
            json=envelope(errors=[{"message": "Not found", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.get_sub_agent_definition("missing")


class TestGetSubAgentAssembled:
    def test_by_slug_returns_prompt_string(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/coder/assembled",
            json=envelope(_assembled()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            prompt = c.get_sub_agent_assembled("coder")
        assert isinstance(prompt, str)
        assert prompt.startswith("# SOUL")


class TestGetSubAgentDefinitionById:
    def test_by_id_returns_definition(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/by-id/{SUB_AGENT_ID}",
            json=envelope(_full(version=3)),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            d = c.get_sub_agent_definition_by_id(SUB_AGENT_ID)
        assert d.id == SUB_AGENT_ID
        assert d.version == 3

    def test_by_id_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/by-id/{SUB_AGENT_ID}",
            status_code=404,
            json=envelope(errors=[{"message": "Not found", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.get_sub_agent_definition_by_id(SUB_AGENT_ID)


class TestGetSubAgentAssembledById:
    def test_by_id_returns_prompt_string(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/by-id/{SUB_AGENT_ID}/assembled",
            json=envelope(_assembled(version=3)),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            prompt = c.get_sub_agent_assembled_by_id(SUB_AGENT_ID)
        assert prompt.startswith("# SOUL")


# ---------------------------------------------------------------------------
# Task claim / poll / get — sub_agent parsing
# ---------------------------------------------------------------------------


class TestClaimTaskParsesSubAgent:
    def test_claim_with_sub_agent_attaches_typed_object(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            json=envelope(
                _task_data(
                    status="in_progress",
                    claimed_by="agent-1",
                    sub_agent=_claim_sub_agent_block(),
                )
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            task = c.claim_task(HIVE_ID, TASK_ID)
        assert isinstance(task["sub_agent"], SubAgent)
        assert task["sub_agent"].id == SUB_AGENT_ID
        assert task["sub_agent"].slug == "coder"
        assert task["sub_agent"].prompt.startswith("# SOUL")
        assert task["sub_agent"].config == {"temperature": 0.2}
        assert task["sub_agent"].allowed_tools == ["Bash", "Read", "Write"]

    def test_claim_without_sub_agent_is_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            json=envelope(_task_data(status="in_progress", sub_agent=None)),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            task = c.claim_task(HIVE_ID, TASK_ID)
        assert task["sub_agent"] is None

    def test_claim_missing_sub_agent_key_is_preserved_as_absent(self, httpx_mock):
        # Older server responses may omit the field entirely. We don't add it
        # defensively — the live server always includes it per TASK-263.
        data = _task_data()
        data.pop("sub_agent", None)
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            json=envelope(data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            task = c.claim_task(HIVE_ID, TASK_ID)
        # When absent, access via .get returns None (the canonical "no sub-agent" signal).
        assert task.get("sub_agent") is None


class TestPollTasksParsesSubAgent:
    def test_poll_parses_lightweight_ref_on_each_task(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/poll",
            json=envelope(
                [
                    _task_data(sub_agent={"id": SUB_AGENT_ID, "slug": "coder", "version": 1}),
                    _task_data(id="T" * 26, sub_agent=None),
                ]
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            tasks = c.poll_tasks(HIVE_ID)
        assert isinstance(tasks[0]["sub_agent"], SubAgent)
        assert tasks[0]["sub_agent"].slug == "coder"
        assert tasks[0]["sub_agent"].prompt is None  # poll is lightweight
        assert tasks[1]["sub_agent"] is None


class TestGetTaskParsesSubAgent:
    def test_get_task_parses_sub_agent_ref(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}",
            json=envelope(
                _task_data(sub_agent={"id": SUB_AGENT_ID, "slug": "coder", "version": 2})
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            task = c.get_task(HIVE_ID, TASK_ID)
        assert isinstance(task["sub_agent"], SubAgent)
        assert task["sub_agent"].version == 2


# ---------------------------------------------------------------------------
# create_task with sub_agent_definition_slug
# ---------------------------------------------------------------------------


class TestCreateTaskWithSubAgentSlug:
    def test_without_slug_does_not_include_field(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(_task_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.create_task(HIVE_ID, task_type="process")
        body = json.loads(httpx_mock.get_request().content)
        assert "sub_agent_definition_slug" not in body

    def test_with_slug_includes_field(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(
                _task_data(sub_agent={"id": SUB_AGENT_ID, "slug": "coder", "version": 1})
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            task = c.create_task(HIVE_ID, task_type="process", sub_agent_definition_slug="coder")
        body = json.loads(httpx_mock.get_request().content)
        assert body["sub_agent_definition_slug"] == "coder"
        assert isinstance(task["sub_agent"], SubAgent)
        assert task["sub_agent"].slug == "coder"


# ---------------------------------------------------------------------------
# AgentContext forwarding
# ---------------------------------------------------------------------------


class TestAgentContextForwarding:
    def test_create_task_forwards_slug(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(_task_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            ctx = AgentContext(base_url=BASE_URL, token=TOKEN, hive_id=HIVE_ID, client=c)
            ctx.create_task(task_type="process", sub_agent_definition_slug="coder")
        body = json.loads(httpx_mock.get_request().content)
        assert body["sub_agent_definition_slug"] == "coder"

    def test_create_task_without_slug_omits_field(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(_task_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            ctx = AgentContext(base_url=BASE_URL, token=TOKEN, hive_id=HIVE_ID, client=c)
            ctx.create_task(task_type="process")
        body = json.loads(httpx_mock.get_request().content)
        assert "sub_agent_definition_slug" not in body


# ---------------------------------------------------------------------------
# Async client — parallel coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAsyncSubAgentMethods:
    async def test_list(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents",
            json=envelope([_summary()]),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            defs = await c.get_sub_agent_definitions()
        assert len(defs) == 1
        assert isinstance(defs[0], SubAgentSummary)

    async def test_get_by_slug(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/coder",
            json=envelope(_full()),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            d = await c.get_sub_agent_definition("coder")
        assert isinstance(d, SubAgentDefinition)

    async def test_assembled_by_slug(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/coder/assembled",
            json=envelope(_assembled()),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            prompt = await c.get_sub_agent_assembled("coder")
        assert prompt.startswith("# SOUL")

    async def test_get_by_id(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/by-id/{SUB_AGENT_ID}",
            json=envelope(_full(version=4)),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            d = await c.get_sub_agent_definition_by_id(SUB_AGENT_ID)
        assert d.version == 4

    async def test_assembled_by_id(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/sub-agents/by-id/{SUB_AGENT_ID}/assembled",
            json=envelope(_assembled(version=4)),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            prompt = await c.get_sub_agent_assembled_by_id(SUB_AGENT_ID)
        assert prompt.startswith("# SOUL")

    async def test_claim_parses_sub_agent(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            json=envelope(
                _task_data(
                    status="in_progress",
                    sub_agent=_claim_sub_agent_block(),
                )
            ),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            task = await c.claim_task(HIVE_ID, TASK_ID)
        assert isinstance(task["sub_agent"], SubAgent)
        assert task["sub_agent"].slug == "coder"

    async def test_claim_without_sub_agent_is_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks/{TASK_ID}/claim",
            json=envelope(_task_data(sub_agent=None)),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            task = await c.claim_task(HIVE_ID, TASK_ID)
        assert task["sub_agent"] is None

    async def test_create_task_forwards_slug(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(_task_data()),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            await c.create_task(HIVE_ID, task_type="process", sub_agent_definition_slug="coder")
        body = json.loads(httpx_mock.get_request().content)
        assert body["sub_agent_definition_slug"] == "coder"

    async def test_async_agent_context_forwards_slug(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/tasks",
            status_code=201,
            json=envelope(_task_data()),
        )
        async with AsyncSuperposClient(BASE_URL, token=TOKEN) as c:
            ctx = AsyncAgentContext(base_url=BASE_URL, token=TOKEN, hive_id=HIVE_ID, client=c)
            await ctx.create_task(task_type="process", sub_agent_definition_slug="coder")
        body = json.loads(httpx_mock.get_request().content)
        assert body["sub_agent_definition_slug"] == "coder"
