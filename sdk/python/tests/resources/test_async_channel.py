"""Tests for :class:`superpos_sdk.resources.async_resources.AsyncChannel`."""

from __future__ import annotations

from typing import Any

from superpos_sdk.resources.async_resources import AsyncChannel


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


def _sample_channel() -> dict[str, Any]:
    return {
        "id": "chan-1",
        "title": "Release v2",
        "channel_type": "discussion",
        "status": "open",
        "topic": "Pick a date",
        "participants": [{"participant_id": "agent-1", "role": "initiator"}],
        "resolution_policy": {"type": "manual"},
        "created_at": "2026-04-19T10:00:00Z",
        "updated_at": "2026-04-19T10:05:00Z",
    }


class TestConstruction:
    def test_attribute_access(self):
        ctx = AsyncContextStub()
        ch = AsyncChannel(_sample_channel(), ctx)
        assert ch.id == "chan-1"
        assert ch.title == "Release v2"
        assert ch.channel_type == "discussion"
        assert ch.status == "open"
        assert ch.topic == "Pick a date"
        assert ch.resolution_policy == {"type": "manual"}

    def test_to_dict_shallow_copy(self):
        ctx = AsyncContextStub()
        ch = AsyncChannel(_sample_channel(), ctx)
        d = ch.to_dict()
        d["title"] = "MUTATED"
        assert ch.title == "Release v2"

    def test_repr(self):
        ctx = AsyncContextStub()
        ch = AsyncChannel(_sample_channel(), ctx)
        r = repr(ch)
        assert "chan-1" in r
        assert "Release v2" in r
        assert "AsyncChannel" in r

    def test_equality_by_id(self):
        ctx = AsyncContextStub()
        a = AsyncChannel({"id": "x"}, ctx)
        b = AsyncChannel({"id": "x", "title": "diff"}, ctx)
        c = AsyncChannel({"id": "y"}, ctx)
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


class TestRead:
    async def test_refresh_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["get_channel"] = {"id": "chan-1", "status": "resolved"}
        ch = AsyncChannel(_sample_channel(), ctx)
        result = await ch.refresh()
        assert result is ch
        assert ch.status == "resolved"

    async def test_messages_forwards(self):
        ctx = AsyncContextStub()
        ctx.returns["list_messages"] = [{"id": "m1"}]
        ch = AsyncChannel(_sample_channel(), ctx)
        msgs = await ch.messages(per_page=25)
        assert msgs == [{"id": "m1"}]
        assert (
            "list_messages",
            ("chan-1",),
            {
                "since": None,
                "after_id": None,
                "page": None,
                "per_page": 25,
            },
        ) in ctx.calls

    async def test_participants_refreshes(self):
        ctx = AsyncContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = AsyncChannel({"id": "chan-1"}, ctx)
        parts = await ch.participants()
        assert parts == [{"participant_id": "agent-1", "role": "initiator"}]


class TestReadSummary:
    async def test_summary_calls_raw_channel_summary(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["channel_summary"] = {"unread_count": 3}
        ch = AsyncChannel(_sample_channel(), ctx)
        assert await ch.summary() == {"unread_count": 3}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "channel_summary"
        assert args == ("hive-X", "chan-1")


class TestWriteMessages:
    async def test_post_refreshes(self):
        ctx = AsyncContextStub()
        ctx.returns["post_message"] = {"id": "m1"}
        ctx.returns["get_channel"] = {"id": "chan-1", "updated_at": "2026-04-19T12:00:00Z"}
        ch = AsyncChannel(_sample_channel(), ctx)
        result = await ch.post("hello")
        assert result == {"id": "m1"}
        assert ch.updated_at == "2026-04-19T12:00:00Z"
        names = [c[0] for c in ctx.calls]
        assert names == ["post_message", "get_channel"]


class TestMarkRead:
    async def test_mark_read_calls_raw(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["mark_channel_read"] = {"last_read_at": "T"}
        ch = AsyncChannel(_sample_channel(), ctx)
        assert await ch.mark_read() == {"last_read_at": "T"}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "mark_channel_read"
        assert args == ("hive-X", "chan-1")


class TestWriteParticipants:
    async def test_invite_default_agent_type(self):
        ctx = AsyncContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = AsyncChannel(_sample_channel(), ctx)
        await ch.invite("ag-2", role="decider")
        call = next(c for c in ctx.calls if c[0] == "add_participant")
        # signature: ctx.add_participant(
        #     channel_id, participant_type, participant_id, *, role=..., mention_policy=...
        # )
        assert call[1] == ("chan-1", "agent", "ag-2")
        assert call[2] == {"role": "decider", "mention_policy": None}

    async def test_remove_participant_goes_to_raw(self):
        ctx = AsyncContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = AsyncChannel(_sample_channel(), ctx)
        await ch.remove_participant("ag-2")
        assert ("remove_channel_participant", ("hive-X", "chan-1", "ag-2"), {}) in ctx.raw.calls


class TestWriteLifecycle:
    async def test_resolve_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["resolve_channel"] = {"id": "chan-1", "status": "resolved"}
        ch = AsyncChannel(_sample_channel(), ctx)
        await ch.resolve(outcome="shipped")
        assert ch.status == "resolved"

    async def test_archive_merges(self):
        ctx = AsyncContextStub()
        ctx.returns["archive_channel"] = {"id": "chan-1", "status": "archived"}
        ch = AsyncChannel(_sample_channel(), ctx)
        await ch.archive()
        assert ch.status == "archived"

    async def test_reopen_uses_raw(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["reopen_channel"] = {"id": "chan-1", "status": "open"}
        ch = AsyncChannel({**_sample_channel(), "status": "resolved"}, ctx)
        await ch.reopen()
        assert ch.status == "open"

    async def test_materialize_calls_raw(self):
        ctx = AsyncContextStub()
        ctx.raw.returns["materialize_channel"] = [{"id": "t1"}]
        ch = AsyncChannel(_sample_channel(), ctx)
        result = await ch.materialize([{"type": "ship_release"}])
        assert result == [{"id": "t1"}]
        name, args, _ = ctx.raw.calls[-1]
        assert name == "materialize_channel"
        assert args == ("hive-X", "chan-1", [{"type": "ship_release"}])
