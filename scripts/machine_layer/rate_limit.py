"""In-memory token-bucket rate limiter for the MCP server.

Scope: stdio-local single process. The bucket dict is keyed by
`client_name` (from `clientInfo.name` in the MCP initialize handshake)
so that a future HTTP/SSE transport can reuse the same module in a
multi-tenant mode without rewrite.

Defaults:
    MCP_RATE_LIMIT_RPM = 60     burst per minute (refilled at rpm/60 tokens/sec)
    MCP_RATE_LIMIT_RPH = 600    sustained ceiling per rolling hour

Both limits must be satisfied for a request to pass — the tighter bucket
wins. Breach raises `ToolError("rate_limited: retry_after=<seconds>")`
so the SDK converts it to a protocol-level tool error with the message
preserved for the client.

Bypass for tests:
    RATE_LIMIT_DISABLED=true
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from mcp.server.mcpserver.exceptions import ToolError

logger = logging.getLogger(__name__)

DEFAULT_RPM = 60
DEFAULT_RPH = 600


@dataclass
class TokenBucket:
    """Two-level token bucket: per-minute burst + per-hour sustained.

    Refill is fractional — e.g. at 60 rpm each second adds 1.0 token.
    Consume deducts 1.0 from both levels. A request passes when BOTH
    levels have ≥ 1.0 available.
    """

    rpm: float
    rph: float
    now_fn: Callable[[], float] = time.monotonic
    minute_tokens: float = 0.0
    hour_tokens: float = 0.0
    last_refill: float = 0.0

    def __post_init__(self) -> None:
        self.minute_tokens = float(self.rpm)
        self.hour_tokens = float(self.rph)
        self.last_refill = self.now_fn()

    def _refill(self) -> None:
        now = self.now_fn()
        elapsed = max(0.0, now - self.last_refill)
        self.last_refill = now
        if elapsed == 0.0:
            return
        self.minute_tokens = min(
            float(self.rpm),
            self.minute_tokens + elapsed * (self.rpm / 60.0),
        )
        self.hour_tokens = min(
            float(self.rph),
            self.hour_tokens + elapsed * (self.rph / 3600.0),
        )

    def consume(self, n: float = 1.0) -> tuple[bool, float]:
        """Try to consume n tokens. Return (allowed, retry_after_seconds).

        retry_after is 0 on success; otherwise the seconds the tighter
        bucket needs to refill n tokens.
        """
        self._refill()
        if self.minute_tokens < n:
            deficit = n - self.minute_tokens
            retry = deficit * 60.0 / self.rpm
            return False, retry
        if self.hour_tokens < n:
            deficit = n - self.hour_tokens
            retry = deficit * 3600.0 / self.rph
            return False, retry
        self.minute_tokens -= n
        self.hour_tokens -= n
        return True, 0.0


# Module-level registry of buckets per client_name. `threading.Lock`
# is defensive — MCP stdio is single-threaded async, but HTTP mode
# will be multi-threaded and we want one code path.
_buckets: dict[str, TokenBucket] = {}
_lock = threading.Lock()


def _read_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("rate-limit-env-invalid name=%s value=%r fallback=%d",
                       name, raw, default)
        return default


def _disabled() -> bool:
    return (os.getenv("RATE_LIMIT_DISABLED") or "").lower() == "true"


def _get_bucket(client_name: str) -> TokenBucket:
    """Return the bucket for `client_name`, creating it on first use."""
    # Read env each time so tests can adjust without module reload.
    # The bucket itself caches rpm/rph at creation — recreate when env changes.
    rpm = _read_env_int("MCP_RATE_LIMIT_RPM", DEFAULT_RPM)
    rph = _read_env_int("MCP_RATE_LIMIT_RPH", DEFAULT_RPH)
    bucket = _buckets.get(client_name)
    if bucket is None or bucket.rpm != rpm or bucket.rph != rph:
        bucket = TokenBucket(rpm=rpm, rph=rph)
        _buckets[client_name] = bucket
    return bucket


def check_and_consume(client_name: str, tool_name: str | None = None) -> None:
    """Gate a tool invocation. Raise ToolError on limit breach.

    `client_name` is the identity used for bucket lookup (usually
    `clientInfo.name` from the MCP handshake; falls back to "default").
    `tool_name` is passed through to the error message for observability.
    """
    if _disabled():
        return
    with _lock:
        bucket = _get_bucket(client_name)
        allowed, retry_after = bucket.consume(1.0)
    if not allowed:
        tool_hint = f" tool={tool_name}" if tool_name else ""
        logger.warning(
            "rate-limited client=%s%s retry_after=%.2fs",
            client_name,
            tool_hint,
            retry_after,
        )
        raise ToolError(
            f"rate_limited: too many requests "
            f"(retry_after={retry_after:.2f}s, client={client_name})"
        )


def reset_buckets() -> None:
    """Clear all bucket state. Tests call this between scenarios."""
    with _lock:
        _buckets.clear()
