"""Service worker base class and helpers for building Superpos service workers.

A service worker is a regular agent whose sole purpose is to bridge an
external service (Gmail, Jira, GitHub, etc.) into the Superpos task bus.  It:

1. Registers with a ``data:<service>`` capability.
2. Polls for ``data_request`` tasks.
3. Routes each task to a named operation handler.
4. Returns structured results via ``complete_task`` / ``fail_task``.

Quick start::

    from superpos_sdk import SuperposClient
    from superpos_sdk.service_worker import ServiceWorker

    class GmailWorker(ServiceWorker):
        CAPABILITY = "data:gmail"

        def fetch_emails(self, params):
            messages = gmail_api.search(params["query"])
            return {"data": messages, "metadata": {"count": len(messages)}}

        def send_email(self, params):
            gmail_api.send(to=params["to"], subject=params["subject"],
                           body=params["body"])
            return {"sent": True}

    worker = GmailWorker(
        base_url="https://superpos.example.com",
        hive_id="01HXYZ...",
        agent_id="01HABC...",
        secret="s3cr3t",
    )
    worker.run()  # blocks; Ctrl-C for graceful shutdown
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Any, Callable

from superpos_sdk.client import SuperposClient
from superpos_sdk.exceptions import ConflictError, SuperposError
from superpos_sdk.streaming import StreamingTask

logger = logging.getLogger(__name__)


class OperationNotFoundError(SuperposError):
    """Raised when a ``data_request`` task specifies an unknown operation."""


class ServiceWorker:
    """Base class for Superpos service workers.

    Subclasses declare :attr:`CAPABILITY` and implement operation methods
    (or register them with :meth:`register_operation`).

    The naming convention for operation methods is the operation name with
    hyphens replaced by underscores.  For example, the ``fetch-emails``
    operation maps to ``def fetch_emails(self, params): ...``.

    Args:
        base_url: Superpos server base URL (no trailing slash).
        hive_id: The hive this worker belongs to.
        agent_id: Pre-registered agent ID (mutually exclusive with *name*).
        secret: Agent secret for authentication.
        name: Agent name to use when auto-registering (mutually exclusive
            with *agent_id*).
        capabilities: Override the default capabilities list
            (defaults to ``[CAPABILITY]``).
        metadata: Extra agent metadata merged with ``supported_operations``.
        poll_interval: Seconds between polls when the queue is empty
            (default 5).
        claim_type: Task type to filter on when polling (default
            ``"data_request"``).
        token: Pre-supplied auth token (skips login step).
        logger: Custom logger (defaults to module logger).
    """

    #: Override in subclasses — e.g. ``"data:gmail"``
    CAPABILITY: str = "data:custom"

    def __init__(
        self,
        base_url: str,
        hive_id: str,
        *,
        agent_id: str | None = None,
        secret: str | None = None,
        name: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        poll_interval: float = 5.0,
        claim_type: str = "data_request",
        token: str | None = None,
        logger: logging.Logger | None = None,  # noqa: A002
    ) -> None:
        self.hive_id = hive_id
        self.poll_interval = poll_interval
        self.claim_type = claim_type
        self._log = logger or logging.getLogger(type(self).__name__)

        self.client = SuperposClient(base_url, token=token)

        self._capabilities = capabilities or [self.CAPABILITY]
        self._extra_metadata = metadata or {}

        self._agent_id = agent_id
        self._secret = secret
        self._name = name

        # Custom operation registry (populated via register_operation)
        self._operations: dict[str, Callable[[dict[str, Any]], Any]] = {}

        # Graceful shutdown flag
        self._running = False

        # Set during _process(); cleared after handle() returns.  Provides
        # handlers with the response_task_id from the current task payload
        # without requiring them to extract it manually from params.
        self._response_task_id: str | None = None

        # Set during _process(); cleared after the task completes/fails.
        # Provides handlers with the current task's ID for use with open_stream().
        self._current_task_id: str | None = None

    # ------------------------------------------------------------------
    # Operation registry
    # ------------------------------------------------------------------

    def register_operation(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Register a handler function for an operation name.

        Use this when you prefer composition over subclassing::

            worker = ServiceWorker(...)
            worker.register_operation("fetch_emails", my_handler)

        The handler receives the ``params`` dict from the task payload and
        must return the result dict (or raise an exception on failure).
        """
        self._operations[name] = handler

    @property
    def response_task_id(self) -> str | None:
        """The ``response_task_id`` from the current task's payload, if any.

        Available inside operation handlers during :meth:`_process`.  Set to
        ``None`` between tasks.  Use :meth:`deliver_response` to push a result
        to this task ID without passing it explicitly.
        """
        return self._response_task_id

    def handle(self, operation: str, params: dict[str, Any]) -> Any:
        """Dispatch *operation* to the registered handler.

        Resolution order:

        1. Registered via :meth:`register_operation`.
        2. Method on the subclass whose name matches *operation* (with
           hyphens replaced by underscores).

        Raises :class:`OperationNotFoundError` when no handler is found.
        """
        if operation in self._operations:
            return self._operations[operation](params)

        method_name = operation.replace("-", "_")
        handler = getattr(self, method_name, None)
        if callable(handler) and not method_name.startswith("_"):
            return handler(params)

        raise OperationNotFoundError(
            f"No handler for operation '{operation}'. "
            f"Define a method named '{method_name}' or call register_operation()."
        )

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def _supported_operations(self) -> list[dict[str, Any]]:
        """Return the list of supported operation names for agent metadata."""
        ops: list[str] = list(self._operations.keys())

        # Discover method-based handlers (public methods not in base class)
        base_attrs = set(dir(ServiceWorker))
        for attr in dir(self):
            if attr.startswith("_"):
                continue
            if attr in base_attrs:
                continue
            if callable(getattr(self, attr, None)):
                op_name = attr.replace("_", "-")
                if op_name not in ops and attr not in ops:
                    ops.append(attr)

        return [{"name": op} for op in sorted(ops)]

    def setup(self) -> None:
        """Hook called once after authentication, before the poll loop.

        Override to perform one-time initialisation (e.g. API client setup).
        """

    def teardown(self) -> None:
        """Hook called once after the poll loop exits.

        Override to perform cleanup (e.g. closing external connections).
        """

    def _authenticate(self) -> None:
        """Authenticate with the Superpos server."""
        if self.client.token:
            self._log.debug("Using pre-supplied token.")
            return

        ops_meta = self._supported_operations()
        meta = dict(self._extra_metadata)
        if ops_meta:
            meta["supported_operations"] = ops_meta

        if self._agent_id and self._secret:
            self._log.info("Logging in as agent %s…", self._agent_id)
            self.client.login(agent_id=self._agent_id, secret=self._secret)
        elif self._name and self._secret:
            self._log.info(
                "Registering as '%s' with capability %s…", self._name, self._capabilities
            )
            self.client.register(
                name=self._name,
                hive_id=self.hive_id,
                secret=self._secret,
                agent_type="service_worker",
                capabilities=self._capabilities,
                metadata=meta or None,
            )
        else:
            raise ValueError(
                "ServiceWorker requires either (agent_id + secret) for login "
                "or (name + secret) for registration."
            )

    def _shutdown(self, signum: int, frame: object) -> None:
        """Signal handler — sets the stop flag."""
        self._log.info("Received signal %d — shutting down after current task…", signum)
        self._running = False

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the blocking poll loop.

        Installs SIGINT and SIGTERM handlers for graceful shutdown.
        Call :meth:`stop` from another thread to request a clean exit.
        """
        self._authenticate()

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        self.client.update_status("online")
        self._log.info(
            "Service worker online. Polling hive=%s for type=%s capability=%s…",
            self.hive_id,
            self.claim_type,
            self._capabilities,
        )

        self.setup()
        self._running = True

        try:
            while self._running:
                self._tick()
        finally:
            self._log.info("Shutting down…")
            try:
                self.client.update_status("offline")
            except SuperposError:
                pass
            try:
                self.client.logout()
            except SuperposError:
                pass
            self.client.close()
            self.teardown()

    def stop(self) -> None:
        """Request a clean shutdown (thread-safe)."""
        self._running = False

    def _tick(self) -> None:
        """Execute one poll-claim-process cycle."""
        try:
            self.client.heartbeat()
        except SuperposError as exc:
            self._log.warning("Heartbeat failed: %s", exc)

        try:
            envelope = self.client.poll_tasks_with_meta(
                self.hive_id,
                capability=self._capabilities[0] if self._capabilities else None,
            )
        except SuperposError as exc:
            self._log.warning("Poll failed: %s — retrying in %ss", exc, self.poll_interval)
            time.sleep(self.poll_interval)
            return

        tasks: list[dict[str, Any]] = envelope.get("data") or []

        # Honour server backpressure: next_poll_ms > 0 means the server wants us
        # to wait before the next poll (empty queue, high load, or rate limited).
        next_poll_ms: int = (envelope.get("meta") or {}).get("next_poll_ms", 0)

        if not tasks:
            wait_s = next_poll_ms / 1000.0 if next_poll_ms > 0 else self.poll_interval
            time.sleep(wait_s)
            return

        for task in tasks:
            if not self._running:
                break
            # Skip tasks whose type doesn't match claim_type to avoid stealing
            # unrelated tasks that the poll endpoint may return (e.g. open tasks
            # with target_capability=null).
            if task.get("type") != self.claim_type:
                self._log.debug(
                    "Skipping task %s — type=%s does not match claim_type=%s",
                    task.get("id"),
                    task.get("type"),
                    self.claim_type,
                )
                continue
            self._process(task)

        # Honour backpressure even when tasks were returned (rate-limit / high-load).
        if next_poll_ms > 0:
            time.sleep(next_poll_ms / 1000.0)

    # ------------------------------------------------------------------
    # Data request helpers (for use inside operation handlers)
    # ------------------------------------------------------------------

    def dispatch_data_request(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        *,
        target_capability: str | None = None,
        delivery: str = "task_result",
        timeout_seconds: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a ``data_request`` task targeting another service worker.

        Convenience method for use inside operation handlers when one service
        worker needs data from another.  Returns immediately with a task dict
        containing the new task's ``id`` — the caller does **not** block.

        Example::

            class OrchestratorWorker(ServiceWorker):
                CAPABILITY = "data:orchestrator"

                def run_pipeline(self, params):
                    # Fan out to two service workers:
                    github_ref = self.dispatch_data_request(
                        "fetch_issues",
                        {"repo": "acme/backend", "state": "open"},
                        target_capability="data:github",
                    )
                    return {"dispatched": github_ref["id"]}

        Args:
            operation: Operation name for the target service worker.
            params: Operation-specific parameters.
            target_capability: Service worker capability to target.  Defaults
                to ``self.CAPABILITY`` (fan-in pattern within same worker type).
            delivery: Result delivery mode — ``"task_result"`` (default) or
                ``"knowledge"``.
            timeout_seconds: Task-level timeout override.
            idempotency_key: Idempotency key to prevent duplicate requests.

        Returns:
            The created task dict (``{id, status, ...}``).
        """
        capability = target_capability or self.CAPABILITY
        return self.client.data_request(
            self.hive_id,
            capability=capability,
            operation=operation,
            params=params,
            delivery=delivery,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    def deliver_response(
        self,
        data: dict[str, Any],
        *,
        response_task_id: str | None = None,
        status_message: str | None = None,
    ) -> dict[str, Any]:
        """Complete a pending ``data_request`` task with a structured response.

        Use this when the response destination is carried in the payload's
        ``response_task_id`` field (push-style delivery).  The caller completes
        the *response task* directly rather than the task it is currently
        processing.

        If *response_task_id* is omitted, the value from the current task's
        payload (``self.response_task_id``) is used automatically.  Raises
        :class:`ValueError` when no task ID is available from either source.

        Example::

            class GithubWorker(ServiceWorker):
                CAPABILITY = "data:github"

                def fetch_issues(self, params):
                    issues = github_api.list_issues(params["repo"])
                    result = {"status": "success", "data": {"issues": issues}}

                    # Push result to the waiting task (id from self.response_task_id)
                    if self.response_task_id:
                        self.deliver_response(result, status_message="Issues fetched")
                    return result

        Args:
            data: Response payload — should follow the convention::

                {
                    "status": "success",   # or "error"
                    "data": {...},         # operation result
                    "error": "...",        # present when status="error"
                }

            response_task_id: ID of the task to deliver the response to.
                Defaults to ``self.response_task_id`` (set from the current
                task payload).
            status_message: Optional human-readable status message.

        Returns:
            The completed task dict.

        Raises:
            ValueError: When *response_task_id* is ``None`` and the current
                task payload did not include one.
        """
        target = response_task_id or self._response_task_id
        if target is None:
            raise ValueError(
                "No response_task_id available. Pass one explicitly or ensure "
                'the task payload includes "response_task_id".'
            )
        return self.client.deliver_response_task(
            self.hive_id,
            target,
            data,
            status_message=status_message,
        )

    def open_stream(self, task_id: str, *, auto_sequence: bool = True) -> StreamingTask:
        """Return a :class:`~superpos_sdk.streaming.StreamingTask` for *task_id*.

        Convenience factory method — equivalent to::

            StreamingTask(self.client, self.hive_id, task_id)

        Intended for use inside operation handlers::

            def generate(self, params):
                with self.open_stream(self._current_task_id) as stream:
                    for i, chunk in enumerate(generate_chunks(params)):
                        stream.send_chunk({"text": chunk}, sequence=i)
                return {}
        """
        return StreamingTask(self.client, self.hive_id, task_id, auto_sequence=auto_sequence)

    def stream_process(self, task: dict[str, Any], stream: StreamingTask) -> None:
        """Override to implement streaming delivery for the entire task.

        Called by :meth:`_process` when the task has ``delivery_mode='stream'``
        **and** no matching operation handler exists (or the subclass has not
        overridden :meth:`handle`).

        The default implementation raises :class:`NotImplementedError`.

        Args:
            task: The claimed task dict.
            stream: An open :class:`~superpos_sdk.streaming.StreamingTask`
                pre-bound to the task.  The caller will call
                :meth:`~superpos_sdk.streaming.StreamingTask.complete` after this
                method returns if it has not already been finalised.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.stream_process() is not implemented. "
            "Override stream_process() or use handle() with open_stream() instead."
        )

    def _process(self, task: dict[str, Any]) -> None:
        """Claim and execute a single task."""
        task_id = task["id"]

        try:
            task = self.client.claim_task(self.hive_id, task_id)
        except ConflictError:
            self._log.debug("Task %s already claimed, skipping.", task_id)
            return
        except SuperposError as exc:
            self._log.warning("Could not claim %s: %s", task_id, exc)
            return

        payload = task.get("payload") or {}
        operation = payload.get("operation", "")
        params = payload.get("params") or {}
        self._response_task_id = payload.get("response_task_id") or None
        self._current_task_id = task_id
        delivery_mode = task.get("delivery_mode", "default")

        self._log.info(
            "Processing task %s — operation=%s delivery_mode=%s",
            task_id,
            operation or "(none)",
            delivery_mode,
        )

        try:
            if delivery_mode == "stream":
                # Stream delivery: the handler (or stream_process()) is
                # responsible for finalising the stream via open_stream() /
                # StreamingTask.complete().  We NEVER call complete_task()
                # here — doing so would cause a 409 double-completion because
                # the final send_stream_chunk(is_final=True) already marks the
                # parent task completed on the server.
                try:
                    self.handle(operation, params)
                    self._log.info("Completed stream task %s via handle()", task_id)
                except OperationNotFoundError:
                    # No operation handler — delegate to stream_process().
                    stream = StreamingTask(self.client, self.hive_id, task_id)
                    self.stream_process(task, stream)
                    if not stream._finalized:  # noqa: SLF001
                        stream.complete()
                    self._log.info("Completed stream task %s via stream_process()", task_id)
            else:
                result = self.handle(operation, params)
                self.client.complete_task(
                    self.hive_id,
                    task_id,
                    result=result if isinstance(result, dict) else {"value": result},
                    status_message=f"Completed operation '{operation}'",
                )
                self._log.info("Completed task %s", task_id)

        except OperationNotFoundError as exc:
            error_msg = str(exc)
            self._log.error("Unknown operation '%s' on task %s: %s", operation, task_id, error_msg)
            self.client.fail_task(
                self.hive_id,
                task_id,
                error={
                    "type": "OperationNotFoundError",
                    "message": error_msg,
                    "operation": operation,
                },
                status_message=f"Unknown operation '{operation}'",
            )

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            self._log.error("Error on task %s (operation=%s): %s", task_id, operation, error_msg)
            try:
                self.client.fail_task(
                    self.hive_id,
                    task_id,
                    error={
                        "type": type(exc).__name__,
                        "message": error_msg,
                        "operation": operation,
                    },
                    status_message="Worker error",
                )
            except SuperposError as fail_exc:
                self._log.error("Could not fail task %s: %s", task_id, fail_exc)

        finally:
            self._response_task_id = None
            self._current_task_id = None
