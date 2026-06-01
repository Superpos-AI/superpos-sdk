"""OOP resource wrappers over :class:`~superpos_sdk.agent.AgentContext`.

Phase 2 of the agent-centric SDK refactor (TASK-257). Each wrapper holds
a dict representing a single resource plus the :class:`AgentContext`
that fetched it, and exposes bound methods so agents can write
``channel.post("hi")`` instead of ``ctx.post_message(channel["id"], "hi")``.

Wrappers are deliberately thin — they do not implement cross-resource
skills (``discuss()``, ``decide()``, ``remember()``). Those belong in
Phase 3.
"""

from __future__ import annotations

from superpos_sdk.resources.channel import Channel
from superpos_sdk.resources.knowledge import KnowledgeEntry
from superpos_sdk.resources.task import Task

__all__ = [
    "Channel",
    "KnowledgeEntry",
    "Task",
]
