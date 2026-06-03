"""superpos-gh-token — mint short-lived GitHub tokens via the Superpos platform broker.

CLI credential helper that resolves a GitHub App installation token through the
Superpos API, caches it on tmpfs, and optionally speaks the git-credential
protocol so ``git`` can use it transparently.

Connection selection precedence (first match wins):

1. ``--connection <id>`` CLI flag
2. ``GH_CONNECTION_ID`` env var
3. ``.superpos/github.toml`` discovered by walking upward from CWD
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

from ._github_host import normalize_host as _normalize_host
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
        _die("httpx is required: pip install superpos-sdk[github]")


def _cache_path(connection_id: str) -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime_dir) / f"superpos-gh-token-{connection_id}.json"


def _read_cache(connection_id: str) -> dict[str, Any] | None:
    path = _cache_path(connection_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        from datetime import datetime, timezone

        expires_at = data.get("expires_at")
        if expires_at is None:
            # PATs have no expiry — never serve from cache so that
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
        candidate = directory / ".superpos" / "github.toml"
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
    """Return a connection's identifier per the documented persona contract.

    The persona ``github.connections[]`` contract identifies each connection by
    ``service_connection_id`` (see docs/proposals/github-app-integration.md).
    A legacy ``id`` key is tolerated as a fallback so the helper stays robust if
    an older payload shape is ever returned.
    """
    return conn.get("service_connection_id") or conn.get("id")


def _persona_default_connection() -> str | None:
    persona = _fetch_persona()
    gh = persona.get("github", {})
    default_id = gh.get("default_connection_id")
    if default_id:
        return default_id
    # Only auto-select a sole connection when it is broker-compatible.
    # A lone PAT connection must not be silently chosen here — it would be
    # rejected by the broker (pat_brokering_unsupported); resolve_connection()
    # handles that case downstream with a clear error message.
    connections = gh.get("connections", [])
    compatible = [c for c in connections if _is_broker_compatible(c)]
    if len(compatible) == 1:
        return _connection_id(compatible[0])
    return None


def _persona_connections() -> list[dict[str, Any]]:
    persona = _fetch_persona()
    return persona.get("github", {}).get("connections", [])


def _find_persona_connection(connection_id: str) -> dict[str, Any] | None:
    """Return the persona connection entry for *connection_id*, or None.

    Returning None specifically means the persona does NOT advertise this
    connection. That distinction is security-critical: an absent connection
    proves nothing about its host, whereas a connection that *is* present but
    carries no base_url is a genuine public-github.com connection. Callers that
    bind credentials to a host MUST fail closed on None rather than assume
    public GitHub.
    """
    for conn in _persona_connections():
        if _connection_id(conn) == connection_id:
            return conn
    return None


def _connection_base_url(connection_id: str) -> str:
    """Return the persona-advertised API base_url for *connection_id*.

    The persona ``github.connections[]`` contract carries each connection's
    stored ``base_url`` (e.g. ``https://github.acme.corp/api/v3`` for GitHub
    Enterprise Server). Returns an empty string when the connection is not found
    OR carries no base_url.

    WARNING: this conflates "connection absent" with "connection present but no
    base_url" — both return "". Do NOT use it for host-binding decisions; use
    :func:`_connection_host` / :func:`_connection_api_base_url`, which fail
    closed (return None) on an absent connection.
    """
    conn = _find_persona_connection(connection_id)
    return (conn.get("base_url") or "") if conn else ""


def _connection_host(connection_id: str) -> str | None:
    """Return the git host the bound connection vouches for, or None when it
    cannot be proven.

    * connection present, no base_url -> ``"github.com"`` (public GitHub)
    * connection present, base_url is public API (``https://api.github.com``)
      -> ``"github.com"`` (the git host, not the API host)
    * connection present with base_url -> that URL's normalized host
    * connection ABSENT from persona  -> None (host unprovable -> fail closed)
    * base_url present but unparseable -> None (fail closed)
    """
    conn = _find_persona_connection(connection_id)
    if conn is None:
        return None
    base_url = conn.get("base_url") or ""
    if not base_url:
        return "github.com"
    host = _normalize_host(urlsplit(base_url).hostname or "") or None
    if host == "api.github.com":
        return "github.com"
    return host


def _connection_api_base_url(connection_id: str) -> str | None:
    """Return the REST API base URL the bound connection vouches for, or None
    when the connection is absent from the persona.

    * connection present, no base_url -> ``"https://api.github.com"``
    * connection present with base_url -> that base_url
    * connection ABSENT from persona  -> None (host unprovable -> fail closed)
    """
    conn = _find_persona_connection(connection_id)
    if conn is None:
        return None
    return conn.get("base_url") or "https://api.github.com"


def _is_broker_compatible(conn: dict[str, Any]) -> bool:
    """Return True if the connection can be used with the token broker.

    Checks the explicit ``broker_compatible`` field first (set by the server
    since the persona contract includes all connection types), falling back
    to an ``auth_type`` check for backward compatibility with older payloads.
    """
    marker = conn.get("broker_compatible")
    if marker is not None:
        return bool(marker)
    return conn.get("auth_type") == "github_app"


def resolve_connection(explicit: str | None = None) -> str:
    """Return the service_connection_id to use, following the precedence chain."""
    if explicit:
        return explicit

    from_env = os.environ.get("GH_CONNECTION_ID")
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
        # Only show broker-compatible connections as candidates
        compatible = [c for c in connections if _is_broker_compatible(c)]
        if len(compatible) == 1:
            return _connection_id(compatible[0]) or ""
        if compatible:
            lines = [
                f"  {_connection_id(c) or '?'}  "
                f"{c.get('target_login', '')}  {c.get('actor_login', '')}"
                for c in compatible
            ]
            _die(
                "Multiple GitHub App connections available — specify one:\n"
                + "\n".join(lines)
                + "\n\nUse --connection <id>, GH_CONNECTION_ID env, "
                "or .superpos/github.toml"
            )
        # All connections are PAT-backed — none are broker-compatible
        _die(
            "No broker-compatible GitHub connections found. All connections "
            "are PAT-backed (auth_type='token') which the token broker cannot "
            "serve.\nUse the legacy GITHUB_TOKEN env var or migrate to a "
            "GitHub App installation."
        )
    _die("No GitHub connections found for this agent persona")
    return ""  # unreachable, keeps mypy happy


# ---------------------------------------------------------------------------
# Token minting
# ---------------------------------------------------------------------------


def mint_token(connection_id: str, *, force: bool = False) -> dict[str, Any]:
    """Mint (or return cached) installation token for *connection_id*."""
    if not force:
        cached = _read_cache(connection_id)
        if cached:
            return cached

    _require_httpx()
    r = httpx.post(
        f"{_api_base()}/api/v1/github/installation-token",
        headers={
            "Authorization": f"Bearer {_api_token()}",
            "Content-Type": "application/json",
        },
        json={"service_connection_id": connection_id},
        timeout=30,
    )

    if r.status_code == 403:
        try:
            body = r.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        # The API error envelope is {"data": null, "meta": {...}, "errors": [...]}.
        # The error code lives at errors[0].code; install_url lives at the
        # top-level meta (ApiError carries no meta, so read it separately).
        errors = _parse_errors(body.get("errors"))
        error_code = errors[0].code if errors else ""
        if error_code == "github_app_not_installed":
            meta = body.get("meta")
            install_url = meta.get("install_url", "") if isinstance(meta, dict) else ""
            msg = "GitHub App is not installed on the target account."
            if install_url:
                msg += f"\nInstall it here: {install_url}"
            _die(msg)

    if r.status_code == 400:
        try:
            body400 = r.json()
        except Exception:
            body400 = {}
        if not isinstance(body400, dict):
            body400 = {}
        errors400 = _parse_errors(body400.get("errors"))
        error_code400 = errors400[0].code if errors400 else ""
        if error_code400 == "pat_brokering_unsupported":
            _die(
                "This connection is PAT-backed (auth_type='token') and cannot "
                "be used with the token broker.\nUse the legacy GITHUB_TOKEN "
                "env var or migrate to a GitHub App installation."
            )

    if r.status_code >= 400:
        try:
            detail = r.text
        except Exception:
            detail = f"HTTP {r.status_code}"
        _die(f"Token broker error: {detail}")

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
    # If protocol is absent we default to https (safe). If it is present and
    # is anything other than "https", fail closed — git treats no output as
    # "no credentials".
    protocol = fields.get("protocol")
    if protocol is not None and protocol != "https":
        sys.exit(0)

    host = fields.get("host", "")

    # FAST PATH: an empty host (manual probe) is a no-op — exit cleanly without
    # touching the persona or minting anything.
    if not host:
        sys.exit(0)

    # The minted token is bound to a specific connection, so the only safe
    # recipient is that connection's OWN host. Resolve the connection that
    # would issue the token, then require the requested host to equal the host
    # advertised by that connection. A connection present in the persona with no
    # base_url is a public github.com connection; a connection whose base_url is
    # a GitHub Enterprise Server instance (e.g. https://github.acme.corp/api/v3)
    # only vouches for that enterprise host.
    #
    # This deliberately does NOT special-case github.com or SUPERPOS_GHES_HOST.
    # "Is this host generally allowed?" is the wrong question: a token bound to
    # a GHES connection must never be handed to github.com (or vice versa), even
    # though both are otherwise "allowed" hosts. Validating the request host
    # against the *issuing connection* is what prevents off-host token
    # disclosure.
    #
    # A connection that the persona does NOT advertise is the critical case:
    # _connection_host() returns None because its host is unprovable. An absent
    # persona entry is NOT evidence of a public github.com connection, so we must
    # NOT default to github.com — we fail closed exactly like any other
    # unprovable host.
    #
    # Any failure to resolve the connection or prove its host fails closed: git
    # treats a clean exit with no output as "no credentials", so this must never
    # surface as a hard error.
    try:
        cid = resolve_connection(args.connection)
        connection_host = _connection_host(cid)
    except (SystemExit, Exception):
        sys.exit(0)

    if not connection_host or _normalize_host(host) != connection_host:
        # Fail closed: never mint a token for a host the bound connection does
        # not vouch for (including a connection absent from the persona).
        sys.exit(0)

    data = mint_token(cid, force=args.refresh)
    print(f"protocol={fields.get('protocol', 'https')}")
    print(f"host={host}")
    print("username=x-access-token")
    print(f"password={data['token']}")


def _cmd_bot_login(args: argparse.Namespace) -> None:
    cid = resolve_connection(args.connection)
    data = mint_token(cid, force=args.refresh)
    print(data.get("actor_login", ""))


def _cmd_api_base_url(args: argparse.Namespace) -> None:
    """Print the resolved connection's API base_url.

    Lets the worker discover the connection's GitHub REST API host (public
    GitHub or a GitHub Enterprise Server instance) without hard-coding it.

    A connection present in the persona with no base_url is a public-GitHub
    connection and resolves to ``https://api.github.com``. But a connection the
    persona does NOT advertise is a hard failure: its host is unprovable, and
    silently defaulting to public GitHub would let a connection-bound (possibly
    GHES) token be routed to api.github.com. We fail closed (non-zero exit, no
    stdout); GitHubWorker treats an empty/failed helper result as a refusal.
    """
    cid = resolve_connection(args.connection)
    base_url = _connection_api_base_url(cid)
    if base_url is None:
        _die(
            f"Cannot resolve an API base URL for connection {cid!r}: the agent "
            f"persona does not advertise it, so its host cannot be proven. "
            f"Refusing to default to public GitHub."
        )
    print(base_url)


def _cmd_list_connections(args: argparse.Namespace) -> None:
    connections = _persona_connections()
    if not connections:
        print("No GitHub connections found.", file=sys.stderr)
        sys.exit(1)
    for c in connections:
        compat = "" if _is_broker_compatible(c) else "\t(pat — broker incompatible)"
        print(
            f"{_connection_id(c) or '?'}\t{c.get('target_login', '')}\t"
            f"{c.get('actor_login', '')}{compat}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="superpos-gh-token",
        description="Mint short-lived GitHub tokens via the Superpos platform broker.",
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
        help="Force re-mint, bypass cache.",
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
        help="Print the resolved connection's API base URL (for GHES discovery).",
    )
    # git passes a credential operation (get/store/erase) as a positional
    # argument when this CLI is wired as `!superpos-gh-token --git-credential`.
    # Accept it so argparse does not reject the invocation; only --git-credential
    # mode interprets it.
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
