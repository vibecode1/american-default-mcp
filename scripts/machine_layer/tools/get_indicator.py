"""Tool: get_indicator(slug) → compact indicator snapshot + citation."""
from __future__ import annotations

import logging

from mcp.server.fastmcp.exceptions import ToolError

from scripts.machine_layer.citation import build_indicator_citation
from scripts.machine_layer.data_loaders import (
    load_indicator_bundle,
    load_indicator_registry,
)
from scripts.machine_layer.freshness import compute_freshness
from scripts.machine_layer.schemas import (
    Citation,
    IndicatorAggregates,
    IndicatorProse,
    IndicatorResponse,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_indicator"


def run(slug: str) -> dict:
    """Fetch a compact indicator snapshot + canonical citation.

    Returns a JSON-serializable dict. The raw 300+ point data series is
    intentionally omitted — consumers needing the full series hit
    `https://americandefault.org/api/indicators/{slug}.json`.

    Raises ToolError("slug_not_found: ...") for unknown slugs,
    ToolError("invalid_input: ...") for schema-invalid input,
    ToolError("output_schema_violation: ...") if the handler ships a
    response that fails the output contract.
    """
    validate_tool_input(TOOL_NAME, {"slug": slug})

    registry = load_indicator_registry()
    meta = registry["by_slug"].get(slug)
    if not meta:
        raise ToolError(f"slug_not_found: unknown indicator slug '{slug}'")

    bundle = load_indicator_bundle(slug)
    if bundle is None:
        raise ToolError(f"slug_not_found: bundle file missing for '{slug}'")

    latest_value = bundle.get("latest_value")
    latest_period = bundle.get("latest_period")
    latest_date = bundle.get("latest_date")
    data_array = bundle.get("data") or []

    # An indicator is "awaiting_population" when the bundle has no data
    # points AND no non-zero latest value. Don't raise — return metadata
    # so agents can discover the slug exists but data isn't populated yet.
    awaiting = (not data_array) and (latest_value in (0, None))

    prose_obj = bundle.get("prose")
    prose = IndicatorProse(**prose_obj) if isinstance(prose_obj, dict) else None

    aggregates_obj = bundle.get("aggregates")
    aggregates: IndicatorAggregates | None = None
    if isinstance(aggregates_obj, dict) and not awaiting:
        aggregates = IndicatorAggregates(
            period_averages=aggregates_obj.get("period_averages") or {},
            extremes=aggregates_obj.get("extremes") or {},
            sustained_runs=aggregates_obj.get("sustained_runs") or [],
        )

    display = meta.get("branded_name") or meta["name"]

    citation_dict = build_indicator_citation(
        name=meta["name"],
        branded_name=meta.get("branded_name"),
        source=meta["source"],
        source_url=meta["source_url"],
        slug=slug,
        latest_value=None if awaiting else latest_value,
        latest_period=None if awaiting else latest_period,
        unit=meta["unit"],
    )

    # Freshness — `as_of_date` is the latest data point; `freshness_warning`
    # fires when it exceeds the per-frequency threshold. Stubs return
    # (None, False) — the `awaiting_population` status carries that signal
    # already, so doubling up via `freshness_warning=True` is noise.
    if awaiting:
        as_of_date, freshness_warning = None, False
    else:
        as_of_date, freshness_warning = compute_freshness(
            latest_date or latest_period,
            meta.get("frequency"),
        )

    response = IndicatorResponse(
        status="awaiting_population" if awaiting else "ok",
        slug=slug,
        branded_name=display,
        name=meta["name"],
        unit=meta["unit"],
        frequency=meta["frequency"],
        direction=meta["direction"],
        category=meta.get("category"),
        latest_value=None if awaiting else latest_value,
        latest_period=None if awaiting else latest_period,
        source=meta["source"],
        source_url=meta["source_url"],
        url=f"https://americandefault.org/indicators/{slug}/",
        aggregates=aggregates,
        prose=prose,
        citation=Citation(**citation_dict),
        as_of_date=as_of_date,
        freshness_warning=freshness_warning,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
