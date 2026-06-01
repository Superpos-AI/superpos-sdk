"""Backward-compatibility shim — re-exports everything from ``superpos_sdk``.

.. deprecated::
    The ``apiary_sdk`` package has been renamed to ``superpos_sdk``.
    Update your imports to use ``superpos_sdk`` directly.  This shim will
    be removed in a future release.
"""

import warnings as _warnings

_warnings.warn(
    "The 'apiary_sdk' package has been renamed to 'superpos_sdk'. "
    "Please update your imports.  This compatibility shim will be "
    "removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the entire public API from superpos_sdk.
from superpos_sdk import (  # noqa: E402
    CHANNEL_STATUSES,
    CHANNEL_TYPES,
    KNOWLEDGE_SCOPES,
    KNOWLEDGE_VISIBILITY,
    LARGE_RESULT_THRESHOLD_BYTES,
    MESSAGE_TYPES,
    RESOLUTION_POLICIES,
    TASK_STATUSES,
    AgentContext,
    AsyncAgentContext,
    AsyncChannel,
    AsyncKnowledgeEntry,
    AsyncSuperposClient,
    AsyncTask,
    AuthenticationError,
    Channel,
    ChannelMessage,
    ChannelModel,
    ChannelResource,
    ConflictError,
    Event,
    KnowledgeEntry,
    LargeResultDelivery,
    NotFoundError,
    OperationNotFoundError,
    ServiceWorker,
    StreamingTask,
    Subscription,
    SuperposClient,
    SuperposError,
    SuperposPermissionError,
    Task,
    ValidationError,
    __version__,
    agent_scope,
    constants,
    resources,
    skills,
    workers,
)

# ---------------------------------------------------------------------------
# Legacy class-name aliases (old Apiary* names → new Superpos* names)
# ---------------------------------------------------------------------------
ApiaryClient = SuperposClient
AsyncApiaryClient = AsyncSuperposClient
ApiaryError = SuperposError
ApiaryPermissionError = SuperposPermissionError

__all__ = [
    # Legacy aliases
    "ApiaryClient",
    "AsyncApiaryClient",
    "ApiaryError",
    "ApiaryPermissionError",
    # Everything from superpos_sdk
    "AgentContext",
    "AsyncAgentContext",
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
    "Subscription",
    "SuperposClient",
    "SuperposError",
    "SuperposPermissionError",
    "TASK_STATUSES",
    "Task",
    "ValidationError",
    "__version__",
    "agent_scope",
    "constants",
    "resources",
    "skills",
    "workers",
]
