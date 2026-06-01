"""Data classes for API response objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    """An event from the Superpos EventBus.

    Attributes correspond to the JSON shape returned by
    ``GET /api/v1/hives/{hive}/events/poll``.
    """

    id: str
    type: str
    payload: dict = field(default_factory=dict)
    source_agent_id: str | None = None
    hive_id: str | None = None
    organization_id: str | None = None
    is_cross_hive: bool = False
    seq: int | None = None
    created_at: str | None = None
    invoke: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        """Create an :class:`Event` from an API response dict."""
        return cls(
            id=data["id"],
            type=data["type"],
            payload=data.get("payload", {}),
            source_agent_id=data.get("source_agent_id"),
            hive_id=data.get("hive_id"),
            organization_id=data.get("organization_id") or data.get("superpos_id"),
            is_cross_hive=data.get("is_cross_hive", False),
            seq=data.get("seq"),
            created_at=data.get("created_at"),
            invoke=data.get("invoke"),
        )


@dataclass
class Subscription:
    """An agent's event subscription.

    Attributes correspond to the JSON shape returned by the
    ``/api/v1/agents/subscriptions`` endpoints.
    """

    agent_id: str
    event_type: str
    scope: str = "hive"
    created_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Subscription:
        """Create a :class:`Subscription` from an API response dict."""
        return cls(
            agent_id=data["agent_id"],
            event_type=data["event_type"],
            scope=data.get("scope", "hive"),
            created_at=data.get("created_at"),
        )


@dataclass
class Channel:
    """A channel in the Superpos platform.

    Attributes correspond to the JSON shape returned by the
    ``/api/v1/hives/{hive}/channels`` endpoints.
    """

    id: str
    title: str
    channel_type: str
    status: str
    hive_id: str | None = None
    organization_id: str | None = None
    topic: str | None = None
    urgency: str | None = None
    resolution_policy: dict | None = None
    resolution_state: dict | None = None
    stage_progress: dict | None = None
    linked_refs: list | None = None
    on_resolve: dict | None = None
    resolution: dict | list | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    stale_after: int | None = None
    message_count: int | None = None
    last_message_at: str | None = None
    summary: str | None = None
    participants: list | None = None
    created_by_type: str | None = None
    created_by_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Channel:
        """Create a :class:`Channel` from an API response dict."""
        return cls(
            id=data["id"],
            title=data["title"],
            channel_type=data["channel_type"],
            status=data["status"],
            hive_id=data.get("hive_id"),
            organization_id=data.get("organization_id") or data.get("superpos_id"),
            topic=data.get("topic"),
            urgency=data.get("urgency"),
            resolution_policy=data.get("resolution_policy"),
            resolution_state=data.get("resolution_state"),
            stage_progress=data.get("stage_progress"),
            linked_refs=data.get("linked_refs"),
            on_resolve=data.get("on_resolve"),
            resolution=data.get("resolution"),
            resolved_by=data.get("resolved_by"),
            resolved_at=data.get("resolved_at"),
            stale_after=data.get("stale_after"),
            message_count=data.get("message_count"),
            last_message_at=data.get("last_message_at"),
            summary=data.get("summary"),
            participants=data.get("participants"),
            created_by_type=data.get("created_by_type"),
            created_by_id=data.get("created_by_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class ChannelMessage:
    """A message in a channel.

    Attributes correspond to the JSON shape returned by the
    ``/api/v1/hives/{hive}/channels/{channel}/messages`` endpoints.
    """

    id: str
    channel_id: str
    message_type: str
    content: str
    author_type: str | None = None
    author_id: str | None = None
    metadata: dict | None = None
    reply_to: str | None = None
    mentions: list | None = None
    edited_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ChannelMessage:
        """Create a :class:`ChannelMessage` from an API response dict."""
        return cls(
            id=data["id"],
            channel_id=data["channel_id"],
            message_type=data["message_type"],
            content=data["content"],
            author_type=data.get("author_type"),
            author_id=data.get("author_id"),
            metadata=data.get("metadata"),
            reply_to=data.get("reply_to"),
            mentions=data.get("mentions"),
            edited_at=data.get("edited_at"),
            created_at=data.get("created_at"),
        )


@dataclass
class SubAgentSummary:
    """Lightweight sub-agent definition (from list endpoint).

    Attributes correspond to the JSON shape returned by
    ``GET /api/v1/sub-agents``.
    """

    id: str
    slug: str
    name: str
    description: str | None = None
    model: str | None = None
    version: int = 1
    document_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> SubAgentSummary:
        """Create a :class:`SubAgentSummary` from an API response dict."""
        return cls(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data.get("description"),
            model=data.get("model"),
            version=data.get("version", 1),
            document_count=data.get("document_count", 0),
        )


@dataclass
class SubAgentDefinition:
    """Full sub-agent definition with documents.

    Attributes correspond to the JSON shape returned by
    ``GET /api/v1/sub-agents/{slug}`` and ``GET /api/v1/sub-agents/by-id/{id}``.
    """

    id: str
    slug: str
    name: str
    version: int = 1
    description: str | None = None
    model: str | None = None
    documents: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SubAgentDefinition:
        """Create a :class:`SubAgentDefinition` from an API response dict."""
        return cls(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            version=data.get("version", 1),
            description=data.get("description"),
            model=data.get("model"),
            documents=data.get("documents") or {},
            config=data.get("config") or {},
            allowed_tools=data.get("allowed_tools"),
        )


@dataclass
class SubAgent:
    """Sub-agent info attached to a claimed task.

    Delivered in the ``sub_agent`` block of task claim responses. Carries the
    assembled prompt plus config and tool allow-list needed to configure the
    sub-agent runtime.
    """

    id: str
    slug: str
    version: int = 1
    name: str | None = None
    model: str | None = None
    prompt: str | None = None
    config: dict[str, Any] | None = None
    allowed_tools: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SubAgent:
        """Create a :class:`SubAgent` from an API response dict.

        Gracefully handles both the full claim-time shape (with ``prompt``,
        ``config``, ``allowed_tools``, ``name``, ``model``) and the lightweight
        poll/show shape (``id``, ``slug``, ``version`` only).
        """
        return cls(
            id=data["id"],
            slug=data["slug"],
            version=data.get("version", 1),
            name=data.get("name"),
            model=data.get("model"),
            prompt=data.get("prompt"),
            config=data.get("config"),
            allowed_tools=data.get("allowed_tools"),
        )
