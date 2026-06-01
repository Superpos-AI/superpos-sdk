"""Async OOP resource wrappers over :class:`~superpos_sdk.async_agent.AsyncAgentContext`.

Phase 3 companion to the sync :mod:`superpos_sdk.resources` package.
Attribute reads stay synchronous; every method that issues an HTTP call
is ``async def``.
"""

from __future__ import annotations

from superpos_sdk.resources.async_resources.channel import AsyncChannel
from superpos_sdk.resources.async_resources.knowledge import AsyncKnowledgeEntry
from superpos_sdk.resources.async_resources.task import AsyncTask

__all__ = [
    "AsyncChannel",
    "AsyncKnowledgeEntry",
    "AsyncTask",
]
