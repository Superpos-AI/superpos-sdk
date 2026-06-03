"""Tests for :class:`superpos_sdk.resources.Task`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources import Task


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


def _sample_task() -> dict[str, Any]:
    return {
        "id": "task-1",
        "type": "summarize",
        "status": "pending",
        "payload": {"text": "hi"},
        "priority": 2,
        "progress": 0,
        "status_message": None,
        "created_at": "2026-04-19T10:00:00Z",
        "updated_at": "2026-04-19T10:00:00Z",
    }


class TestConstruction:
    def test_attribute_access(self):
        ctx = ContextStub()
        t = Task(_sample_task(), ctx)
        assert t.id == "task-1"
        assert t.type == "summarize"
        assert t.status == "pending"
        assert t.payload == {"text": "hi"}
        assert t.priority == 2
        assert t.progress == 0
        assert t.result is None

    def test_type_falls_back_to_task_type(self):
        ctx = ContextStub()
        t = Task({"id": "t", "task_type": "legacy"}, ctx)
        assert t.type == "legacy"

    def test_to_dict_shallow_copy(self):
        ctx = ContextStub()
        t = Task(_sample_task(), ctx)
        d = t.to_dict()
        d["status"] = "mutated"
        assert t.status == "pending"

    def test_repr(self):
        ctx = ContextStub()
        t = Task(_sample_task(), ctx)
        r = repr(t)
        assert "task-1" in r
        assert "summarize" in r
        assert "pending" in r

    def test_equality_by_id(self):
        ctx = ContextStub()
        a = Task({"id": "task-1", "status": "pending"}, ctx)
        b = Task({"id": "task-1", "status": "completed"}, ctx)
        c = Task({"id": "task-2"}, ctx)
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


class TestWrite:
    def test_claim_merges_response(self):
        ctx = ContextStub()
        ctx.returns["claim_task"] = {
            "id": "task-1",
            "status": "in_progress",
            "assigned_agent_id": "agent-1",
        }
        t = Task(_sample_task(), ctx)
        result = t.claim()
        assert result is t
        assert t.status == "in_progress"
        assert t.to_dict()["assigned_agent_id"] == "agent-1"
        name, args, _ = ctx.calls[-1]
        assert name == "claim_task"
        assert args == ("task-1",)

    def test_update_progress_merges(self):
        ctx = ContextStub()
        ctx.returns["update_progress"] = {
            "id": "task-1",
            "progress": 50,
            "status_message": "halfway",
        }
        t = Task(_sample_task(), ctx)
        t.update_progress(50, status_message="halfway")
        assert t.progress == 50
        assert t.status_message == "halfway"
        name, args, kwargs = ctx.calls[-1]
        assert name == "update_progress"
        assert args == ("task-1",)
        assert kwargs["progress"] == 50

    def test_complete_merges(self):
        ctx = ContextStub()
        ctx.returns["complete_task"] = {
            "id": "task-1",
            "status": "completed",
            "result": {"output": "ok"},
        }
        t = Task(_sample_task(), ctx)
        t.complete(result={"output": "ok"})
        assert t.status == "completed"
        assert t.result == {"output": "ok"}
        name, args, kwargs = ctx.calls[-1]
        assert name == "complete_task"
        assert args == ("task-1",)
        assert kwargs["result"] == {"output": "ok"}

    def test_fail_merges(self):
        ctx = ContextStub()
        ctx.returns["fail_task"] = {
            "id": "task-1",
            "status": "failed",
            "status_message": "boom",
        }
        t = Task(_sample_task(), ctx)
        t.fail(error={"code": "oops"}, status_message="boom")
        assert t.status == "failed"
        name, args, kwargs = ctx.calls[-1]
        assert name == "fail_task"
        assert args == ("task-1",)
        assert kwargs["error"] == {"code": "oops"}

    def test_replay_returns_new_task(self):
        ctx = ContextStub()
        ctx.raw.returns["replay_task"] = {
            "id": "task-2",
            "type": "summarize",
            "status": "pending",
        }
        original = Task(_sample_task(), ctx)
        replayed = original.replay()
        assert isinstance(replayed, Task)
        assert replayed is not original
        assert replayed.id == "task-2"
        # Original is untouched.
        assert original.id == "task-1"
        name, args, kwargs = ctx.raw.calls[-1]
        assert name == "replay_task"
        assert args == ("hive-X", "task-1")
        assert kwargs["override_payload"] is None


class TestRead:
    def test_trace_calls_raw(self):
        ctx = ContextStub()
        ctx.raw.returns["get_task_trace"] = {"steps": [{"id": "s1"}]}
        t = Task(_sample_task(), ctx)
        assert t.trace() == {"steps": [{"id": "s1"}]}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "get_task_trace"
        assert args == ("hive-X", "task-1")

    def test_refresh_merges_get_task_response(self):
        ctx = ContextStub()
        ctx.raw.returns["get_task"] = {
            "id": "task-1",
            "status": "completed",
            "result": {"ok": True},
        }
        t = Task(_sample_task(), ctx)
        result = t.refresh()
        assert result is t
        assert t.status == "completed"
        assert t.result == {"ok": True}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "get_task"
        assert args == ("hive-X", "task-1")

    def test_refresh_raises_on_non_dict_response(self):
        ctx = ContextStub()
        ctx.raw.returns["get_task"] = "not-a-dict"
        t = Task(_sample_task(), ctx)
        with pytest.raises(ValueError, match="expected dict"):
            t.refresh()
        # State should remain untouched.
        assert t.status == "pending"
