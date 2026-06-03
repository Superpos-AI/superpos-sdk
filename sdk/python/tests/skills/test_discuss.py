"""Tests for :func:`superpos_sdk.skills.discuss` (sync)."""

from __future__ import annotations

from typing import Any

from superpos_sdk.resources import Channel
from superpos_sdk.skills import discuss
from superpos_sdk.skills.sync_skills import discuss as sync_discuss


class SyncCtxStub:
    """Sync stub implementing just what the ``discuss`` skill needs."""

    def __init__(self, hive_id: str = "hive-X") -> None:
        self._hive_id = hive_id
        self.created: dict[str, Any] | None = None
        self.posted: list[dict[str, Any]] = []
        self._last_channel: dict[str, Any] = {}

    def _require_hive(self) -> str:
        return self._hive_id

    def create_channel_obj(self, **kwargs: Any) -> Channel:
        self.created = kwargs
        self._last_channel = {
            "id": "ch-99",
            "title": kwargs["title"],
            "channel_type": kwargs["channel_type"],
            "topic": kwargs.get("topic"),
            "status": "open",
        }
        return Channel(self._last_channel, self)

    def post_message(
        self,
        channel_id: str,
        body: str,
        *,
        message_type: str = "discussion",
        mentions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        self.posted.append(
            {
                "channel_id": channel_id,
                "body": body,
                "message_type": message_type,
                "metadata": metadata,
            }
        )
        return {"id": f"msg-{len(self.posted)}"}

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        return dict(self._last_channel)


class TestDiscussSkill:
    def test_creates_channel_only_when_no_message(self):
        ctx = SyncCtxStub()
        ch = discuss(ctx, "Release plan", topic="Pick a date")
        assert isinstance(ch, Channel)
        assert ctx.created == {
            "title": "Release plan",
            "channel_type": "discussion",
            "topic": "Pick a date",
            "participants": None,
        }
        assert ctx.posted == []

    def test_posts_opener_when_initial_message_given(self):
        ctx = SyncCtxStub()
        discuss(ctx, "Release plan", initial_message="Kick things off")
        assert len(ctx.posted) == 1
        assert ctx.posted[0]["body"] == "Kick things off"
        assert ctx.posted[0]["channel_id"] == "ch-99"

    def test_custom_channel_type(self):
        ctx = SyncCtxStub()
        discuss(ctx, "Post-mortem", channel_type="incident")
        assert ctx.created["channel_type"] == "incident"

    def test_sync_module_function_matches_facade(self):
        ctx = SyncCtxStub()
        ctx2 = SyncCtxStub()
        ch1 = discuss(ctx, "A")
        ch2 = sync_discuss(ctx2, "A")
        assert isinstance(ch1, Channel)
        assert isinstance(ch2, Channel)
