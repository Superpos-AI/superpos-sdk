"""Tests for knowledge CRUD endpoints."""

from __future__ import annotations

import json

import pytest

from superpos_sdk import SuperposClient
from superpos_sdk.exceptions import ConflictError, NotFoundError

from .conftest import BASE_URL, ENTRY_ID, HIVE_ID, TOKEN, envelope


def _entry_data(**overrides):
    base = {
        "id": ENTRY_ID,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "key": "config.timeout",
        "value": {"seconds": 30},
        "scope": "hive",
        "visibility": "public",
        "created_by": "agent-1",
        "version": 1,
        "ttl": None,
        "created_at": "2026-02-26T12:00:00Z",
        "updated_at": "2026-02-26T12:00:00Z",
    }
    base.update(overrides)
    return base


class TestListKnowledge:
    def test_list_returns_entries(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            json=envelope([_entry_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entries = c.list_knowledge(HIVE_ID)
        assert len(entries) == 1
        assert entries[0]["key"] == "config.timeout"

    def test_list_with_filters(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge?key=config.*&scope=hive&limit=10",
            json=envelope([]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entries = c.list_knowledge(HIVE_ID, key="config.*", scope="hive", limit=10)
        assert entries == []


class TestSearchKnowledge:
    def test_search(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/search?q=timeout",
            json=envelope([_entry_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.search_knowledge(HIVE_ID, q="timeout")
        assert len(results) == 1


class TestGetKnowledge:
    def test_get_entry(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entry = c.get_knowledge(HIVE_ID, ENTRY_ID)
        assert entry["value"] == {"seconds": 30}

    def test_get_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/NOPE",
            status_code=404,
            json=envelope(errors=[{"message": "Not found.", "code": "not_found"}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(NotFoundError):
                c.get_knowledge(HIVE_ID, "NOPE")


class TestCreateKnowledge:
    def test_create_entry(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entry = c.create_knowledge(
                HIVE_ID,
                key="config.timeout",
                value={"seconds": 30},
            )
        assert entry["version"] == 1
        body = json.loads(httpx_mock.get_request().content)
        assert body["key"] == "config.timeout"

    def test_create_with_all_options(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data(scope="apiary", visibility="private")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.create_knowledge(
                HIVE_ID,
                key="config.timeout",
                value={"seconds": 30},
                scope="apiary",
                visibility="private",
                ttl="2026-12-31T23:59:59Z",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["scope"] == "apiary"
        assert body["visibility"] == "private"
        assert body["ttl"] == "2026-12-31T23:59:59Z"

    def test_create_conflict(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=409,
            json=envelope(
                errors=[
                    {
                        "message": "A knowledge entry with key 'x' already exists.",
                        "code": "conflict",
                    }
                ]
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(ConflictError):
                c.create_knowledge(HIVE_ID, key="x", value="v")


class TestUpdateKnowledge:
    def test_update_bumps_version(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data(version=2, value={"seconds": 60})),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entry = c.update_knowledge(HIVE_ID, ENTRY_ID, value={"seconds": 60})
        assert entry["version"] == 2
        body = json.loads(httpx_mock.get_request().content)
        assert body["value"] == {"seconds": 60}


class TestDeleteKnowledge:
    def test_delete_returns_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.delete_knowledge(HIVE_ID, ENTRY_ID)
        assert result is None
