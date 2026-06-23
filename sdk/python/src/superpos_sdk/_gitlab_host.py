"""Shared GitLab host-normalization helpers.

Host parsing for credential routing is security-sensitive — a sloppy match can
leak a token to a lookalike domain (``gitlab.com.evil.com``) or send a
self-managed credential to public GitLab. The normalization logic therefore
lives in one place and is reused by the ``superpos-gl-token`` credential helper.

This mirrors :mod:`superpos_sdk._github_host`; the rule is identical because the
threat (token disclosure to the wrong host) is identical.
"""

from __future__ import annotations


def normalize_host(value: str) -> str:
    """Lowercase a host and strip an optional ``:port`` suffix.

    A caller may hand us the host as ``gitlab.com`` or ``gitlab.com:443``; an
    explicit port is tolerated but everything else must match exactly so that
    lookalike domains are never treated as equivalent.
    """
    h = value.strip().lower()
    # Strip a trailing :port. IPv6 literals (bracketed) are not GitLab hosts,
    # so we only do this for non-bracketed values.
    if ":" in h and not h.startswith("["):
        h = h.rsplit(":", 1)[0]
    return h
