"""Tests for :class:`superpos_sdk.async_agent.AsyncAgentContext`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk import AsyncAgentContext, AsyncChannel, AsyncKnowledgeEntry, AsyncTask


class AsyncClientStub:
    """Async analogue of the sync ``ClientStub`` — records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False
        self.return_value: Any = {"id": "ret"}
        self.returns: dict[str, Any] = {}

    def _make(self, name: str):
        async def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in self.returns:
                return self.returns[name]
            return self.return_value

        return _call

    def __getattr__(self, name: str):
        return self._make(name)

    async def aclose(self) -> None:
        self.closed = True


# ----------------------------------------------------------------------
# from_env
# ----------------------------------------------------------------------


class TestFromEnv:
    def test_reads_all_four_env_vars(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "tok-123")
        monkeypatch.setenv("SUPERPOS_HIVE_ID", "hive-1")
        monkeypatch.setenv("SUPERPOS_AGENT_ID", "agent-1")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())

        assert ctx.base_url == "https://superpos.test"
        assert ctx.token == "tok-123"
        assert ctx.hive_id == "hive-1"
        assert ctx.agent_id == "agent-1"

    def test_missing_base_url_raises(self, monkeypatch):
        monkeypatch.delenv("SUPERPOS_BASE_URL", raising=False)
        monkeypatch.delenv("APIARY_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="SUPERPOS_BASE_URL"):
            AsyncAgentContext.from_env(client=AsyncClientStub())

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.delenv("SUPERPOS_TOKEN", raising=False)
        monkeypatch.delenv("APIARY_API_TOKEN", raising=False)
        monkeypatch.delenv("APIARY_TOKEN", raising=False)
        with pytest.raises(ValueError, match="no token"):
            AsyncAgentContext.from_env(client=AsyncClientStub())

    def test_token_fallback(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.setenv("SUPERPOS_TOKEN", "legacy-token")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.token == "legacy-token"

    def test_explicit_args_override_env(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://env.test")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "env-tok")
        ctx = AsyncAgentContext.from_env(
            base_url="https://explicit.test",
            token="explicit-tok",
            client=AsyncClientStub(),
        )
        assert ctx.base_url == "https://explicit.test"
        assert ctx.token == "explicit-tok"


# ----------------------------------------------------------------------
# Legacy APIARY_* env var fallbacks
# ----------------------------------------------------------------------


class TestLegacyApiaryEnvFallbacks:
    """Ensure APIARY_* env vars are accepted as fallbacks for SUPERPOS_*."""

    def _clear_superpos_vars(self, monkeypatch):
        """Remove all SUPERPOS_* env vars so only APIARY_* ones remain."""
        for var in (
            "SUPERPOS_BASE_URL",
            "SUPERPOS_API_TOKEN",
            "SUPERPOS_TOKEN",
            "SUPERPOS_HIVE_ID",
            "SUPERPOS_AGENT_ID",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_apiary_base_url_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.base_url == "https://apiary.legacy"

    def test_apiary_api_token_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-api-tok")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.token == "legacy-api-tok"

    def test_apiary_token_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.delenv("APIARY_API_TOKEN", raising=False)
        monkeypatch.setenv("APIARY_TOKEN", "legacy-tok")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.token == "legacy-tok"

    def test_apiary_hive_id_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        monkeypatch.setenv("APIARY_HIVE_ID", "legacy-hive")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.hive_id == "legacy-hive"

    def test_apiary_agent_id_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        monkeypatch.setenv("APIARY_AGENT_ID", "legacy-agent")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.agent_id == "legacy-agent"

    def test_superpos_vars_take_precedence_over_apiary(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.new")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "new-tok")
        monkeypatch.setenv("SUPERPOS_HIVE_ID", "new-hive")
        monkeypatch.setenv("SUPERPOS_AGENT_ID", "new-agent")
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.old")
        monkeypatch.setenv("APIARY_API_TOKEN", "old-tok")
        monkeypatch.setenv("APIARY_HIVE_ID", "old-hive")
        monkeypatch.setenv("APIARY_AGENT_ID", "old-agent")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.base_url == "https://superpos.new"
        assert ctx.token == "new-tok"
        assert ctx.hive_id == "new-hive"
        assert ctx.agent_id == "new-agent"

    def test_all_apiary_vars_together(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        monkeypatch.setenv("APIARY_HIVE_ID", "legacy-hive")
        monkeypatch.setenv("APIARY_AGENT_ID", "legacy-agent")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.base_url == "https://apiary.legacy"
        assert ctx.token == "legacy-tok"
        assert ctx.hive_id == "legacy-hive"
        assert ctx.agent_id == "legacy-agent"

    def test_no_vars_at_all_raises(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        for var in ("APIARY_BASE_URL", "APIARY_API_TOKEN", "APIARY_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValueError, match="SUPERPOS_BASE_URL"):
            AsyncAgentContext.from_env(client=AsyncClientStub())

    def test_superpos_token_beats_apiary_api_token(self, monkeypatch):
        """SUPERPOS_TOKEN (the weaker new var) still beats APIARY_API_TOKEN."""
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.setenv("SUPERPOS_TOKEN", "new-legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "old-canonical")
        ctx = AsyncAgentContext.from_env(client=AsyncClientStub())
        assert ctx.token == "new-legacy"


# ----------------------------------------------------------------------
# Hive binding
# ----------------------------------------------------------------------


class TestHiveBinding:
    async def test_methods_forward_hive_id(self):
        stub = AsyncClientStub()
        ctx = AsyncAgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id="hive-X",
            client=stub,
        )

        await ctx.poll_tasks(capability="code")
        await ctx.claim_task("t1")
        await ctx.complete_task("t1", result={"ok": True})

        assert ("poll_tasks", ("hive-X",), {"capability": "code", "limit": None}) in stub.calls
        assert ("claim_task", ("hive-X", "t1"), {}) in stub.calls
        # complete_task signature: (hive_id, task_id, **kwargs)
        names = [c[0] for c in stub.calls]
        assert "complete_task" in names

    async def test_missing_hive_raises(self):
        stub = AsyncClientStub()
        ctx = AsyncAgentContext(
            base_url="https://superpos.test",
            token="tok",
            client=stub,
        )
        with pytest.raises(ValueError, match="no hive_id"):
            await ctx.poll_tasks()


# ----------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------


class TestFactories:
    async def test_channel_returns_async_channel(self):
        stub = AsyncClientStub()
        stub.returns["get_channel"] = {"id": "ch-1", "title": "Hi", "status": "open"}
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        ch = await ctx.channel("ch-1")
        assert isinstance(ch, AsyncChannel)
        assert ch.id == "ch-1"
        assert ch.title == "Hi"

    async def test_create_channel_obj(self):
        stub = AsyncClientStub()
        stub.returns["create_channel"] = {
            "id": "ch-2",
            "title": "New",
            "channel_type": "discussion",
            "status": "open",
        }
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        ch = await ctx.create_channel_obj(title="New", channel_type="discussion")
        assert isinstance(ch, AsyncChannel)
        assert ch.id == "ch-2"

    async def test_list_channels_obj(self):
        stub = AsyncClientStub()
        stub.returns["list_channels"] = [{"id": "a"}, {"id": "b"}]
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        chans = await ctx.list_channels_obj(status="open")
        assert [c.id for c in chans] == ["a", "b"]
        assert all(isinstance(c, AsyncChannel) for c in chans)

    async def test_task_factory_returns_async_task(self):
        stub = AsyncClientStub()
        stub.returns["get_task"] = {
            "id": "t1",
            "type": "process",
            "status": "completed",
            "result": {"ok": True},
        }
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        task = await ctx.task("t1")
        assert isinstance(task, AsyncTask)
        assert task.id == "t1"
        assert task.status == "completed"
        assert task.result == {"ok": True}

    async def test_claim_next_returns_task(self):
        stub = AsyncClientStub()
        stub.returns["poll_tasks"] = [{"id": "t1"}]
        stub.returns["claim_task"] = {"id": "t1", "status": "in_progress"}
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        task = await ctx.claim_next(capability="code")
        assert isinstance(task, AsyncTask)
        assert task.id == "t1"
        assert task.status == "in_progress"

    async def test_claim_next_none_when_empty(self):
        stub = AsyncClientStub()
        stub.returns["poll_tasks"] = []
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        assert await ctx.claim_next() is None

    async def test_knowledge_factory(self):
        stub = AsyncClientStub()
        stub.returns["get_knowledge"] = {"id": "k1", "key": "x", "version": 1}
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        entry = await ctx.knowledge("k1")
        assert isinstance(entry, AsyncKnowledgeEntry)
        assert entry.id == "k1"

    async def test_list_knowledge_obj(self):
        stub = AsyncClientStub()
        stub.returns["list_knowledge"] = [{"id": "k1"}, {"id": "k2"}]
        ctx = AsyncAgentContext(
            base_url="https://superpos.test", token="t", hive_id="h", client=stub
        )
        entries = await ctx.list_knowledge_obj(key="foo")
        assert [e.id for e in entries] == ["k1", "k2"]


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


class TestLifecycle:
    async def test_async_context_closes_client(self):
        stub = AsyncClientStub()
        async with AsyncAgentContext(
            base_url="https://superpos.test", token="t", client=stub
        ) as ctx:
            assert ctx.raw is stub
        assert stub.closed
