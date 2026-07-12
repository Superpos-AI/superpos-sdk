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
        "type": "topic",
        "slug": "config.timeout",
        "title": "Config timeout",
        "body": "30",
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
        assert entries[0]["slug"] == "config.timeout"

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
        assert entry["slug"] == "config.timeout"

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
    def test_create_typed_entry(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entry = c.create_knowledge(
                HIVE_ID,
                type="topic",
                slug="config.timeout",
                title="Config timeout",
                body="30 seconds",
                summary="Default request timeout",
                frontmatter={"summary": "Default request timeout"},
                tags=["config"],
            )
        assert entry["version"] == 1
        body = json.loads(httpx_mock.get_request().content)
        assert body["type"] == "topic"
        assert body["slug"] == "config.timeout"
        assert body["title"] == "Config timeout"
        assert body["body"] == "30 seconds"
        assert body["summary"] == "Default request timeout"
        assert body["frontmatter"] == {"summary": "Default request timeout"}
        assert body["tags"] == ["config"]
        # The legacy shape must never be sent.
        assert "key" not in body
        assert "value" not in body

    def test_create_with_all_options(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data(scope="apiary", visibility="private")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.create_knowledge(
                HIVE_ID,
                type="topic",
                slug="config.timeout",
                body="30 seconds",
                scope="apiary",
                visibility="private",
                ttl="2026-12-31T23:59:59Z",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["scope"] == "apiary"
        assert body["visibility"] == "private"
        assert body["ttl"] == "2026-12-31T23:59:59Z"

    def test_create_legacy_key_value_is_converted(self, httpx_mock):
        """A legacy ``key``/``value`` call is adapted to the typed shape and
        emits a DeprecationWarning. The wire payload carries no key/value."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.create_knowledge(
                    HIVE_ID,
                    key="config.timeout",
                    value={"seconds": 30},
                )
        body = json.loads(httpx_mock.get_request().content)
        assert "key" not in body
        assert "value" not in body
        assert body["slug"] == "config.timeout"
        assert body["type"] == "topic"
        # The structured value is serialized into body and preserved verbatim
        # under frontmatter so nothing is lost.
        assert body["body"] == '{"seconds": 30}'
        assert body["frontmatter"] == {"legacy_value": {"seconds": 30}}

    def test_create_legacy_key_with_typed_type_is_not_dropped(self, httpx_mock):
        """Mixing a legacy ``key``/``value`` with a typed ``type`` must still
        normalize ``key``→``slug`` and ``value``→``body`` rather than silently
        dropping the legacy data (regression: previously built
        ``{"type":"procedure","slug":null}``)."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.create_knowledge(
                    HIVE_ID,
                    type="procedure",
                    key="legacy.k",
                    value={"x": 1},
                )
        body = json.loads(httpx_mock.get_request().content)
        assert "key" not in body
        assert "value" not in body
        assert body["type"] == "procedure"
        assert body["slug"] == "legacy.k"
        assert body["body"] == '{"x": 1}'
        assert body["frontmatter"] == {"legacy_value": {"x": 1}}

    def test_create_legacy_value_with_typed_slug_is_not_dropped(self, httpx_mock):
        """A legacy ``value`` supplied alongside a typed ``slug`` must be
        normalized into ``body``/``frontmatter`` (regression: previously built
        ``{"type":"topic","slug":"typed.slug"}`` and dropped the value)."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.create_knowledge(
                    HIVE_ID,
                    slug="typed.slug",
                    value={"x": 1},
                )
        body = json.loads(httpx_mock.get_request().content)
        assert "value" not in body
        assert body["type"] == "topic"
        assert body["slug"] == "typed.slug"
        assert body["body"] == '{"x": 1}'
        assert body["frontmatter"] == {"legacy_value": {"x": 1}}

    def test_create_typed_fields_win_over_legacy_when_both_supplied(self, httpx_mock):
        """When a typed field and its legacy counterpart are both supplied, the
        typed value wins, but a structured legacy ``value`` is still preserved
        verbatim under ``frontmatter`` so nothing is lost."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.create_knowledge(
                    HIVE_ID,
                    slug="typed.slug",
                    body="typed body",
                    key="legacy.k",
                    value={"x": 1},
                )
        body = json.loads(httpx_mock.get_request().content)
        assert "key" not in body
        assert "value" not in body
        assert body["slug"] == "typed.slug"
        assert body["body"] == "typed body"
        # The structured legacy value is preserved even though body/slug were typed.
        assert body["frontmatter"] == {"legacy_value": {"x": 1}}

    def test_create_explicit_frontmatter_not_overwritten_by_legacy_value(self, httpx_mock):
        """An explicitly supplied ``frontmatter`` is never clobbered by the
        legacy-value preservation shim."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=201,
            json=envelope(_entry_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.create_knowledge(
                    HIVE_ID,
                    slug="typed.slug",
                    frontmatter={"owner": "team-a"},
                    value={"x": 1},
                )
        body = json.loads(httpx_mock.get_request().content)
        assert body["frontmatter"] == {"owner": "team-a"}
        assert body["body"] == '{"x": 1}'

    def test_create_conflict(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge",
            status_code=409,
            json=envelope(
                errors=[
                    {
                        "message": "A knowledge entry with slug 'x' already exists.",
                        "code": "conflict",
                    }
                ]
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.raises(ConflictError):
                c.create_knowledge(HIVE_ID, type="topic", slug="x", body="v")


class TestUpdateKnowledge:
    def test_update_typed_bumps_version(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data(version=2, body="60 seconds")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            entry = c.update_knowledge(HIVE_ID, ENTRY_ID, body="60 seconds")
        assert entry["version"] == 2
        body = json.loads(httpx_mock.get_request().content)
        assert body["body"] == "60 seconds"
        assert "value" not in body

    def test_update_legacy_value_is_converted(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data(version=2)),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            with pytest.warns(DeprecationWarning):
                c.update_knowledge(HIVE_ID, ENTRY_ID, value={"seconds": 60})
        body = json.loads(httpx_mock.get_request().content)
        assert "value" not in body
        assert body["body"] == '{"seconds": 60}'
        assert body["frontmatter"] == {"legacy_value": {"seconds": 60}}

    def test_update_visibility_only_emits_visibility_shape(self, httpx_mock):
        # Drift guard: a visibility-only update must emit exactly
        # {"visibility": ...} — the shape the server now accepts.
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data(version=2, visibility="private")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.update_knowledge(HIVE_ID, ENTRY_ID, visibility="private")
        body = json.loads(httpx_mock.get_request().content)
        assert body == {"visibility": "private"}

    def test_update_ttl_only_emits_ttl_shape(self, httpx_mock):
        # Drift guard: a ttl-only update must emit exactly {"ttl": ...}.
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            json=envelope(_entry_data(version=2, ttl="2026-12-31T23:59:59Z")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.update_knowledge(HIVE_ID, ENTRY_ID, ttl="2026-12-31T23:59:59Z")
        body = json.loads(httpx_mock.get_request().content)
        assert body == {"ttl": "2026-12-31T23:59:59Z"}


class TestDeleteKnowledge:
    def test_delete_returns_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/knowledge/{ENTRY_ID}",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.delete_knowledge(HIVE_ID, ENTRY_ID)
        assert result is None
