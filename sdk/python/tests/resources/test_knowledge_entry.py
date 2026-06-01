"""Tests for :class:`superpos_sdk.resources.KnowledgeEntry`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources import KnowledgeEntry


class RawStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.returns: dict[str, Any] = {}

    def _make(self, name: str):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name, {"ok": True, "method": name})

        return _call

    def __getattr__(self, name: str):
        return self._make(name)


class ContextStub:
    def __init__(self, hive_id: str = "hive-X") -> None:
        self._hive_id = hive_id
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.returns: dict[str, Any] = {}
        self.raw = RawStub()

    def _require_hive(self) -> str:
        if self._hive_id is None:
            raise ValueError("hive_id required")
        return self._hive_id

    def _make(self, name: str):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name, {"ok": True, "method": name})

        return _call

    def __getattr__(self, name: str):
        return self._make(name)


def _sample_entry() -> dict[str, Any]:
    return {
        "id": "entry-1",
        "key": "release.v2.date",
        "value": {"date": "2026-05-01"},
        "scope": "hive",
        "visibility": "public",
        "version": 1,
        "created_at": "2026-04-19T10:00:00Z",
        "updated_at": "2026-04-19T10:00:00Z",
    }


class TestConstruction:
    def test_attribute_access(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        assert e.id == "entry-1"
        assert e.key == "release.v2.date"
        assert e.value == {"date": "2026-05-01"}
        assert e.scope == "hive"
        assert e.visibility == "public"
        assert e.version == 1
        assert e.deleted is False

    def test_to_dict_shallow_copy(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        d = e.to_dict()
        d["version"] = 99
        assert e.version == 1

    def test_repr(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        r = repr(e)
        assert "entry-1" in r
        assert "release.v2.date" in r
        assert "1" in r

    def test_equality_by_id(self):
        ctx = ContextStub()
        a = KnowledgeEntry({"id": "e1", "version": 1}, ctx)
        b = KnowledgeEntry({"id": "e1", "version": 99}, ctx)
        c = KnowledgeEntry({"id": "e2"}, ctx)
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


class TestRead:
    def test_refresh_merges(self):
        ctx = ContextStub()
        ctx.returns["get_knowledge"] = {
            "id": "entry-1",
            "version": 5,
            "value": {"date": "2026-05-02"},
        }
        e = KnowledgeEntry(_sample_entry(), ctx)
        result = e.refresh()
        assert result is e
        assert e.version == 5
        assert e.value == {"date": "2026-05-02"}
        name, args, _ = ctx.calls[-1]
        assert name == "get_knowledge"
        assert args == ("entry-1",)

    def test_links_threads_source_id(self):
        ctx = ContextStub()
        ctx.raw.returns["list_knowledge_links"] = [{"id": "link-1"}]
        e = KnowledgeEntry(_sample_entry(), ctx)
        result = e.links(target_type="task", limit=10)
        assert result == [{"id": "link-1"}]
        name, args, kwargs = ctx.raw.calls[-1]
        assert name == "list_knowledge_links"
        assert args == ("hive-X",)
        assert kwargs["source_id"] == "entry-1"
        assert kwargs["target_type"] == "task"
        assert kwargs["limit"] == 10


class TestWrite:
    def test_update_merges_response(self):
        ctx = ContextStub()
        ctx.returns["update_knowledge"] = {
            "id": "entry-1",
            "value": {"date": "2026-05-15"},
            "version": 2,
        }
        e = KnowledgeEntry(_sample_entry(), ctx)
        e.update({"date": "2026-05-15"})
        assert e.version == 2
        assert e.value == {"date": "2026-05-15"}
        name, args, kwargs = ctx.calls[-1]
        assert name == "update_knowledge"
        assert args == ("entry-1",)
        assert kwargs["value"] == {"date": "2026-05-15"}

    def test_delete_marks_entry_dead(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        e.delete()
        assert e.deleted is True
        name, args, _ = ctx.calls[-1]
        assert name == "delete_knowledge"
        assert args == ("entry-1",)

    def test_mutations_after_delete_raise(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        e.delete()
        with pytest.raises(RuntimeError, match="already deleted"):
            e.update({"x": 1})
        with pytest.raises(RuntimeError, match="already deleted"):
            e.delete()
        with pytest.raises(RuntimeError, match="already deleted"):
            e.refresh()
        with pytest.raises(RuntimeError, match="already deleted"):
            e.link_to("other-id")

    def test_attribute_reads_still_work_after_delete(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        e.delete()
        assert e.id == "entry-1"
        assert e.key == "release.v2.date"
        assert e.version == 1

    def test_link_to_calls_raw(self):
        ctx = ContextStub()
        ctx.raw.returns["create_knowledge_link"] = {"id": "link-1"}
        e = KnowledgeEntry(_sample_entry(), ctx)
        result = e.link_to("entry-2", link_type="supersedes")
        assert result == {"id": "link-1"}
        name, args, kwargs = ctx.raw.calls[-1]
        assert name == "create_knowledge_link"
        assert args == ("hive-X", "entry-1")
        assert kwargs["target_id"] == "entry-2"
        assert kwargs["link_type"] == "supersedes"
        assert kwargs["target_type"] == "knowledge"
        assert "target_ref" not in kwargs

    def test_link_to_non_knowledge_sends_target_ref(self):
        ctx = ContextStub()
        ctx.raw.returns["create_knowledge_link"] = {"id": "link-2"}
        e = KnowledgeEntry(_sample_entry(), ctx)
        result = e.link_to("task-42", target_type="task", link_type="relates_to")
        assert result == {"id": "link-2"}
        name, args, kwargs = ctx.raw.calls[-1]
        assert name == "create_knowledge_link"
        assert args == ("hive-X", "entry-1")
        assert kwargs["target_ref"] == "task-42"
        assert kwargs["target_type"] == "task"
        assert "target_id" not in kwargs

    def test_unlink_calls_raw(self):
        ctx = ContextStub()
        e = KnowledgeEntry(_sample_entry(), ctx)
        e.unlink("link-xyz")
        name, args, _ = ctx.raw.calls[-1]
        assert name == "delete_knowledge_link"
        assert args == ("hive-X", "link-xyz")
