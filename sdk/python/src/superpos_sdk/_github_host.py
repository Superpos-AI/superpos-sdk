"""Shared GitHub host-normalization helpers.

Host parsing for credential routing is security-sensitive — a sloppy match can
leak a token to a lookalike domain (``github.com.evil.com``) or send an
enterprise credential to public GitHub. The normalization logic therefore lives
in one place and is reused by both the ``superpos-gh-token`` credential helper
and the :class:`~superpos_sdk.workers.github.GitHubWorker`.
"""

from __future__ import annotations


def normalize_host(value: str) -> str:
    """Lowercase a host and strip an optional ``:port`` suffix.

    A caller may hand us the host as ``github.com`` or ``github.com:443``; an
    explicit port is tolerated but everything else must match exactly so that
    lookalike domains are never treated as equivalent.
    """
    h = value.strip().lower()
    # Strip a trailing :port. IPv6 literals (bracketed) are not GitHub hosts,
    # so we only do this for non-bracketed values.
    if ":" in h and not h.startswith("["):
        h = h.rsplit(":", 1)[0]
    return h
