"""Async variant of :class:`~superpos_sdk.client.SuperposClient`.

This mirrors the sync client's surface for the methods
:class:`~superpos_sdk.async_agent.AsyncAgentContext` wraps. Not every
``SuperposClient`` method is ported — only the ones agent code actually
calls through the context. Exotic paths (workflows, thread helpers,
large-result delivery, service catalog discovery) stay sync-only; use
``asyncio.to_thread`` with an :class:`SuperposClient` when you need them.

Usage::

    async with AsyncSuperposClient("https://superpos.example.com", token="...") as client:
        tasks = await client.poll_tasks(hive_id)
"""

from __future__ import annotations

from typing import Any

import httpx

from superpos_sdk.client import _attach_sub_agent
from superpos_sdk.exceptions import SuperposError, raise_for_status
from superpos_sdk.models import Event, SubAgentDefinition, SubAgentSummary


class AsyncSuperposClient:
    """Minimal async Superpos API client.

    Deliberately parallel to :class:`SuperposClient`. Response parsing and
    error handling match the sync client exactly — the ``{data, meta,
    errors}`` envelope is unwrapped by :meth:`_request` and
    :meth:`_request_envelope`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Construct an ``AsyncSuperposClient``.

        Args:
            base_url: Superpos base URL (e.g. ``https://superpos.example.com``).
            token: Bearer token for agent auth.
            timeout: HTTP timeout in seconds.
            transport: Optional async transport (primarily for tests — pass
                :class:`httpx.MockTransport` to stub HTTP).
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": timeout,
            "headers": {"Accept": "application/json"},
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.AsyncClient(**kwargs)
        self._event_cursors: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request, unwrap the Superpos envelope, raise on errors."""
        response = await self._http.request(
            method,
            path,
            json=json,
            params=params,
            headers=self._headers(),
        )

        if response.status_code == 204:
            return None

        try:
            body = response.json()
        except Exception:
            if response.status_code >= 400:
                snippet = response.text[:200]
                raise SuperposError(
                    f"HTTP {response.status_code}: {snippet}",
                    status_code=response.status_code,
                )
            raise SuperposError(
                f"Expected JSON response, got {response.headers.get('content-type', 'unknown')}",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            raise_for_status(response.status_code, body)

        return body.get("data")

    async def _request_envelope(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Like :meth:`_request` but returns the full envelope."""
        response = await self._http.request(
            method,
            path,
            json=json,
            params=params,
            headers=self._headers(),
        )

        try:
            body = response.json()
        except Exception:
            if response.status_code >= 400:
                snippet = response.text[:200]
                raise SuperposError(
                    f"HTTP {response.status_code}: {snippet}",
                    status_code=response.status_code,
                )
            raise SuperposError(
                f"Expected JSON response, got {response.headers.get('content-type', 'unknown')}",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            raise_for_status(response.status_code, body)

        return body

    # ------------------------------------------------------------------
    # Agent auth / lifecycle
    # ------------------------------------------------------------------

    async def register(
        self,
        *,
        name: str,
        hive_id: str,
        secret: str,
        organization_id: str | None = None,
        agent_type: str = "custom",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        # Deprecated alias — use organization_id instead.
        superpos_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a new agent and store the returned token."""
        # Support deprecated superpos_id kwarg as fallback.
        _org_id = organization_id or superpos_id
        payload: dict[str, Any] = {
            "name": name,
            "hive_id": hive_id,
            "secret": secret,
            "type": agent_type,
        }
        if _org_id is not None:
            payload["organization_id"] = _org_id
        if capabilities is not None:
            payload["capabilities"] = capabilities
        if metadata is not None:
            payload["metadata"] = metadata

        data = await self._request("POST", "/api/v1/agents/register", json=payload)
        self.token = data["token"]
        self._event_cursors: dict[str, str] = {}
        return data

    async def login(self, *, agent_id: str, secret: str) -> dict[str, Any]:
        """Authenticate an existing agent and store the returned token."""
        data = await self._request(
            "POST",
            "/api/v1/agents/login",
            json={"agent_id": agent_id, "secret": secret},
        )
        self.token = data["token"]
        self._event_cursors: dict[str, str] = {}
        return data

    async def logout(self) -> None:
        """Revoke the current token."""
        try:
            await self._request("POST", "/api/v1/agents/logout")
        finally:
            self.token = None
            self._event_cursors.clear()

    async def me(self) -> dict[str, Any]:
        """Return the currently authenticated agent's profile."""
        return await self._request("GET", "/api/v1/agents/me")

    async def heartbeat(self, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a heartbeat to keep the agent alive."""
        payload: dict[str, Any] = {}
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._request("POST", "/api/v1/agents/heartbeat", json=payload)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def create_task(
        self,
        hive_id: str,
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
        """Create a new task in the given hive.

        When ``sub_agent_definition_slug`` is provided, the server resolves
        the slug to an active sub-agent definition in the target hive. See
        :meth:`superpos_sdk.SuperposClient.create_task` for details.
        """
        body: dict[str, Any] = {"type": task_type, "delivery_mode": delivery_mode}
        if priority is not None:
            body["priority"] = priority
        if target_agent_id is not None:
            body["target_agent_id"] = target_agent_id
        if target_capability is not None:
            body["target_capability"] = target_capability
        if payload is not None:
            body["payload"] = payload
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        if max_retries is not None:
            body["max_retries"] = max_retries
        if parent_task_id is not None:
            body["parent_task_id"] = parent_task_id
        if context_refs is not None:
            body["context_refs"] = context_refs
        if guarantee is not None:
            body["guarantee"] = guarantee
        if expires_at is not None:
            body["expires_at"] = expires_at
        if invoke_instructions is not None or invoke_context is not None:
            body["invoke"] = {}
            if invoke_instructions is not None:
                body["invoke"]["instructions"] = invoke_instructions
            if invoke_context is not None:
                body["invoke"]["context"] = invoke_context
        if failure_policy is not None:
            body["failure_policy"] = failure_policy
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        if sub_agent_definition_slug is not None:
            body["sub_agent_definition_slug"] = sub_agent_definition_slug
        task = await self._request("POST", f"/api/v1/hives/{hive_id}/tasks", json=body)
        return _attach_sub_agent(task)

    async def poll_tasks(
        self,
        hive_id: str,
        *,
        capability: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Poll for available tasks."""
        params: dict[str, Any] = {}
        if capability is not None:
            params["capability"] = capability
        if limit is not None:
            params["limit"] = limit
        tasks = await self._request(
            "GET", f"/api/v1/hives/{hive_id}/tasks/poll", params=params or None
        )
        if isinstance(tasks, list):
            for task in tasks:
                _attach_sub_agent(task)
        return tasks

    async def get_task(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Fetch a single task by ID.

        Async counterpart of :meth:`superpos_sdk.SuperposClient.get_task`.
        Returns the task dict in the same shape produced by the write
        endpoints (claim / complete / fail).
        """
        task = await self._request("GET", f"/api/v1/hives/{hive_id}/tasks/{task_id}")
        return _attach_sub_agent(task)

    async def claim_task(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Atomically claim a pending task.

        When the task has a sub-agent binding, the response includes a
        ``sub_agent`` block parsed into a
        :class:`~superpos_sdk.models.SubAgent`.
        """
        task = await self._request("PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/claim")
        return _attach_sub_agent(task)

    async def update_progress(
        self,
        hive_id: str,
        task_id: str,
        *,
        progress: int,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Report progress on a claimed task (0-100)."""
        body: dict[str, Any] = {"progress": progress}
        if status_message is not None:
            body["status_message"] = status_message
        return await self._request(
            "PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/progress", json=body
        )

    async def complete_task(
        self,
        hive_id: str,
        task_id: str,
        *,
        result: dict[str, Any] | list | None = None,
        status_message: str | None = None,
        delivery_mode: str | None = None,
        knowledge_entry_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark a claimed task as completed."""
        body: dict[str, Any] = {}
        if result is not None:
            body["result"] = result
        if status_message is not None:
            body["status_message"] = status_message
        if delivery_mode is not None:
            body["delivery_mode"] = delivery_mode
        if knowledge_entry_id is not None:
            body["knowledge_entry_id"] = knowledge_entry_id
        return await self._request(
            "PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/complete", json=body
        )

    async def fail_task(
        self,
        hive_id: str,
        task_id: str,
        *,
        error: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Mark a claimed task as failed."""
        body: dict[str, Any] = {}
        if error is not None:
            body["error"] = error
        if status_message is not None:
            body["status_message"] = status_message
        return await self._request(
            "PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/fail", json=body
        )

    async def get_task_trace(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Get the full execution trace for a task."""
        return await self._request("GET", f"/api/v1/hives/{hive_id}/tasks/{task_id}/trace")

    async def replay_task(
        self,
        hive_id: str,
        task_id: str,
        *,
        override_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a replay of a completed/failed/dead_letter/expired task."""
        body: dict[str, Any] = {}
        if override_payload is not None:
            body["override_payload"] = override_payload
        return await self._request(
            "POST", f"/api/v1/hives/{hive_id}/tasks/{task_id}/replay", json=body or None
        )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    async def list_knowledge(
        self,
        hive_id: str,
        *,
        key: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List knowledge entries in a hive."""
        params: dict[str, Any] = {}
        if key is not None:
            params["key"] = key
        if scope is not None:
            params["scope"] = scope
        if limit is not None:
            params["limit"] = limit
        return await self._request(
            "GET", f"/api/v1/hives/{hive_id}/knowledge", params=params or None
        )

    async def search_knowledge(
        self,
        hive_id: str,
        *,
        q: str | None = None,
        scope: str | None = None,
        mode: str | None = None,
        explain: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search knowledge entries.

        ``mode`` selects the ranking strategy: ``"hybrid"`` (default,
        RRF-fused FTS + pgvector + recency), ``"fts"`` (Postgres
        ``ts_query`` / ``ts_rank``), or ``"semantic"`` (pgvector cosine).
        When ``mode`` is ``None`` the server picks its own default.
        Pass ``explain=True`` to receive per-result ``score_breakdown``.
        """
        params: dict[str, Any] = {}
        if q is not None:
            params["q"] = q
        if scope is not None:
            params["scope"] = scope
        if mode is not None:
            params["mode"] = mode
        if explain:
            params["explain"] = "true"
        if limit is not None:
            params["limit"] = limit
        return await self._request(
            "GET", f"/api/v1/hives/{hive_id}/knowledge/search", params=params or None
        )

    async def get_knowledge(self, hive_id: str, entry_id: str) -> dict[str, Any]:
        """Get a single knowledge entry by ID."""
        return await self._request("GET", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}")

    async def create_knowledge(
        self,
        hive_id: str,
        *,
        key: str,
        value: Any,
        scope: str | None = None,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> dict[str, Any]:
        """Create a new knowledge entry."""
        body: dict[str, Any] = {"key": key, "value": value}
        if scope is not None:
            body["scope"] = scope
        if visibility is not None:
            body["visibility"] = visibility
        if ttl is not None:
            body["ttl"] = ttl
        return await self._request("POST", f"/api/v1/hives/{hive_id}/knowledge", json=body)

    async def update_knowledge(
        self,
        hive_id: str,
        entry_id: str,
        *,
        value: Any,
        visibility: str | None = None,
        ttl: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing knowledge entry (bumps version)."""
        body: dict[str, Any] = {"value": value}
        if visibility is not None:
            body["visibility"] = visibility
        if ttl is not None:
            body["ttl"] = ttl
        return await self._request(
            "PUT", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}", json=body
        )

    async def delete_knowledge(self, hive_id: str, entry_id: str) -> None:
        """Delete a knowledge entry."""
        await self._request("DELETE", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}")

    async def list_knowledge_links(
        self,
        hive_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        target_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List knowledge links filtered by source or target."""
        params: dict[str, Any] = {}
        if source_id is not None:
            params["source"] = source_id
        if target_id is not None:
            params["target_ref"] = target_id
        if target_type is not None:
            params["target_type"] = target_type
        if limit is not None:
            params["limit"] = limit
        return await self._request(
            "GET", f"/api/v1/hives/{hive_id}/knowledge/links", params=params or None
        )

    async def create_knowledge_link(
        self,
        hive_id: str,
        entry_id: str,
        *,
        target_id: str | None = None,
        target_type: str = "knowledge",
        target_ref: str | None = None,
        link_type: str = "relates_to",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a link from a knowledge entry to another entity."""
        body: dict[str, Any] = {"target_type": target_type, "link_type": link_type}
        if target_id is not None:
            body["target_id"] = target_id
        if target_ref is not None:
            body["target_ref"] = target_ref
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request(
            "POST", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}/links", json=body
        )

    async def delete_knowledge_link(self, hive_id: str, link_id: str) -> None:
        """Delete a knowledge link."""
        await self._request("DELETE", f"/api/v1/hives/{hive_id}/knowledge/links/{link_id}")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def poll_events(
        self,
        hive_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """Poll for new events matching the agent's subscriptions.

        Tracks the cursor internally (``_event_cursors``) so callers
        don't manage pagination state. When the response signals
        ``has_more`` the method re-polls until all events drain.
        """
        all_events: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {}
            cursor = self._event_cursors.get(hive_id)
            if cursor is not None:
                params["last_event_id"] = cursor
            elif since is not None:
                params["since"] = since
            if limit is not None:
                params["limit"] = limit

            envelope = await self._request_envelope(
                "GET", f"/api/v1/hives/{hive_id}/events/poll", params=params or None
            )

            events = envelope.get("data", []) or []
            meta = envelope.get("meta", {}) or {}
            all_events.extend(events)

            next_cursor = meta.get("next_cursor")
            if next_cursor is not None:
                self._event_cursors[hive_id] = next_cursor

            if meta.get("has_more", False):
                continue
            break

        return [Event.from_dict(e) for e in all_events]

    async def publish_event(
        self,
        hive_id: str,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish an event to the EventBus."""
        body: dict[str, Any] = {"type": event_type}
        if payload is not None:
            body["payload"] = payload
        return await self._request("POST", f"/api/v1/hives/{hive_id}/events", json=body)

    def reset_event_cursor(self, hive_id: str | None = None) -> None:
        """Reset the internal event poll cursor."""
        if hive_id is not None:
            self._event_cursors.pop(hive_id, None)
        else:
            self._event_cursors.clear()

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    async def list_schedules(
        self,
        hive_id: str,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List task schedules in a hive."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        return await self._request(
            "GET", f"/api/v1/hives/{hive_id}/schedules", params=params or None
        )

    async def create_schedule(
        self,
        hive_id: str,
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
        """Create a new task schedule."""
        body: dict[str, Any] = {
            "name": name,
            "trigger_type": trigger_type,
            "task_type": task_type,
        }
        if cron_expression is not None:
            body["cron_expression"] = cron_expression
        if interval_seconds is not None:
            body["interval_seconds"] = interval_seconds
        if run_at is not None:
            body["run_at"] = run_at
        if description is not None:
            body["description"] = description
        if task_payload is not None:
            body["task_payload"] = task_payload
        if task_priority is not None:
            body["task_priority"] = task_priority
        if task_target_agent_id is not None:
            body["task_target_agent_id"] = task_target_agent_id
        if task_target_capability is not None:
            body["task_target_capability"] = task_target_capability
        if task_timeout_seconds is not None:
            body["task_timeout_seconds"] = task_timeout_seconds
        if task_max_retries is not None:
            body["task_max_retries"] = task_max_retries
        if task_context_refs is not None:
            body["task_context_refs"] = task_context_refs
        if task_failure_policy is not None:
            body["task_failure_policy"] = task_failure_policy
        if overlap_policy is not None:
            body["overlap_policy"] = overlap_policy
        if expires_at is not None:
            body["expires_at"] = expires_at
        return await self._request("POST", f"/api/v1/hives/{hive_id}/schedules", json=body)

    async def delete_schedule(self, hive_id: str, schedule_id: str) -> None:
        """Delete a task schedule."""
        await self._request("DELETE", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}")

    # ------------------------------------------------------------------
    # Persona memory
    # ------------------------------------------------------------------

    async def update_memory(
        self,
        *,
        content: str,
        message: str | None = None,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Update the agent's MEMORY document (append/prepend/replace)."""
        if mode not in ("replace", "append", "prepend"):
            raise ValueError(f"Invalid mode {mode!r}. Allowed: replace, append, prepend.")
        body: dict[str, Any] = {"content": content, "mode": mode}
        if message is not None:
            body["message"] = message
        return await self._request("PATCH", "/api/v1/persona/memory", json=body)

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    async def list_channels(
        self,
        hive_id: str,
        *,
        status: str | None = None,
        channel_type: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List channels in a hive with optional filters."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if channel_type is not None:
            params["channel_type"] = channel_type
        if page is not None:
            params["page"] = page
        if per_page is not None:
            params["per_page"] = per_page
        return await self._request(
            "GET", f"/api/v1/hives/{hive_id}/channels", params=params or None
        )

    async def create_channel(
        self,
        hive_id: str,
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
        """Create a new channel in a hive."""
        body: dict[str, Any] = {"title": title, "channel_type": channel_type}
        if topic is not None:
            body["topic"] = topic
        if participants is not None:
            body["participants"] = participants
        if resolution_policy is not None:
            body["resolution_policy"] = resolution_policy
        if linked_refs is not None:
            body["linked_refs"] = linked_refs
        if on_resolve is not None:
            body["on_resolve"] = on_resolve
        if stale_after is not None:
            body["stale_after"] = stale_after
        if initial_message is not None:
            body["initial_message"] = initial_message
        if auto_invite is not None:
            body["auto_invite"] = auto_invite
        return await self._request("POST", f"/api/v1/hives/{hive_id}/channels", json=body)

    async def get_channel(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Get a single channel by ID."""
        return await self._request("GET", f"/api/v1/hives/{hive_id}/channels/{channel_id}")

    async def archive_channel(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Archive a channel (soft delete)."""
        return await self._request("DELETE", f"/api/v1/hives/{hive_id}/channels/{channel_id}")

    async def list_channel_messages(
        self,
        hive_id: str,
        channel_id: str,
        *,
        since: str | None = None,
        after_id: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List messages in a channel."""
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if after_id is not None:
            params["after_id"] = after_id
        if page is not None:
            params["page"] = page
        if per_page is not None:
            params["per_page"] = per_page
        return await self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages",
            params=params or None,
        )

    async def post_channel_message(
        self,
        hive_id: str,
        channel_id: str,
        body: str,
        *,
        message_type: str = "discussion",
        mentions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Post a new message to a channel."""
        payload: dict[str, Any] = {"content": body, "message_type": message_type}
        if mentions is not None:
            payload["mentions"] = mentions
        if metadata is not None:
            payload["metadata"] = metadata
        if reply_to is not None:
            payload["reply_to"] = reply_to
        return await self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages",
            json=payload,
        )

    async def add_channel_participant(
        self,
        hive_id: str,
        channel_id: str,
        participant_type: str,
        participant_id: str,
        *,
        role: str = "contributor",
        mention_policy: str | None = None,
    ) -> dict[str, Any]:
        """Add a participant to a channel."""
        body: dict[str, Any] = {
            "participant_type": participant_type,
            "participant_id": participant_id,
            "role": role,
        }
        if mention_policy is not None:
            body["mention_policy"] = mention_policy
        return await self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/participants",
            json=body,
        )

    async def remove_channel_participant(
        self,
        hive_id: str,
        channel_id: str,
        participant_id: str,
    ) -> None:
        """Remove a participant from a channel."""
        await self._request(
            "DELETE",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/participants/{participant_id}",
        )

    async def channel_summary(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Lightweight per-agent channel summary."""
        return await self._request("GET", f"/api/v1/hives/{hive_id}/channels/{channel_id}/summary")

    async def mark_channel_read(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Mark a channel as read for the authenticated agent."""
        return await self._request("POST", f"/api/v1/hives/{hive_id}/channels/{channel_id}/read")

    async def materialize_channel(
        self,
        hive_id: str,
        channel_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create tasks from a resolved channel's outcome."""
        return await self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/materialize",
            json={"tasks": tasks},
        )

    async def resolve_channel(
        self,
        hive_id: str,
        channel_id: str,
        *,
        outcome: str,
        materialized_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Manually resolve a channel."""
        body: dict[str, Any] = {"outcome": outcome}
        if materialized_tasks is not None:
            body["materialized_tasks"] = materialized_tasks
        return await self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/resolve",
            json=body,
        )

    async def reopen_channel(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Reopen a resolved or stale channel."""
        return await self._request("POST", f"/api/v1/hives/{hive_id}/channels/{channel_id}/reopen")

    # ------------------------------------------------------------------
    # Sub-agent definitions
    # ------------------------------------------------------------------

    async def get_sub_agent_definitions(self) -> list[SubAgentSummary]:
        """List active sub-agent definitions in the agent's hive.

        Async counterpart of
        :meth:`superpos_sdk.SuperposClient.get_sub_agent_definitions`.
        """
        data = await self._request("GET", "/api/v1/sub-agents")
        return [SubAgentSummary.from_dict(item) for item in (data or [])]

    async def get_sub_agent_definition(self, slug: str) -> SubAgentDefinition:
        """Get a sub-agent definition by slug (current active version)."""
        data = await self._request("GET", f"/api/v1/sub-agents/{slug}")
        return SubAgentDefinition.from_dict(data)

    async def get_sub_agent_assembled(self, slug: str) -> str:
        """Get the assembled system prompt for a sub-agent by slug."""
        data = await self._request("GET", f"/api/v1/sub-agents/{slug}/assembled")
        return data["prompt"]

    async def get_sub_agent_definition_by_id(self, sub_agent_id: str) -> SubAgentDefinition:
        """Get a sub-agent definition by ULID (version-stable)."""
        data = await self._request("GET", f"/api/v1/sub-agents/by-id/{sub_agent_id}")
        return SubAgentDefinition.from_dict(data)

    async def get_sub_agent_assembled_by_id(self, sub_agent_id: str) -> str:
        """Get the assembled system prompt for a sub-agent by ULID."""
        data = await self._request("GET", f"/api/v1/sub-agents/by-id/{sub_agent_id}/assembled")
        return data["prompt"]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def __aenter__(self) -> AsyncSuperposClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


__all__ = ["AsyncSuperposClient"]
