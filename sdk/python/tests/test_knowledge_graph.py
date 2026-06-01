"""Tests for knowledge graph, link, index, and health SDK methods."""

from __future__ import annotations

import json

import pytest

from superpos_sdk import SuperposClient
from superpos_sdk.exceptions import NotFoundError

from .conftest import BASE_URL, ENTRY_ID, HIVE_ID, TOKEN, envelope

LINK_ID = "01HXYZ00000000000000000099"
TARGET_ENTRY_ID = "01HXYZ00000000000000000055"
AGENT_ID = "01HXYZ00000000000000000002"


def _link_data(**overrides):
    base = {
        "id": LINK_ID,
        "source_id": ENTRY_ID,
        "target_id": TARGET_ENTRY_ID,
        "target_type": "knowledge",
        "target_ref": TARGET_ENTRY_ID,
        "link_type": "relates_to",
        "metadata": {},
        "status": "confirmed",
        "created_by": AGENT_ID,
        "created_at": "2026-03-15T10:00:00Z",
    }
    base.update(overrides)
    return base


def _entry_data(**overrides):
    base = {
        "id": ENTRY_ID,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "key": "config.timeout",
        "value": {"seconds": 30},
        "scope": "hive",
        "visibility": "public",
        "created_by": AGENT_ID,
        "version": 1,
        "ttl": None,
        "created_at": "2026-02-26T12:00:00Z",
        "updated_at": "2026-02-26T12:00:00Z",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ #
# Knowledge links
# ------------------------------------------------------------------ #


class TestCreateKnowledgeLink:
    def test_create_link_minimal(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/links",
            status_code=201,
            json=envelope(_link_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            link = c.create_knowledge_link(
                HIVE_ID,
                ENTRY_ID,
                target_id=TARGET_ENTRY_ID,
            )
        assert link["id"] == LINK_ID
        assert link["link_type"] == "relates_to"
        body = json.loads(httpx_mock.get_request().content)
        assert body["target_type"] == "knowledge"
        assert body["link_type"] == "relates_to"
        assert body["target_id"] == TARGET_ENTRY_ID

    def test_create_link_with_all_options(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/links",
            status_code=201,
            json=envelope(
                _link_data(
                    target_type="task",
                    target_ref="task-123",
                    link_type="depends_on",
                    metadata={"priority": "high"},
                )
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            link = c.create_knowledge_link(
                HIVE_ID,
                ENTRY_ID,
                target_type="task",
                target_ref="task-123",
                link_type="depends_on",
                metadata={"priority": "high"},
            )
        assert link["link_type"] == "depends_on"
        body = json.loads(httpx_mock.get_request().content)
        assert body["target_type"] == "task"
        assert body["target_ref"] == "task-123"
        assert body["link_type"] == "depends_on"
        assert body["metadata"] == {"priority": "high"}
        # target_id should not be in the body when not provided
        assert "target_id" not in body

    def test_create_link_source_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/NOPE/links",
            status_code=404,
            json=envelope(errors=[{"message": "Knowledge entry not found.", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.create_knowledge_link(HIVE_ID, "NOPE", target_id=TARGET_ENTRY_ID)


class TestListKnowledgeLinks:
    def test_list_by_source(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links?source={ENTRY_ID}",
            json=envelope([_link_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            links = c.list_knowledge_links(HIVE_ID, source_id=ENTRY_ID)
        assert len(links) == 1
        assert links[0]["source_id"] == ENTRY_ID

    def test_list_by_target(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links?target_ref={TARGET_ENTRY_ID}&target_type=knowledge",
            json=envelope([_link_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            links = c.list_knowledge_links(
                HIVE_ID,
                target_id=TARGET_ENTRY_ID,
                target_type="knowledge",
            )
        assert len(links) == 1

    def test_list_with_limit(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links?source={ENTRY_ID}&limit=5",
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            links = c.list_knowledge_links(HIVE_ID, source_id=ENTRY_ID, limit=5)
        assert links == []


class TestDeleteKnowledgeLink:
    def test_delete_returns_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links/{LINK_ID}",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.delete_knowledge_link(HIVE_ID, LINK_ID)
        assert result is None

    def test_delete_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links/NOPE",
            status_code=404,
            json=envelope(errors=[{"message": "Knowledge link not found.", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.delete_knowledge_link(HIVE_ID, "NOPE")


class TestConfirmKnowledgeLink:
    def test_confirm_link(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links/{LINK_ID}/confirm",
            json=envelope(_link_data(status="confirmed")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            link = c.confirm_knowledge_link(HIVE_ID, LINK_ID)
        assert link["status"] == "confirmed"


class TestDismissKnowledgeLink:
    def test_dismiss_link(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/links/{LINK_ID}/dismiss",
            json=envelope(_link_data(status="dismissed")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            link = c.dismiss_knowledge_link(HIVE_ID, LINK_ID)
        assert link["status"] == "dismissed"


class TestSuggestedLinks:
    def test_list_suggested(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/suggested-links",
            json=envelope([_link_data(status="suggested", metadata={"confidence": 0.85})]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            suggestions = c.suggested_links(HIVE_ID, ENTRY_ID)
        assert len(suggestions) == 1
        assert suggestions[0]["status"] == "suggested"

    def test_list_suggested_with_limit(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/suggested-links?limit=10",
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            suggestions = c.suggested_links(HIVE_ID, ENTRY_ID, limit=10)
        assert suggestions == []


# ------------------------------------------------------------------ #
# Knowledge graph traversal
# ------------------------------------------------------------------ #


class TestGetKnowledgeGraph:
    def test_graph_defaults(self, httpx_mock):
        graph_data = {
            "nodes": [
                {"id": ENTRY_ID, "key": "root", "depth": 0},
                {"id": TARGET_ENTRY_ID, "key": "related", "depth": 1},
            ],
            "edges": [
                {
                    "source_id": ENTRY_ID,
                    "target_id": TARGET_ENTRY_ID,
                    "link_type": "relates_to",
                }
            ],
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/graph",
            json=envelope(graph_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            graph = c.get_knowledge_graph(HIVE_ID, ENTRY_ID)
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1

    def test_graph_with_params(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}/graph?depth=3&link_types=relates_to%2Cdepends_on&max_nodes=100",
            json=envelope({"nodes": [], "edges": []}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            graph = c.get_knowledge_graph(
                HIVE_ID,
                ENTRY_ID,
                depth=3,
                link_types="relates_to,depends_on",
                max_nodes=100,
            )
        assert graph["nodes"] == []
        assert graph["edges"] == []

    def test_graph_entry_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/NOPE/graph",
            status_code=404,
            json=envelope(errors=[{"message": "Knowledge entry not found.", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.get_knowledge_graph(HIVE_ID, "NOPE")


# ------------------------------------------------------------------ #
# Knowledge index & health
# ------------------------------------------------------------------ #


class TestKnowledgeTopics:
    def test_get_topics(self, httpx_mock):
        topics_data = _entry_data(
            key="_index:topics",
            value={"clusters": [{"label": "auth", "count": 5}]},
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/index/topics",
            json=envelope(topics_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            topics = c.knowledge_topics(HIVE_ID)
        assert topics["key"] == "_index:topics"


class TestKnowledgeDecisions:
    def test_get_decisions(self, httpx_mock):
        decisions_data = _entry_data(key="_index:decisions", value={"decisions": []})
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/index/decisions",
            json=envelope(decisions_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            decisions = c.knowledge_decisions(HIVE_ID)
        assert decisions["key"] == "_index:decisions"


class TestKnowledgeByAgent:
    def test_get_agent_index(self, httpx_mock):
        agent_data = _entry_data(
            key=f"_index:agent:{AGENT_ID}",
            value={"entries_created": 12},
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/index/agent/{AGENT_ID}",
            json=envelope(agent_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            index = c.knowledge_by_agent(HIVE_ID, AGENT_ID)
        assert index["key"] == f"_index:agent:{AGENT_ID}"


class TestKnowledgeHealth:
    def test_get_health(self, httpx_mock):
        health_data = {
            "score": 78,
            "grade": "B+",
            "metrics": {
                "total_entries": 42,
                "linked_ratio": 0.65,
                "freshness": 0.8,
            },
            "recommendations": [
                "Consider adding links to 15 orphan entries.",
            ],
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/health",
            json=envelope(health_data),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            health = c.knowledge_health(HIVE_ID)
        assert health["score"] == 78
        assert health["grade"] == "B+"
        assert "metrics" in health
        assert "recommendations" in health
