"""HTTP service worker — executes outbound HTTP requests on behalf of agents.

Install the optional dependency::

    pip install superpos-sdk[http]

Task payload (``params``) schema::

    {
        "url":     "https://example.com/api/resource",   # required
        "method":  "GET",                                 # default: GET
        "headers": {"X-Custom": "value"},                 # optional
        "body":    "...",                                 # optional string / dict
        "timeout": 30                                     # seconds, default 30
    }

Result schema::

    {
        "status_code": 200,
        "headers":     {"content-type": "application/json"},
        "body":        "...",
        "elapsed_ms":  142
    }
"""

from __future__ import annotations

import logging
from typing import Any

from superpos_sdk.service_worker import ServiceWorker

logger = logging.getLogger(__name__)


class HttpWorker(ServiceWorker):
    """Service worker that executes HTTP requests.

    Supports ``request`` as the sole operation.  The operation name is the
    primary entry-point; callers may also name their operation anything — the
    :meth:`process` method is the raw dispatch hook used when the task payload
    has no ``operation`` field.

    Operations:
        - ``request``: execute an HTTP request (GET, POST, PUT, PATCH, DELETE…)
    """

    CAPABILITY = "data:http"

    def request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an HTTP request and return the response.

        Args:
            params: Dict with ``url`` (required), ``method``, ``headers``,
                ``body``, and ``timeout`` keys.

        Returns:
            Dict with ``status_code``, ``headers``, ``body``, and
            ``elapsed_ms``.

        Raises:
            ValueError: When ``url`` is missing from *params*.
            RuntimeError: On connection errors or timeouts.
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "httpx is required for HttpWorker. Install it with: pip install superpos-sdk[http]"
            ) from exc

        url = params.get("url")
        if not url:
            raise ValueError("params.url is required for the 'request' operation")

        method = (params.get("method") or "GET").upper()
        headers = params.get("headers") or {}
        body = params.get("body")
        timeout = float(params.get("timeout") or 30)

        # Normalise body: a dict is sent as JSON, a string as raw text.
        kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
        if isinstance(body, dict):
            kwargs["json"] = body
        elif body is not None:
            kwargs["content"] = body if isinstance(body, bytes) else str(body).encode()

        try:
            with httpx.Client() as client:
                response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Request timed out after {timeout}s: {exc}") from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(f"Connection error for {url}: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"HTTP request failed: {exc}") from exc

        # Attempt to decode body as text; fall back to empty string.
        try:
            body_text = response.text
        except Exception:  # noqa: BLE001
            body_text = ""

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body_text,
            "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
        }
