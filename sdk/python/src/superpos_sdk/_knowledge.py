"""Shared helpers for building typed knowledge write payloads.

Phase D (issue #43, §9.1) retired the legacy ``key``+``value`` knowledge
write shape on the server: the API now 422s any payload carrying ``value`` or a
bare ``key``. The SDK must therefore send the *typed* shape
(``type``+``slug``+``body``/…). These helpers build that typed payload and
provide a backward-compatible adapter that converts a legacy ``key``/``value``
call into the typed shape (emitting a :class:`DeprecationWarning`) so existing
consumers keep working.

Both the sync (:mod:`superpos_sdk.client`) and async
(:mod:`superpos_sdk.async_client`) clients import these helpers so the
conversion logic never drifts between them.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

#: Default ``type`` used when adapting a legacy ``key``/``value`` write to the
#: typed shape. ``topic`` is the general free-form page type in
#: ``App\Knowledge\FrontmatterSchema::TYPES`` — it has no hard-required
#: frontmatter keys, so an arbitrary legacy entry maps onto it cleanly.
DEFAULT_KNOWLEDGE_TYPE = "topic"


def _value_to_body(value: Any) -> str:
    """Serialize a legacy ``value`` to a ``body`` string.

    Strings pass through unchanged; everything else is JSON-encoded so no
    information is lost when a structured value is flattened into the typed
    ``body`` field.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_create_payload(
    *,
    type: str | None = None,
    slug: str | None = None,
    title: str | None = None,
    body: str | None = None,
    summary: str | None = None,
    frontmatter: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    scope: str | None = None,
    visibility: str | None = None,
    ttl: str | None = None,
    # ---- deprecated legacy params --------------------------------------
    key: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Build a typed knowledge-create request body.

    Prefers the typed fields. Whenever a deprecated ``key``/``value`` arg is
    supplied — even mixed with typed fields — each legacy field is normalized
    independently into the typed shape (``slug=key`` when ``slug`` is absent,
    ``body=<value>`` when ``body`` is absent, ``type`` defaulting to ``topic``)
    and a :class:`DeprecationWarning` is emitted. Structured values are also
    preserved verbatim under ``frontmatter`` regardless of which typed fields
    were supplied, so nothing is lost. The returned body NEVER contains ``key``
    or ``value`` keys.
    """
    legacy_used = key is not None or value is not None

    if legacy_used:
        warnings.warn(
            "The legacy `key`/`value` knowledge write shape is deprecated and "
            "rejected by the server. Pass the typed `type`/`slug`/`body` fields "
            "instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        # Normalize each legacy field independently of the others so a call
        # that mixes legacy and typed args never silently drops the legacy
        # data or mints an invalid payload.
        if slug is None and key is not None:
            slug = key
        if body is None and value is not None:
            body = _value_to_body(value)
        # Preserve the original structured value verbatim regardless of which
        # typed fields were supplied, so nothing is lost.
        if frontmatter is None and isinstance(value, (dict, list)):
            frontmatter = {"legacy_value": value}

    if type is None:
        type = DEFAULT_KNOWLEDGE_TYPE

    payload: dict[str, Any] = {"type": type, "slug": slug}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if summary is not None:
        payload["summary"] = summary
    if frontmatter is not None:
        payload["frontmatter"] = frontmatter
    if tags is not None:
        payload["tags"] = tags
    if scope is not None:
        payload["scope"] = scope
    if visibility is not None:
        payload["visibility"] = visibility
    if ttl is not None:
        payload["ttl"] = ttl
    return payload


def build_update_payload(
    *,
    type: str | None = None,
    slug: str | None = None,
    title: str | None = None,
    body: str | None = None,
    summary: str | None = None,
    frontmatter: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    visibility: str | None = None,
    ttl: str | None = None,
    # ---- deprecated legacy params --------------------------------------
    value: Any = None,
) -> dict[str, Any]:
    """Build a typed knowledge-update request body.

    ``UpdateKnowledgeRequest`` makes every typed field optional, so only the
    provided fields are sent. A legacy ``value`` is converted to ``body`` (and,
    for structured values, ``frontmatter``) with a :class:`DeprecationWarning`.
    The returned body NEVER contains a ``value`` key.
    """
    legacy_used = value is not None and body is None

    if legacy_used:
        warnings.warn(
            "The legacy `value` knowledge update shape is deprecated and "
            "rejected by the server. Pass the typed `body` field instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        body = _value_to_body(value)
        if frontmatter is None and isinstance(value, (dict, list)):
            frontmatter = {"legacy_value": value}

    payload: dict[str, Any] = {}
    if type is not None:
        payload["type"] = type
    if slug is not None:
        payload["slug"] = slug
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if summary is not None:
        payload["summary"] = summary
    if frontmatter is not None:
        payload["frontmatter"] = frontmatter
    if tags is not None:
        payload["tags"] = tags
    if visibility is not None:
        payload["visibility"] = visibility
    if ttl is not None:
        payload["ttl"] = ttl
    return payload


__all__ = [
    "DEFAULT_KNOWLEDGE_TYPE",
    "build_create_payload",
    "build_update_payload",
]
