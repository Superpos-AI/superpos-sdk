"""Tests for :class:`superpos_sdk.resources.async_resources.AsyncKnowledgeEntry`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources.async_resources import AsyncKnowledgeEntry


class AsyncRawStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.returns: dict[str, Any] = {}

    def _make(self, name: str):
        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name, {"ok": True, "method": name})

        return _call

    def __getattr__(self, name: str):
        return self._make(name)


class AsyncContextStub:
    def __init__(self, hive_id: str = "hive-X") -> None:
        self._hive_id = hive_id
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.returns: dict[str, Any] = {}
        self.raw = AsyncRawStub()

    def _require_hive(self) -> str:
        if self._hive_id is None:
            raise ValueError("hive_id required")
        return self._hive_id

    def _make(self, name: str):
        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name, {"ok": True, "method": name})

        return _call

    def __getattr__(self, name: str):
        return self._make(name)


def _sample_entry() -> dict[str, Any]:
    return {
        "id": "k-1",
        "key": "release.v2.date",
        "type": "note",
        "slug": "release-v2-date",
        "title": "Release v2 date",
        "body": "Ships on 2026-05-01.",
        "summary": "Ship date for v2.",
        "frontmatter": {"owner": "release-team"},
        "tags": ["release", "v2"],
        "source_ids": ["src-1", "src-2"],
        "scope": "hive",
        "visibility": "public",
        "version": 1,
        "ttl": None,
        "created_at": "2026-04-19T10:00:00Z",
        "updated_at": "2026-04-19T10:00:00Z",
    }


class TestConstruction:
    def test_attributes(self):
        ctx = AsyncContextStub()
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        assert e.id == "k-1"
        assert e.key == "release.v2.date"
        assert e.version == 1
        assert e.deleted is False

    def test_typed_accessors(self):
        ctx = AsyncContextStub()
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        assert e.type == "note"
        assert e.slug == "release-v2-date"
        assert e.title == "Release v2 date"
        assert e.body == "Ships on 2026-05-01."
        assert e.summary == "Ship date for v2."
        assert e.frontmatter == {"owner": "release-team"}
        assert e.tags == ["release", "v2"]
        assert e.source_ids == ["src-1", "src-2"]

    def test_typed_accessor_defaults_when_absent(self):
        ctx = AsyncContextStub()
        e = AsyncKnowledgeEntry({"id": "k-1"}, ctx)
        assert e.type is None
        assert e.slug is None
        assert e.title is None
        assert e.body is None
        assert e.summary is None
        assert e.frontmatter == {}
        assert e.tags == []
        assert e.source_ids == []

    def test_value_alias_is_deprecated(self):
        ctx = AsyncContextStub()
        # Typed responses no longer carry `value`; the alias returns None.
        assert AsyncKnowledgeEntry(_sample_entry(), ctx).value is None
        # Legacy payloads with `value` still surface through the alias.
        legacy = AsyncKnowledgeEntry({"id": "k-1", "value": {"x": 1}}, ctx)
        assert legacy.value == {"x": 1}

    def test_repr(self):
        ctx = AsyncContextStub()
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        r = repr(e)
        assert "k-1" in r
        assert "release.v2.date" in r
        assert "AsyncKnowledgeEntry" in r

    def test_equality(self):
        ctx = AsyncContextStub()
        a = AsyncKnowledgeEntry({"id": "k"}, ctx)
        b = AsyncKnowledgeEntry({"id": "k", "version": 3}, ctx)
        assert a == b


class TestWrites:
    async def test_update_bumps_version(self):
        ctx = AsyncContextStub()
        ctx.returns["update_knowledge"] = {
            "id": "k-1",
            "body": "Ships on 2026-05-15.",
            "summary": "Slipped a fortnight.",
            "version": 2,
        }
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        await e.update(body="Ships on 2026-05-15.")
        assert e.version == 2
        assert e.body == "Ships on 2026-05-15."
        assert e.summary == "Slipped a fortnight."

    async def test_delete_marks_sticky(self):
        ctx = AsyncContextStub()
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        await e.delete()
        assert e.deleted is True
        with pytest.raises(RuntimeError, match="already deleted"):
            await e.update({"date": "nope"})
        with pytest.raises(RuntimeError, match="already deleted"):
            await e.refresh()

    async def test_link_to_knowledge_uses_target_id(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["create_knowledge_link"] = {"id": "link-1"}
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        result = await e.link_to("k-2", link_type="supersedes")
        assert result == {"id": "link-1"}
        call = ctx.raw.calls[0]
        assert call[0] == "create_knowledge_link"
        assert call[1] == ("hive-X", "k-1")
        assert call[2]["target_id"] == "k-2"
        assert call[2]["link_type"] == "supersedes"

    async def test_link_to_task_uses_target_ref(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["create_knowledge_link"] = {"id": "link-2"}
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        await e.link_to("task-42", target_type="task", link_type="derived_from")
        call = ctx.raw.calls[0]
        assert call[2]["target_ref"] == "task-42"
        assert call[2]["target_type"] == "task"
        assert "target_id" not in call[2]


class TestRead:
    async def test_refresh_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["get_knowledge"] = {
            "id": "k-1",
            "version": 5,
            "body": "Ships on 2026-05-02.",
        }
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        await e.refresh()
        assert e.version == 5
        assert e.body == "Ships on 2026-05-02."
        # Untouched typed fields survive the merge.
        assert e.title == "Release v2 date"

    async def test_links_calls_raw(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["list_knowledge_links"] = [{"id": "l1"}]
        e = AsyncKnowledgeEntry(_sample_entry(), ctx)
        result = await e.links(limit=5)
        assert result == [{"id": "l1"}]
        call = ctx.raw.calls[0]
        assert call[0] == "list_knowledge_links"
        assert call[2]["source_id"] == "k-1"
        assert call[2]["limit"] == 5
