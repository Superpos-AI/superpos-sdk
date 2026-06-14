"""Core HTTP client with envelope parsing and auth management."""

from __future__ import annotations

from typing import Any

import httpx

from superpos_sdk.constants import CHANNEL_TYPES as _CHANNEL_TYPES_TUPLE
from superpos_sdk.exceptions import SuperposError, raise_for_status
from superpos_sdk.models import Event, SubAgent, SubAgentDefinition, SubAgentSummary

#: Valid channel types accepted by the API. Kept as a ``list`` for backward
#: compatibility with pre-0.2 callers; the canonical source is
#: :data:`superpos_sdk.constants.CHANNEL_TYPES` (a tuple).
CHANNEL_TYPES: list[str] = list(_CHANNEL_TYPES_TUPLE)


def _attach_sub_agent(task: Any) -> Any:
    """Parse a task's ``sub_agent`` block (if present) into a :class:`SubAgent`.

    Mutates the task dict in place so callers can continue to use ``task[...]``
    access while also benefitting from typed access via ``task["sub_agent"]``.
    Returns the task unchanged when the input is not a dict (e.g. None) so
    this helper can wrap any ``_request`` return value safely.

    The helper is a no-op when the response does not carry a ``sub_agent`` key
    at all (i.e. older servers / unrelated endpoints), preserving
    backward-compatible dict shapes. When the key is present but ``None``, it
    is left as ``None``. When the key is a dict, it is parsed into a
    :class:`SubAgent`.
    """
    if not isinstance(task, dict):
        return task
    if "sub_agent" not in task:
        return task
    block = task["sub_agent"]
    if isinstance(block, dict):
        task["sub_agent"] = SubAgent.from_dict(block)
    # None (or already a SubAgent) — leave as-is.
    return task


class SuperposClient:
    """Minimal Python client for the Superpos agent orchestration API.

    Usage::

        client = SuperposClient("https://superpos.example.com")
        data = client.register(
            name="my-agent",
            hive_id="01HXYZ...",
            secret="super-secret-value-16+",
        )
        # client.token is now set automatically

        tasks = client.poll_tasks(hive_id="01HXYZ...")
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Send a request, unwrap the Superpos envelope, raise on errors."""
        response = self._http.request(
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

    def _request_envelope(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Like :meth:`_request` but returns the full ``{data, meta, errors}`` envelope."""
        response = self._http.request(
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
    # Agent auth
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        hive_id: str,
        secret: str,
        registration_token: str | None = None,
        organization_id: str | None = None,
        agent_type: str = "custom",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        # Deprecated alias — use organization_id instead.
        superpos_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a new agent and store the returned token.

        ``registration_token`` is required by default on the server (when
        ``platform.agent_registration.require_token`` is enabled); pass the
        ``srt_…`` token issued by the hive to authorize registration.

        Returns the full ``data`` dict (``agent`` + ``token``).
        """
        # Support deprecated superpos_id kwarg as fallback.
        _org_id = organization_id or superpos_id
        payload: dict[str, Any] = {
            "name": name,
            "hive_id": hive_id,
            "secret": secret,
            "type": agent_type,
        }
        if registration_token is not None:
            payload["registration_token"] = registration_token
        if _org_id is not None:
            payload["organization_id"] = _org_id
        if capabilities is not None:
            payload["capabilities"] = capabilities
        if metadata is not None:
            payload["metadata"] = metadata

        data = self._request("POST", "/api/v1/agents/register", json=payload)
        self.token = data["token"]
        self._event_cursors: dict[str, str] = {}
        return data

    def login(self, *, agent_id: str, secret: str) -> dict[str, Any]:
        """Authenticate an existing agent and store the returned token."""
        data = self._request(
            "POST",
            "/api/v1/agents/login",
            json={"agent_id": agent_id, "secret": secret},
        )
        self.token = data["token"]
        self._event_cursors: dict[str, str] = {}
        return data

    def logout(self) -> None:
        """Revoke the current token."""
        try:
            self._request("POST", "/api/v1/agents/logout")
        finally:
            self.token = None
            self._event_cursors: dict[str, str] = {}

    def me(self) -> dict[str, Any]:
        """Return the currently authenticated agent's profile."""
        return self._request("GET", "/api/v1/agents/me")

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def heartbeat(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """Send a heartbeat to keep the agent alive.

        ``model`` and ``effort`` are optional free-form labels (e.g.
        ``claude-opus-4-7`` and ``low``/``medium``/``high``) that surface on
        the agent's dashboard row when provided.
        """
        payload: dict[str, Any] = {}
        if metadata is not None:
            payload["metadata"] = metadata
        if model is not None:
            payload["model"] = model
        if effort is not None:
            payload["effort"] = effort
        return self._request("POST", "/api/v1/agents/heartbeat", json=payload)

    def update_status(self, status: str) -> dict[str, Any]:
        """Update the agent's status (online/busy/idle/offline/error)."""
        return self._request("PATCH", "/api/v1/agents/status", json={"status": status})

    def update_capabilities(self, capabilities: list[str]) -> dict[str, Any]:
        """Update the agent's capabilities. Requires agents:write permission."""
        return self._request(
            "PUT",
            "/api/v1/agents/capabilities",
            json={"capabilities": capabilities},
        )

    # ------------------------------------------------------------------
    # Drain mode
    # ------------------------------------------------------------------

    def enter_drain(
        self,
        *,
        reason: str | None = None,
        deadline_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Enter drain mode. The agent stops accepting new tasks."""
        body: dict[str, Any] = {}
        if reason is not None:
            body["reason"] = reason
        if deadline_minutes is not None:
            body["deadline_minutes"] = deadline_minutes
        return self._request("POST", "/api/v1/agents/drain", json=body or None)

    def exit_drain(self) -> dict[str, Any]:
        """Exit drain mode, restoring normal operation."""
        return self._request("POST", "/api/v1/agents/undrain")

    def drain_status(self) -> dict[str, Any]:
        """Get current drain status for the authenticated agent."""
        return self._request("GET", "/api/v1/agents/drain")

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_key(
        self,
        *,
        new_secret: str,
        grace_period_minutes: int = 0,
    ) -> dict[str, Any]:
        """Rotate the agent's API key. Returns a new token.

        The old key remains valid for ``grace_period_minutes`` (0 = immediate).
        """
        body: dict[str, Any] = {"new_secret": new_secret}
        if grace_period_minutes:
            body["grace_period_minutes"] = grace_period_minutes
        data = self._request("POST", "/api/v1/agents/key/rotate", json=body)
        self.token = data["token"]
        return data

    def revoke_previous_key(self) -> dict[str, Any]:
        """Immediately revoke the previous (grace-period) key."""
        return self._request("POST", "/api/v1/agents/key/revoke")

    def key_status(self) -> dict[str, Any]:
        """Get current key rotation status."""
        return self._request("GET", "/api/v1/agents/key/status")

    # ------------------------------------------------------------------
    # Pool health
    # ------------------------------------------------------------------

    def get_pool_health(
        self,
        hive_id: str,
        *,
        window: int | None = None,
    ) -> dict[str, Any]:
        """Get pool health metrics (agents, backlog, throughput) for a hive."""
        params: dict[str, Any] = {}
        if window is not None:
            params["window"] = window
        return self._request("GET", f"/api/v1/hives/{hive_id}/pool/health", params=params or None)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(
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

        When ``sub_agent_definition_slug`` is provided, the server resolves the
        slug to an active sub-agent definition in the target hive and binds it
        to the task. Invalid or unknown slugs fail open — the task is still
        created without a sub-agent binding (see TASK-263).
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
        task = self._request("POST", f"/api/v1/hives/{hive_id}/tasks", json=body)
        return _attach_sub_agent(task)

    def poll_tasks(
        self,
        hive_id: str,
        *,
        capability: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Poll for available tasks. Returns a list (may be empty).

        The response envelope also contains ``meta.persona_version`` — the
        server-assigned persona version for this agent. Use
        :meth:`poll_tasks_with_meta` when you need to inspect that field.
        """
        params: dict[str, Any] = {}
        if capability is not None:
            params["capability"] = capability
        if limit is not None:
            params["limit"] = limit
        tasks = self._request("GET", f"/api/v1/hives/{hive_id}/tasks/poll", params=params)
        if isinstance(tasks, list):
            for task in tasks:
                _attach_sub_agent(task)
        return tasks

    def poll_tasks_with_meta(
        self,
        hive_id: str,
        *,
        capability: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Poll for available tasks and return the full envelope.

        Unlike :meth:`poll_tasks`, this method returns the full
        ``{data, meta, errors}`` envelope so callers can inspect
        ``meta["persona_version"]``, ``meta["platform_context_version"]``,
        ``meta["environment_version"]``, and ``meta["github_version"]``
        and react to persona, platform context, hive environment, or
        GitHub connection changes without issuing a separate request.

        Example::

            envelope = client.poll_tasks_with_meta(hive_id)
            tasks = envelope["data"]
            meta = envelope.get("meta", {})
            server_persona_version = meta.get("persona_version")
            server_platform_version = meta.get("platform_context_version")
            server_environment_version = meta.get("environment_version")
            server_github_version = meta.get("github_version")
            if server_persona_version != my_cached_version:
                persona = client.get_persona()  # refresh local cache
            if server_platform_version != my_cached_platform_version:
                persona = client.get_persona()  # includes platform_context
            if server_environment_version != my_cached_environment_version:
                assembled = client.get_persona_assembled()  # includes environment
            if server_github_version != my_cached_github_version:
                persona = client.get_persona()  # includes github block
        """
        params: dict[str, Any] = {}
        if capability is not None:
            params["capability"] = capability
        if limit is not None:
            params["limit"] = limit
        envelope = self._request_envelope(
            "GET", f"/api/v1/hives/{hive_id}/tasks/poll", params=params or None
        )
        data = envelope.get("data")
        if isinstance(data, list):
            for task in data:
                _attach_sub_agent(task)
        return envelope

    def get_task(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Fetch a single task by ID.

        Returns the task dict in the same shape produced by the write
        endpoints (claim / complete / fail). Raises
        :class:`~superpos_sdk.exceptions.NotFoundError` when the task does
        not exist in the target hive or the caller's apiary.
        """
        task = self._request("GET", f"/api/v1/hives/{hive_id}/tasks/{task_id}")
        return _attach_sub_agent(task)

    def claim_task(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Atomically claim a pending task.

        When the task has a sub-agent binding, the response includes a
        ``sub_agent`` block with the assembled prompt, config, and allowed
        tools. The SDK parses this block into a
        :class:`~superpos_sdk.models.SubAgent` instance exposed as
        ``task["sub_agent"]``. For tasks without a binding (or when the
        definition has been deleted), ``task["sub_agent"]`` is ``None``.
        """
        task = self._request("PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/claim")
        return _attach_sub_agent(task)

    def update_progress(
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
        return self._request(
            "PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/progress", json=body
        )

    def complete_task(
        self,
        hive_id: str,
        task_id: str,
        *,
        result: dict[str, Any] | list | None = None,
        status_message: str | None = None,
        delivery_mode: str | None = None,
        knowledge_entry_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark a claimed task as completed.

        For normal completions pass *result* directly (dict or list payloads
        are both supported).  For knowledge-store delivery (large results
        pre-stored via :class:`~superpos_sdk.large_result.LargeResultDelivery`)
        pass ``delivery_mode="knowledge"`` and *knowledge_entry_id* instead.
        """
        body: dict[str, Any] = {}
        if result is not None:
            body["result"] = result
        if status_message is not None:
            body["status_message"] = status_message
        if delivery_mode is not None:
            body["delivery_mode"] = delivery_mode
        if knowledge_entry_id is not None:
            body["knowledge_entry_id"] = knowledge_entry_id
        return self._request(
            "PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/complete", json=body
        )

    def complete_task_large(
        self,
        hive_id: str,
        task_id: str,
        result: Any,
        *,
        status_message: str | None = None,
        key: str | None = None,
        threshold_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Complete a task, automatically offloading large results to the Knowledge Store.

        Serialises *result* and measures its UTF-8 byte length.  If the
        payload exceeds the threshold (default 1 MB) it is written to a new
        hive-scoped knowledge entry and the task is completed with
        ``delivery_mode="knowledge"``.  Small payloads are completed inline.

        This is a convenience wrapper around
        :meth:`complete_task` +
        :class:`~superpos_sdk.large_result.LargeResultDelivery`.

        Args:
            hive_id: Hive that owns the task (and where the knowledge entry
                will be created when the result is large).
            task_id: ID of the in-progress task to complete.
            result: Result data (must be JSON-serialisable).
            status_message: Optional human-readable status message.
            key: Knowledge entry key override (default
                ``"task-result:<task_id>"``).
            threshold_bytes: Override the 1 MB threshold.

        Returns:
            The completed task dict returned by the server.
        """
        # Import here to avoid a circular import at module level.
        from superpos_sdk.large_result import LargeResultDelivery  # noqa: PLC0415

        kwargs: dict[str, int] = {}
        if threshold_bytes is not None:
            kwargs["threshold_bytes"] = threshold_bytes

        delivery = LargeResultDelivery(self, **kwargs)
        completion = delivery.deliver(task_id, hive_id, result, key=key)

        return self.complete_task(
            hive_id,
            task_id,
            status_message=status_message,
            **completion,
        )

    def deliver_response_task(
        self,
        hive_id: str,
        response_task_id: str,
        data: dict[str, Any],
        *,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Deliver a response to a pending data_request response task.

        Uses the dedicated ``POST /deliver-response`` endpoint which bypasses
        the normal in_progress/ownership requirements.  The server authorises
        the call by verifying the calling agent has an in_progress task whose
        ``payload.response_task_id`` matches *response_task_id*.

        Args:
            hive_id: Hive the calling agent belongs to.
            response_task_id: ID of the pending response task to complete.
            data: Result payload to store on the response task.
            status_message: Optional human-readable status message.

        Returns:
            The completed task dict.
        """
        body: dict[str, Any] = {"result": data}
        if status_message is not None:
            body["status_message"] = status_message
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/tasks/{response_task_id}/deliver-response",
            json=body,
        )

    def fail_task(
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
        return self._request("PATCH", f"/api/v1/hives/{hive_id}/tasks/{task_id}/fail", json=body)

    def send_stream_chunk(
        self,
        hive_id: str,
        task_id: str,
        *,
        data: dict[str, Any],
        sequence: int | None = None,
        is_final: bool = False,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Deliver one chunk of a streaming task result.

        The target task must be ``in_progress`` with ``delivery_mode='stream'``
        and claimed by the calling agent.  Creates a child ``stream_chunk`` task.

        When *is_final* is ``True`` the parent task is marked completed and no
        further chunks can be delivered.

        Args:
            hive_id: The hive that owns the parent task.
            task_id: ID of the parent stream task.
            data: Chunk payload dict.
            sequence: Chunk sequence number.  The server auto-increments when
                ``None``.
            is_final: Whether this is the last chunk (completes the parent).
            status_message: Optional human-readable status stored on the chunk.

        Returns:
            Dict with ``chunk`` and ``parent`` task dicts.
        """
        body: dict[str, Any] = {"data": data, "is_final": is_final}
        if sequence is not None:
            body["sequence"] = sequence
        if status_message is not None:
            body["status_message"] = status_message
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/tasks/{task_id}/stream-chunk",
            json=body,
        )

    def get_stream_chunks(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Retrieve all stream chunk child tasks for a stream-mode parent task.

        Returns chunks ordered by ``stream_sequence`` ascending, along with
        metadata about the parent task (``parent_task_id``, ``stream_complete``,
        ``count``).

        Args:
            hive_id: The hive that owns the parent task.
            task_id: ID of the parent stream task.

        Returns:
            API envelope whose ``data`` list contains chunk dicts (each with
            ``id``, ``result``, ``stream_sequence``, ``created_at``) and whose
            ``meta`` dict contains ``parent_task_id``, ``stream_complete``, and
            ``count``.
        """
        return self._request_envelope(
            "GET",
            f"/api/v1/hives/{hive_id}/tasks/{task_id}/stream-chunks",
        )

    # ------------------------------------------------------------------
    # Task replay / time travel
    # ------------------------------------------------------------------

    def get_task_trace(self, hive_id: str, task_id: str) -> dict[str, Any]:
        """Get the full execution trace for a task."""
        return self._request("GET", f"/api/v1/hives/{hive_id}/tasks/{task_id}/trace")

    def replay_task(
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
        return self._request(
            "POST", f"/api/v1/hives/{hive_id}/tasks/{task_id}/replay", json=body or None
        )

    def compare_tasks(
        self,
        hive_id: str,
        *,
        task_a: str,
        task_b: str,
    ) -> dict[str, Any]:
        """Compare two tasks by payload, result, and trace."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/tasks/compare",
            params={"task_a": task_a, "task_b": task_b},
        )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def list_knowledge(
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
        return self._request("GET", f"/api/v1/hives/{hive_id}/knowledge", params=params)

    def search_knowledge(
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
        return self._request("GET", f"/api/v1/hives/{hive_id}/knowledge/search", params=params)

    def get_knowledge(self, hive_id: str, entry_id: str) -> dict[str, Any]:
        """Get a single knowledge entry by ID."""
        return self._request("GET", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}")

    def create_knowledge(
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
        return self._request("POST", f"/api/v1/hives/{hive_id}/knowledge", json=body)

    def update_knowledge(
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
        return self._request("PUT", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}", json=body)

    def delete_knowledge(self, hive_id: str, entry_id: str) -> None:
        """Delete a knowledge entry."""
        self._request("DELETE", f"/api/v1/hives/{hive_id}/knowledge/{entry_id}")

    # ------------------------------------------------------------------
    # Knowledge links
    # ------------------------------------------------------------------

    def create_knowledge_link(
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
        """Create a link from a knowledge entry to another entity.

        Args:
            hive_id: Hive that owns the source entry.
            entry_id: ID of the source knowledge entry.
            target_id: ID of the target knowledge entry (required when
                *target_type* is ``"knowledge"``).
            target_type: Type of the target entity — ``"knowledge"``
                (default), ``"task"``, ``"channel"``, or ``"agent"``.
            target_ref: Reference identifier for non-knowledge targets.
            link_type: Relationship type — ``"relates_to"`` (default),
                ``"depends_on"``, ``"supersedes"``, ``"derived_from"``,
                ``"decided_in"``, ``"implemented_by"``, ``"authored_by"``,
                or ``"part_of"``.
            metadata: Optional JSONB metadata attached to the link.

        Returns:
            The created link dict.
        """
        body: dict[str, Any] = {
            "target_type": target_type,
            "link_type": link_type,
        }
        if target_id is not None:
            body["target_id"] = target_id
        if target_ref is not None:
            body["target_ref"] = target_ref
        if metadata is not None:
            body["metadata"] = metadata
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/knowledge/{entry_id}/links",
            json=body,
        )

    def list_knowledge_links(
        self,
        hive_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        target_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List knowledge links filtered by source or target.

        Either *source_id* or both *target_id* and *target_type* must be
        provided — the API requires one of the two filter combinations.

        Args:
            hive_id: Hive to query.
            source_id: Filter by source knowledge entry ID.
            target_id: Filter by target reference (used with *target_type*).
            target_type: Filter by target type (used with *target_id*).
            limit: Maximum number of links to return (1–100, default 50).

        Returns:
            List of link dicts.
        """
        params: dict[str, Any] = {}
        if source_id is not None:
            params["source"] = source_id
        if target_id is not None:
            params["target_ref"] = target_id
        if target_type is not None:
            params["target_type"] = target_type
        if limit is not None:
            params["limit"] = limit
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/links",
            params=params,
        )

    def delete_knowledge_link(self, hive_id: str, link_id: str) -> None:
        """Delete a knowledge link.

        Args:
            hive_id: Hive that owns the link's source entry.
            link_id: ID of the link to delete.
        """
        self._request(
            "DELETE",
            f"/api/v1/hives/{hive_id}/knowledge/links/{link_id}",
        )

    def confirm_knowledge_link(self, hive_id: str, link_id: str) -> dict[str, Any]:
        """Confirm a suggested knowledge link.

        Promotes a link with ``status: suggested`` to ``status: confirmed``.

        Args:
            hive_id: Hive that owns the link's source entry.
            link_id: ID of the suggested link to confirm.

        Returns:
            The confirmed link dict.
        """
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/knowledge/links/{link_id}/confirm",
        )

    def dismiss_knowledge_link(self, hive_id: str, link_id: str) -> dict[str, Any]:
        """Dismiss a suggested knowledge link.

        Marks the suggestion as dismissed so it is excluded from future
        listings.

        Args:
            hive_id: Hive that owns the link's source entry.
            link_id: ID of the suggested link to dismiss.

        Returns:
            The dismissed link dict.
        """
        return self._request(
            "DELETE",
            f"/api/v1/hives/{hive_id}/knowledge/links/{link_id}/dismiss",
        )

    def suggested_links(
        self,
        hive_id: str,
        entry_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List suggested (auto-detected) links for a knowledge entry.

        Args:
            hive_id: Hive that owns the entry.
            entry_id: ID of the knowledge entry.
            limit: Maximum number of suggestions to return (1–100, default 50).

        Returns:
            List of suggested link dicts.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/{entry_id}/suggested-links",
            params=params or None,
        )

    # ------------------------------------------------------------------
    # Knowledge graph traversal
    # ------------------------------------------------------------------

    def get_knowledge_graph(
        self,
        hive_id: str,
        entry_id: str,
        *,
        depth: int | None = None,
        link_types: str | None = None,
        max_nodes: int | None = None,
    ) -> dict[str, Any]:
        """Traverse the knowledge graph starting from an entry.

        Returns a graph structure with nodes and edges reachable from the
        given entry within the specified depth.

        Args:
            hive_id: Hive that owns the root entry.
            entry_id: ID of the root knowledge entry.
            depth: Maximum traversal depth (1–5, default 2).
            link_types: Comma-separated list of link types to traverse
                (e.g. ``"relates_to,depends_on"``). All types if omitted.
            max_nodes: Maximum number of nodes to return (1–200, default 50).

        Returns:
            Graph dict with ``nodes`` and ``edges``.
        """
        params: dict[str, Any] = {}
        if depth is not None:
            params["depth"] = depth
        if link_types is not None:
            params["link_types"] = link_types
        if max_nodes is not None:
            params["max_nodes"] = max_nodes
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/{entry_id}/graph",
            params=params or None,
        )

    # ------------------------------------------------------------------
    # Knowledge index & health
    # ------------------------------------------------------------------

    def knowledge_topics(self, hive_id: str) -> dict[str, Any]:
        """Get the auto-maintained topics index for a hive.

        Returns the ``_index:topics`` knowledge entry containing extracted
        topic clusters from the hive's knowledge base.

        Args:
            hive_id: Hive to query.

        Returns:
            The topics index entry dict.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/index/topics",
        )

    def knowledge_decisions(self, hive_id: str) -> dict[str, Any]:
        """Get the auto-maintained decisions index for a hive.

        Returns the ``_index:decisions`` knowledge entry containing extracted
        decisions from the hive's knowledge base.

        Args:
            hive_id: Hive to query.

        Returns:
            The decisions index entry dict.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/index/decisions",
        )

    def knowledge_by_agent(
        self,
        hive_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        """Get the agent-specific knowledge index.

        Returns the ``_index:agent:{agent_id}`` knowledge entry for the
        calling agent. Agents can only access their own agent index.

        Args:
            hive_id: Hive to query.
            agent_id: ID of the agent (must be the authenticated agent).

        Returns:
            The agent index entry dict.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/index/agent/{agent_id}",
        )

    def knowledge_health(self, hive_id: str) -> dict[str, Any]:
        """Get the knowledge base health score and metrics for a hive.

        Returns a health score (0–100), letter grade, detailed metrics
        (coverage, freshness, linking density, etc.), and recommendations
        for improving the knowledge base.

        Args:
            hive_id: Hive to query.

        Returns:
            Health dict with ``score``, ``grade``, ``metrics``, and
            ``recommendations``.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/knowledge/health",
        )

    # ------------------------------------------------------------------
    # Context threads
    # ------------------------------------------------------------------

    def list_threads(
        self,
        hive_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List context threads in a hive."""
        params: dict[str, Any] = {"limit": limit}
        return self._request("GET", f"/api/v1/hives/{hive_id}/threads", params=params)

    def create_thread(
        self,
        hive_id: str,
        *,
        title: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new context thread, optionally seeded with an initial message."""
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if message is not None:
            body["message"] = message
        if metadata is not None:
            body["metadata"] = metadata
        return self._request("POST", f"/api/v1/hives/{hive_id}/threads", json=body)

    def get_thread(self, hive_id: str, thread_id: str) -> dict[str, Any]:
        """Get a single context thread with full message history."""
        return self._request("GET", f"/api/v1/hives/{hive_id}/threads/{thread_id}")

    def append_thread_message(
        self,
        hive_id: str,
        thread_id: str,
        message: str,
        *,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a message to a context thread."""
        body: dict[str, Any] = {"message": message}
        if task_id is not None:
            body["task_id"] = task_id
        if metadata is not None:
            body["metadata"] = metadata
        url = f"/api/v1/hives/{hive_id}/threads/{thread_id}/messages"
        return self._request("POST", url, json=body)

    def clear_thread_messages(self, hive_id: str, thread_id: str) -> dict[str, Any]:
        """Clear all messages from a context thread (thread itself is kept)."""
        return self._request("DELETE", f"/api/v1/hives/{hive_id}/threads/{thread_id}/messages")

    def delete_thread(self, hive_id: str, thread_id: str) -> None:
        """Delete a context thread and all its messages."""
        self._request("DELETE", f"/api/v1/hives/{hive_id}/threads/{thread_id}")

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    def list_schedules(
        self,
        hive_id: str,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List task schedules in a hive."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        return self._request("GET", f"/api/v1/hives/{hive_id}/schedules", params=params or None)

    def get_schedule(self, hive_id: str, schedule_id: str) -> dict[str, Any]:
        """Get a single task schedule by ID."""
        return self._request("GET", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}")

    def create_schedule(
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
        return self._request("POST", f"/api/v1/hives/{hive_id}/schedules", json=body)

    def update_schedule(
        self,
        hive_id: str,
        schedule_id: str,
        **fields: Any,
    ) -> dict[str, Any]:
        """Update a task schedule. Pass only the fields to change."""
        return self._request("PUT", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}", json=fields)

    def delete_schedule(self, hive_id: str, schedule_id: str) -> None:
        """Delete a task schedule."""
        self._request("DELETE", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}")

    def pause_schedule(self, hive_id: str, schedule_id: str) -> dict[str, Any]:
        """Pause an active schedule."""
        return self._request("PATCH", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}/pause")

    def resume_schedule(self, hive_id: str, schedule_id: str) -> dict[str, Any]:
        """Resume a paused schedule."""
        return self._request("PATCH", f"/api/v1/hives/{hive_id}/schedules/{schedule_id}/resume")

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    def rate_limit_status(self) -> dict[str, Any]:
        """Get current rate limit configuration and usage for this agent."""
        return self._request("GET", "/api/v1/agents/rate-limit")

    def update_rate_limit(
        self,
        *,
        rate_limit_per_minute: int | None,
    ) -> dict[str, Any]:
        """Update the per-agent rate limit. Pass None to reset to system default."""
        return self._request(
            "PUT",
            "/api/v1/agents/rate-limit",
            json={"rate_limit_per_minute": rate_limit_per_minute},
        )

    # ------------------------------------------------------------------
    # Persona
    # ------------------------------------------------------------------

    def get_persona_version(
        self,
        *,
        known_version: int | None = None,
        known_platform_version: int | None = None,
        known_environment_version: str | None = None,
        known_github_version: str | None = None,
    ) -> dict[str, Any]:
        """Get the server-assigned persona version for this agent.

        Lightweight alternative to :meth:`get_persona` — fetches only the version
        number without downloading full documents. Use this in poll loops to detect
        persona changes efficiently.

        Args:
            known_version: If provided, the response will include a ``changed``
                boolean comparing the server version against this value.
            known_platform_version: If provided, platform context version changes
                will also be factored into the ``changed`` flag. Without this,
                only persona version changes are detected.
            known_environment_version: If provided, hive environment (siblings,
                service connections, webhook routes) version changes will also
                be factored into the ``changed`` flag. The value is a hex
                content-hash returned by a previous call as
                ``environment_version``; compared case-insensitively.
            known_github_version: If provided, GitHub connection permission
                changes will also be factored into the ``changed`` flag.
                The value is a hex content-hash returned by a previous call
                as ``github_version``; compared case-insensitively.

        Returns:
            A dict with ``version`` (int | None), ``platform_context_version``
            (int | None), ``environment_version`` (str),
            ``github_version`` (str), and optionally ``changed`` (bool).
        """
        params: dict[str, Any] = {}
        if known_version is not None:
            params["known_version"] = known_version
        if known_platform_version is not None:
            params["known_platform_version"] = known_platform_version
        if known_environment_version is not None:
            params["known_environment_version"] = known_environment_version
        if known_github_version is not None:
            params["known_github_version"] = known_github_version
        return self._request("GET", "/api/v1/persona/version", params=params or None)

    def check_persona_version(
        self,
        known_version: int | None,
        known_platform_version: int | None = None,
        known_environment_version: str | None = None,
        known_github_version: str | None = None,
    ) -> bool:
        """Return True if the server-assigned persona version differs from *known_version*.

        Calls ``GET /api/v1/persona/version?known_version=N`` and returns the
        ``changed`` field. Returns True (treat as changed) when the agent has no
        persona assigned (version is None) and *known_version* is also None only if
        the server explicitly signals a change; otherwise returns False for None/None.

        Args:
            known_version: The version number the agent currently holds locally.
            known_platform_version: The platform context version the agent
                currently holds locally. When provided, platform context changes
                will also trigger a refresh.
            known_environment_version: The hive environment version (hex
                content-hash) the agent currently holds locally. When provided,
                environment changes (sibling agents, service connections,
                webhook routes) will also trigger a refresh.
            known_github_version: The GitHub connection version (hex
                content-hash) the agent currently holds locally. When provided,
                GitHub connection permission changes will also trigger a refresh.

        Returns:
            True if the persona should be refreshed, False otherwise.
        """
        result = self.get_persona_version(
            known_version=known_version,
            known_platform_version=known_platform_version,
            known_environment_version=known_environment_version,
            known_github_version=known_github_version,
        )
        return bool(result.get("changed", False))

    def get_persona(self) -> dict[str, Any]:
        """Get the agent's active persona (policy-selected version).

        The response includes ``platform_context`` (str | None) and
        ``platform_context_version`` (int | None) so agents can access the
        shared platform SDK knowledge without a separate call to
        :meth:`get_persona_assembled`.
        """
        return self._request("GET", "/api/v1/persona")

    def get_persona_config(self) -> dict[str, Any]:
        """Get persona config only."""
        return self._request("GET", "/api/v1/persona/config")

    def get_persona_document(self, name: str) -> dict[str, Any]:
        """Get a single persona document by name."""
        return self._request("GET", f"/api/v1/persona/documents/{name}")

    def get_persona_assembled(self) -> dict[str, Any]:
        """Get pre-assembled system prompt (SOUL→AGENT→RULES→STYLE→EXAMPLES→MEMORY)."""
        return self._request("GET", "/api/v1/persona/assembled")

    def update_persona_document(
        self,
        name: str,
        *,
        content: str,
        message: str | None = None,
        mode: str = "replace",
    ) -> dict[str, Any]:
        """Update a single persona document (agent self-update).

        Args:
            name: Document name (SOUL, AGENT, RULES, STYLE, EXAMPLES, MEMORY).
            content: New content for the document.
            message: Optional human-readable commit message.
            mode: How to apply *content*. One of:
                - ``"replace"`` (default) — overwrite the document entirely.
                - ``"append"``  — add *content* after the existing text.
                - ``"prepend"`` — add *content* before the existing text.
        """
        if mode not in ("replace", "append", "prepend"):
            raise ValueError(f"Invalid mode {mode!r}. Allowed: replace, append, prepend.")
        body: dict[str, Any] = {"content": content, "mode": mode}
        if message is not None:
            body["message"] = message
        return self._request("PATCH", f"/api/v1/persona/documents/{name}", json=body)

    def update_memory(
        self,
        *,
        content: str,
        message: str | None = None,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Update the agent's MEMORY document.

        Calls the dedicated ``PATCH /api/v1/persona/memory`` endpoint.
        Agents use this to persist learned facts, project context, and runtime
        observations across executions.

        Args:
            content: Content to write to the MEMORY document.
            message: Optional human-readable commit message (e.g. "learned new auth pattern").
            mode: How to apply *content*. One of:
                - ``"append"``  (default) — add *content* after existing text.
                - ``"prepend"`` — add *content* before existing text.
                - ``"replace"`` — overwrite the document entirely.
        """
        if mode not in ("replace", "append", "prepend"):
            raise ValueError(f"Invalid mode {mode!r}. Allowed: replace, append, prepend.")
        body: dict[str, Any] = {"content": content, "mode": mode}
        if message is not None:
            body["message"] = message
        return self._request("PATCH", "/api/v1/persona/memory", json=body)

    # ------------------------------------------------------------------
    # Service workers
    # ------------------------------------------------------------------

    def data_request(
        self,
        hive_id: str,
        *,
        capability: str,
        operation: str,
        params: dict[str, Any] | None = None,
        delivery: str = "task_result",
        result_format: str | None = None,
        continuation_of: str | None = None,
        response_task_id: str | None = None,
        timeout_seconds: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a ``data_request`` task targeting a service worker capability.

        This is a convenience wrapper around :meth:`create_task` for the
        service worker pattern.  The agent does **not** block — it gets back a
        ``task_id`` and continues doing other work.  On the next poll cycle it
        can check the task status with ``GET /api/v1/hives/{hive_id}/tasks/{task_id}``.

        Example::

            ref = client.data_request(
                hive_id,
                capability="data:gmail",
                operation="fetch_emails",
                params={"query": "from:client@acme.com", "max_results": 50},
            )
            task_id = ref["id"]  # save this, check later

        Args:
            hive_id: Hive to create the task in.
            capability: Service worker capability to target (e.g. ``"data:gmail"``).
            operation: Operation name (e.g. ``"fetch_emails"``).
            params: Operation-specific parameters passed to the worker.
            delivery: Result delivery mode — ``"task_result"`` (default) or
                ``"knowledge"``.
            result_format: Optional hint to the worker (e.g. ``"array"``).
            continuation_of: Task ID of a previous request to continue from
                (pagination / resumable operations).
            response_task_id: If set, the worker will call
                ``POST /tasks/{id}/deliver-response`` with *this* task ID to
                push the result (push-style delivery).
            timeout_seconds: Task-level timeout.
            idempotency_key: Idempotency key to prevent duplicate requests.

        Returns:
            The created task dict (``{id, status, ...}``).
        """
        payload: dict[str, Any] = {
            "operation": operation,
            "delivery": delivery,
        }
        if params is not None:
            payload["params"] = params
        if result_format is not None:
            payload["result_format"] = result_format
        if continuation_of is not None:
            payload["continuation_of"] = continuation_of
        if response_task_id is not None:
            payload["response_task_id"] = response_task_id

        return self.create_task(
            hive_id,
            task_type="data_request",
            target_capability=capability,
            payload=payload,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    def discover_services(
        self,
        hive_id: str,
        *,
        capability_prefix: str = "data:",
    ) -> list[dict[str, Any]]:
        """List service workers registered in a hive.

        Queries the agents endpoint filtered to the ``data:*`` capability
        prefix (or a custom prefix) and returns the matching agent records.
        Each record includes ``metadata.supported_operations`` when the worker
        has declared them.

        Example::

            services = client.discover_services(hive_id)
            for svc in services:
                print(svc["name"], svc.get("metadata", {}).get("supported_operations"))

        Args:
            hive_id: Hive to query.
            capability_prefix: Capability prefix to filter on
                (default ``"data:"``).

        Returns:
            List of agent dicts matching the capability prefix.
        """
        agents = self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/agents",
            params={"capability": capability_prefix},
        )
        if not isinstance(agents, list):
            return []
        return [
            a
            for a in agents
            if any(str(cap).startswith(capability_prefix) for cap in (a.get("capabilities") or []))
        ]

    def discover_service_catalog(
        self,
        hive_id: str,
        *,
        service_type: str | None = None,
        capability: str | None = None,
        status: str = "active",
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        """List service connections available in a hive via the catalog API.

        Queries ``GET /api/v1/hives/{hive}/services`` and returns all pages
        as a flat list.  Requires the ``services:read`` permission.

        Example::

            services = client.discover_service_catalog(hive_id)
            for svc in services:
                print(svc["name"], svc["service_type"], svc["capabilities"])

        Args:
            hive_id: Hive to query.
            service_type: Optional service type filter (e.g. ``"github"``).
            capability: Optional capability tag filter.
            status: Status filter — ``"active"`` (default), ``"inactive"``,
                or ``"all"``.
            per_page: Page size (1–100, default 50).

        Returns:
            Flat list of service connection dicts from all pages.
        """
        # Clamp per_page to the valid API range (1–100) so the pagination
        # sentinel ``len(page) < effective_per_page`` is always correct.
        # Without clamping: per_page>100 → API returns 100 items but
        # len(100) < 500 is False → first page treated as last page.
        # per_page<=0 → API returns 1 item but len([]) < 0 is always
        # False → potential infinite loop.
        effective_per_page = max(1, min(per_page, 100))

        params: dict[str, Any] = {"status": status, "per_page": effective_per_page}

        if service_type is not None:
            params["type"] = service_type

        if capability is not None:
            params["capability"] = capability

        results: list[dict[str, Any]] = []
        page = 1

        while True:
            params["page"] = page
            envelope = self._request(
                "GET",
                f"/api/v1/hives/{hive_id}/services",
                params=params,
            )

            if not isinstance(envelope, list):
                break

            results.extend(envelope)

            # Stop if we received fewer records than requested (last page)
            if len(envelope) < effective_per_page:
                break

            page += 1

        return results

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    def list_workflows(
        self,
        hive_id: str,
        *,
        page: int = 1,
        per_page: int = 15,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workflows in a hive."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        if is_active is not None:
            params["is_active"] = "true" if is_active else "false"
        if search is not None:
            params["search"] = search
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows",
            params=params,
        )

    def get_workflow(self, hive_id: str, workflow_id: str) -> dict[str, Any]:
        """Get a single workflow by ID."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}",
        )

    def create_workflow(
        self,
        hive_id: str,
        *,
        slug: str,
        name: str,
        steps: dict[str, dict[str, Any]],
        trigger_config: dict[str, Any] | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new workflow."""
        body: dict[str, Any] = {
            "slug": slug,
            "name": name,
            "steps": steps,
        }
        if trigger_config is not None:
            body["trigger_config"] = trigger_config
        if description is not None:
            body["description"] = description
        if is_active is not None:
            body["is_active"] = is_active
        if settings is not None:
            body["settings"] = settings
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/workflows",
            json=body,
        )

    def update_workflow(
        self,
        hive_id: str,
        workflow_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        steps: dict[str, dict[str, Any]] | None = None,
        trigger_config: dict[str, Any] | None = None,
        is_active: bool | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a workflow. Pass only the fields to change."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if slug is not None:
            body["slug"] = slug
        if description is not None:
            body["description"] = description
        if steps is not None:
            body["steps"] = steps
        if trigger_config is not None:
            body["trigger_config"] = trigger_config
        if is_active is not None:
            body["is_active"] = is_active
        if settings is not None:
            body["settings"] = settings
        return self._request(
            "PUT",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}",
            json=body,
        )

    def delete_workflow(self, hive_id: str, workflow_id: str) -> None:
        """Delete a workflow."""
        self._request(
            "DELETE",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}",
        )

    def run_workflow(
        self,
        hive_id: str,
        workflow_id: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a workflow run."""
        body: dict[str, Any] = {}
        if payload is not None:
            body["payload"] = payload
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/runs",
            json=body or None,
        )

    def list_workflow_runs(
        self,
        hive_id: str,
        workflow_id: str,
        *,
        page: int = 1,
        per_page: int = 15,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List runs for a workflow."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": min(per_page, 100),
        }
        if status is not None:
            params["status"] = status
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/runs",
            params=params,
        )

    def get_workflow_run(
        self,
        hive_id: str,
        workflow_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Get a single workflow run."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/runs/{run_id}",
        )

    def cancel_workflow_run(
        self,
        hive_id: str,
        workflow_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Cancel a running workflow run."""
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/runs/{run_id}/cancel",
        )

    def retry_workflow_run(
        self,
        hive_id: str,
        workflow_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Retry a failed workflow run."""
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/runs/{run_id}/retry",
        )

    def list_workflow_versions(
        self,
        hive_id: str,
        workflow_id: str,
        *,
        page: int = 1,
        per_page: int = 15,
    ) -> list[dict[str, Any]]:
        """List versions of a workflow."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/versions",
            params={"page": page, "per_page": min(per_page, 100)},
        )

    def get_workflow_version(
        self,
        hive_id: str,
        workflow_id: str,
        version: int | str,
    ) -> dict[str, Any]:
        """Get a specific workflow version."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/versions/{version}",
        )

    def diff_workflow_versions(
        self,
        hive_id: str,
        workflow_id: str,
        from_version: int | str,
        to_version: int | str,
    ) -> dict[str, Any]:
        """Diff two workflow versions."""
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}"
            f"/versions/{from_version}/diff/{to_version}",
        )

    def rollback_workflow_version(
        self,
        hive_id: str,
        workflow_id: str,
        version: int | str,
    ) -> dict[str, Any]:
        """Rollback a workflow to a specific version."""
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/workflows/{workflow_id}/versions/{version}/rollback",
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: str,
        scope: str = "hive",
        capability: str | None = None,
    ) -> dict[str, Any]:
        """Subscribe to an event type.

        Args:
            event_type: The event type to subscribe to (e.g. ``"task.completed"``).
            scope: Subscription scope — ``"hive"`` (default) or ``"apiary"``
                (requires cross-hive permission).
            capability: Optional capability name. When provided, creates a
                capability-pool subscription that fans out to every agent in
                the hive (or apiary, for ``"apiary"`` scope) owning the
                capability — rather than subscribing the caller directly.

        Returns:
            The subscription dict.
        """
        body: dict[str, Any] = {"event_type": event_type, "scope": scope}
        if capability is not None:
            body["capability"] = capability
        return self._request(
            "POST",
            "/api/v1/agents/subscriptions",
            json=body,
        )

    def unsubscribe(
        self,
        event_type: str,
        capability: str | None = None,
        scope: str | None = None,
    ) -> None:
        """Unsubscribe from an event type.

        Args:
            event_type: The event type to unsubscribe from.
            capability: Optional capability name. When provided, removes the
                capability-pool subscription instead of a direct subscription
                — symmetric with :meth:`subscribe`.
            scope: Optional pool scope (``"hive"`` or ``"apiary"``). Only
                meaningful when ``capability`` is set; defaults server-side
                to ``"hive"``.
        """
        params: dict[str, str] = {}
        if capability is not None:
            params["capability"] = capability
        if scope is not None:
            params["scope"] = scope
        self._request(
            "DELETE",
            f"/api/v1/agents/subscriptions/{event_type}",
            params=params or None,
        )

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """List the agent's direct event subscriptions.

        Returns the agent's own ``event_subscriptions`` rows. Does not
        include capability-pool subscriptions the agent receives by virtue
        of owning a capability — use :meth:`list_capability_pool_subscriptions`
        for those, or :meth:`list_subscriptions_with_pools` to fetch both at
        once.
        """
        return self._request("GET", "/api/v1/agents/subscriptions")

    def list_capability_pool_subscriptions(self) -> list[dict[str, Any]]:
        """List capability-pool subscriptions visible to this agent.

        A capability-pool subscription is visible to the agent when the
        agent owns the pool's capability and the pool's scope/hive match —
        i.e. it is a subscription the agent receives events from even
        though the agent never subscribed to it directly.
        """
        envelope = self._request_envelope("GET", "/api/v1/agents/subscriptions")
        meta = envelope.get("meta") or {}
        pools = meta.get("capability_pools") or []
        return list(pools)

    def list_subscriptions_with_pools(self) -> dict[str, Any]:
        """Fetch direct subscriptions and visible capability pools in one call.

        Returns a dict with the keys:

        - ``subscriptions``: the agent's direct ``event_subscriptions`` rows.
        - ``capability_pools``: capability-pool subscriptions visible to the
          agent (matched by capability + hive/organization).
        - ``capability_pool_count``: count of the visible pools.
        """
        envelope = self._request_envelope("GET", "/api/v1/agents/subscriptions")
        meta = envelope.get("meta") or {}
        return {
            "subscriptions": list(envelope.get("data") or []),
            "capability_pools": list(meta.get("capability_pools") or []),
            "capability_pool_count": int(meta.get("capability_pool_count") or 0),
        }

    def replace_subscriptions(
        self,
        subscriptions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Atomically replace all event subscriptions.

        Each entry should have ``event_type`` (str) and optionally ``scope``
        (``"hive"`` or ``"apiary"``).

        Args:
            subscriptions: List of subscription dicts to set.

        Returns:
            The new subscription list.
        """
        return self._request(
            "PUT",
            "/api/v1/agents/subscriptions",
            json={"subscriptions": subscriptions},
        )

    def poll_events(
        self,
        hive_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """Poll for new events matching the agent's subscriptions.

        The SDK tracks the cursor (``last_event_id``) internally so callers
        don't need to manage pagination state.  On each call, events newer
        than the last seen cursor are returned.  When the response indicates
        ``has_more``, the method automatically re-polls until all pending
        events have been fetched.

        Args:
            hive_id: Hive to poll events from.
            since: ISO-8601 datetime — only used on the first poll when no
                cursor has been established yet.
            limit: Maximum events per server round-trip (default 50).

        Returns:
            A flat list of :class:`Event` objects accumulated across all pages.
        """
        all_events: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {}
            cursors = getattr(self, "_event_cursors", {})
            cursor = cursors.get(hive_id)
            if cursor is not None:
                params["last_event_id"] = cursor
            elif since is not None:
                params["since"] = since
            if limit is not None:
                params["limit"] = limit

            envelope = self._request_envelope(
                "GET",
                f"/api/v1/hives/{hive_id}/events/poll",
                params=params or None,
            )

            events = envelope.get("data", []) or []
            meta = envelope.get("meta", {}) or {}

            all_events.extend(events)

            # Update internal cursor from response meta.
            next_cursor = meta.get("next_cursor")
            if next_cursor is not None:
                if not hasattr(self, "_event_cursors"):
                    self._event_cursors = {}
                self._event_cursors[hive_id] = next_cursor

            # Re-poll immediately if the server indicates more events.
            if meta.get("has_more", False):
                continue

            break

        return [Event.from_dict(e) for e in all_events]

    def poll_events_with_meta(
        self,
        hive_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Poll for events and return the full envelope (single page).

        Unlike :meth:`poll_events` (which returns typed :class:`Event`
        objects), this method returns the **raw API envelope** with event
        data left as plain ``dict`` objects.  No automatic cursor-based
        re-polling is performed.  The internal cursor is still updated
        from the response.

        Args:
            hive_id: Hive to poll events from.
            since: ISO-8601 datetime filter.
            limit: Maximum events to return.

        Returns:
            The full ``{data, meta, errors}`` envelope where ``data`` is a
            list of raw event dicts (not :class:`Event` instances).
        """
        params: dict[str, Any] = {}
        cursors = getattr(self, "_event_cursors", {})
        cursor = cursors.get(hive_id)
        if cursor is not None:
            params["last_event_id"] = cursor
        elif since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit

        envelope = self._request_envelope(
            "GET",
            f"/api/v1/hives/{hive_id}/events/poll",
            params=params or None,
        )

        meta = envelope.get("meta", {}) or {}
        next_cursor = meta.get("next_cursor")
        if next_cursor is not None:
            if not hasattr(self, "_event_cursors"):
                self._event_cursors = {}
            self._event_cursors[hive_id] = next_cursor

        return envelope

    def publish_event(
        self,
        hive_id: str,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish an event to the EventBus.

        Args:
            hive_id: Hive to publish the event in.
            event_type: Event type string (e.g. ``"task.completed"``).
            payload: Optional event payload dict.

        Returns:
            The created event dict.
        """
        body: dict[str, Any] = {"type": event_type}
        if payload is not None:
            body["payload"] = payload
        return self._request("POST", f"/api/v1/hives/{hive_id}/events", json=body)

    def reset_event_cursor(self, hive_id: str | None = None) -> None:
        """Reset the internal event poll cursor.

        Args:
            hive_id: If provided, reset only the cursor for that hive.
                If ``None`` (default), reset cursors for all hives.

        After calling this, the next :meth:`poll_events` call will start from
        the beginning (or from the ``since`` parameter if provided).
        """
        if not hasattr(self, "_event_cursors"):
            self._event_cursors = {}
            return
        if hive_id is not None:
            self._event_cursors.pop(hive_id, None)
        else:
            self._event_cursors.clear()

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def list_channels(
        self,
        hive_id: str,
        *,
        status: str | None = None,
        channel_type: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List channels in a hive with optional filters.

        Args:
            hive_id: Hive to list channels from.
            status: Filter by channel status (e.g. ``"open"``, ``"resolved"``).
            channel_type: Filter by channel type (e.g. ``"discussion"``).
            page: Page number for pagination.
            per_page: Results per page (1–100, default 15).

        Returns:
            List of channel dicts.
        """
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if channel_type is not None:
            params["channel_type"] = channel_type
        if page is not None:
            params["page"] = page
        if per_page is not None:
            params["per_page"] = per_page
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels",
            params=params or None,
        )

    def create_channel(
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
        """Create a new channel in a hive.

        Args:
            hive_id: Hive to create the channel in.
            title: Channel title (max 255 chars).
            channel_type: Channel type — one of ``"discussion"``, ``"review"``,
                ``"planning"``, or ``"incident"``.
            topic: Optional topic description (max 1000 chars).
            participants: List of participant dicts with ``agent_id`` or
                ``user_id`` and optional ``role``.
            resolution_policy: Resolution policy configuration.
            linked_refs: External references linked to this channel.
            on_resolve: Actions to perform on resolution (e.g. ``create_tasks``).
            stale_after: Minutes of inactivity before the channel becomes stale.
            initial_message: Optional initial message with ``content``,
                ``message_type``, and ``metadata``.
            auto_invite: Auto-invite configuration with ``capabilities`` list.

        Returns:
            The created channel dict with participants and message count.
        """
        body: dict[str, Any] = {
            "title": title,
            "channel_type": channel_type,
        }
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
        return self._request("POST", f"/api/v1/hives/{hive_id}/channels", json=body)

    def get_channel(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Get a single channel with participants and message count.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.

        Returns:
            Channel detail dict.
        """
        return self._request("GET", f"/api/v1/hives/{hive_id}/channels/{channel_id}")

    def update_channel(
        self,
        hive_id: str,
        channel_id: str,
        *,
        title: str | None = None,
        resolution_policy: dict[str, Any] | None = None,
        stale_after: int | None = None,
        on_resolve: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a channel's settings.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel to update.
            title: New title (max 255 chars).
            resolution_policy: Updated resolution policy.
            stale_after: Updated stale timeout in minutes.
            on_resolve: Updated on-resolve actions.

        Returns:
            Updated channel detail dict.
        """
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if resolution_policy is not None:
            body["resolution_policy"] = resolution_policy
        if stale_after is not None:
            body["stale_after"] = stale_after
        if on_resolve is not None:
            body["on_resolve"] = on_resolve
        return self._request(
            "PATCH",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}",
            json=body,
        )

    def archive_channel(self, hive_id: str, channel_id: str) -> dict[str, Any]:
        """Archive a channel (soft delete).

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel to archive.

        Returns:
            The archived channel dict.
        """
        return self._request("DELETE", f"/api/v1/hives/{hive_id}/channels/{channel_id}")

    # ------------------------------------------------------------------
    # Channel messages
    # ------------------------------------------------------------------

    def list_channel_messages(
        self,
        hive_id: str,
        channel_id: str,
        *,
        since: str | None = None,
        after_id: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """List messages in a channel with optional filters.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            since: ISO-8601 timestamp — return messages created after this time.
            after_id: Message ID cursor — return messages with ID greater than this.
            page: Page number for pagination.
            per_page: Results per page (1–100, default 15).

        Returns:
            List of message dicts.
        """
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if after_id is not None:
            params["after_id"] = after_id
        if page is not None:
            params["page"] = page
        if per_page is not None:
            params["per_page"] = per_page
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages",
            params=params or None,
        )

    def post_channel_message(
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
        """Post a new message to a channel.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            body: Message content text.
            message_type: Type of message — ``"discussion"`` (default),
                ``"proposal"``, ``"vote"``, ``"decision"``, ``"context"``,
                ``"system"``, or ``"action"``.
            mentions: List of agent IDs to mention.
            metadata: Type-specific metadata (e.g. ``options`` for proposals,
                ``vote`` and ``proposal_ref`` for votes).
            reply_to: ID of a message to reply to.

        Returns:
            The created message dict.
        """
        payload: dict[str, Any] = {
            "content": body,
            "message_type": message_type,
        }
        if mentions is not None:
            payload["mentions"] = mentions
        if metadata is not None:
            payload["metadata"] = metadata
        if reply_to is not None:
            payload["reply_to"] = reply_to
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages",
            json=payload,
        )

    def edit_channel_message(
        self,
        hive_id: str,
        channel_id: str,
        message_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Edit a channel message (author only, within 5-minute window).

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            message_id: ID of the message to edit.
            body: New message content.

        Returns:
            The updated message dict.
        """
        return self._request(
            "PATCH",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages/{message_id}",
            json={"content": body},
        )

    # ------------------------------------------------------------------
    # Channel participants
    # ------------------------------------------------------------------

    def list_channel_participants(
        self,
        hive_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """List participants in a channel.

        Fetches the channel detail which includes participants.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.

        Returns:
            Channel detail dict containing a ``participants`` list.
        """
        return self._request("GET", f"/api/v1/hives/{hive_id}/channels/{channel_id}")

    def add_channel_participant(
        self,
        hive_id: str,
        channel_id: str,
        participant_type: str,
        participant_id: str,
        *,
        role: str = "contributor",
        mention_policy: str | None = None,
    ) -> dict[str, Any]:
        """Add a participant to a channel.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            participant_type: ``"agent"`` or ``"user"``.
            participant_id: ID of the agent or user to add.
            role: Participant role (e.g. ``"contributor"``, ``"reviewer"``,
                ``"decider"``, ``"initiator"``, ``"observer"``).  Required by
                the server; defaults to ``"contributor"``.
            mention_policy: Mention policy (e.g. ``"all"``, ``"mention_only"``).

        Returns:
            The created participant dict.
        """
        body: dict[str, Any] = {
            "participant_type": participant_type,
            "participant_id": participant_id,
            "role": role,
        }
        if mention_policy is not None:
            body["mention_policy"] = mention_policy
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/participants",
            json=body,
        )

    def remove_channel_participant(
        self,
        hive_id: str,
        channel_id: str,
        participant_id: str,
    ) -> None:
        """Remove a participant from a channel.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            participant_id: ID of the participant to remove.
        """
        self._request(
            "DELETE",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/participants/{participant_id}",
        )

    # ------------------------------------------------------------------
    # Channel voting
    # ------------------------------------------------------------------

    def vote_on_proposal(
        self,
        hive_id: str,
        channel_id: str,
        proposal_msg_id: str,
        vote_value: str,
        *,
        body: str | None = None,
        option_key: str | None = None,
    ) -> dict[str, Any]:
        """Vote on a proposal in a channel.

        This is a convenience wrapper around :meth:`post_channel_message`
        that posts a ``vote`` type message with the correct metadata.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            proposal_msg_id: ID of the proposal message to vote on.
            vote_value: Vote value — ``"approve"``, ``"reject"``,
                ``"abstain"``, or ``"block"``.
            body: Optional vote justification text.
            option_key: Optional key of the specific proposal option being voted on.

        Returns:
            The created vote message dict.
        """
        metadata: dict[str, Any] = {
            "vote": vote_value,
            "proposal_ref": proposal_msg_id,
        }
        if option_key is not None:
            metadata["option_key"] = option_key
        return self.post_channel_message(
            hive_id,
            channel_id,
            body or f"Vote: {vote_value}",
            message_type="vote",
            metadata=metadata,
        )

    def get_proposal_votes(
        self,
        hive_id: str,
        channel_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Get vote tally for a proposal message.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.
            message_id: ID of the proposal message.

        Returns:
            Vote tally dict with ``proposal_id``, ``total_votes``, ``tally``,
            ``per_option``, and ``voters``.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/messages/{message_id}/votes",
        )

    # ------------------------------------------------------------------
    # Channel summary (TASK-248)
    # ------------------------------------------------------------------

    def channel_summary(
        self,
        hive_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """Get a lightweight summary of the channel for the authenticated agent.

        Returns unread count, mention status, vote status, and the agent's
        ``last_read_at`` position.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.

        Returns:
            Summary dict with ``channel_id``, ``status``, ``unread_count``,
            ``mentioned``, ``needs_vote``, ``last_message_at``, and
            ``last_read_at``.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/summary",
        )

    def mark_channel_read(
        self,
        hive_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """Mark a channel as read for the authenticated agent.

        Updates the agent's ``last_read_at`` timestamp to the channel's
        most recent message time.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.

        Returns:
            Dict with ``channel_id`` and updated ``last_read_at``.
        """
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/read",
        )

    # ------------------------------------------------------------------
    # Channel materialization (TASK-207)
    # ------------------------------------------------------------------

    def materialize_channel(
        self,
        hive_id: str,
        channel_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create tasks from a resolved channel's outcome.

        Only allowed on channels with status ``resolved``.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the resolved channel.
            tasks: List of task template dicts, each with ``type`` (required),
                and optional ``payload``, ``target_capability``, ``priority``.

        Returns:
            List of created task dicts.
        """
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/materialize",
            json={"tasks": tasks},
        )

    def list_channel_tasks(
        self,
        hive_id: str,
        channel_id: str,
    ) -> list[dict[str, Any]]:
        """List tasks created from a channel.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel.

        Returns:
            List of task dicts associated with the channel.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/tasks",
        )

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def resolve_channel(
        self,
        hive_id: str,
        channel_id: str,
        *,
        outcome: str,
        materialized_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Manually resolve a channel.

        Only authorized participants (with ``initiator`` or ``decider`` role)
        can resolve. Only ``open`` or ``deliberating`` channels can be resolved.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel to resolve.
            outcome: Resolution outcome description (max 2000 chars).
            materialized_tasks: Optional list of task templates to store
                with the resolution.  These are **not** created automatically;
                use :meth:`materialize_channel` or configure
                ``on_resolve.create_tasks`` to create tasks from them.

        Returns:
            The resolved channel detail dict.
        """
        body: dict[str, Any] = {"outcome": outcome}
        if materialized_tasks is not None:
            body["materialized_tasks"] = materialized_tasks
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/resolve",
            json=body,
        )

    def reopen_channel(
        self,
        hive_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """Reopen a resolved or stale channel.

        Only ``resolved`` or ``stale`` channels can be reopened.

        Args:
            hive_id: Hive that owns the channel.
            channel_id: ID of the channel to reopen.

        Returns:
            The reopened channel detail dict.
        """
        return self._request(
            "POST",
            f"/api/v1/hives/{hive_id}/channels/{channel_id}/reopen",
        )

    # ------------------------------------------------------------------
    # Channel polling
    # ------------------------------------------------------------------

    def poll_channels(
        self,
        hive_id: str,
    ) -> list[dict[str, Any]]:
        """Poll channels for activity relevant to the authenticated agent.

        Returns channels with unread messages, pending mentions, or votes needed.

        The response envelope also contains ``meta.next_poll_ms`` — the
        server-recommended delay before the next poll.  Use
        :meth:`poll_channels_with_meta` when you need to inspect that field.

        Args:
            hive_id: Hive to poll channels from.

        Returns:
            List of channel activity dicts.
        """
        return self._request(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/poll",
        )

    def poll_channels_with_meta(
        self,
        hive_id: str,
    ) -> dict[str, Any]:
        """Poll channels for activity and return the full envelope.

        Unlike :meth:`poll_channels`, this method returns the full
        ``{data, meta, errors}`` envelope so callers can inspect
        ``meta["next_poll_ms"]`` for adaptive polling / backoff.

        Example::

            envelope = client.poll_channels_with_meta(hive_id)
            channels = envelope["data"]
            meta = envelope.get("meta", {})
            next_poll_ms = meta.get("next_poll_ms", 5000)

        Args:
            hive_id: Hive to poll channels from.

        Returns:
            The full ``{data, meta, errors}`` envelope where ``data`` is a
            list of channel activity dicts.
        """
        return self._request_envelope(
            "GET",
            f"/api/v1/hives/{hive_id}/channels/poll",
        )

    # ------------------------------------------------------------------
    # Sub-agent definitions
    # ------------------------------------------------------------------

    def get_sub_agent_definitions(self) -> list[SubAgentSummary]:
        """List active sub-agent definitions in the agent's hive.

        Calls ``GET /api/v1/sub-agents``. Returns lightweight summaries
        (id, slug, name, description, model, version, document_count) without
        full documents. Use :meth:`get_sub_agent_definition` for the full body.
        """
        data = self._request("GET", "/api/v1/sub-agents")
        return [SubAgentSummary.from_dict(item) for item in (data or [])]

    def get_sub_agent_definition(self, slug: str) -> SubAgentDefinition:
        """Get a sub-agent definition by slug (current active version).

        Calls ``GET /api/v1/sub-agents/{slug}``. Raises
        :class:`~superpos_sdk.exceptions.NotFoundError` when the slug does not
        exist or has no active version in the agent's hive.
        """
        data = self._request("GET", f"/api/v1/sub-agents/{slug}")
        return SubAgentDefinition.from_dict(data)

    def get_sub_agent_assembled(self, slug: str) -> str:
        """Get the assembled system prompt for a sub-agent by slug.

        Calls ``GET /api/v1/sub-agents/{slug}/assembled``. Returns the
        concatenated prompt string as produced by the server-side assembler.
        """
        data = self._request("GET", f"/api/v1/sub-agents/{slug}/assembled")
        return data["prompt"]

    def get_sub_agent_definition_by_id(self, sub_agent_id: str) -> SubAgentDefinition:
        """Get a sub-agent definition by ULID (version-stable).

        Calls ``GET /api/v1/sub-agents/by-id/{id}``. Returns the exact row
        regardless of whether this version is still the active one for the
        slug — used to re-fetch a pinned definition from a claimed task's
        ``sub_agent.id``.
        """
        data = self._request("GET", f"/api/v1/sub-agents/by-id/{sub_agent_id}")
        return SubAgentDefinition.from_dict(data)

    def get_sub_agent_assembled_by_id(self, sub_agent_id: str) -> str:
        """Get the assembled system prompt for a sub-agent by ULID.

        Calls ``GET /api/v1/sub-agents/by-id/{id}/assembled``. Version-stable
        variant of :meth:`get_sub_agent_assembled`.
        """
        data = self._request("GET", f"/api/v1/sub-agents/by-id/{sub_agent_id}/assembled")
        return data["prompt"]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> SuperposClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
