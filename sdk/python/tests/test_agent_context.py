"""Tests for :class:`superpos_sdk.AgentContext`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk import AgentContext, SuperposClient


class ClientStub:
    """Minimal stub that records the last call made against it.

    ``AgentContext`` is designed for dependency injection — it accepts a
    preconstructed client via ``client=`` — so we can substitute this stub
    and assert the method name + args without touching the network.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False
        # Fixed return values so tests don't crash on tuple unpacking.
        self.return_value: Any = {"id": "ret"}

    def _make(self, name: str):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.return_value

        return _call

    def __getattr__(self, name: str):
        # Any attribute access produces a recording callable.
        return self._make(name)

    def close(self) -> None:
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
        ctx = AgentContext.from_env(client=ClientStub())

        assert ctx.base_url == "https://superpos.test"
        assert ctx.token == "tok-123"
        assert ctx.hive_id == "hive-1"
        assert ctx.agent_id == "agent-1"

    def test_missing_base_url_raises(self, monkeypatch):
        monkeypatch.delenv("SUPERPOS_BASE_URL", raising=False)
        monkeypatch.delenv("APIARY_BASE_URL", raising=False)
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "tok")
        with pytest.raises(ValueError, match="SUPERPOS_BASE_URL"):
            AgentContext.from_env(client=ClientStub())

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.delenv("SUPERPOS_TOKEN", raising=False)
        monkeypatch.delenv("APIARY_API_TOKEN", raising=False)
        monkeypatch.delenv("APIARY_TOKEN", raising=False)
        with pytest.raises(ValueError, match="token"):
            AgentContext.from_env(client=ClientStub())

    def test_api_token_wins_over_token(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "canonical")
        monkeypatch.setenv("SUPERPOS_TOKEN", "legacy")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.token == "canonical"

    def test_falls_back_to_legacy_token(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.setenv("SUPERPOS_TOKEN", "legacy")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.token == "legacy"

    def test_kwargs_override_env(self, monkeypatch):
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://env")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "env-tok")
        ctx = AgentContext.from_env(
            base_url="https://kwarg",
            token="kwarg-tok",
            hive_id="kw-hive",
            client=ClientStub(),
        )
        assert ctx.base_url == "https://kwarg"
        assert ctx.token == "kwarg-tok"
        assert ctx.hive_id == "kw-hive"

    def test_token_cached_on_instance(self, monkeypatch):
        # NFR-3: from_env reads the token once; later env mutations don't
        # propagate into an already-built context.
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "first")
        ctx = AgentContext.from_env(client=ClientStub())
        monkeypatch.setenv("SUPERPOS_API_TOKEN", "second")
        assert ctx.token == "first"


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
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.base_url == "https://apiary.legacy"

    def test_apiary_api_token_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-api-tok")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.token == "legacy-api-tok"

    def test_apiary_token_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.delenv("APIARY_API_TOKEN", raising=False)
        monkeypatch.setenv("APIARY_TOKEN", "legacy-tok")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.token == "legacy-tok"

    def test_apiary_hive_id_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        monkeypatch.setenv("APIARY_HIVE_ID", "legacy-hive")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.hive_id == "legacy-hive"

    def test_apiary_agent_id_fallback(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        monkeypatch.setenv("APIARY_BASE_URL", "https://apiary.legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "legacy-tok")
        monkeypatch.setenv("APIARY_AGENT_ID", "legacy-agent")
        ctx = AgentContext.from_env(client=ClientStub())
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
        ctx = AgentContext.from_env(client=ClientStub())
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
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.base_url == "https://apiary.legacy"
        assert ctx.token == "legacy-tok"
        assert ctx.hive_id == "legacy-hive"
        assert ctx.agent_id == "legacy-agent"

    def test_no_vars_at_all_raises(self, monkeypatch):
        self._clear_superpos_vars(monkeypatch)
        for var in ("APIARY_BASE_URL", "APIARY_API_TOKEN", "APIARY_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValueError, match="SUPERPOS_BASE_URL"):
            AgentContext.from_env(client=ClientStub())

    def test_superpos_token_beats_apiary_api_token(self, monkeypatch):
        """SUPERPOS_TOKEN (the weaker new var) still beats APIARY_API_TOKEN."""
        monkeypatch.setenv("SUPERPOS_BASE_URL", "https://superpos.test")
        monkeypatch.delenv("SUPERPOS_API_TOKEN", raising=False)
        monkeypatch.setenv("SUPERPOS_TOKEN", "new-legacy")
        monkeypatch.setenv("APIARY_API_TOKEN", "old-canonical")
        ctx = AgentContext.from_env(client=ClientStub())
        assert ctx.token == "new-legacy"


# ----------------------------------------------------------------------
# Properties / raw
# ----------------------------------------------------------------------


class TestProperties:
    def test_raw_returns_underlying_client(self):
        stub = ClientStub()
        ctx = AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id="hive",
            client=stub,
        )
        assert ctx.raw is stub

    def test_default_client_is_superpos_client(self):
        ctx = AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id="hive",
        )
        try:
            assert isinstance(ctx.raw, SuperposClient)
        finally:
            ctx.close()

    def test_identity_properties(self):
        ctx = AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id="hive-1",
            agent_id="agent-1",
            client=ClientStub(),
        )
        assert ctx.base_url == "https://superpos.test"
        assert ctx.hive_id == "hive-1"
        assert ctx.agent_id == "agent-1"


# ----------------------------------------------------------------------
# Hive binding
# ----------------------------------------------------------------------


class TestHiveBinding:
    def _ctx(self, stub: ClientStub, *, hive_id: str | None = "hive-X") -> AgentContext:
        return AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id=hive_id,
            client=stub,
        )

    def test_poll_tasks_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.poll_tasks(capability="code", limit=10)
        name, args, kwargs = stub.calls[-1]
        assert name == "poll_tasks"
        assert args == ("hive-X",)
        assert kwargs == {"capability": "code", "limit": 10}

    def test_create_task_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.create_task(task_type="summarize", payload={"text": "hi"})
        name, args, kwargs = stub.calls[-1]
        assert name == "create_task"
        assert args == ("hive-X",)
        assert kwargs["task_type"] == "summarize"
        assert kwargs["payload"] == {"text": "hi"}

    def test_claim_task_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.claim_task("task-1")
        assert stub.calls[-1][:2] == ("claim_task", ("hive-X", "task-1"))

    def test_complete_task_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.complete_task("task-1", result={"ok": True})
        name, args, kwargs = stub.calls[-1]
        assert name == "complete_task"
        assert args == ("hive-X", "task-1")
        assert kwargs["result"] == {"ok": True}

    def test_fail_task_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.fail_task("task-1", error={"code": "oops"})
        name, args, _ = stub.calls[-1]
        assert name == "fail_task"
        assert args == ("hive-X", "task-1")

    def test_update_progress_threads_hive_id(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.update_progress("task-1", progress=50)
        name, args, kwargs = stub.calls[-1]
        assert name == "update_progress"
        assert args == ("hive-X", "task-1")
        assert kwargs["progress"] == 50

    def test_post_message_maps_to_post_channel_message(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.post_message(
            "chan-1",
            "hello",
            message_type="discussion",
            mentions=["agent-42"],
        )
        name, args, kwargs = stub.calls[-1]
        assert name == "post_channel_message"
        assert args == ("hive-X", "chan-1", "hello")
        assert kwargs["mentions"] == ["agent-42"]

    def test_list_messages_maps_to_list_channel_messages(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.list_messages("chan-1", per_page=20)
        name, args, kwargs = stub.calls[-1]
        assert name == "list_channel_messages"
        assert args == ("hive-X", "chan-1")
        assert kwargs["per_page"] == 20

    def test_add_participant_maps_to_add_channel_participant(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.add_participant("chan-1", "agent", "agent-42", role="reviewer")
        name, args, kwargs = stub.calls[-1]
        assert name == "add_channel_participant"
        assert args == ("hive-X", "chan-1", "agent", "agent-42")
        assert kwargs["role"] == "reviewer"

    def test_resolve_channel(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.resolve_channel("chan-1", outcome="shipped")
        name, args, kwargs = stub.calls[-1]
        assert name == "resolve_channel"
        assert args == ("hive-X", "chan-1")
        assert kwargs["outcome"] == "shipped"

    def test_archive_channel(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.archive_channel("chan-1")
        assert stub.calls[-1][:2] == ("archive_channel", ("hive-X", "chan-1"))

    def test_create_channel(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.create_channel(title="T", channel_type="discussion")
        name, args, kwargs = stub.calls[-1]
        assert name == "create_channel"
        assert args == ("hive-X",)
        assert kwargs["title"] == "T"
        assert kwargs["channel_type"] == "discussion"

    def test_list_channels(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.list_channels(status="open")
        name, args, kwargs = stub.calls[-1]
        assert name == "list_channels"
        assert args == ("hive-X",)
        assert kwargs["status"] == "open"

    def test_get_channel(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.get_channel("chan-1")
        assert stub.calls[-1][:2] == ("get_channel", ("hive-X", "chan-1"))

    def test_knowledge_crud(self):
        stub = ClientStub()
        ctx = self._ctx(stub)

        ctx.create_knowledge(key="k", value={"v": 1}, scope="hive")
        assert stub.calls[-1][0] == "create_knowledge"
        assert stub.calls[-1][1] == ("hive-X",)

        ctx.list_knowledge(scope="hive")
        assert stub.calls[-1][0] == "list_knowledge"

        ctx.search_knowledge(q="foo")
        assert stub.calls[-1][0] == "search_knowledge"

        ctx.get_knowledge("entry-1")
        assert stub.calls[-1][:2] == ("get_knowledge", ("hive-X", "entry-1"))

        ctx.update_knowledge("entry-1", value={"v": 2})
        assert stub.calls[-1][0] == "update_knowledge"

        ctx.delete_knowledge("entry-1")
        assert stub.calls[-1][:2] == ("delete_knowledge", ("hive-X", "entry-1"))

    def test_events(self):
        stub = ClientStub()
        stub.return_value = []  # poll_events returns a list
        ctx = self._ctx(stub)

        ctx.poll_events(limit=10)
        assert stub.calls[-1][0] == "poll_events"
        assert stub.calls[-1][1] == ("hive-X",)

        stub.return_value = {"id": "evt"}
        ctx.publish_event(event_type="task.completed", payload={"task_id": "1"})
        name, args, kwargs = stub.calls[-1]
        assert name == "publish_event"
        assert args == ("hive-X",)
        assert kwargs["event_type"] == "task.completed"

    def test_schedules(self):
        stub = ClientStub()
        ctx = self._ctx(stub)
        ctx.create_schedule(
            name="nightly",
            trigger_type="cron",
            task_type="cleanup",
            cron_expression="0 2 * * *",
        )
        assert stub.calls[-1][0] == "create_schedule"

        ctx.list_schedules(status="active")
        assert stub.calls[-1][0] == "list_schedules"

        ctx.delete_schedule("sched-1")
        assert stub.calls[-1][:2] == ("delete_schedule", ("hive-X", "sched-1"))

    def test_update_memory_does_not_require_hive(self):
        stub = ClientStub()
        ctx = self._ctx(stub, hive_id=None)  # no hive_id
        ctx.update_memory(content="learned something", mode="append")
        assert stub.calls[-1][0] == "update_memory"

    def test_heartbeat_does_not_require_hive(self):
        stub = ClientStub()
        ctx = self._ctx(stub, hive_id=None)
        ctx.heartbeat()
        assert stub.calls[-1][0] == "heartbeat"

    def test_hive_scoped_method_raises_without_hive(self):
        stub = ClientStub()
        ctx = self._ctx(stub, hive_id=None)
        with pytest.raises(ValueError, match="hive_id"):
            ctx.poll_tasks()
        with pytest.raises(ValueError, match="hive_id"):
            ctx.create_knowledge(key="k", value=1)


class TestLifecycle:
    def test_context_manager_closes(self):
        stub = ClientStub()
        with AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id="hive-X",
            client=stub,
        ):
            pass
        assert stub.closed is True


# ----------------------------------------------------------------------
# OOP resource factory methods (Phase 2 — TASK-257)
# ----------------------------------------------------------------------


class TestResourceFactories:
    """Factory methods that return :class:`Channel`, :class:`Task`, and
    :class:`KnowledgeEntry` wrappers instead of raw dicts.
    """

    def _ctx(self, stub: ClientStub, *, hive_id: str | None = "hive-X") -> AgentContext:
        return AgentContext(
            base_url="https://superpos.test",
            token="tok",
            hive_id=hive_id,
            client=stub,
        )

    def test_channel_factory_returns_channel_wrapper(self):
        from superpos_sdk.resources import Channel

        stub = ClientStub()
        stub.return_value = {"id": "chan-1", "title": "T", "channel_type": "discussion"}
        ctx = self._ctx(stub)

        ch = ctx.channel("chan-1")
        assert isinstance(ch, Channel)
        assert ch.id == "chan-1"
        assert stub.calls[-1][:2] == ("get_channel", ("hive-X", "chan-1"))

    def test_create_channel_obj_returns_channel_wrapper(self):
        from superpos_sdk.resources import Channel

        stub = ClientStub()
        stub.return_value = {"id": "chan-2", "title": "New", "channel_type": "review"}
        ctx = self._ctx(stub)

        ch = ctx.create_channel_obj(title="New", channel_type="review")
        assert isinstance(ch, Channel)
        assert ch.id == "chan-2"
        assert ch.title == "New"
        name, _, kwargs = stub.calls[-1]
        assert name == "create_channel"
        assert kwargs["title"] == "New"
        assert kwargs["channel_type"] == "review"

    def test_list_channels_obj_returns_channel_list(self):
        from superpos_sdk.resources import Channel

        stub = ClientStub()
        stub.return_value = [
            {"id": "chan-a", "title": "A", "channel_type": "discussion"},
            {"id": "chan-b", "title": "B", "channel_type": "review"},
        ]
        ctx = self._ctx(stub)

        items = ctx.list_channels_obj(status="open")
        assert len(items) == 2
        assert all(isinstance(x, Channel) for x in items)
        assert items[0].id == "chan-a"
        assert items[1].title == "B"

    def test_list_channels_obj_handles_empty(self):
        stub = ClientStub()
        stub.return_value = []
        ctx = self._ctx(stub)
        assert ctx.list_channels_obj() == []

    def test_knowledge_factory_returns_entry_wrapper(self):
        from superpos_sdk.resources import KnowledgeEntry

        stub = ClientStub()
        stub.return_value = {
            "id": "entry-1",
            "key": "release.v2",
            "value": {"x": 1},
            "version": 1,
        }
        ctx = self._ctx(stub)

        entry = ctx.knowledge("entry-1")
        assert isinstance(entry, KnowledgeEntry)
        assert entry.id == "entry-1"
        assert entry.key == "release.v2"
        assert stub.calls[-1][:2] == ("get_knowledge", ("hive-X", "entry-1"))

    def test_create_knowledge_obj_returns_entry_wrapper(self):
        from superpos_sdk.resources import KnowledgeEntry

        stub = ClientStub()
        stub.return_value = {
            "id": "entry-2",
            "key": "new.key",
            "value": {"a": 1},
            "version": 1,
        }
        ctx = self._ctx(stub)

        entry = ctx.create_knowledge_obj(key="new.key", value={"a": 1})
        assert isinstance(entry, KnowledgeEntry)
        assert entry.key == "new.key"
        name, args, kwargs = stub.calls[-1]
        assert name == "create_knowledge"
        assert args == ("hive-X",)
        assert kwargs["key"] == "new.key"

    def test_list_knowledge_obj_returns_entries(self):
        from superpos_sdk.resources import KnowledgeEntry

        stub = ClientStub()
        stub.return_value = [
            {"id": "e1", "key": "a", "value": 1, "version": 1},
            {"id": "e2", "key": "b", "value": 2, "version": 1},
        ]
        ctx = self._ctx(stub)

        items = ctx.list_knowledge_obj(scope="hive")
        assert len(items) == 2
        assert all(isinstance(x, KnowledgeEntry) for x in items)

    def test_task_factory_returns_task_wrapper(self):
        from superpos_sdk.resources import Task

        stub = ClientStub()
        stub.return_value = {
            "id": "task-42",
            "type": "summarize",
            "status": "completed",
            "result": {"ok": True},
        }
        ctx = self._ctx(stub)

        t = ctx.task("task-42")
        assert isinstance(t, Task)
        assert t.id == "task-42"
        assert t.status == "completed"
        assert t.result == {"ok": True}
        assert stub.calls[-1][:2] == ("get_task", ("hive-X", "task-42"))

    def test_claim_next_returns_task_wrapper(self):
        from superpos_sdk.resources import Task

        class SequencedStub(ClientStub):
            def __init__(self):
                super().__init__()
                self.queue = [
                    [{"id": "task-42", "type": "summarize", "status": "pending"}],
                    {"id": "task-42", "type": "summarize", "status": "in_progress"},
                ]

            def _make(self, name):
                def _call(*args, **kwargs):
                    self.calls.append((name, args, kwargs))
                    if self.queue:
                        return self.queue.pop(0)
                    return self.return_value

                return _call

        stub = SequencedStub()
        ctx = self._ctx(stub)
        t = ctx.claim_next(capability="code")
        assert isinstance(t, Task)
        assert t.id == "task-42"
        assert t.status == "in_progress"  # claim response wins over poll dict

        # Assert both calls happened in order.
        names = [c[0] for c in stub.calls]
        assert "poll_tasks" in names
        assert "claim_task" in names
        assert names.index("poll_tasks") < names.index("claim_task")

    def test_claim_next_returns_none_when_no_tasks(self):
        stub = ClientStub()
        stub.return_value = []
        ctx = self._ctx(stub)
        assert ctx.claim_next() is None

    def test_claim_next_skips_malformed_first_task(self):
        stub = ClientStub()
        # First call returns a list with a dict missing "id"; should skip.
        stub.return_value = [{"no_id_here": True}]
        ctx = self._ctx(stub)
        assert ctx.claim_next() is None
