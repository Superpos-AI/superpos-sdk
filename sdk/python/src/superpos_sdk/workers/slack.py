"""Slack service worker — interact with the Slack Web API.

Install the optional dependency::

    pip install superpos-sdk[slack]

Credentials (env-first, payload fallback):

- ``SLACK_BOT_TOKEN`` — Bot User OAuth Token (``xoxb-…``)

Supported operations
--------------------

``post_message``
    ``{"channel": "#general", "text": "Hello!", "blocks": [...]}``

``get_channel``
    ``{"channel": "C01234567"}``  (channel ID)

``list_channels``
    ``{"types": "public_channel,private_channel", "limit": 200, "cursor": "..."}``

``get_message``
    ``{"channel": "C01234567", "ts": "1234567890.123456"}``

``add_reaction``
    ``{"channel": "C01234567", "ts": "1234567890.123456", "name": "thumbsup"}``
"""

from __future__ import annotations

import os
from typing import Any

from superpos_sdk.service_worker import ServiceWorker

_SLACK_API = "https://slack.com/api"


class SlackWorker(ServiceWorker):
    """Service worker that proxies Slack Web API calls.

    Credentials are read from the ``SLACK_BOT_TOKEN`` environment variable.
    A per-request ``token`` key in *params* overrides the environment token.
    """

    CAPABILITY = "data:slack"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _token(self, params: dict[str, Any]) -> str:
        token = params.get("token") or os.environ.get("SLACK_BOT_TOKEN", "")
        if not token:
            raise ValueError(
                "Slack token not found. Set SLACK_BOT_TOKEN env var or pass token in params."
            )
        return token

    def _client(self, params: dict[str, Any]):  # type: ignore[return]
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "httpx is required for SlackWorker. "
                "Install it with: pip install superpos-sdk[slack]"
            ) from exc

        token = self._token(params)
        return httpx.Client(
            base_url=_SLACK_API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    def _check_ok(self, data: dict[str, Any]) -> dict[str, Any]:
        """Raise RuntimeError if Slack returned ok=false."""
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise RuntimeError(f"Slack API error: {error}")
        return data

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def post_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Post a message to a Slack channel.

        Args:
            params: Must include ``channel``.  Optional: ``text``, ``blocks``,
                ``thread_ts``, ``mrkdwn``.

        Returns:
            Slack API response dict (channel, ts, message).
        """
        body: dict[str, Any] = {"channel": params["channel"]}
        for key in ("text", "blocks", "attachments", "thread_ts", "mrkdwn"):
            if params.get(key) is not None:
                body[key] = params[key]

        with self._client(params) as c:
            r = c.post("/chat.postMessage", json=body)
            r.raise_for_status()
            return self._check_ok(r.json())

    def get_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch info about a channel.

        Args:
            params: Must include ``channel`` (channel ID).

        Returns:
            Slack channel object.
        """
        with self._client(params) as c:
            r = c.get("/conversations.info", params={"channel": params["channel"]})
            r.raise_for_status()
            data = self._check_ok(r.json())
            return data["channel"]

    def list_channels(self, params: dict[str, Any]) -> dict[str, Any]:
        """List channels in the workspace.

        Args:
            params: Optional ``types``, ``limit``, ``cursor``.

        Returns:
            Dict with ``channels`` list and ``response_metadata``.
        """
        query: dict[str, Any] = {
            "types": params.get("types", "public_channel"),
            "limit": params.get("limit", 200),
        }
        if params.get("cursor"):
            query["cursor"] = params["cursor"]

        with self._client(params) as c:
            r = c.get("/conversations.list", params=query)
            r.raise_for_status()
            data = self._check_ok(r.json())
            return {
                "channels": data.get("channels", []),
                "response_metadata": data.get("response_metadata", {}),
            }

    def get_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single message by channel and timestamp.

        Args:
            params: Must include ``channel`` and ``ts``.

        Returns:
            The message dict.

        Raises:
            RuntimeError: When the message is not found.
        """
        query: dict[str, Any] = {
            "channel": params["channel"],
            "latest": params["ts"],
            "oldest": params["ts"],
            "inclusive": "true",
            "limit": 1,
        }
        with self._client(params) as c:
            r = c.get("/conversations.history", params=query)
            r.raise_for_status()
            data = self._check_ok(r.json())

        messages = data.get("messages", [])
        if not messages:
            raise RuntimeError(f"Message not found: channel={params['channel']} ts={params['ts']}")
        return messages[0]

    def add_reaction(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add an emoji reaction to a message.

        Args:
            params: Must include ``channel``, ``ts``, and ``name``
                (emoji name without colons).

        Returns:
            ``{"ok": true}``
        """
        body = {
            "channel": params["channel"],
            "timestamp": params["ts"],
            "name": params["name"],
        }
        with self._client(params) as c:
            r = c.post("/reactions.add", json=body)
            r.raise_for_status()
            return self._check_ok(r.json())
