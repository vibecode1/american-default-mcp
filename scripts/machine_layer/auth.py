"""API-key auth hook for the MCP server.

**Scaffolding** for a future HTTP/SSE transport where multi-tenant API
keys matter. On stdio today the OS process boundary IS the auth
boundary: Claude Desktop spawns the server via its config and nothing
else can reach the process.

Contract:

- When ``MCP_API_KEY`` is unset → no auth configured → both hooks are
  no-ops. Session 1 probe + Session 2 tools keep working as before.
- When ``MCP_API_KEY`` is set → ``log_auth_attempt()`` records each
  tool invocation's asserted identity to stderr (INFO on match,
  WARNING on mismatch). It does NOT block on stdio — blocking is
  reserved for HTTP mode, where the in-band credential is available
  on every request.
- ``verify_api_key(provided)`` is the stricter hook that DOES block —
  tests exercise it directly. The HTTP transport will wrap each
  request with ``verify_api_key(request.headers.get("x-api-key"))``;
  the stdio transport never calls it.

Tests MUST leave ``MCP_API_KEY`` unset at module level so existing
Session 1 tests aren't gated by auth. Fixtures that need auth set it
via ``monkeypatch.setenv`` and clean up in teardown.
"""
from __future__ import annotations

import logging
import os

from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


def get_expected_key() -> str | None:
    """Return the server-side API key, or None if auth is not configured.

    Whitespace around the env value is stripped before return — Ross's
    deploy step copies-pastes keys into a Workers env, and a trailing
    newline from a clipboard paste must not silently change the
    expected key.
    """
    raw = os.getenv("MCP_API_KEY")
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped == "":
        return None
    return stripped


def _normalize_provided_key(provided: str | None) -> str | None:
    """Strip whitespace from a provided bearer token.

    Closes threat B1 — pasted bearer tokens with trailing newlines or
    leading whitespace must match the stored key. Returns None for
    None or empty-after-strip input so the caller hits the same
    "missing key" branch as a literal None.
    """
    if provided is None:
        return None
    stripped = provided.strip()
    return stripped if stripped else None


def log_auth_attempt(
    client_name: str | None,
    asserted_key: str | None = None,
    tool_name: str | None = None,
) -> None:
    """Stdio audit log. No-op when MCP_API_KEY is unset.

    The asserted_key is always None on stdio today — we log the identity
    that the client declared via clientInfo.name, so Ross can see in
    stderr which Claude Desktop / Cursor / other process is hitting the
    server. When HTTP mode lands, the asserted_key will carry the
    request-side token for matching.
    """
    expected = get_expected_key()
    if expected is None:
        return

    client = client_name or "anonymous"
    tool_hint = f" tool={tool_name}" if tool_name else ""
    asserted = _normalize_provided_key(asserted_key)

    if asserted and asserted == expected:
        logger.info("auth-ok client=%s%s", client, tool_hint)
    elif asserted:
        logger.warning("auth-mismatch client=%s%s", client, tool_hint)
    else:
        # Stdio has no in-band key surface today — this is expected
        # during stdio usage when a server-side key is configured.
        logger.warning("auth-missing-key client=%s%s (stdio mode)", client, tool_hint)


def verify_api_key(provided: str | None) -> bool:
    """HTTP-mode middleware hook. Raises ToolError on mismatch.

    Returns True when no server-side key is configured (auth optional)
    or when the provided key matches. Raises
    ToolError("unauthorized: ...") otherwise.

    stdio tools call ``log_auth_attempt`` instead — this function is
    the entry point for a future HTTP/SSE transport.
    """
    expected = get_expected_key()
    if expected is None:
        return True
    normalized = _normalize_provided_key(provided)
    if normalized is None or normalized != expected:
        raise ToolError("unauthorized: invalid or missing API key")
    return True
