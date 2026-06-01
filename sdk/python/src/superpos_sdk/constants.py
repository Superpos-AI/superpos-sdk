"""Authoritative enum values mirroring the Superpos backend models.

Values are plain ``tuple[str, ...]`` (or ``dict`` for nested shapes) rather
than :class:`enum.Enum` subclasses. The backend validates incoming strings,
so forcing agents to import an Enum just to pass a known string adds
friction for no gain. If you want stricter typing at call sites use
``typing.Literal`` against the tuple's elements.

Every constant here has a direct mapping to a backend source:

- ``CHANNEL_TYPES``        → ``App\\Models\\Channel::TYPES``
- ``CHANNEL_STATUSES``     → ``App\\Models\\Channel::STATUSES``
- ``MESSAGE_TYPES``        → ``App\\Models\\ChannelMessage::TYPES``
- ``RESOLUTION_POLICIES``  → ``App\\Services\\ResolutionEngine``
  (match on ``policy['type']``) + manual resolve.
- ``TASK_STATUSES``        → ``App\\Models\\Task::STATUSES``
- ``KNOWLEDGE_SCOPES``     → ``CompleteTaskRequest`` regex
  ``/^(hive|organization|apiary|agent:[a-zA-Z0-9]+)$/``.
- ``KNOWLEDGE_VISIBILITY`` → ``CreateKnowledgeRequest`` ``in:public,private``.
"""

from __future__ import annotations

from typing import Any

#: Valid channel types accepted by the API.
CHANNEL_TYPES: tuple[str, ...] = (
    "discussion",
    "review",
    "planning",
    "incident",
)

#: Valid channel statuses.
CHANNEL_STATUSES: tuple[str, ...] = (
    "open",
    "deliberating",
    "resolved",
    "stale",
    "failed",
    "archived",
)

#: Valid channel message types.
MESSAGE_TYPES: tuple[str, ...] = (
    "discussion",
    "proposal",
    "vote",
    "decision",
    "context",
    "system",
    "action",
)

#: Valid task statuses.
TASK_STATUSES: tuple[str, ...] = (
    "waiting",
    "pending",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
    "dead_letter",
    "expired",
    "awaiting_children",
)

#: Top-level knowledge scopes accepted as-is by the backend.
#: Agent-private scopes require the ``"agent:<id>"`` format — use
#: :func:`agent_scope` to build that string.
KNOWLEDGE_SCOPES: tuple[str, ...] = (
    "hive",
    "organization",
)

#: Deprecated alias kept for backward compatibility.
KNOWLEDGE_SCOPES_LEGACY: tuple[str, ...] = (
    "hive",
    "apiary",
)

#: Valid knowledge visibility values.
KNOWLEDGE_VISIBILITY: tuple[str, ...] = (
    "public",
    "private",
)


def agent_scope(agent_id: str) -> str:
    """Build an agent-private knowledge scope string (``agent:<id>``)."""
    return f"agent:{agent_id}"


#: Preset ``resolution_policy`` shapes for channel creation. Each entry is
#: a starter dict — copy, edit, and pass as the ``resolution_policy`` kwarg
#: on :meth:`SuperposClient.create_channel`. Only the ``type`` field is
#: required; other fields are backend-interpreted based on policy type.
RESOLUTION_POLICIES: dict[str, dict[str, Any]] = {
    "manual": {
        "type": "manual",
    },
    "agent_decision": {
        "type": "agent_decision",
        # Allowed roles that can resolve the channel.
        "allowed_roles": ["decider", "initiator"],
    },
    "consensus": {
        "type": "consensus",
        # Fraction of participants that must approve (0.0 - 1.0).
        "threshold": 0.66,
        # Whether any "block" vote prevents resolution.
        "blocking_enabled": True,
    },
    "human_approval": {
        "type": "human_approval",
        # Users or user IDs that can approve.
        "approvers": [],
    },
    "staged": {
        "type": "staged",
        # Ordered stages — each stage is itself a resolution policy.
        "stages": [
            {"type": "consensus", "threshold": 0.5},
            {"type": "human_approval", "approvers": []},
        ],
    },
}


__all__ = [
    "CHANNEL_STATUSES",
    "CHANNEL_TYPES",
    "KNOWLEDGE_SCOPES",
    "KNOWLEDGE_SCOPES_LEGACY",
    "KNOWLEDGE_VISIBILITY",
    "MESSAGE_TYPES",
    "RESOLUTION_POLICIES",
    "TASK_STATUSES",
    "agent_scope",
]
