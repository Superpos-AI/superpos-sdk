"""superpos-gl-token — serve short-lived GitLab OAuth tokens via the Superpos platform.

CLI credential helper that resolves a GitLab OAuth access token through the
Superpos API, caches it on tmpfs, and optionally speaks the git-credential
protocol so ``git`` / ``glab`` can use it transparently for local clones.

This is the GitLab analogue of :mod:`superpos_sdk.gh_token`. GitLab has no
GitHub-App-style installation-token broker; a ``gitlab_oauth`` connection holds a
per-connection access/refresh token pair, and the platform hands back a
**refreshed access token** (short-lived, never the refresh token or client
secret) for git operations.

Connection selection precedence (first match wins):

1. ``--connection <id>`` CLI flag
2. ``GL_CONNECTION_ID`` env var
3. ``.superpos/gitlab.toml`` discovered by walking upward from CWD
4. Persona ``default_connection_id`` from ``GET /api/v1/persona``
5. If still ambiguous — exit non-zero with candidate list
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ._gitlab_host import normalize_host as _normalize_host
from .exceptions import _parse_errors

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


# Default GitLab API base for a connection the persona advertises without an
# explicit base_url (a public gitlab.com connection).
_DEFAULT_API_BASE = "https://gitlab.com/api/v4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_base() -> str:
    base = os.environ.get("SUPERPOS_BASE_URL", "")
    if not base:
        _die("SUPERPOS_BASE_URL is not set")
    return base.rstrip("/")


def _api_token() -> str:
    token = os.environ.get("SUPERPOS_API_TOKEN", "")
    if not token:
        _die("SUPERPOS_API_TOKEN is not set")
    return token


def _die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _require_httpx():  # type: ignore[return]
    if httpx is None:  # pragma: no cover
        _die("httpx is required: pip install superpos-sdk[gitlab]")


def _cache_path(connection_id: str) -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime_dir) / f"superpos-gl-token-{connection_id}.json"


def _read_cache(connection_id: str) -> dict[str, Any] | None:
    path = _cache_path(connection_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        from datetime import datetime, timezone

        expires_at = data.get("expires_at")
        if expires_at is None:
            # No expiry advertised — never serve from cache so that
            # rotation/revocation takes effect immediately.
            return None
        if expires_at.endswith("Z"):
            expires_at = expires_at[:-1] + "+00:00"
        expires = datetime.fromisoformat(expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if (expires - now).total_seconds() > 60:
            return data
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        pass
    return None


def _write_cache(connection_id: str, data: dict[str, Any]) -> None:
    path = _cache_path(connection_id)
    path.write_text(json.dumps(data))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# Connection resolution
# ---------------------------------------------------------------------------


def _discover_toml() -> str | None:
    if tomllib is None:
        return None
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".superpos" / "gitlab.toml"
        if candidate.is_file():
            try:
                doc = tomllib.loads(candidate.read_text())
                return doc.get("connection_id")
            except Exception:
                pass
    return None


def _fetch_persona() -> dict[str, Any]:
    _require_httpx()
    r = httpx.get(
        f"{_api_base()}/api/v1/persona",
        headers={"Authorization": f"Bearer {_api_token()}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", r.json())


def _connection_id(conn: dict[str, Any]) -> str | None:
    """Return a connection's identifier per the persona contract.

    The persona ``gitlab.connections[]`` contract identifies each connection by
    ``service_connection_id``. A legacy ``id`` key is tolerated as a fallback so
    the helper stays robust if an older payload shape is ever returned.
    """
    return conn.get("service_connection_id") or conn.get("id")


def _persona_connections() -> list[dict[str, Any]]:
    persona = _fetch_persona()
    return persona.get("gitlab", {}).get("connections", [])


def _persona_default_connection() -> str | None:
    persona = _fetch_persona()
    gl = persona.get("gitlab", {})
    default_id = gl.get("default_connection_id")
    if default_id:
        return default_id
    connections = gl.get("connections", [])
    compatible = [c for c in connections if _is_broker_compatible(c)]
    if len(compatible) == 1:
        return _connection_id(compatible[0])
    return None


def _find_persona_connection(connection_id: str) -> dict[str, Any] | None:
    """Return the persona connection entry for *connection_id*, or None.

    Returning None specifically means the persona does NOT advertise this
    connection. That distinction is security-critical: an absent connection
    proves nothing about its host. Callers that bind credentials to a host MUST
    fail closed on None rather than assume public GitLab.
    """
    for conn in _persona_connections():
        if _connection_id(conn) == connection_id:
            return conn
    return None


def _connection_host(connection_id: str) -> str | None:
    """Return the git host the bound connection vouches for, or None when it
    cannot be proven.

    * connection present, no base_url -> ``"gitlab.com"`` (public GitLab)
    * connection present with base_url -> that URL's normalized host
    * connection ABSENT from persona  -> None (host unprovable -> fail closed)
    * base_url present but unparseable -> None (fail closed)
    """
    conn = _find_persona_connection(connection_id)
    if conn is None:
        return None
    base_url = conn.get("base_url") or ""
    if not base_url:
        return "gitlab.com"
    return _normalize_host(urlsplit(base_url).hostname or "") or None


def _connection_api_base_url(connection_id: str) -> str | None:
    """Return the REST API base URL the bound connection vouches for, or None
    when the connection is absent from the persona.

    * connection present, no base_url -> ``"https://gitlab.com/api/v4"``
    * connection present with base_url -> that base_url
    * connection ABSENT from persona  -> None (host unprovable -> fail closed)
    """
    conn = _find_persona_connection(connection_id)
    if conn is None:
        return None
    return conn.get("base_url") or _DEFAULT_API_BASE


def _is_broker_compatible(conn: dict[str, Any]) -> bool:
    """Return True if the connection can be served an access token.

    Every ``gitlab_oauth`` connection is compatible (the server holds a
    refreshable access token for it). Checks the explicit ``broker_compatible``
    field first, falling back to an ``auth_type`` check for older payloads.
    """
    marker = conn.get("broker_compatible")
    if marker is not None:
        return bool(marker)
    return conn.get("auth_type") == "gitlab_oauth"


def resolve_connection(explicit: str | None = None) -> str:
    """Return the service_connection_id to use, following the precedence chain."""
    if explicit:
        return explicit

    from_env = os.environ.get("GL_CONNECTION_ID")
    if from_env:
        return from_env

    from_toml = _discover_toml()
    if from_toml:
        return from_toml

    from_persona = _persona_default_connection()
    if from_persona:
        return from_persona

    connections = _persona_connections()
    if connections:
        compatible = [c for c in connections if _is_broker_compatible(c)]
        if len(compatible) == 1:
            return _connection_id(compatible[0]) or ""
        if compatible:
            lines = [
                f"  {_connection_id(c) or '?'}  {c.get('name', '')}  {c.get('actor_login', '')}"
                for c in compatible
            ]
            _die(
                "Multiple GitLab connections available — specify one:\n"
                + "\n".join(lines)
                + "\n\nUse --connection <id>, GL_CONNECTION_ID env, "
                "or .superpos/gitlab.toml"
            )
        _die("No usable GitLab connections found for this agent persona")
    _die("No GitLab connections found for this agent persona")
    return ""  # unreachable, keeps type-checkers happy


# ---------------------------------------------------------------------------
# Token minting
# ---------------------------------------------------------------------------


def mint_token(connection_id: str, *, force: bool = False) -> dict[str, Any]:
    """Serve (or return cached) GitLab access token for *connection_id*."""
    if not force:
        cached = _read_cache(connection_id)
        if cached:
            return cached

    _require_httpx()
    r = httpx.post(
        f"{_api_base()}/api/v1/gitlab/access-token",
        headers={
            "Authorization": f"Bearer {_api_token()}",
            "Content-Type": "application/json",
        },
        json={"service_connection_id": connection_id},
        timeout=30,
    )

    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        errors = _parse_errors(body.get("errors"))
        if errors:
            _die(f"GitLab token error: {errors[0].message}")
        _die(f"GitLab token error: HTTP {r.status_code}: {r.text}")

    data = r.json().get("data", r.json())
    if data.get("expires_at") is not None:
        _write_cache(connection_id, data)
    return data


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------


def _cmd_print_token(args: argparse.Namespace) -> None:
    cid = resolve_connection(args.connection)
    data = mint_token(cid, force=args.refresh)
    print(data["token"])


def _cmd_git_credential(args: argparse.Namespace) -> None:
    # git invokes a credential helper with an operation argument: get, store,
    # or erase. We only supply credentials on "get"; store/erase are no-ops
    # because nothing is persisted by this helper. A missing operation (manual
    # invocation) is treated like "get" for convenience.
    operation = getattr(args, "operation", None)
    if operation not in (None, "get"):
        return

    fields: dict[str, str] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            break
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v

    # Reject non-HTTPS protocols to prevent leaking tokens over cleartext.
    protocol = fields.get("protocol")
    if protocol is not None and protocol != "https":
        sys.exit(0)

    host = fields.get("host", "")

    # FAST PATH: an empty host (manual probe) is a no-op.
    if not host:
        sys.exit(0)

    # The served token is bound to a specific connection, so the only safe
    # recipient is that connection's OWN host. Resolve the connection that would
    # issue the token, then require the requested host to equal the host the
    # connection vouches for. A connection the persona does NOT advertise has an
    # unprovable host (_connection_host returns None) — fail closed, never
    # defaulting to gitlab.com.
    try:
        cid = resolve_connection(args.connection)
        connection_host = _connection_host(cid)
    except (SystemExit, Exception):
        sys.exit(0)

    if not connection_host or _normalize_host(host) != connection_host:
        sys.exit(0)

    data = mint_token(cid, force=args.refresh)
    # GitLab accepts an OAuth access token as the password with the literal
    # username ``oauth2`` over HTTPS.
    print(f"protocol={fields.get('protocol', 'https')}")
    print(f"host={host}")
    print("username=oauth2")
    print(f"password={data['token']}")


def _cmd_bot_login(args: argparse.Namespace) -> None:
    cid = resolve_connection(args.connection)
    data = mint_token(cid, force=args.refresh)
    print(data.get("actor_login", ""))


def _cmd_api_base_url(args: argparse.Namespace) -> None:
    """Print the resolved connection's API base_url.

    Lets a worker discover the connection's GitLab REST API host (public GitLab
    or an allowlisted self-managed instance) without hard-coding it. A
    connection the persona does NOT advertise is a hard failure: its host is
    unprovable, and silently defaulting to public GitLab would let a
    connection-bound (possibly self-managed) token be routed to gitlab.com.
    """
    cid = resolve_connection(args.connection)
    base_url = _connection_api_base_url(cid)
    if base_url is None:
        _die(
            f"Cannot resolve an API base URL for connection {cid!r}: the agent "
            f"persona does not advertise it, so its host cannot be proven. "
            f"Refusing to default to public GitLab."
        )
    print(base_url)


def _cmd_list_connections(args: argparse.Namespace) -> None:
    connections = _persona_connections()
    if not connections:
        print("No GitLab connections found.", file=sys.stderr)
        sys.exit(1)
    for c in connections:
        print(f"{_connection_id(c) or '?'}\t{c.get('name', '')}\t{c.get('actor_login', '')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="superpos-gl-token",
        description="Serve short-lived GitLab OAuth tokens via the Superpos platform.",
    )
    parser.add_argument(
        "--git-credential",
        action="store_true",
        help="Speak the git-credential protocol on stdin/stdout.",
    )
    parser.add_argument(
        "--bot-login",
        action="store_true",
        help="Print the connection's actor login.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch, bypass cache.",
    )
    parser.add_argument(
        "--connection",
        default=None,
        help="Override connection selection with a specific service_connection_id.",
    )
    parser.add_argument(
        "--list-connections",
        action="store_true",
        help="Print permitted connections (debug).",
    )
    parser.add_argument(
        "--api-base-url",
        action="store_true",
        help="Print the resolved connection's API base URL (for self-managed discovery).",
    )
    # git passes a credential operation (get/store/erase) as a positional
    # argument when this CLI is wired as `!superpos-gl-token --git-credential`.
    parser.add_argument(
        "operation",
        nargs="?",
        default=None,
        help="git-credential operation (get/store/erase); used only with --git-credential.",
    )

    args = parser.parse_args()

    if args.list_connections:
        _cmd_list_connections(args)
    elif args.api_base_url:
        _cmd_api_base_url(args)
    elif args.git_credential:
        _cmd_git_credential(args)
    elif args.bot_login:
        _cmd_bot_login(args)
    else:
        _cmd_print_token(args)


if __name__ == "__main__":
    main()
