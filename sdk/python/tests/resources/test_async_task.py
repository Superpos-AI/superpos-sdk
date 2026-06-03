"""Tests for :class:`superpos_sdk.resources.async_resources.AsyncTask`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources.async_resources import AsyncTask


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
    def test_attributes(self):
        ctx = AsyncContextStub()
        t = AsyncTask(_sample_task(), ctx)
        assert t.id == "task-1"
        assert t.type == "summarize"
        assert t.status == "pending"
        assert t.payload == {"text": "hi"}
        assert t.priority == 2

    def test_type_fallback(self):
        ctx = AsyncContextStub()
        t = AsyncTask({"id": "t", "task_type": "legacy"}, ctx)
        assert t.type == "legacy"

    def test_repr_and_equality(self):
        ctx = AsyncContextStub()
        a = AsyncTask(_sample_task(), ctx)
        b = AsyncTask({"id": "task-1", "status": "completed"}, ctx)
        c = AsyncTask({"id": "task-2"}, ctx)
        assert a == b
        assert a != c
        r = repr(a)
        assert "task-1" in r
        assert "AsyncTask" in r


class TestWrites:
    async def test_claim_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["claim_task"] = {"id": "task-1", "status": "in_progress"}
        t = AsyncTask(_sample_task(), ctx)
        result = await t.claim()
        assert result is t
        assert t.status == "in_progress"

    async def test_update_progress_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["update_progress"] = {"id": "task-1", "progress": 50}
        t = AsyncTask(_sample_task(), ctx)
        await t.update_progress(50, status_message="halfway")
        assert t.progress == 50

    async def test_complete_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["complete_task"] = {"id": "task-1", "status": "completed", "result": {"out": 1}}
        t = AsyncTask(_sample_task(), ctx)
        await t.complete(result={"out": 1})
        assert t.status == "completed"
        assert t.result == {"out": 1}

    async def test_fail_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["fail_task"] = {"id": "task-1", "status": "failed"}
        t = AsyncTask(_sample_task(), ctx)
        await t.fail(error={"message": "boom"})
        assert t.status == "failed"

    async def test_replay_returns_new_task(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["replay_task"] = {"id": "task-2", "status": "pending"}
        t = AsyncTask(_sample_task(), ctx)
        replayed = await t.replay()
        assert replayed is not t
        assert replayed.id == "task-2"


class TestRefresh:
    async def test_refresh_merges_get_task_response(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["get_task"] = {
            "id": "task-1",
            "status": "completed",
            "progress": 100,
            "result": {"ok": True},
        }
        t = AsyncTask(_sample_task(), ctx)
        result = await t.refresh()
        assert result is t
        assert t.status == "completed"
        assert t.progress == 100
        assert t.result == {"ok": True}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "get_task"
        assert args == ("hive-X", "task-1")

    async def test_refresh_invalid_raises(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["get_task"] = "not-a-dict"
        t = AsyncTask(_sample_task(), ctx)
        with pytest.raises(ValueError, match="expected dict"):
            await t.refresh()
        assert t.status == "pending"
