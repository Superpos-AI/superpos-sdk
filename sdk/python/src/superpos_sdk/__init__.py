"""Superpos Python SDK — minimal client for the Superpos agent orchestration platform."""

from superpos_sdk import constants, skills
from superpos_sdk.agent import AgentContext
from superpos_sdk.async_agent import AsyncAgentContext
from superpos_sdk.async_client import AsyncSuperposClient
from superpos_sdk.client import SuperposClient
from superpos_sdk.constants import (
    CHANNEL_STATUSES,
    KNOWLEDGE_SCOPES,
    KNOWLEDGE_SCOPES_LEGACY,
    KNOWLEDGE_VISIBILITY,
    MESSAGE_TYPES,
    RESOLUTION_POLICIES,
    TASK_STATUSES,
    agent_scope,
)
from superpos_sdk.constants import (
    CHANNEL_TYPES as _CHANNEL_TYPES_TUPLE,
)
from superpos_sdk.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    SuperposError,
    ValidationError,
)
from superpos_sdk.exceptions import PermissionError as SuperposPermissionError
from superpos_sdk.large_result import LARGE_RESULT_THRESHOLD_BYTES, LargeResultDelivery
from superpos_sdk.models import Channel as ChannelModel
from superpos_sdk.models import (
    ChannelMessage,
    Event,
    SubAgent,
    SubAgentDefinition,
    SubAgentSummary,
    Subscription,
)
from superpos_sdk.resources import Channel as ChannelResource
from superpos_sdk.resources import KnowledgeEntry, Task
from superpos_sdk.resources.async_resources import (
    AsyncChannel,
    AsyncKnowledgeEntry,
    AsyncTask,
)
from superpos_sdk.service_worker import OperationNotFoundError, ServiceWorker
from superpos_sdk.streaming import StreamingTask

# Keep backward-compatible top-level name: ``Channel`` is the legacy model.
Channel = ChannelModel

__version__ = "0.1.0"

#: Re-export CHANNEL_TYPES as a ``list`` for backward compatibility — existing
#: callers (and ``superpos_sdk.client.CHANNEL_TYPES``) expect a list, not a tuple.
CHANNEL_TYPES: list[str] = list(_CHANNEL_TYPES_TUPLE)

# ---------------------------------------------------------------------------
# Backward-compatible aliases (old Apiary* names → new Superpos* names)
# Allows ``from superpos_sdk import ApiaryClient`` during the transition.
# ---------------------------------------------------------------------------
ApiaryClient = SuperposClient
AsyncApiaryClient = AsyncSuperposClient
ApiaryError = SuperposError
ApiaryPermissionError = SuperposPermissionError

__all__ = [
    "AgentContext",
    "SuperposClient",
    "SuperposError",
    "SuperposPermissionError",
    "ApiaryClient",
    "AsyncApiaryClient",
    "ApiaryError",
    "ApiaryPermissionError",
    "AsyncAgentContext",
    "AsyncSuperposClient",
    "AsyncChannel",
    "AsyncKnowledgeEntry",
    "AsyncTask",
    "AuthenticationError",
    "CHANNEL_STATUSES",
    "CHANNEL_TYPES",
    "Channel",
    "ChannelMessage",
    "ChannelModel",
    "ChannelResource",
    "ConflictError",
    "Event",
    "KNOWLEDGE_SCOPES",
    "KNOWLEDGE_SCOPES_LEGACY",
    "KNOWLEDGE_VISIBILITY",
    "KnowledgeEntry",
    "LARGE_RESULT_THRESHOLD_BYTES",
    "LargeResultDelivery",
    "MESSAGE_TYPES",
    "NotFoundError",
    "OperationNotFoundError",
    "RESOLUTION_POLICIES",
    "ServiceWorker",
    "StreamingTask",
    "SubAgent",
    "SubAgentDefinition",
    "SubAgentSummary",
    "Subscription",
    "TASK_STATUSES",
    "Task",
    "ValidationError",
    "__version__",
    "agent_scope",
    "constants",
    "skills",
]
