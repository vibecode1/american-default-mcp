"""Tool: get_indicator_v2(slug, response_version) -> versioned snapshot."""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from scripts.machine_layer.tools.get_indicator import _build_response
from scripts.machine_layer.validators import validate_tool_input

TOOL_NAME = "get_indicator_v2"
SUPPORTED_RESPONSE_VERSION = "v2"


def run(slug: str, response_version: str) -> dict:
    """Fetch a v2 indicator snapshot with comparison-safety metadata.

    Callers must opt in to both the versioned tool name and the response
    version. Unknown versions fail with a stable error instead of silently
    falling back to v1 or a future contract.
    """
    if response_version != SUPPORTED_RESPONSE_VERSION:
        raise ToolError(
            "unsupported_version: get_indicator_v2 supports response_version "
            f"'{SUPPORTED_RESPONSE_VERSION}', got {response_version!r}"
        )
    validate_tool_input(
        TOOL_NAME,
        {"slug": slug, "response_version": response_version},
    )
    return _build_response(
        slug,
        response_version=response_version,
        tool_name=TOOL_NAME,
    )
