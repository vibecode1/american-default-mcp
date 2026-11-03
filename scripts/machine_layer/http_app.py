"""HTTP transport for the American Default MCP server.

Wraps ``MCPServer.streamable_http_app()`` (a Starlette ASGI app) with two
ASGI middlewares plus extra non-MCP routes:

1. **Bearer-auth middleware (tier model).** No bearer header = anonymous
   tier (allowed at lower rate). Valid bearer = issued tier (allowed at
   higher rate). Invalid bearer = HTTP 401. The tier is stamped on the
   ASGI scope so the rate-limit layer can apply different caps.

2. **Per-IP rate-limit middleware.** Sliding-window cap by IP-prefix
   (``/24`` for IPv4, ``/64`` for IPv6) at 100 rpm / 1000 rph. Cost
   ceiling regardless of how many keys an attacker rotates.

3. **Health endpoint** at ``/up`` — bypasses both middlewares.

4. **Contact endpoint** at ``/contact`` — accepts form-encoded POSTs
   from the public ``/press/mcp/`` page, validates fields, sends an
   email via the Resend API to ``MCP_CONTACT_TO`` (or ``NOTIFY_EMAIL``,
   or ``MCP_CONTACT_FROM`` as fallback), redirects to
   ``CONTACT_REDIRECT_URL`` on success.

Module-level entry point ``build_app()`` constructs and returns the
Starlette app for ``uvicorn`` to serve. ``mcp_server.main()`` calls it
when ``--transport http`` is selected.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from scripts.machine_layer.auth import _normalize_provided_key, get_expected_key
from scripts.machine_layer.discovery import CARD_PATH, CATALOG_PATH, COMPAT_CARD_PATH, discovery_response
from scripts.machine_layer.rate_limit import TokenBucket, _read_env_int

logger = logging.getLogger(__name__)

HEALTH_PATH = "/up"
CONTACT_PATH = "/contact"
MCP_PATH_PREFIX = "/mcp"

# Per-IP rate limit ceiling. Per the security model §4 — total per-IP
# cap (rpm) bounds abuse from one source even if it rotates anonymous
# keys.
DEFAULT_PER_IP_RPM = 100
DEFAULT_PER_IP_RPH = 1000

# Per-IP cap for /contact (much tighter — abuse here = spam at Ross).
DEFAULT_CONTACT_PER_IP_RPM = 1
DEFAULT_CONTACT_PER_IP_RPH = 5

_ip_buckets: dict[str, TokenBucket] = {}
_contact_buckets: dict[str, TokenBucket] = {}
_ip_lock = threading.Lock()


def _client_ip_prefix(request: Request) -> str:
    """Truncate the request client IP to /24 (IPv4) or /64 (IPv6)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "0.0.0.0"

    if ":" in ip:
        groups = ip.split(":")
        return ":".join(groups[:4]) + "::/64"
    octets = ip.split(".")
    if len(octets) == 4:
        return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
    return ip


def _ip_bucket(prefix: str) -> TokenBucket:
    rpm = _read_env_int("MCP_HTTP_PER_IP_RPM", DEFAULT_PER_IP_RPM)
    rph = _read_env_int("MCP_HTTP_PER_IP_RPH", DEFAULT_PER_IP_RPH)
    bucket = _ip_buckets.get(prefix)
    if bucket is None or bucket.rpm != rpm or bucket.rph != rph:
        bucket = TokenBucket(rpm=rpm, rph=rph)
        _ip_buckets[prefix] = bucket
    return bucket


def _contact_bucket(prefix: str) -> TokenBucket:
    rpm = _read_env_int("MCP_CONTACT_PER_IP_RPM", DEFAULT_CONTACT_PER_IP_RPM)
    rph = _read_env_int("MCP_CONTACT_PER_IP_RPH", DEFAULT_CONTACT_PER_IP_RPH)
    bucket = _contact_buckets.get(prefix)
    if bucket is None or bucket.rpm != rpm or bucket.rph != rph:
        bucket = TokenBucket(rpm=rpm, rph=rph)
        _contact_buckets[prefix] = bucket
    return bucket


def _ip_allowed(request: Request) -> tuple[bool, float, str]:
    if (os.getenv("RATE_LIMIT_DISABLED") or "").lower() == "true":
        return True, 0.0, _client_ip_prefix(request)
    prefix = _client_ip_prefix(request)
    with _ip_lock:
        bucket = _ip_bucket(prefix)
        allowed, retry_after = bucket.consume(1.0)
    return allowed, retry_after, prefix


def _contact_allowed(request: Request) -> tuple[bool, float, str]:
    if (os.getenv("RATE_LIMIT_DISABLED") or "").lower() == "true":
        return True, 0.0, _client_ip_prefix(request)
    prefix = _client_ip_prefix(request)
    with _ip_lock:
        bucket = _contact_bucket(prefix)
        allowed, retry_after = bucket.consume(1.0)
    return allowed, retry_after, prefix


def reset_ip_buckets() -> None:
    """Clear all per-IP bucket state. Tests call this between scenarios."""
    with _ip_lock:
        _ip_buckets.clear()
        _contact_buckets.clear()


# ---------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------


def _is_mcp_request(path: str) -> bool:
    if path == CARD_PATH:
        return False  # Public metadata, never an authenticated MCP operation.
    return path == MCP_PATH_PREFIX or path.startswith(MCP_PATH_PREFIX + "/")


async def _send_json(send, status: int, body: dict, extra_headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


def _parse_bearer(scope) -> str | None:
    """Extract the bearer token from the Authorization header, if any."""
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            raw = value.decode("latin-1", errors="replace")
            if raw.lower().startswith("bearer "):
                return raw[7:]
            break
    return None


class BearerAuthMiddleware:
    """ASGI middleware implementing the tier-aware auth model.

    Three states for /mcp requests:

    - **Anonymous tier** — no ``Authorization`` header, OR no
      ``MCP_API_KEY`` configured server-side. Stamp ``mcp_tier`` =
      ``"anonymous"`` on the scope and pass through. Rate-limit layer
      caps anonymous traffic tightly.
    - **Issued tier** — ``Authorization: Bearer <token>`` matches the
      server-side ``MCP_API_KEY``. Stamp ``mcp_tier`` = ``"issued"``
      and pass through. Higher rate-limit allowance.
    - **Rejected** — bearer present but doesn't match. HTTP 401.

    Non-MCP paths bypass auth entirely so /up and /contact stay open.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_mcp_request(path):
            await self.app(scope, receive, send)
            return

        expected = get_expected_key()
        provided_raw = _parse_bearer(scope)
        provided = _normalize_provided_key(provided_raw)

        if expected is None or provided is None:
            # No server-side key OR no bearer header → anonymous tier.
            scope["mcp_tier"] = "anonymous"
            await self.app(scope, receive, send)
            return

        if provided == expected:
            scope["mcp_tier"] = "issued"
            await self.app(scope, receive, send)
            return

        # Bearer provided but wrong → reject.
        logger.warning("auth-rejected path=%s reason=mismatch", path)
        await _send_json(send, 401, {
            "error": "unauthorized",
            "message": "invalid bearer token",
        })


class PerIpRateLimitMiddleware:
    """ASGI middleware: per-IP-prefix cap on /mcp + /contact.

    HTTP 429 with ``Retry-After`` on breach. /up bypasses so probes
    aren't gated.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_mcp_request(path):
            # /contact has its own bucket (tighter), enforced below.
            # /up + everything else is uncapped.
            if path == CONTACT_PATH and scope.get("method") == "POST":
                request = Request(scope, receive=receive)
                allowed, retry_after, prefix = _contact_allowed(request)
                if not allowed:
                    retry_seconds = max(1, int(retry_after) + 1)
                    logger.warning(
                        "contact-rate-limited prefix=%s retry_after=%.2fs",
                        prefix, retry_after,
                    )
                    await _send_json(
                        send, 429,
                        {
                            "error": "rate_limited",
                            "retry_after_seconds": retry_seconds,
                            "tier": "contact",
                        },
                        extra_headers=[(b"retry-after", str(retry_seconds).encode("ascii"))],
                    )
                    return
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        allowed, retry_after, prefix = _ip_allowed(request)
        if not allowed:
            retry_seconds = max(1, int(retry_after) + 1)
            logger.warning(
                "ip-rate-limited prefix=%s retry_after=%.2fs path=%s",
                prefix, retry_after, path,
            )
            await _send_json(
                send,
                429,
                {
                    "error": "rate_limited",
                    "retry_after_seconds": retry_seconds,
                    "tier": "per_ip",
                },
                extra_headers=[(b"retry-after", str(retry_seconds).encode("ascii"))],
            )
            return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------


async def _healthz(_request: Request) -> Response:
    return JSONResponse({
        "status": "ok",
        "transport": "streamable-http",
        "now": int(time.time()),
    })


# ---------------------------------------------------------------------
# Contact endpoint — form post → Resend email → 302 redirect
# ---------------------------------------------------------------------


# Loose RFC-5322-ish email pattern. Strict validation is the upstream
# mail provider's job; we just reject the obviously-broken.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

RESEND_ENDPOINT = "https://api.resend.com/emails"

CONTACT_DEFAULT_REDIRECT = "https://americandefault.org/press/mcp/?submitted=1"
CONTACT_DEFAULT_REJECT_REDIRECT = "https://americandefault.org/press/mcp/?submitted=0"


def _validate_contact_fields(name: str, email: str, use_case: str) -> str | None:
    """Return None if valid; an error code string if not."""
    name = name.strip()
    email = email.strip()
    use_case = use_case.strip()

    if not (2 <= len(name) <= 100):
        return "invalid_name_length"
    if not (5 <= len(email) <= 200):
        return "invalid_email_length"
    if not _EMAIL_RE.match(email):
        return "invalid_email_format"
    if not (20 <= len(use_case) <= 2000):
        return "invalid_use_case_length"
    # Cheap spam guard — reject HTML/JS injection attempts.
    for blob in (name, email, use_case):
        if "<" in blob or ">" in blob or "javascript:" in blob.lower():
            return "invalid_field_content"
    return None


def _send_contact_email(name: str, email: str, use_case: str) -> bool:
    """Send the form submission via the Resend API. Returns True on success."""
    api_key = os.getenv("RESEND_API_KEY")
    from_addr = os.getenv("MCP_CONTACT_FROM", "info@americandefault.org")
    to_addr = os.getenv("MCP_CONTACT_TO") or os.getenv("NOTIFY_EMAIL") or from_addr
    if not api_key:
        logger.error("contact-email-misconfigured resend_key_present=%s", bool(api_key))
        return False

    payload = json.dumps({
        "from": from_addr,
        "to": [to_addr],
        "subject": "[MCP] API key request",
        "reply_to": email,
        "text": (
            f"New MCP API-key request from /press/mcp/ contact form:\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n\n"
            f"Use case:\n{use_case}\n"
        ),
    }).encode("utf-8")

    req = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare in front of api.resend.com blocks the default
            # ``Python-urllib/...`` UA with error 1010. Identify ourselves.
            "User-Agent": "american-default-mcp/1.0 (+https://americandefault.org)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                return True
            logger.error("contact-email-send-failed status=%s", resp.status)
            return False
    except urllib.error.HTTPError as e:
        # Read the body so the log shows Resend's error reason, not just the code.
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error("contact-email-send-failed http_status=%s body=%s", e.code, body)
        return False
    except Exception:
        logger.exception("contact-email-send-failed")
        return False


async def _contact_post(request: Request) -> Response:
    """Handle a /contact form submission.

    Accepts ``application/x-www-form-urlencoded`` or
    ``multipart/form-data``. On success, redirects to the configured
    success URL so the user lands back on /press/mcp/ with a thanks
    state. On failure, redirects with ?submitted=0 plus an error code.
    """
    redirect_ok = os.getenv("MCP_CONTACT_REDIRECT_OK", CONTACT_DEFAULT_REDIRECT)
    redirect_bad = os.getenv("MCP_CONTACT_REDIRECT_BAD", CONTACT_DEFAULT_REJECT_REDIRECT)

    try:
        form = await request.form()
    except Exception:
        return RedirectResponse(f"{redirect_bad}&error=invalid_form", status_code=302)

    name = str(form.get("name", "") or "")
    email = str(form.get("email", "") or "")
    use_case = str(form.get("use_case", "") or "")
    # Honeypot — a hidden field that humans never fill but bots often do.
    if str(form.get("website", "") or "").strip():
        logger.warning("contact-honeypot-tripped ip_prefix=%s", _client_ip_prefix(request))
        return RedirectResponse(redirect_ok, status_code=302)

    err = _validate_contact_fields(name, email, use_case)
    if err is not None:
        return RedirectResponse(f"{redirect_bad}&error={err}", status_code=302)

    sent = _send_contact_email(name.strip(), email.strip(), use_case.strip())
    if not sent:
        return RedirectResponse(f"{redirect_bad}&error=send_failed", status_code=302)

    logger.info("contact-submitted name_len=%d use_case_len=%d",
                len(name.strip()), len(use_case.strip()))
    return RedirectResponse(redirect_ok, status_code=302)


# ---------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------


def build_app(mcp_app=None) -> Starlette:
    """Construct the Starlette app for the MCP HTTP transport."""
    if mcp_app is None:
        from scripts.machine_layer.mcp_server import (
            _build_transport_security,
            mcp as _mcp,
        )

        mcp_app = _mcp.streamable_http_app(
            transport_security=_build_transport_security()
        )

    routes: list = [
        Route(path, endpoint=discovery_response, methods=["GET", "HEAD", "OPTIONS"])
        for path in (CARD_PATH, COMPAT_CARD_PATH, CATALOG_PATH)
    ] + list(mcp_app.routes)
    routes.append(Route(HEALTH_PATH, endpoint=_healthz, methods=["GET"]))
    routes.append(Route(CONTACT_PATH, endpoint=_contact_post, methods=["POST"]))

    app = Starlette(
        debug=False,
        routes=routes,
        lifespan=mcp_app.router.lifespan_context,
    )

    wrapped = PerIpRateLimitMiddleware(app)
    wrapped = BearerAuthMiddleware(wrapped)
    return wrapped  # type: ignore[return-value]
