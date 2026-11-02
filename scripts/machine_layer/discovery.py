"""Public discovery metadata, derived from the registry and live SDK tools.

The experimental MCP card and Cloudflare's earlier tool-bearing card are
different formats. Keep each at its own URL; neither exposes research data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

REGISTRY = json.loads(Path(__file__).with_name("server.json").read_text())
CARD_PATH = "/mcp/server-card"
COMPAT_CARD_PATH = "/.well-known/mcp/server-card.json"
CATALOG_PATH = "/.well-known/ai-catalog.json"
DESCRIPTION = "Read-only U.S. household distress research: public indicators, ADI and county scorecards."


def server_card() -> dict:
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        **{key: REGISTRY[key] for key in (
            "name", "title", "version", "websiteUrl", "repository", "remotes"
        )},
        "description": DESCRIPTION,
    }


def catalog() -> dict:
    return {"specVersion": "1.0", "host": {"displayName": REGISTRY["title"]}, "entries": [{
        "identifier": "urn:air:americandefault.org:mcp:research",
        "type": "application/mcp-server-card+json",
        "url": REGISTRY["remotes"][0]["url"] + "/server-card",
    }, {
        "identifier": "urn:air:americandefault.org:skill:cite-american-default",
        "type": "application/agent-skills+md",
        "url": "https://americandefault.org/.well-known/agent-skills/cite-american-default/SKILL.md",
    }]}


async def compatibility_card() -> dict:
    # Import lazily: the server imports REGISTRY for its initialize identity.
    from scripts.machine_layer.mcp_server import mcp
    from mcp.types import LATEST_PROTOCOL_VERSION

    tools = await mcp.list_tools()
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/mcp-server-card/v1.json",
        "version": "1.0",
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "serverInfo": {key: REGISTRY[key] for key in ("name", "title", "version")},
        "description": DESCRIPTION,
        "transport": {"type": "streamable-http", "endpoint": REGISTRY["remotes"][0]["url"]},
        "authentication": {"required": False},
        "capabilities": mcp._lowlevel_server.get_capabilities().model_dump(
            mode="json", by_alias=True, exclude_none=True
        ),
        "tools": [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools],
    }


async def discovery_response(request: Request) -> Response:
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, If-None-Match",
        "Access-Control-Expose-Headers": "ETag",
        "Cache-Control": "public, max-age=3600",
    }
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=headers)
    path = request.url.path
    if path == CARD_PATH:
        payload, media_type = server_card(), "application/mcp-server-card+json"
    elif path == CATALOG_PATH:
        payload, media_type = catalog(), "application/ai-catalog+json"
    else:
        payload, media_type = await compatibility_card(), "application/json"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(body).hexdigest() + '"'
    headers["ETag"] = etag
    validators = [value.strip().removeprefix("W/") for value in request.headers.get("if-none-match", "").split(",")]
    if etag in validators or "*" in validators:
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(len(body))
    return Response(b"" if request.method == "HEAD" else body, media_type=media_type, headers=headers)
