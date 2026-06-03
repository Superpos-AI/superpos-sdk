"""Tests for :func:`superpos_sdk.skills.recall` (sync)."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources import KnowledgeEntry
from superpos_sdk.skills import recall


class SyncCtxStub:
    def __init__(self) -> None:
        self._hive_id = "hive-X"
        self.list_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.list_returns: list[dict[str, Any]] = []
        self.search_returns: list[dict[str, Any]] = []

    def _require_hive(self) -> str:
        return self._hive_id

    def list_knowledge(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_calls.append(kwargs)
        return list(self.list_returns)

    def search_knowledge(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.search_calls.append(kwargs)
        return list(self.search_returns)


class TestRecall:
    def test_by_key_uses_list_knowledge(self):
        ctx = SyncCtxStub()
        ctx.list_returns = [{"id": "k-1"}, {"id": "k-2"}]
        entries = recall(ctx, "release.v2", limit=5)
        assert [e.id for e in entries] == ["k-1", "k-2"]
        assert all(isinstance(e, KnowledgeEntry) for e in entries)
        assert ctx.list_calls == [{"key": "release.v2", "scope": None, "limit": 5}]
        assert ctx.search_calls == []

    def test_by_query_uses_search(self):
        ctx = SyncCtxStub()
        ctx.search_returns = [{"id": "k-9"}]
        entries = recall(ctx, query="ship date", scope="hive")
        assert [e.id for e in entries] == ["k-9"]
        assert ctx.search_calls == [{"q": "ship date", "scope": "hive", "limit": 10}]
        assert ctx.list_calls == []

    def test_neither_raises(self):
        ctx = SyncCtxStub()
        with pytest.raises(ValueError, match="one of"):
            recall(ctx)

    def test_both_raises(self):
        ctx = SyncCtxStub()
        with pytest.raises(ValueError, match="not both"):
            recall(ctx, "k", query="q")

    def test_empty_result(self):
        ctx = SyncCtxStub()
        ctx.list_returns = []
        entries = recall(ctx, "k")
        assert entries == []
