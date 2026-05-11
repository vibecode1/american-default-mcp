"""JSON Schema validators for MCP tool input + output payloads.

The pydantic models in `schemas.py` give in-process type safety. These
JSON Schema files at `scripts/machine_layer/schemas/*.json` are the
**public contract** — what MCP consumers can pin against — and the
**mechanical gate** that catches handler drift before a malformed
response leaves the process.

Defense map (see `docs/machine_layer/MCP_THREAT_MODEL_2026-05-03.md`):
    - input validation closes A2/A3 (oversize payload, unicode pattern)
    - output validation closes C1/C3/C5 (schema drift, version drift,
      citation drift)

Both functions raise ToolError on failure. The handler never sees
malformed input; the consumer never sees malformed output.

Schemas are loaded once and cached via @lru_cache. Calling code does
not need to know the file paths.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

_INPUT_SUFFIX = "_input"
_OUTPUT_SUFFIX = "_output"


@lru_cache(maxsize=32)
def _load_validator(schema_filename: str) -> Draft202012Validator:
    """Load and compile a JSON Schema validator. Cached after first call."""
    path = SCHEMAS_DIR / schema_filename
    if not path.exists():
        raise FileNotFoundError(f"missing MCP schema: {path}")
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _format_error(err: ValidationError) -> str:
    """Compact one-line description suitable for ToolError messages."""
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"


def validate_tool_input(tool_name: str, args: dict[str, Any]) -> None:
    """Validate tool args against `schemas/{tool_name}_input.json`.

    Raises ToolError("invalid_input: ...") on failure. On success,
    returns None — the caller proceeds to the handler with the same
    args (validation does not mutate or coerce).
    """
    if not isinstance(args, dict):
        raise ToolError("invalid_input: args must be a JSON object")
    validator = _load_validator(f"{tool_name}{_INPUT_SUFFIX}.json")
    errors = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        raise ToolError(f"invalid_input: {_format_error(first)}")


def validate_tool_output(tool_name: str, response: Any) -> None:
    """Validate handler response against `schemas/{tool_name}_output.json`.

    Failure logs ERROR (so a future deploy or test run sees the drift
    in stderr) AND raises ToolError("output_schema_violation: ...") so
    the consumer never sees the malformed response. This is the
    mechanical gate that locks the contract — closes class C1 in the
    threat model.
    """
    if not isinstance(response, dict):
        logger.error(
            "mcp-output-non-dict tool=%s type=%s",
            tool_name,
            type(response).__name__,
        )
        raise ToolError(
            f"output_schema_violation: {tool_name} returned "
            f"{type(response).__name__}, expected object"
        )
    validator = _load_validator(f"{tool_name}{_OUTPUT_SUFFIX}.json")
    errors = sorted(validator.iter_errors(response), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        # Log every error, not just the first — helps debug schema drift
        # after the fact. The thrown ToolError carries only the head
        # because the consumer doesn't need a stack trace.
        for err in errors:
            logger.error(
                "mcp-output-schema-violation tool=%s path=%s msg=%s",
                tool_name,
                "/".join(str(p) for p in err.absolute_path) or "<root>",
                err.message,
            )
        raise ToolError(
            f"output_schema_violation: {tool_name} {_format_error(first)}"
        )


def known_tool_names() -> list[str]:
    """Return the list of tools that have a schema pair on disk.

    Used by tests to enumerate input/output schemas and assert every
    tool registered with FastMCP has both schemas.
    """
    inputs = {p.stem.removesuffix(_INPUT_SUFFIX) for p in SCHEMAS_DIR.glob(f"*{_INPUT_SUFFIX}.json")}
    outputs = {p.stem.removesuffix(_OUTPUT_SUFFIX) for p in SCHEMAS_DIR.glob(f"*{_OUTPUT_SUFFIX}.json")}
    return sorted(inputs & outputs)
