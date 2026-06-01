"""Tests for the async variants of the skills layer."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk import AsyncAgentContext
from superpos_sdk.resources.async_resources import AsyncChannel, AsyncKnowledgeEntry
from superpos_sdk.skills import decide, discuss, recall, remember


class AsyncClientStub:
    """Async client stub — records calls and yields canned returns."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.returns: dict[str, Any] = {}
        self.closed = False

    def _make(self, name: str):
        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name, {"ok": True, "method": name})

        return _call

    def __getattr__(self, name: str):
        return self._make(name)

    async def aclose(self) -> None:
        self.closed = True


def _make_ctx(stub: AsyncClientStub) -> AsyncAgentContext:
    return AsyncAgentContext(
        base_url="https://superpos.test",
        token="t",
        hive_id="hive-X",
        client=stub,
    )


class TestDispatch:
    async def test_dispatcher_returns_awaitable_for_async_ctx(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {
            "id": "ch-1",
            "title": "T",
            "channel_type": "discussion",
            "status": "open",
        }
        ctx = _make_ctx(stub)
        result = discuss(ctx, "T")
        # Must be a coroutine — the dispatcher picked the async variant.
        import inspect

        assert inspect.iscoroutine(result)
        ch = await result
        assert isinstance(ch, AsyncChannel)
        assert ch.id == "ch-1"


class TestAsyncDiscuss:
    async def test_creates_channel(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {
            "id": "ch-1",
            "title": "T",
            "channel_type": "discussion",
        }
        ctx = _make_ctx(stub)
        ch = await discuss(ctx, "T")
        assert isinstance(ch, AsyncChannel)
        assert ch.id == "ch-1"

    async def test_posts_opener(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {"id": "ch-1", "title": "T"}
        stub.returns["post_channel_message"] = {"id": "m-1"}
        stub.returns["get_channel"] = {"id": "ch-1", "title": "T"}
        ctx = _make_ctx(stub)
        await discuss(ctx, "T", initial_message="Hi")
        names = [c[0] for c in stub.calls]
        assert "post_channel_message" in names


class TestAsyncDecide:
    async def test_posts_proposal_with_options(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {"id": "ch-2", "title": "T"}
        stub.returns["post_channel_message"] = {"id": "m-1"}
        stub.returns["get_channel"] = {"id": "ch-2", "title": "T"}
        ctx = _make_ctx(stub)
        await decide(ctx, "Q", "q?", ["a", "b"])

        post_call = next(c for c in stub.calls if c[0] == "post_channel_message")
        # Signature: post_channel_message(hive_id, channel_id, body, *, message_type, ...)
        assert post_call[2]["message_type"] == "proposal"
        assert post_call[2]["metadata"] == {
            "options": [{"key": "a", "label": "a"}, {"key": "b", "label": "b"}]
        }


class TestAsyncRemember:
    async def test_string_value_wrapped(self):
        stub = AsyncClientStub()
        stub.returns["create_knowledge"] = {
            "id": "k-1",
            "key": "k",
            "value": {"title": "k", "content": "body", "format": "markdown", "tags": []},
            "version": 1,
        }
        ctx = _make_ctx(stub)
        entry = await remember(ctx, "k", "body")
        assert isinstance(entry, AsyncKnowledgeEntry)
        create_call = next(c for c in stub.calls if c[0] == "create_knowledge")
        assert create_call[2]["value"] == {
            "title": "k",
            "content": "body",
            "format": "markdown",
            "tags": [],
        }

    async def test_dict_passthrough(self):
        stub = AsyncClientStub()
        payload = {"custom": "shape"}
        stub.returns["create_knowledge"] = {"id": "k-2", "key": "k", "value": payload}
        ctx = _make_ctx(stub)
        await remember(ctx, "k", payload)
        create_call = next(c for c in stub.calls if c[0] == "create_knowledge")
        assert create_call[2]["value"] is payload


class TestAsyncRecall:
    async def test_by_key(self):
        stub = AsyncClientStub()
        stub.returns["list_knowledge"] = [{"id": "k-1"}]
        ctx = _make_ctx(stub)
        entries = await recall(ctx, "k")
        assert [e.id for e in entries] == ["k-1"]
        assert all(isinstance(e, AsyncKnowledgeEntry) for e in entries)

    async def test_by_query(self):
        stub = AsyncClientStub()
        stub.returns["search_knowledge"] = [{"id": "k-7"}]
        ctx = _make_ctx(stub)
        entries = await recall(ctx, query="ship")
        assert [e.id for e in entries] == ["k-7"]

    async def test_neither_raises(self):
        stub = AsyncClientStub()
        ctx = _make_ctx(stub)
        with pytest.raises(ValueError, match="one of"):
            await recall(ctx)


class TestMethodBinding:
    async def test_async_context_has_skill_methods(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {"id": "ch-99", "title": "T"}
        ctx = _make_ctx(stub)
        ch = await ctx.discuss("T")
        assert isinstance(ch, AsyncChannel)
