"""Origin enforcement + CSP helpers for the public widget endpoints.

The widget iframe (loaded inside a host site) calls
``GET /widgets/{id}/config`` to pull its runtime config. The parent origin
is sent either via the standard ``Origin`` request header (for direct
fetches) OR via a ``parent_origin`` query parameter (because a cross-origin
iframe cannot read ``window.parent.location`` — the loader injects it
into the iframe URL instead).

A widget's ``allowed_origins`` can contain:

- a full origin like ``https://example.com``
- ``*`` — wildcard, public widget (use sparingly)

We also emit a ``Content-Security-Policy: frame-ancestors`` header derived
from the same allowlist so browsers will refuse to render the response in
a forbidden parent frame.
"""

from __future__ import annotations

from typing import Iterable, Optional

from fastapi import Request


def normalize_origin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().rstrip("/")


def extract_parent_origin(request: Request) -> Optional[str]:
    """Resolve the most trustworthy parent-origin signal we can find."""
    explicit = request.query_params.get("parent_origin")
    if explicit:
        return normalize_origin(explicit)
    origin_header = request.headers.get("origin")
    if origin_header:
        return normalize_origin(origin_header)
    # Fallback: Referer (less trustworthy but useful for direct browser hits).
    referer = request.headers.get("referer")
    if referer:
        from urllib.parse import urlparse

        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


def origin_allowed(origin: Optional[str], allowed_origins: Iterable[str]) -> bool:
    allow_list = [normalize_origin(o) for o in allowed_origins if o]
    if "*" in allow_list:
        return True
    if not origin:
        return False
    return origin in allow_list


def frame_ancestors_csp(allowed_origins: Iterable[str]) -> str:
    """Build a ``frame-ancestors`` CSP directive from the widget allowlist."""
    sources: list[str] = []
    for o in allowed_origins:
        o = normalize_origin(o) or ""
        if not o:
            continue
        if o == "*":
            return "frame-ancestors *"
        sources.append(o)
    if not sources:
        return "frame-ancestors 'none'"
    return "frame-ancestors " + " ".join(sources)


__all__ = [
    "extract_parent_origin",
    "frame_ancestors_csp",
    "normalize_origin",
    "origin_allowed",
]
