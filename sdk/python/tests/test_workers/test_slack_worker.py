"""Tests for SlackWorker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.slack import SlackWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"
TOKEN = "xoxb-test-token"
CHANNEL = "C01234567"


def _worker() -> SlackWorker:
    return SlackWorker(BASE_URL, HIVE_ID, name="slack-worker", secret="s3cr3t")


def _mock_client(json_data: dict, *, ok: bool = True) -> MagicMock:
    """Return a patched httpx.Client that returns the given JSON."""
    payload = {"ok": ok, **json_data}
    if not ok and "error" not in payload:
        payload["error"] = "channel_not_found"

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = resp
    mock_client.post.return_value = resp
    return mock_client


class TestSlackWorkerPostMessage:
    def test_post_message_returns_response(self):
        worker = _worker()
        payload = {"channel": CHANNEL, "ts": "1234567890.000001", "message": {}}

        with patch("httpx.Client", return_value=_mock_client(payload)):
            result = worker.post_message({"token": TOKEN, "channel": CHANNEL, "text": "Hello!"})

        assert result["channel"] == CHANNEL
        assert result["ok"] is True

    def test_post_message_slack_error_raises(self):
        worker = _worker()

        with patch("httpx.Client", return_value=_mock_client({}, ok=False)):
            with pytest.raises(RuntimeError, match="channel_not_found"):
                worker.post_message({"token": TOKEN, "channel": CHANNEL, "text": "Hi"})


class TestSlackWorkerGetChannel:
    def test_get_channel_returns_channel_object(self):
        worker = _worker()
        channel_obj = {"id": CHANNEL, "name": "general", "is_channel": True}

        with patch("httpx.Client", return_value=_mock_client({"channel": channel_obj})):
            result = worker.get_channel({"token": TOKEN, "channel": CHANNEL})

        assert result["id"] == CHANNEL
        assert result["name"] == "general"

    def test_missing_token_raises_value_error(self):
        worker = _worker()
        with pytest.raises(ValueError, match="Slack token"):
            worker.get_channel({"channel": CHANNEL})


class TestSlackWorkerListChannels:
    def test_list_channels_returns_channels_and_metadata(self):
        worker = _worker()
        channels = [{"id": "C1"}, {"id": "C2"}]
        mock_data = {"channels": channels, "response_metadata": {"next_cursor": ""}}

        with patch("httpx.Client", return_value=_mock_client(mock_data)):
            result = worker.list_channels({"token": TOKEN})

        assert len(result["channels"]) == 2
        assert "response_metadata" in result

    def test_list_channels_with_cursor(self):
        worker = _worker()
        channels = [{"id": "C3"}]
        mock_data = {"channels": channels, "response_metadata": {}}

        with patch("httpx.Client", return_value=_mock_client(mock_data)) as mock_cls:
            mock_instance = mock_cls.return_value
            worker.list_channels({"token": TOKEN, "cursor": "dXNlcjpV"})
            call_kwargs = mock_instance.get.call_args[1]

        assert call_kwargs["params"]["cursor"] == "dXNlcjpV"


class TestSlackWorkerGetMessage:
    def test_get_message_returns_first_message(self):
        worker = _worker()
        ts = "1234567890.000001"
        messages = [{"ts": ts, "text": "Hello!"}]
        mock_data = {"messages": messages, "has_more": False}

        with patch("httpx.Client", return_value=_mock_client(mock_data)):
            result = worker.get_message({"token": TOKEN, "channel": CHANNEL, "ts": ts})

        assert result["ts"] == ts
        assert result["text"] == "Hello!"

    def test_get_message_not_found_raises(self):
        worker = _worker()

        with patch("httpx.Client", return_value=_mock_client({"messages": [], "has_more": False})):
            with pytest.raises(RuntimeError, match="Message not found"):
                worker.get_message({"token": TOKEN, "channel": CHANNEL, "ts": "0"})


class TestSlackWorkerAddReaction:
    def test_add_reaction_returns_ok(self):
        worker = _worker()

        with patch("httpx.Client", return_value=_mock_client({})):
            result = worker.add_reaction(
                {"token": TOKEN, "channel": CHANNEL, "ts": "1234.000001", "name": "thumbsup"}
            )

        assert result["ok"] is True
