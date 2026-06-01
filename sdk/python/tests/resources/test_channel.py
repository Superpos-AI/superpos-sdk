"""Tests for :class:`superpos_sdk.resources.Channel`."""

from __future__ import annotations

from typing import Any

import pytest

from superpos_sdk.resources import Channel


class RawStub:
    """Stub for ``ctx.raw`` — records attribute calls and returns fixed values."""

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
    """Stub standing in for :class:`AgentContext`.

    Records calls on both its own surface and on ``.raw``.
    """

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
        # Limit noise: only proxy names we actually care about on the
        # AgentContext surface; other attribute lookups (``_require_hive``,
        # ``_hive_id``, etc.) take the real attribute path.
        return self._make(name)


# ---------------------------------------------------------------------
# Construction & attributes
# ---------------------------------------------------------------------


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
        ctx = ContextStub()
        # participants() does a refresh, so stub get_channel to return sample data
        ctx.returns["get_channel"] = _sample_channel()
        ch = Channel(_sample_channel(), ctx)
        assert ch.id == "chan-1"
        assert ch.title == "Release v2"
        assert ch.channel_type == "discussion"
        assert ch.status == "open"
        assert ch.topic == "Pick a date"
        assert ch.participants() == [{"participant_id": "agent-1", "role": "initiator"}]
        assert ch.resolution_policy == {"type": "manual"}
        assert ch.created_at == "2026-04-19T10:00:00Z"
        assert ch.updated_at == "2026-04-19T10:05:00Z"

    def test_missing_optional_fields_tolerated(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = {"id": "chan-only"}
        ch = Channel({"id": "chan-only"}, ctx)
        assert ch.id == "chan-only"
        assert ch.title is None
        assert ch.channel_type is None
        assert ch.participants() == []

    def test_to_dict_returns_shallow_copy(self):
        ctx = ContextStub()
        ch = Channel(_sample_channel(), ctx)
        d = ch.to_dict()
        d["title"] = "MUTATED"
        assert ch.title == "Release v2"

    def test_repr(self):
        ctx = ContextStub()
        ch = Channel(_sample_channel(), ctx)
        r = repr(ch)
        assert "chan-1" in r
        assert "Release v2" in r

    def test_equality_and_hash_by_id(self):
        ctx = ContextStub()
        a = Channel({"id": "chan-1", "title": "A"}, ctx)
        b = Channel({"id": "chan-1", "title": "B"}, ctx)
        c = Channel({"id": "chan-2", "title": "A"}, ctx)
        assert a == b
        assert a != c
        assert hash(a) == hash(b)
        assert {a, b, c} == {a, c}

    def test_equality_vs_non_channel(self):
        ctx = ContextStub()
        ch = Channel({"id": "x"}, ctx)
        assert ch != "x"


# ---------------------------------------------------------------------
# Read methods
# ---------------------------------------------------------------------


class TestRead:
    def test_refresh_merges_updated_dict(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = {
            "id": "chan-1",
            "title": "Release v2",
            "status": "deliberating",
        }
        ch = Channel(_sample_channel(), ctx)
        assert ch.status == "open"

        result = ch.refresh()
        assert result is ch  # fluent
        assert ("get_channel", ("chan-1",), {}) in ctx.calls
        assert ch.status == "deliberating"

    def test_messages_threads_channel_id(self):
        ctx = ContextStub()
        ctx.returns["list_messages"] = [{"id": "m1"}]
        ch = Channel(_sample_channel(), ctx)
        result = ch.messages(per_page=50)
        assert result == [{"id": "m1"}]
        name, args, kwargs = ctx.calls[-1]
        assert name == "list_messages"
        assert args == ("chan-1",)
        assert kwargs["per_page"] == 50

    def test_summary_calls_raw_channel_summary(self):
        ctx = ContextStub()
        ctx.raw.returns["channel_summary"] = {"unread_count": 3}
        ch = Channel(_sample_channel(), ctx)
        assert ch.summary() == {"unread_count": 3}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "channel_summary"
        assert args == ("hive-X", "chan-1")

    def test_participants_refreshes_and_returns(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = {
            "id": "chan-1",
            "participants": [{"participant_id": "agent-2", "role": "decider"}],
        }
        ch = Channel(_sample_channel(), ctx)
        ps = ch.participants()
        assert ps == [{"participant_id": "agent-2", "role": "decider"}]


# ---------------------------------------------------------------------
# Write methods
# ---------------------------------------------------------------------


class TestWrite:
    def test_post_threads_channel_id(self):
        ctx = ContextStub()
        # Stub get_channel for the refresh() call after post
        ctx.returns["get_channel"] = {
            **_sample_channel(),
            "updated_at": "2026-04-19T10:10:00Z",
        }
        ch = Channel(_sample_channel(), ctx)
        ch.post("hello", message_type="proposal", mentions=["agent-2"])
        # The first call is post_message, the second is get_channel (refresh)
        name, args, kwargs = ctx.calls[0]
        assert name == "post_message"
        assert args == ("chan-1", "hello")
        assert kwargs["message_type"] == "proposal"
        assert kwargs["mentions"] == ["agent-2"]

    def test_post_refreshes_local_state(self):
        """FR-6: post() must refresh _data after a successful write."""
        ctx = ContextStub()
        ctx.returns["post_message"] = {"id": "msg-1", "body": "hello"}
        ctx.returns["get_channel"] = {
            **_sample_channel(),
            "updated_at": "2026-04-19T10:10:00Z",
        }
        ch = Channel(_sample_channel(), ctx)
        assert ch.updated_at == "2026-04-19T10:05:00Z"  # original

        result = ch.post("hello")
        # Should return the message dict (not the channel dict)
        assert result == {"id": "msg-1", "body": "hello"}
        # Local state must reflect the refreshed channel
        assert ch.updated_at == "2026-04-19T10:10:00Z"
        # refresh() must have called get_channel
        call_names = [c[0] for c in ctx.calls]
        assert "post_message" in call_names
        assert "get_channel" in call_names

    def test_mark_read_calls_raw(self):
        ctx = ContextStub()
        ctx.raw.returns["mark_channel_read"] = {"last_read_at": "T"}
        ch = Channel(_sample_channel(), ctx)
        assert ch.mark_read() == {"last_read_at": "T"}
        name, args, _ = ctx.raw.calls[-1]
        assert name == "mark_channel_read"
        assert args == ("hive-X", "chan-1")

    def test_invite_defaults_to_agent_type(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = Channel(_sample_channel(), ctx)
        ch.invite("agent-42", role="decider")
        name, args, kwargs = ctx.calls[0]
        assert name == "add_participant"
        assert args == ("chan-1", "agent", "agent-42")
        assert kwargs["role"] == "decider"

    def test_invite_user_participant(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = Channel(_sample_channel(), ctx)
        ch.invite("user-1", participant_type="user")
        name, args, _ = ctx.calls[0]
        assert name == "add_participant"
        assert args == ("chan-1", "user", "user-1")

    def test_invite_refreshes_local_state(self):
        """FR-6: invite() must refresh _data after a successful write."""
        ctx = ContextStub()
        ctx.returns["add_participant"] = {"participant_id": "agent-42", "role": "decider"}
        ctx.returns["get_channel"] = {
            **_sample_channel(),
            "participants": [
                {"participant_id": "agent-1", "role": "initiator"},
                {"participant_id": "agent-42", "role": "decider"},
            ],
            "updated_at": "2026-04-19T10:10:00Z",
        }
        ch = Channel(_sample_channel(), ctx)
        assert ch.updated_at == "2026-04-19T10:05:00Z"

        result = ch.invite("agent-42", role="decider")
        # Should return the participant dict (not the channel dict)
        assert result == {"participant_id": "agent-42", "role": "decider"}
        # Local state must reflect the refreshed channel
        assert ch.updated_at == "2026-04-19T10:10:00Z"
        assert len(ch._data["participants"]) == 2
        # refresh() must have called get_channel
        call_names = [c[0] for c in ctx.calls]
        assert "add_participant" in call_names
        assert "get_channel" in call_names

    def test_remove_participant_calls_raw(self):
        ctx = ContextStub()
        ctx.returns["get_channel"] = _sample_channel()
        ch = Channel(_sample_channel(), ctx)
        ch.remove_participant("agent-42")
        name, args, _ = ctx.raw.calls[-1]
        assert name == "remove_channel_participant"
        assert args == ("hive-X", "chan-1", "agent-42")

    def test_remove_participant_refreshes_local_state(self):
        """FR-6: remove_participant() must refresh _data after a successful write."""
        ctx = ContextStub()
        ctx.returns["get_channel"] = {
            **_sample_channel(),
            "participants": [],
            "updated_at": "2026-04-19T10:10:00Z",
        }
        ch = Channel(_sample_channel(), ctx)
        assert ch.updated_at == "2026-04-19T10:05:00Z"
        assert len(ch._data["participants"]) == 1

        ch.remove_participant("agent-1")
        # Local state must reflect the refreshed channel
        assert ch.updated_at == "2026-04-19T10:10:00Z"
        assert ch._data["participants"] == []
        # refresh() must have called get_channel
        call_names = [c[0] for c in ctx.calls]
        assert "get_channel" in call_names

    def test_resolve_merges_response(self):
        ctx = ContextStub()
        ctx.returns["resolve_channel"] = {
            "id": "chan-1",
            "status": "resolved",
            "resolved_at": "2026-04-19T11:00:00Z",
        }
        ch = Channel(_sample_channel(), ctx)
        result = ch.resolve("shipped")
        assert result is ch
        assert ch.status == "resolved"
        assert ch.to_dict()["resolved_at"] == "2026-04-19T11:00:00Z"
        name, args, kwargs = ctx.calls[-1]
        assert name == "resolve_channel"
        assert args == ("chan-1",)
        assert kwargs["outcome"] == "shipped"

    def test_reopen_merges_response(self):
        ctx = ContextStub()
        ctx.raw.returns["reopen_channel"] = {"id": "chan-1", "status": "open"}
        ch = Channel({**_sample_channel(), "status": "resolved"}, ctx)
        ch.reopen()
        assert ch.status == "open"
        name, args, _ = ctx.raw.calls[-1]
        assert name == "reopen_channel"
        assert args == ("hive-X", "chan-1")

    def test_archive_merges_response(self):
        ctx = ContextStub()
        ctx.returns["archive_channel"] = {"id": "chan-1", "status": "archived"}
        ch = Channel(_sample_channel(), ctx)
        ch.archive()
        assert ch.status == "archived"

    def test_materialize_calls_raw(self):
        ctx = ContextStub()
        ctx.raw.returns["materialize_channel"] = [{"id": "t1"}]
        ch = Channel(_sample_channel(), ctx)
        result = ch.materialize([{"type": "ship_release"}])
        assert result == [{"id": "t1"}]
        name, args, _ = ctx.raw.calls[-1]
        assert name == "materialize_channel"
        assert args == ("hive-X", "chan-1", [{"type": "ship_release"}])


# ---------------------------------------------------------------------
# Refresh after write is explicit via resolve/archive/reopen tests above.
# Also guard against the "missing hive" path.
# ---------------------------------------------------------------------


class TestHiveBinding:
    def test_raw_dependent_methods_require_hive(self):
        ctx = ContextStub(hive_id=None)
        ch = Channel(_sample_channel(), ctx)
        with pytest.raises(ValueError, match="hive_id"):
            ch.summary()
