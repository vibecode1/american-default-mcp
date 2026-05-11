"""American Default MCP server — Track C1 of the 2026-05 Machine-First Rebuild.

Exposes read-only tool endpoints over Anthropic's Model Context Protocol:

    Session 1:
        - get_indicator(slug)
        - get_county_scorecard(fips)
        - get_adi_composite()

    Session 2:
        - search_indicators(query, limit)
        - get_cross_correlations(slug)

All tool invocations pass through `_gate()`, which:
    - rate-limits per client (60 rpm burst, 600 rph sustained;
      configurable via MCP_RATE_LIMIT_RPM / MCP_RATE_LIMIT_RPH;
      bypass with RATE_LIMIT_DISABLED=true)
    - logs an auth-attempt line per request when MCP_API_KEY is
      configured server-side (stdio does not block — see auth.py)

Invocation:

    PYTHONPATH=. python3 -m scripts.machine_layer.mcp_server            # stdio serve
    PYTHONPATH=. python3 -m scripts.machine_layer.mcp_server --probe    # handshake + exit 0

Transport: stdio. Logs to stderr (stdout is reserved for JSON-RPC framing).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Configure root logger to stderr BEFORE any import that may log at module load.
# stdout must stay clean for JSON-RPC framing.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("machine_layer.mcp_server")

# Silence noisy third-party loggers
for _noisy in ("httpx", "anyio", "mcp.server.lowlevel.server"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


from typing import Annotated  # noqa: E402

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402

from scripts.machine_layer.auth import log_auth_attempt  # noqa: E402
from scripts.machine_layer.rate_limit import check_and_consume  # noqa: E402
from scripts.machine_layer.tools import (  # noqa: E402
    get_adi_composite,
    get_county_scorecard,
    get_cross_correlations,
    get_indicator,
    search_indicators,
)

SERVER_NAME = "american-default-mcp"
SERVER_VERSION = "1.0.0-session-2"
SCHEMA_VERSION = "v1"


def _build_transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection config for the streamable-HTTP transport.

    FastMCP's default rejects any Host header other than ``localhost`` /
    ``127.0.0.1`` with HTTP 421 to defend against DNS-rebinding attacks
    that target browser-origin clients. Cloud Run's hostname trips this.

    For our deployment posture — server-to-server traffic, HTTPS at the
    edge, bearer-token auth + per-IP rate limit — DNS rebinding is not
    in the threat model. Two ways to satisfy the middleware:

    - ``MCP_ALLOWED_HOSTS=host1,host2,...`` keeps the protection on and
      whitelists production hostnames (preferred when set).
    - Unset → disable the protection entirely (the production default
      until ``MCP_ALLOWED_HOSTS`` is configured per-deploy).
    """
    raw = os.getenv("MCP_ALLOWED_HOSTS", "").strip()
    if raw:
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


# The FastMCP app is constructed at module load so tests can import it and
# invoke tools in-process via create_connected_server_and_client_session.
mcp = FastMCP(name=SERVER_NAME, transport_security=_build_transport_security())


# ----------------------------------------------------------------------
# Gate — shared pre-tool middleware (rate limit + auth-attempt log)
# ----------------------------------------------------------------------


def _client_name(ctx: Context | None) -> str:
    """Pull `clientInfo.name` from the MCP initialize handshake.

    Falls back to "default" when ctx is None (unit-test direct-call
    path) or when the session has not been initialized.
    """
    if ctx is None:
        return "default"
    try:
        params = ctx.request_context.session.client_params
        if params and params.clientInfo and params.clientInfo.name:
            return params.clientInfo.name
    except Exception:  # pragma: no cover — defensive
        pass
    return "default"


def _gate(ctx: Context | None, tool_name: str) -> None:
    client = _client_name(ctx)
    check_and_consume(client, tool_name=tool_name)
    # Stdio has no in-band asserted-key surface; pass None. When
    # MCP_API_KEY is unset (the common case), this is a no-op.
    log_auth_attempt(client, asserted_key=None, tool_name=tool_name)


# ----------------------------------------------------------------------
# Tool endpoints
# ----------------------------------------------------------------------


@mcp.tool(
    name="get_indicator",
    description=(
        "Fetch a compact snapshot of an American Default economic indicator "
        "by slug. Returns latest value, unit, frequency, direction, "
        "pre-computed aggregates (period averages, extremes, sustained "
        "runs), editorial prose (when available), and canonical APA / MLA / "
        "Chicago / news-copy citations. Raw historical series is NOT "
        "included — use https://americandefault.org/api/indicators/{slug}.json "
        "for the full data. Slug examples: 'the-buffer' (personal savings "
        "rate), 'mortgage-delinquency', 'initial-unemployment-claims-sa'."
    ),
    annotations=ToolAnnotations(
        title="Get indicator",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def _get_indicator(
    slug: Annotated[
        str,
        Field(
            description=(
                "The kebab-case indicator slug (e.g., 'the-buffer' for personal "
                "savings rate, 'mortgage-delinquency', 'initial-unemployment-claims-sa'). "
                "96 indicators available. Use `search_indicators` first to discover "
                "which slug corresponds to a concept."
            ),
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    """Fetch a compact snapshot of an American Default indicator by slug."""
    _gate(ctx, "get_indicator")
    return get_indicator.run(slug)


@mcp.tool(
    name="get_county_scorecard",
    description=(
        "Fetch a county's County Distress Index (CDI) scorecard by 5-digit "
        "FIPS code. Returns composite score (0-100), zone (Healthy / "
        "Normal / Elevated / Serious / Crisis), national + state rank, "
        "5-domain breakdown (Consumer Credit Distress, Housing Cost "
        "Burden, Structural Poverty, Economic Vitality, Legal Distress), "
        "key findings, and pre-baked APA / MLA / Chicago / news-copy "
        "citations. Accepts 4-digit FIPS with implicit leading zero. "
        "3,144 counties available."
    ),
    annotations=ToolAnnotations(
        title="Get county scorecard",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def _get_county_scorecard(
    fips: Annotated[
        str,
        Field(
            description=(
                "The 5-digit numeric county FIPS code as a string (e.g., '13063' "
                "for Clayton County, GA). 4-digit values are zero-padded internally. "
                "3,144 counties available."
            ),
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    """Fetch a county's County Distress Index (CDI) scorecard."""
    _gate(ctx, "get_county_scorecard")
    return get_county_scorecard.run(fips)


@mcp.tool(
    name="get_adi_composite",
    description=(
        "Fetch the latest quarterly reading of the American Distress Index "
        "(ADI) composite. Returns composite score (0-100), zone, composite "
        "Z-score, and the 5-component breakdown (Buffer, Debt Stress, "
        "Financial Conditions, Cost Pressure, Labor) with Z-scores and "
        "point contributions. Updated quarterly."
    ),
    annotations=ToolAnnotations(
        title="Get ADI composite",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def _get_adi_composite(ctx: Context | None = None) -> dict:
    """Fetch the latest American Distress Index (ADI) composite reading.

    No parameters. Returns the most recent quarter's composite score, zone,
    and 5-component breakdown.
    """
    _gate(ctx, "get_adi_composite")
    return get_adi_composite.run()


@mcp.tool(
    name="search_indicators",
    description=(
        "Search the 96-indicator registry by keyword. Returns ranked "
        "matches (up to `limit`, default 10, max 50) with slug, branded "
        "name, underlying name, category, and canonical URL. Scoring is "
        "substring+prefix over slug, branded_name, name, and category — "
        "e.g. query 'savings' returns both The Buffer (personal saving "
        "rate) and The Safety Net (emergency savings survey). Use this "
        "when you want to discover which slug corresponds to a concept "
        "before calling `get_indicator`."
    ),
    annotations=ToolAnnotations(
        title="Search indicators",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def _search_indicators(
    query: Annotated[
        str,
        Field(
            description=(
                "The keyword to search (e.g., 'savings', 'mortgage', 'inflation'). "
                "Scoring runs substring + prefix matching over slug, branded_name, "
                "name, and category fields."
            ),
        ),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            description=(
                "Max number of ranked matches to return. Default 10. Hard cap 50 "
                "(values above are clamped). Values above 1000 are rejected as abuse."
            ),
        ),
    ] = 10,
    ctx: Context | None = None,
) -> dict:
    """Search the 96-indicator registry by keyword."""
    _gate(ctx, "search_indicators")
    return search_indicators.run(query, limit=limit)


@mcp.tool(
    name="get_cross_correlations",
    description=(
        "Fetch statistically-validated leading/lagging relationships for "
        "an indicator. Source: the five-filter leading-indicator scanner "
        "(cross-correlation → first-differenced CCF → multi-crisis "
        "validation → Granger causality → out-of-sample validation). "
        "Returns two lists: `as_leader` (pairs where this indicator "
        "precedes its follower) and `as_follower` (pairs where another "
        "indicator precedes this one). Only fully-validated pairs are "
        "included — partial matches are not surfaced. Most of the 96 "
        "indicators return empty lists; currently six pairs clear the "
        "full gauntlet."
    ),
    annotations=ToolAnnotations(
        title="Get cross-correlations",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def _get_cross_correlations(
    slug: Annotated[
        str,
        Field(
            description=(
                "The kebab-case indicator slug to look up (e.g., 'the-buffer', "
                "'initial-unemployment-claims-sa'). Returns split lists of pairs "
                "where this indicator is the leader vs the follower. Empty lists "
                "are common — only fully-validated pairs surface."
            ),
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    """Fetch validated leading/lagging indicator relationships."""
    _gate(ctx, "get_cross_correlations")
    return get_cross_correlations.run(slug)


# ----------------------------------------------------------------------
# Probe handshake — synchronous, does NOT enter the stdio loop.
# ----------------------------------------------------------------------


def probe_handshake(transport: str = "stdio") -> dict:
    """Return server metadata + tool list without spinning up stdio."""
    try:
        from importlib.metadata import version as _v

        sdk_version = _v("mcp")
    except Exception:
        sdk_version = "unknown"

    tools = [
        {
            "name": t.name,
            "description": (t.description or "").strip().splitlines()[0]
            if t.description
            else "",
        }
        for t in mcp._tool_manager.list_tools()
    ]
    return {
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "sdk_version": sdk_version,
        "transport": transport,
        "tools": tools,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp_server",
        description="American Default MCP server (stdio + streamable-http transports).",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Emit handshake JSON to stdout and exit 0 (does not serve).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the stdio loop (default behavior).",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport mode. stdio for local clients (Claude Desktop); "
             "http for remote agents (Streamable HTTP). Defaults to "
             "$MCP_TRANSPORT or stdio.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="HTTP bind host (http transport only). Defaults to $MCP_HOST or 0.0.0.0.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", os.getenv("MCP_PORT", "8080"))),
        help="HTTP bind port (http transport only). Defaults to $PORT "
             "(Cloud Run convention) then $MCP_PORT then 8080.",
    )
    args = parser.parse_args(argv)

    if args.probe:
        handshake = probe_handshake(transport=args.transport)
        print(json.dumps(handshake, indent=2))
        return 0

    logger.info(
        "mcp-server-starting name=%s version=%s sdk=%s transport=%s",
        SERVER_NAME,
        SERVER_VERSION,
        probe_handshake(transport=args.transport)["sdk_version"],
        args.transport,
    )

    if args.transport == "http":
        # Lazy import — uvicorn pulls in starlette routing, only needed
        # when actually serving HTTP. stdio path stays lean.
        import uvicorn

        from scripts.machine_layer.http_app import build_app

        app = build_app(mcp.streamable_http_app())
        logger.info("mcp-http-listening host=%s port=%d", args.host, args.port)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            access_log=False,  # FastMCP + our middleware emit structured logs
        )
        return 0

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
