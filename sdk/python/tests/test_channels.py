"""Tests for channel SDK methods."""

from __future__ import annotations

import json
import re

from superpos_sdk import SuperposClient

from .conftest import BASE_URL, HIVE_ID, TOKEN, envelope

CHANNEL_ID = "01HXYZ00000000000000000010"
MESSAGE_ID = "01HXYZ00000000000000000011"
AGENT_ID = "01HXYZ00000000000000000002"


def _channel_data(**overrides):
    base = {
        "id": CHANNEL_ID,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "title": "Test Channel",
        "topic": "Testing",
        "channel_type": "discussion",
        "urgency": "normal",
        "status": "open",
        "resolution_policy": None,
        "resolution_state": None,
        "stage_progress": None,
        "linked_refs": None,
        "on_resolve": None,
        "resolution": None,
        "resolved_by": None,
        "resolved_at": None,
        "stale_after": None,
        "message_count": 0,
        "last_message_at": None,
        "summary": None,
        "created_by_type": "agent",
        "created_by_id": AGENT_ID,
        "created_at": "2026-04-15T10:00:00Z",
        "updated_at": "2026-04-15T10:00:00Z",
    }
    base.update(overrides)
    return base


def _channel_detail(**overrides):
    data = _channel_data(**overrides)
    if "participants" not in data:
        data["participants"] = [
            {
                "participant_type": "agent",
                "participant_id": AGENT_ID,
                "role": "initiator",
                "mention_policy": "all",
                "joined_at": "2026-04-15T10:00:00Z",
            },
        ]
    return data


def _message_data(**overrides):
    base = {
        "id": MESSAGE_ID,
        "channel_id": CHANNEL_ID,
        "author_type": "agent",
        "author_id": AGENT_ID,
        "message_type": "discussion",
        "content": "Hello world",
        "metadata": None,
        "reply_to": None,
        "mentions": None,
        "edited_at": None,
        "created_at": "2026-04-15T10:00:00Z",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# Channel CRUD
# ------------------------------------------------------------------


class TestListChannels:
    def test_list_channels_basic(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels",
            json=envelope([_channel_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channels = c.list_channels(HIVE_ID)
        assert len(channels) == 1
        assert channels[0]["id"] == CHANNEL_ID

    def test_list_channels_with_filters(self, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(rf"{re.escape(BASE_URL)}/api/v1/hives/{HIVE_ID}/channels\?.*"),
            json=envelope([_channel_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_channels(HIVE_ID, status="open", channel_type="discussion")
        request = httpx_mock.get_request()
        assert "status=open" in str(request.url)
        assert "channel_type=discussion" in str(request.url)


class TestCreateChannel:
    def test_create_channel_minimal(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels",
            status_code=201,
            json=envelope(_channel_detail()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.create_channel(HIVE_ID, title="Test Channel", channel_type="discussion")
        assert channel["id"] == CHANNEL_ID
        body = json.loads(httpx_mock.get_request().content)
        assert body["title"] == "Test Channel"
        assert body["channel_type"] == "discussion"

    def test_create_channel_full(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels",
            status_code=201,
            json=envelope(_channel_detail()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.create_channel(
                HIVE_ID,
                title="Full Channel",
                channel_type="discussion",
                topic="Testing everything",
                participants=[{"agent_id": AGENT_ID, "role": "initiator"}],
                resolution_policy={"method": "vote", "threshold": 0.5},
                stale_after=60,
                initial_message={
                    "content": "Let's discuss",
                    "message_type": "discussion",
                },
                auto_invite={"capabilities": ["code-review"]},
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["title"] == "Full Channel"
        assert body["topic"] == "Testing everything"
        assert body["participants"] == [{"agent_id": AGENT_ID, "role": "initiator"}]
        assert body["resolution_policy"]["method"] == "vote"
        assert body["stale_after"] == 60
        assert body["initial_message"]["content"] == "Let's discuss"
        assert body["auto_invite"]["capabilities"] == ["code-review"]


class TestGetChannel:
    def test_get_channel(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}",
            json=envelope(_channel_detail()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.get_channel(HIVE_ID, CHANNEL_ID)
        assert channel["id"] == CHANNEL_ID
        assert channel["participants"][0]["role"] == "initiator"


class TestUpdateChannel:
    def test_update_channel(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}",
            json=envelope(_channel_detail(title="Updated Title")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.update_channel(HIVE_ID, CHANNEL_ID, title="Updated Title")
        assert channel["title"] == "Updated Title"
        body = json.loads(httpx_mock.get_request().content)
        assert body["title"] == "Updated Title"

    def test_update_channel_partial(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}",
            json=envelope(_channel_detail(stale_after=120)),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.update_channel(HIVE_ID, CHANNEL_ID, stale_after=120)
        body = json.loads(httpx_mock.get_request().content)
        assert body["stale_after"] == 120
        assert "title" not in body


class TestArchiveChannel:
    def test_archive_channel(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}",
            json=envelope(_channel_data(status="archived")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.archive_channel(HIVE_ID, CHANNEL_ID)
        assert channel["status"] == "archived"


# ------------------------------------------------------------------
# Channel messages
# ------------------------------------------------------------------


class TestListChannelMessages:
    def test_list_messages_basic(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            json=envelope([_message_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            messages = c.list_channel_messages(HIVE_ID, CHANNEL_ID)
        assert len(messages) == 1
        assert messages[0]["id"] == MESSAGE_ID

    def test_list_messages_with_since(self, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(
                rf"{re.escape(BASE_URL)}/api/v1/hives/{HIVE_ID}"
                rf"/channels/{CHANNEL_ID}/messages\?.*"
            ),
            json=envelope([_message_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_channel_messages(HIVE_ID, CHANNEL_ID, since="2026-04-15T09:00:00Z")
        request = httpx_mock.get_request()
        assert "since=2026-04-15" in str(request.url)

    def test_list_messages_with_after_id(self, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(
                rf"{re.escape(BASE_URL)}/api/v1/hives/{HIVE_ID}"
                rf"/channels/{CHANNEL_ID}/messages\?.*"
            ),
            json=envelope([_message_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.list_channel_messages(HIVE_ID, CHANNEL_ID, after_id="prev-msg-id")
        request = httpx_mock.get_request()
        assert "after_id=prev-msg-id" in str(request.url)


class TestPostChannelMessage:
    def test_post_discussion_message(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            status_code=201,
            json=envelope(_message_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            msg = c.post_channel_message(HIVE_ID, CHANNEL_ID, "Hello world")
        assert msg["id"] == MESSAGE_ID
        body = json.loads(httpx_mock.get_request().content)
        assert body["content"] == "Hello world"
        assert body["message_type"] == "discussion"

    def test_post_message_with_mentions(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            status_code=201,
            json=envelope(_message_data(mentions=[AGENT_ID])),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.post_channel_message(HIVE_ID, CHANNEL_ID, "Hey @agent", mentions=[AGENT_ID])
        body = json.loads(httpx_mock.get_request().content)
        assert body["mentions"] == [AGENT_ID]

    def test_post_message_with_metadata_and_reply(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            status_code=201,
            json=envelope(_message_data(message_type="context")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.post_channel_message(
                HIVE_ID,
                CHANNEL_ID,
                "Context info",
                message_type="context",
                metadata={"refs": ["ref-1"]},
                reply_to="prev-msg-id",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["message_type"] == "context"
        assert body["metadata"]["refs"] == ["ref-1"]
        assert body["reply_to"] == "prev-msg-id"


class TestEditChannelMessage:
    def test_edit_message(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}",
            json=envelope(_message_data(content="Updated content")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            msg = c.edit_channel_message(HIVE_ID, CHANNEL_ID, MESSAGE_ID, "Updated content")
        assert msg["content"] == "Updated content"
        body = json.loads(httpx_mock.get_request().content)
        assert body["content"] == "Updated content"


# ------------------------------------------------------------------
# Channel participants
# ------------------------------------------------------------------


class TestListChannelParticipants:
    def test_list_participants(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}",
            json=envelope(_channel_detail()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.list_channel_participants(HIVE_ID, CHANNEL_ID)
        assert len(channel["participants"]) == 1


class TestAddChannelParticipant:
    def test_add_participant(self, httpx_mock):
        participant = {
            "participant_type": "agent",
            "participant_id": AGENT_ID,
            "role": "contributor",
            "mention_policy": "all",
            "joined_at": "2026-04-15T10:00:00Z",
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/participants",
            status_code=201,
            json=envelope(participant),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.add_channel_participant(
                HIVE_ID,
                CHANNEL_ID,
                "agent",
                AGENT_ID,
                role="contributor",
                mention_policy="all",
            )
        assert result["participant_id"] == AGENT_ID
        body = json.loads(httpx_mock.get_request().content)
        assert body["participant_type"] == "agent"
        assert body["participant_id"] == AGENT_ID
        assert body["role"] == "contributor"
        assert body["mention_policy"] == "all"

    def test_add_participant_minimal(self, httpx_mock):
        participant = {
            "participant_type": "agent",
            "participant_id": AGENT_ID,
            "role": "contributor",
            "mention_policy": "all",
            "joined_at": "2026-04-15T10:00:00Z",
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/participants",
            status_code=201,
            json=envelope(participant),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.add_channel_participant(HIVE_ID, CHANNEL_ID, "agent", AGENT_ID)
        body = json.loads(httpx_mock.get_request().content)
        assert body["participant_type"] == "agent"
        assert body["participant_id"] == AGENT_ID
        assert body["role"] == "contributor"
        assert "mention_policy" not in body


class TestRemoveChannelParticipant:
    def test_remove_participant(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/participants/{AGENT_ID}",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.remove_channel_participant(HIVE_ID, CHANNEL_ID, AGENT_ID)
        assert result is None


# ------------------------------------------------------------------
# Voting
# ------------------------------------------------------------------


class TestVoteOnProposal:
    def test_vote_approve(self, httpx_mock):
        vote_msg = _message_data(
            message_type="vote",
            metadata={"vote": "approve", "proposal_ref": "prop-id"},
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            status_code=201,
            json=envelope(vote_msg),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            msg = c.vote_on_proposal(HIVE_ID, CHANNEL_ID, "prop-id", "approve")
        assert msg["message_type"] == "vote"
        body = json.loads(httpx_mock.get_request().content)
        assert body["message_type"] == "vote"
        assert body["metadata"]["vote"] == "approve"
        assert body["metadata"]["proposal_ref"] == "prop-id"

    def test_vote_with_body_and_option_key(self, httpx_mock):
        vote_msg = _message_data(
            message_type="vote",
            metadata={
                "vote": "reject",
                "proposal_ref": "prop-id",
                "option_key": "opt-a",
            },
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages",
            status_code=201,
            json=envelope(vote_msg),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.vote_on_proposal(
                HIVE_ID,
                CHANNEL_ID,
                "prop-id",
                "reject",
                body="I disagree because...",
                option_key="opt-a",
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["content"] == "I disagree because..."
        assert body["metadata"]["option_key"] == "opt-a"


class TestGetProposalVotes:
    def test_get_votes(self, httpx_mock):
        tally = {
            "proposal_id": MESSAGE_ID,
            "total_votes": 3,
            "tally": {"approve": 2, "reject": 1, "abstain": 0, "block": 0},
            "per_option": {},
            "voters": [
                {
                    "voter_type": "agent",
                    "voter_id": AGENT_ID,
                    "vote": "approve",
                    "option_key": None,
                    "voted_at": "2026-04-15T10:05:00Z",
                }
            ],
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}/votes",
            json=envelope(tally),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.get_proposal_votes(HIVE_ID, CHANNEL_ID, MESSAGE_ID)
        assert result["total_votes"] == 3
        assert result["tally"]["approve"] == 2


# ------------------------------------------------------------------
# Channel summary (TASK-248)
# ------------------------------------------------------------------


class TestChannelSummary:
    def test_channel_summary(self, httpx_mock):
        summary = {
            "channel_id": CHANNEL_ID,
            "status": "open",
            "unread_count": 5,
            "mentioned": True,
            "needs_vote": False,
            "last_message_at": "2026-04-15T12:00:00Z",
            "last_read_at": "2026-04-15T11:00:00Z",
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/summary",
            json=envelope(summary),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.channel_summary(HIVE_ID, CHANNEL_ID)
        assert result["unread_count"] == 5
        assert result["mentioned"] is True


class TestMarkChannelRead:
    def test_mark_read(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/read",
            json=envelope(
                {
                    "channel_id": CHANNEL_ID,
                    "last_read_at": "2026-04-15T12:00:00Z",
                }
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.mark_channel_read(HIVE_ID, CHANNEL_ID)
        assert result["channel_id"] == CHANNEL_ID
        assert result["last_read_at"] == "2026-04-15T12:00:00Z"


# ------------------------------------------------------------------
# Channel materialization (TASK-207)
# ------------------------------------------------------------------


class TestMaterializeChannel:
    def test_materialize(self, httpx_mock):
        tasks = [
            {
                "id": "T" * 26,
                "type": "implement",
                "status": "pending",
                "priority": 2,
                "channel_id": CHANNEL_ID,
                "payload": {"instruction": "do the thing"},
                "created_at": "2026-04-15T12:00:00Z",
            }
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/materialize",
            status_code=201,
            json=envelope(tasks),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.materialize_channel(
                HIVE_ID,
                CHANNEL_ID,
                [{"type": "implement", "payload": {"instruction": "do the thing"}}],
            )
        assert len(result) == 1
        assert result[0]["type"] == "implement"
        body = json.loads(httpx_mock.get_request().content)
        assert body["tasks"][0]["type"] == "implement"


class TestListChannelTasks:
    def test_list_tasks(self, httpx_mock):
        tasks = [
            {
                "id": "T" * 26,
                "type": "implement",
                "status": "pending",
                "priority": 2,
                "channel_id": CHANNEL_ID,
                "payload": {},
                "created_at": "2026-04-15T12:00:00Z",
            }
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/tasks",
            json=envelope(tasks),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_channel_tasks(HIVE_ID, CHANNEL_ID)
        assert len(result) == 1


# ------------------------------------------------------------------
# Channel resolution
# ------------------------------------------------------------------


class TestResolveChannel:
    def test_resolve_channel(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/resolve",
            json=envelope(_channel_detail(status="resolved")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.resolve_channel(HIVE_ID, CHANNEL_ID, outcome="We agreed on option A")
        assert channel["status"] == "resolved"
        body = json.loads(httpx_mock.get_request().content)
        assert body["outcome"] == "We agreed on option A"

    def test_resolve_channel_with_tasks(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/resolve",
            json=envelope(_channel_detail(status="resolved")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.resolve_channel(
                HIVE_ID,
                CHANNEL_ID,
                outcome="Done",
                materialized_tasks=[{"type": "follow-up"}],
            )
        body = json.loads(httpx_mock.get_request().content)
        assert body["materialized_tasks"] == [{"type": "follow-up"}]


class TestReopenChannel:
    def test_reopen_channel(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/{CHANNEL_ID}/reopen",
            json=envelope(_channel_detail(status="deliberating")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            channel = c.reopen_channel(HIVE_ID, CHANNEL_ID)
        assert channel["status"] == "deliberating"


# ------------------------------------------------------------------
# Channel polling
# ------------------------------------------------------------------


class TestPollChannels:
    def test_poll_channels(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/poll",
            json=envelope([{"channel_id": CHANNEL_ID, "unread": 3}]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.poll_channels(HIVE_ID)
        assert len(result) == 1
        assert result[0]["channel_id"] == CHANNEL_ID


class TestPollChannelsWithMeta:
    def test_returns_full_envelope(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/poll",
            json=envelope(
                [{"channel_id": CHANNEL_ID, "unread": 3}],
                meta={"next_poll_ms": 2000},
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.poll_channels_with_meta(HIVE_ID)
        assert "data" in result
        assert "meta" in result
        assert result["meta"]["next_poll_ms"] == 2000
        assert len(result["data"]) == 1
        assert result["data"][0]["channel_id"] == CHANNEL_ID

    def test_returns_empty_channels(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/channels/poll",
            json=envelope([], meta={"next_poll_ms": 5000}),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.poll_channels_with_meta(HIVE_ID)
        assert result["data"] == []
        assert result["meta"]["next_poll_ms"] == 5000


# ------------------------------------------------------------------
# Model classes
# ------------------------------------------------------------------


class TestChannelModel:
    def test_channel_from_dict(self):
        from superpos_sdk.models import Channel

        data = _channel_data()
        ch = Channel.from_dict(data)
        assert ch.id == CHANNEL_ID
        assert ch.title == "Test Channel"
        assert ch.channel_type == "discussion"
        assert ch.status == "open"

    def test_channel_from_dict_with_participants(self):
        from superpos_sdk.models import Channel

        data = _channel_detail()
        ch = Channel.from_dict(data)
        assert ch.participants is not None
        assert len(ch.participants) == 1


class TestChannelMessageModel:
    def test_message_from_dict(self):
        from superpos_sdk.models import ChannelMessage

        data = _message_data()
        msg = ChannelMessage.from_dict(data)
        assert msg.id == MESSAGE_ID
        assert msg.channel_id == CHANNEL_ID
        assert msg.message_type == "discussion"
        assert msg.content == "Hello world"
