"""Tests for :func:`superpos_sdk.skills.remember` (sync)."""

from __future__ import annotations

from typing import Any

from superpos_sdk.resources import KnowledgeEntry
from superpos_sdk.skills import remember


class SyncCtxStub:
    def __init__(self) -> None:
        self._hive_id = "hive-X"
        self.created: dict[str, Any] | None = None

    def _require_hive(self) -> str:
        return self._hive_id

    def create_knowledge_obj(self, **kwargs: Any) -> KnowledgeEntry:
        self.created = kwargs
        return KnowledgeEntry(
            {
                "id": "k-1",
                "key": kwargs["key"],
                "value": kwargs["value"],
                "scope": kwargs.get("scope"),
                "visibility": kwargs.get("visibility"),
                "version": 1,
            },
            self,
        )


class TestRemember:
    def test_string_value_wrapped(self):
        ctx = SyncCtxStub()
        entry = remember(ctx, "notes.release", "v2 ships Friday", tags=["release"])
        assert isinstance(entry, KnowledgeEntry)
        assert ctx.created["key"] == "notes.release"
        assert ctx.created["value"] == {
            "title": "notes.release",
            "content": "v2 ships Friday",
            "format": "markdown",
            "tags": ["release"],
        }
        assert ctx.created["scope"] == "hive"
        assert ctx.created["visibility"] == "public"

    def test_string_with_title_and_summary(self):
        ctx = SyncCtxStub()
        remember(
            ctx,
            "notes.release",
            "body",
            title="Release v2",
            summary="tldr",
            tags=["x"],
            format="text",
        )
        assert ctx.created["value"] == {
            "title": "Release v2",
            "content": "body",
            "format": "text",
            "tags": ["x"],
            "summary": "tldr",
        }

    def test_dict_value_passthrough(self):
        ctx = SyncCtxStub()
        payload = {"custom": "shape", "n": 42}
        remember(ctx, "custom.key", payload)
        assert ctx.created["value"] is payload

    def test_scope_and_visibility_overrides(self):
        ctx = SyncCtxStub()
        remember(ctx, "k", "v", scope="apiary", visibility="private", ttl="30d")
        assert ctx.created["scope"] == "apiary"
        assert ctx.created["visibility"] == "private"
        assert ctx.created["ttl"] == "30d"
