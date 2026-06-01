"""Agent-centric facade over :class:`~superpos_sdk.client.SuperposClient`.

:class:`AgentContext` auto-reads the agent's identity (base URL, token,
hive ID, agent ID) from environment variables, binds ``hive_id``
implicitly on every call, and exposes a tight, pre-bound surface of the
most common endpoints.

This is Phase 1 of the agent-centric SDK refactor. It is deliberately
shallow — no OOP wrappers (Phase 2), no async variant (Phase 3), no
higher-level skills like ``discuss()`` / ``decide()``. The goal is to
remove the ``hive_id=`` boilerplate from typical agent loops.

Example::

    from superpos_sdk import AgentContext

    ctx = AgentContext.from_env()
    tasks = ctx.poll_tasks(capability="code")
    for task in tasks:
        claimed = ctx.claim_task(task["id"])
        ctx.complete_task(claimed["id"], result={"ok": True})

For endpoints not yet bound on :class:`AgentContext`, drop down to the
underlying client via :attr:`AgentContext.raw`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from superpos_sdk.client import SuperposClient
from superpos_sdk.models import Event

if TYPE_CHECKING:
    from superpos_sdk.resources import Channel, KnowledgeEntry, Task


class AgentContext:
    """Thin, pre-bound facade over :class:`SuperposClient` for agent code.

    Holds the agent's identity (``base_url``, ``token``, ``hive_id``,
    ``agent_id``) and a wrapped :class:`SuperposClient`. Methods are bound
    variants of the client's methods with ``hive_id`` threaded through
    automatically.

    Not all 120 client methods are mirrored — only the ones agents call
    day-to-day. For anything else, use :attr:`raw` to reach the underlying
    client.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        hive_id: str | None = None,
        agent_id: str | None = None,
        client: SuperposClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Construct an ``AgentContext``.

        Args:
            base_url: Superpos base URL (e.g. ``https://superpos.example.com``).
            token: Bearer token for agent auth.
            hive_id: Hive the agent operates in. May be ``None``; in that
                case hive-bound methods raise :class:`ValueError` at call
                time.
            agent_id: Agent ID (optional — used for observability only).
            client: Pre-built :class:`SuperposClient` to wrap (dependency
                injection for tests). When ``None``, a client is created
                using *base_url* and *token*.
            timeout: HTTP timeout in seconds (ignored when *client* is
                supplied).
        """
        self._base_url = base_url
        self._token = token
        self._hive_id = hive_id
        self._agent_id = agent_id
        if client is None:
            client = SuperposClient(base_url, token=token, timeout=timeout)
        self._client = client

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        token: str | None = None,
        hive_id: str | None = None,
        agent_id: str | None = None,
        client: SuperposClient | None = None,
        timeout: float = 30.0,
    ) -> AgentContext:
        """Build an :class:`AgentContext` from environment variables.

        Reads (in order, first match wins):

        - ``SUPERPOS_BASE_URL`` (legacy: ``APIARY_BASE_URL``) → base URL
        - ``SUPERPOS_API_TOKEN`` then ``SUPERPOS_TOKEN`` (legacy:
          ``APIARY_API_TOKEN`` then ``APIARY_TOKEN``) → bearer token
        - ``SUPERPOS_HIVE_ID`` (legacy: ``APIARY_HIVE_ID``) → hive ID
        - ``SUPERPOS_AGENT_ID`` (legacy: ``APIARY_AGENT_ID``) → agent ID

        Keyword arguments override env vars. Raises :class:`ValueError` if
        ``base_url`` or ``token`` cannot be resolved.
        """
        resolved_base = (
            base_url or os.environ.get("SUPERPOS_BASE_URL") or os.environ.get("APIARY_BASE_URL")
        )
        if not resolved_base:
            raise ValueError(
                "AgentContext.from_env: SUPERPOS_BASE_URL is not set. "
                "Pass base_url= explicitly or set the env var."
            )

        resolved_token = (
            token
            or os.environ.get("SUPERPOS_API_TOKEN")
            or os.environ.get("SUPERPOS_TOKEN")
            or os.environ.get("APIARY_API_TOKEN")
            or os.environ.get("APIARY_TOKEN")
        )
        if not resolved_token:
            raise ValueError(
                "AgentContext.from_env: no token found. Set SUPERPOS_API_TOKEN "
                "(or SUPERPOS_TOKEN) or pass token= explicitly."
            )

        resolved_hive = (
            hive_id or os.environ.get("SUPERPOS_HIVE_ID") or os.environ.get("APIARY_HIVE_ID")
        )
        resolved_agent = (
            agent_id or os.environ.get("SUPERPOS_AGENT_ID") or os.environ.get("APIARY_AGENT_ID")
        )

        return cls(
            base_url=resolved_base,
            token=resolved_token,
            hive_id=resolved_hive,
            agent_id=resolved_agent,
            client=client,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Identity properties
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """Superpos base URL this context is bound to."""
        return self._base_url

    @property
    def token(self) -> str:
        """Bearer token this context uses (read-only)."""
        return self._token

    @property
    def hive_id(self) -> str | None:
        """Hive ID bound to this context, or ``None`` if unbound."""
        return self._hive_id

    @property
    def agent_id(self) -> str | None:
        """Agent ID bound to this context, or ``None`` if unknown."""
        return self._agent_id

    @property
    def raw(self) -> SuperposClient:
        """Escape hatch — the underlying :class:`SuperposClient`.

        Use this for endpoints not mirrored on :class:`AgentContext`
        (workflows, channel voting, knowledge graph, etc.).
        """
        return self._client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_hive(self) -> str:
        if self._hive_id is None:
            raise ValueError(
                "AgentContext has no hive_id bound. Set SUPERPOS_HIVE_ID or "
                "pass hive_id= on construction before calling hive-scoped "
                "methods."
            )
        return self._hive_id

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def heartbeat(self, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a heartbeat to keep the agent alive. Requires no permission."""
        return self._client.heartbeat(metadata=metadata)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def poll_tasks(
        self,
        *,
        capability: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Poll for available tasks in the bound hive.

        Requires ``tasks.claim`` or equivalent polling permission on the
        agent.
        """
        return self._client.poll_tasks(
            self._require_hive(),
            capability=capability,
            limit=limit,
        )

    def create_task(
        self,
        *,
        task_type: str,
        priority: int | None = None,
        target_agent_id: str | None = None,
        target_capability: str | None = None,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        parent_task_id: str | None = None,
        context_refs: list[str] | None = None,
        guarantee: str | None = None,
        expires_at: str | None = None,
        invoke_instructions: str | None = None,
        invoke_context: Any | None = None,
        failure_policy: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        delivery_mode: str = "default",
        sub_agent_definition_slug: str | None = None,
    ) -> dict[str, Any]:
        """Create a task in the bound hive. Requires ``tasks.create``.

        When ``sub_agent_definition_slug`` is provided, the server resolves
        the slug to an active sub-agent definition in the agent's hive and
        binds it to the task (see TASK-263).
        """
        return self._client.create_task(
            self._require_hive(),
            task_type=task_type,
            priority=priority,
            target_agent_id=target_agent_id,
            target_capability=target_capability,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            parent_task_id=parent_task_id,
            context_refs=context_refs,
            guarantee=guarantee,
            expires_at=expires_at,
            invoke_instructions=invoke_instructions,
            invoke_context=invoke_context,
            failure_policy=failure_policy,
            idempotency_key=idempotency_key,
            delivery_mode=delivery_mode,
            sub_agent_definition_slug=sub_agent_definition_slug,
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Fetch a single task by ID. Requires ``tasks.read``."""
        return self._client.get_task(self._require_hive(), task_id)

    def claim_task(self, task_id: str) -> dict[str, Any]:
        """Atomically claim a pending task. Requires ``tasks.claim``."""
        return self._client.claim_task(self._require_hive(), task_id)

    def update_progress(
        self,
        task_id: str,
        *,
        progress: int,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Report progress on a claimed task. Requires ``tasks.update``."""
        return self._client.update_progress(
            self._require_hive(),
            task_id,
            progress=progress,
            status_message=status_message,
        )

    def complete_task(
        self,
        task_id: str,
        *,
        result: dict[str, Any] | list | None = None,
        status_message: str | None = None,
        delivery_mode: str | None = None,
        knowledge_entry_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark a task as completed. Requires ``tasks.update``."""
        return self._client.complete_task(
            self._require_hive(),
            task_id,
            result=result,
            status_message=status_message,
            delivery_mode=delivery_mode,
            knowledge_entry_id=knowledge_entry_id,
        )

    def fail_task(
        self,
        task_id: str,
        *,
        error: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Mark a task as failed. Requires ``tasks.update``."""
        return self._client.fail_task(
            self._require_hive(),
            task_id,
            error=error,
            status_message=status_message,
        )

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def create_channel(
        self,
        *,
        title: str,
        channel_type: str,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        resolution_policy: dict[str, Any] | None = None,
        linked_refs: list[dict[str, Any]] | None = None,
        on_resolve: dict[str, Any] | None = None,
        stale_after: int | None = None,
        initial_message: dict[str, Any] | None = None,
        auto_invite: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a channel in the bound hive."""
        return self._client.create_channel(
            self._require_hive(),
            title=title,
            channel_type=channel_type,
            topic=topic,
            participants=participants,
            resolution_policy=resolution_policy,
            linked_refs=linked_refs,
            on_resolve=on_resolve,
            stale_after=stale_after,
            initial_message=initial_message,
            auto_invite=auto_invite,
        )

    def list_channels(
        self,
        *,
        status: str | None = None,
        channel_type: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List channels in the bound hive."""
        return self._client.list_channels(
            self._require_hive(),
            status=status,
            channel_type=channel_type,
            page=page,
            per_page=per_page,
        )

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        """Get a single channel by ID."""
        return self._client.get_channel(self._require_hive(), channel_id)

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
        """Post a message to a channel.

        Wraps :meth:`SuperposClient.post_channel_message`.
        """
        return self._client.post_channel_message(
            self._require_hive(),
            channel_id,
            body,
            message_type=message_type,
            mentions=mentions,
            metadata=metadata,
            reply_to=reply_to,
        )

    def list_messages(
        self,
        channel_id: str,
        *,
        since: str | None = None,
        after_id: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List messages in a channel.

        Wraps :meth:`SuperposClient.list_channel_messages`.
        """
        return self._client.list_channel_messages(
            self._require_hive(),
            channel_id,
            since=since,
            after_id=after_id,
            page=page,
            per_page=per_page,
        )

    def add_participant(
        self,
        channel_id: str,
        participant_type: str,
        participant_id: str,
        *,
        role: str = "contributor",
        mention_policy: str | None = None,
    ) -> dict[str, Any]:
        """Add a participant to a channel.

        Wraps :meth:`SuperposClient.add_channel_participant`.
        """
        return self._client.add_channel_participant(
            self._require_hive(),
            channel_id,
            participant_type,
            participant_id,
            role=role,
            mention_policy=mention_policy,
        )

    def resolve_channel(
        self,
        channel_id: str,
        *,
        outcome: str,
        materialized_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Resolve a channel with an outcome."""
        return self._client.resolve_channel(
            self._require_hive(),
            channel_id,
            outcome=outcome,
            materialized_tasks=materialized_tasks,
        )

    def archive_channel(self, channel_id: str) -> dict[str, Any]:
        """Archive a channel (soft delete)."""
        return self._client.archive_channel(self._require_hive(), channel_id)

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def list_knowledge(
        self,
        *,
        key: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List knowledge entries in the bound hive. Requires ``knowledge.read``."""
        return self._client.list_knowledge(
            self._require_hive(),
            key=key,
            scope=scope,
            limit=limit,
        )

    def create_knowledge(
        self,
        *,
        key: str,
        value: Any,
        scope: str | None = None,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> dict[str, Any]:
        """Create a knowledge entry. Requires ``knowledge.write``."""
        return self._client.create_knowledge(
            self._require_hive(),
            key=key,
            value=value,
            scope=scope,
            visibility=visibility,
            ttl=ttl,
        )

    def get_knowledge(self, entry_id: str) -> dict[str, Any]:
        """Get a knowledge entry by ID. Requires ``knowledge.read``."""
        return self._client.get_knowledge(self._require_hive(), entry_id)

    def update_knowledge(
        self,
        entry_id: str,
        *,
        value: Any,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> dict[str, Any]:
        """Update a knowledge entry (bumps version). Requires ``knowledge.write``."""
        return self._client.update_knowledge(
            self._require_hive(),
            entry_id,
            value=value,
            visibility=visibility,
            ttl=ttl,
        )

    def delete_knowledge(self, entry_id: str) -> None:
        """Delete a knowledge entry. Requires ``knowledge.write``."""
        self._client.delete_knowledge(self._require_hive(), entry_id)

    def search_knowledge(
        self,
        *,
        q: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search knowledge in the bound hive. Requires ``knowledge.read``."""
        return self._client.search_knowledge(
            self._require_hive(),
            q=q,
            scope=scope,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def poll_events(
        self,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """Poll for new events in the bound hive (cursor tracked by client)."""
        return self._client.poll_events(
            self._require_hive(),
            since=since,
            limit=limit,
        )

    def publish_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish an event in the bound hive."""
        return self._client.publish_event(
            self._require_hive(),
            event_type=event_type,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    def create_schedule(
        self,
        *,
        name: str,
        trigger_type: str,
        task_type: str,
        cron_expression: str | None = None,
        interval_seconds: int | None = None,
        run_at: str | None = None,
        description: str | None = None,
        task_payload: dict[str, Any] | None = None,
        task_priority: int | None = None,
        task_target_agent_id: str | None = None,
        task_target_capability: str | None = None,
        task_timeout_seconds: int | None = None,
        task_max_retries: int | None = None,
        task_context_refs: list[str] | None = None,
        task_failure_policy: dict[str, Any] | None = None,
        overlap_policy: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a task schedule in the bound hive."""
        return self._client.create_schedule(
            self._require_hive(),
            name=name,
            trigger_type=trigger_type,
            task_type=task_type,
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            run_at=run_at,
            description=description,
            task_payload=task_payload,
            task_priority=task_priority,
            task_target_agent_id=task_target_agent_id,
            task_target_capability=task_target_capability,
            task_timeout_seconds=task_timeout_seconds,
            task_max_retries=task_max_retries,
            task_context_refs=task_context_refs,
            task_failure_policy=task_failure_policy,
            overlap_policy=overlap_policy,
            expires_at=expires_at,
        )

    def list_schedules(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List task schedules in the bound hive."""
        return self._client.list_schedules(self._require_hive(), status=status)

    def delete_schedule(self, schedule_id: str) -> None:
        """Delete a task schedule."""
        self._client.delete_schedule(self._require_hive(), schedule_id)

    # ------------------------------------------------------------------
    # Persona memory
    # ------------------------------------------------------------------

    def update_memory(
        self,
        *,
        content: str,
        message: str | None = None,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Update the agent's MEMORY document (see :meth:`SuperposClient.update_memory`)."""
        return self._client.update_memory(content=content, message=message, mode=mode)

    # ------------------------------------------------------------------
    # OOP resource factories (Phase 2 — TASK-257)
    # ------------------------------------------------------------------

    def channel(self, channel_id: str) -> Channel:
        """Fetch a channel and return it wrapped as a :class:`Channel`.

        The Phase 1 dict-returning :meth:`get_channel` is still available
        and unchanged.
        """
        from superpos_sdk.resources import Channel  # noqa: PLC0415

        data = self.get_channel(channel_id)
        return Channel(data, self)

    def create_channel_obj(
        self,
        *,
        title: str,
        channel_type: str,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        resolution_policy: dict[str, Any] | None = None,
        linked_refs: list[dict[str, Any]] | None = None,
        on_resolve: dict[str, Any] | None = None,
        stale_after: int | None = None,
        initial_message: dict[str, Any] | None = None,
        auto_invite: dict[str, Any] | None = None,
    ) -> Channel:
        """Create a channel and return it wrapped as a :class:`Channel`."""
        from superpos_sdk.resources import Channel  # noqa: PLC0415

        data = self.create_channel(
            title=title,
            channel_type=channel_type,
            topic=topic,
            participants=participants,
            resolution_policy=resolution_policy,
            linked_refs=linked_refs,
            on_resolve=on_resolve,
            stale_after=stale_after,
            initial_message=initial_message,
            auto_invite=auto_invite,
        )
        return Channel(data, self)

    def list_channels_obj(
        self,
        *,
        status: str | None = None,
        channel_type: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[Channel]:
        """List channels in the bound hive as :class:`Channel` instances."""
        from superpos_sdk.resources import Channel  # noqa: PLC0415

        rows = self.list_channels(
            status=status,
            channel_type=channel_type,
            page=page,
            per_page=per_page,
        )
        return [Channel(row, self) for row in rows or []]

    def task(self, task_id: str) -> Task:
        """Fetch a task and return it wrapped as a :class:`Task`.

        Uses ``GET /api/v1/hives/{hive}/tasks/{task}``. Requires
        ``tasks.read`` on the agent. The dict-returning :meth:`get_task`
        is still available and unchanged.
        """
        from superpos_sdk.resources import Task  # noqa: PLC0415

        data = self.get_task(task_id)
        return Task(data, self)

    def claim_next(self, *, capability: str | None = None) -> Task | None:
        """Poll for one task, claim it, and return it as a :class:`Task`.

        Returns ``None`` if no tasks are available for the given
        *capability* filter. Requires ``tasks.claim`` on the agent.
        """
        from superpos_sdk.resources import Task  # noqa: PLC0415

        tasks = self.poll_tasks(capability=capability, limit=1)
        if not tasks:
            return None
        first = tasks[0]
        if not isinstance(first, dict) or "id" not in first:
            return None
        claimed = self.claim_task(first["id"])
        # Prefer the claimed payload (has the up-to-date status) but fall
        # back to the polled dict if the server returned nothing useful.
        data = claimed if isinstance(claimed, dict) else first
        return Task(data, self)

    def knowledge(self, entry_id: str) -> KnowledgeEntry:
        """Fetch a knowledge entry and return it wrapped as a :class:`KnowledgeEntry`."""
        from superpos_sdk.resources import KnowledgeEntry  # noqa: PLC0415

        data = self.get_knowledge(entry_id)
        return KnowledgeEntry(data, self)

    def create_knowledge_obj(
        self,
        *,
        key: str,
        value: Any,
        scope: str | None = None,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> KnowledgeEntry:
        """Create a knowledge entry and return it wrapped as a :class:`KnowledgeEntry`."""
        from superpos_sdk.resources import KnowledgeEntry  # noqa: PLC0415

        data = self.create_knowledge(
            key=key,
            value=value,
            scope=scope,
            visibility=visibility,
            ttl=ttl,
        )
        return KnowledgeEntry(data, self)

    def list_knowledge_obj(
        self,
        *,
        key: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[KnowledgeEntry]:
        """List knowledge entries as :class:`KnowledgeEntry` instances."""
        from superpos_sdk.resources import KnowledgeEntry  # noqa: PLC0415

        rows = self.list_knowledge(key=key, scope=scope, limit=limit)
        return [KnowledgeEntry(row, self) for row in rows or []]

    # ------------------------------------------------------------------
    # Skills (bound methods — see superpos_sdk.skills)
    # ------------------------------------------------------------------

    def discuss(
        self,
        title: str,
        *,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        initial_message: str | None = None,
        channel_type: str = "discussion",
    ) -> Channel:
        """Create a channel and optionally post an opener.

        See :func:`superpos_sdk.skills.discuss`.
        """
        from superpos_sdk.skills.sync_skills import discuss  # noqa: PLC0415

        return discuss(
            self,
            title,
            topic=topic,
            participants=participants,
            initial_message=initial_message,
            channel_type=channel_type,
        )

    def decide(
        self,
        title: str,
        question: str,
        options: list[str] | list[dict[str, Any]],
        *,
        participants: list[dict[str, Any]] | None = None,
        policy: str = "agent_decision",
        threshold: float | None = None,
        deadline_seconds: int | None = None,
    ) -> Channel:
        """Start a decision channel with a proposal.

        See :func:`superpos_sdk.skills.decide`.
        """
        from superpos_sdk.skills.sync_skills import decide  # noqa: PLC0415

        return decide(
            self,
            title,
            question,
            options,
            participants=participants,
            policy=policy,
            threshold=threshold,
            deadline_seconds=deadline_seconds,
        )

    def remember(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "hive",
        visibility: str = "public",
        ttl: str | None = None,
        tags: list[str] | None = None,
        format: str = "markdown",
        title: str | None = None,
        summary: str | None = None,
    ) -> KnowledgeEntry:
        """Write a knowledge entry.

        See :func:`superpos_sdk.skills.remember`.
        """
        from superpos_sdk.skills.sync_skills import remember  # noqa: PLC0415

        return remember(
            self,
            key,
            value,
            scope=scope,
            visibility=visibility,
            ttl=ttl,
            tags=tags,
            format=format,
            title=title,
            summary=summary,
        )

    def recall(
        self,
        key: str | None = None,
        *,
        query: str | None = None,
        scope: str | None = None,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """Look up knowledge by key or full-text query.

        See :func:`superpos_sdk.skills.recall`.
        """
        from superpos_sdk.skills.sync_skills import recall  # noqa: PLC0415

        return recall(self, key, query=query, scope=scope, limit=limit)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> AgentContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["AgentContext"]
