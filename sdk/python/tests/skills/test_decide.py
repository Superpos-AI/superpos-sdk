"""Tests for :func:`superpos_sdk.skills.decide` (sync)."""

from __future__ import annotations

from typing import Any

from superpos_sdk.resources import Channel
from superpos_sdk.skills import decide


class SyncCtxStub:
    def __init__(self) -> None:
        self._hive_id = "hive-X"
        self.created: dict[str, Any] | None = None
        self.posted: list[dict[str, Any]] = []
        self._last: dict[str, Any] = {}

    def _require_hive(self) -> str:
        return self._hive_id

    def create_channel_obj(self, **kwargs: Any) -> Channel:
        self.created = kwargs
        self._last = {
            "id": "ch-dec",
            "title": kwargs["title"],
            "channel_type": kwargs["channel_type"],
            "status": "open",
        }
        return Channel(self._last, self)

    def post_message(self, channel_id, body, **kwargs):
        self.posted.append({"channel_id": channel_id, "body": body, **kwargs})
        return {"id": "msg-1"}

    def get_channel(self, channel_id):
        return dict(self._last)


class TestDecide:
    def test_default_policy_resolves_to_agent_decision(self):
        ctx = SyncCtxStub()
        decide(ctx, "Do we ship?", "Should we ship on Friday?", ["yes", "no"])
        assert ctx.created["resolution_policy"]["type"] == "agent_decision"
        assert ctx.created["channel_type"] == "discussion"
        assert ctx.created["topic"] == "Should we ship on Friday?"

    def test_proposal_message_posted_with_options(self):
        ctx = SyncCtxStub()
        decide(ctx, "Do we ship?", "Ship?", ["yes", "no", "maybe"])
        assert len(ctx.posted) == 1
        msg = ctx.posted[0]
        assert msg["message_type"] == "proposal"
        assert msg["body"] == "Ship?"
        assert msg["metadata"]["options"] == [
            {"key": "yes", "label": "yes"},
            {"key": "no", "label": "no"},
            {"key": "maybe", "label": "maybe"},
        ]

    def test_dict_options_pass_through(self):
        ctx = SyncCtxStub()
        decide(
            ctx,
            "Which day?",
            "Pick a day",
            [
                {"key": "fri", "label": "Friday"},
                {"key": "mon", "label": "Monday"},
            ],
        )
        msg = ctx.posted[0]
        assert msg["metadata"]["options"] == [
            {"key": "fri", "label": "Friday"},
            {"key": "mon", "label": "Monday"},
        ]

    def test_consensus_policy_with_threshold(self):
        ctx = SyncCtxStub()
        decide(ctx, "Q", "q", ["a", "b"], policy="consensus", threshold=0.75)
        policy = ctx.created["resolution_policy"]
        assert policy["type"] == "consensus"
        assert policy["threshold"] == 0.75
        # Original preset should remain intact (we deep-copy).
        from superpos_sdk.constants import RESOLUTION_POLICIES  # noqa: PLC0415

        assert RESOLUTION_POLICIES["consensus"]["threshold"] == 0.66

    def test_deadline_converts_to_stale_after_minutes_rounded_up(self):
        ctx = SyncCtxStub()
        decide(ctx, "Q", "q", ["a"], deadline_seconds=125)
        # 125s -> 3 minutes (round up)
        assert ctx.created["stale_after"] == 3

    def test_unknown_policy_label_passes_through(self):
        ctx = SyncCtxStub()
        decide(ctx, "Q", "q", ["a"], policy="custom-xyz", threshold=0.5)
        assert ctx.created["resolution_policy"] == {"type": "custom-xyz", "threshold": 0.5}
