"""Tool: get_indicator(slug) → compact indicator snapshot + citation."""
from __future__ import annotations

import logging

from mcp.server.mcpserver.exceptions import ToolError

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
    IndicatorResponseV2,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_indicator"

# The bundle's aggregates.extremes carries a `since-<year>` slot for EVERY year
# of an indicator's history (plus `-ex-covid` variants) so the site's
# Superlative / CrossBundleRef primitives can bind any anchor at build time.
# After the 2026-06-18 FRED-history extension, long series (savings rate to
# 1959, unemployment to 1948) carry 130+ extreme slots — which blew the MCP
# get_indicator response past its 16 KB compact-snapshot budget. The compact
# MCP form does not need every yearly anchor; it ships a fixed, bounded set of
# citation-useful epochs. The full extremes stay in the bundle for the site.
_COMPACT_EXTREME_EPOCHS = (
    "all-time",
    "all-time-ex-covid",
    "ex-covid",
    "since-2000",
    "since-2008",
    "since-2010",
    "since-2020",
)


def _compact_extremes(extremes: dict) -> dict:
    """Keep only the bounded, citation-useful epochs for the compact MCP form.

    Bounded by construction: at most len(_COMPACT_EXTREME_EPOCHS) entries
    regardless of how long the indicator's history is, so the response size
    no longer scales with history (the cause of the 16 KB-budget breach)."""
    if not isinstance(extremes, dict):
        return {}
    return {k: extremes[k] for k in _COMPACT_EXTREME_EPOCHS if k in extremes}


def _build_response(slug: str, response_version: str, tool_name: str) -> dict:
    """Build one validated indicator response for a supported contract.

    Returns a JSON-serializable dict. The raw 300+ point data series is
    intentionally omitted — consumers needing the full series hit
    `https://americandefault.org/api/indicators/{slug}.json`.

    Raises ToolError("slug_not_found: ...") for unknown slugs,
    ToolError("invalid_input: ...") for schema-invalid input,
    ToolError("output_schema_violation: ...") if the handler ships a
    response that fails the output contract.
    """
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
    historical = meta.get("data_status") == "historical"

    # An indicator is "awaiting_population" when the bundle has no data
    # points AND no non-zero latest value. Don't raise — return metadata
    # so agents can discover the slug exists but data isn't populated yet.
    awaiting = (not data_array) and (latest_value in (0, None))

    prose_obj = None if historical else bundle.get("prose")
    prose = IndicatorProse(**prose_obj) if isinstance(prose_obj, dict) else None

    aggregates_obj = bundle.get("aggregates")
    aggregates: IndicatorAggregates | None = None
    if isinstance(aggregates_obj, dict) and not awaiting and not historical:
        aggregates = IndicatorAggregates(
            period_averages=aggregates_obj.get("period_averages") or {},
            extremes=_compact_extremes(aggregates_obj.get("extremes") or {}),
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
        historical=historical,
    )

    # Freshness — `as_of_date` is the latest data point; `freshness_warning`
    # fires when it exceeds the per-frequency threshold. Stubs return
    # (None, False) — the `awaiting_population` status carries that signal
    # already, so doubling up via `freshness_warning=True` is noise.
    if awaiting:
        as_of_date, freshness_warning = None, False
    elif historical:
        as_of_date = latest_date or latest_period
        freshness_warning = True
    else:
        as_of_date, freshness_warning = compute_freshness(
            latest_date or latest_period,
            meta.get("freshness_cadence") or meta.get("frequency"),
            observation_frequency=meta.get("frequency"),
        )

    common_fields = {
        "status": "awaiting_population" if awaiting else "ok",
        "slug": slug,
        "branded_name": display,
        "name": meta["name"],
        "unit": meta["unit"],
        "frequency": meta["frequency"],
        "direction": meta["direction"],
        "category": meta.get("category"),
        "latest_value": None if awaiting or historical else latest_value,
        "latest_period": None if awaiting or historical else latest_period,
        "source": meta["source"],
        "source_url": meta["source_url"],
        "url": f"https://americandefault.org/indicators/{slug}/",
        "aggregates": aggregates,
        "prose": prose,
        "citation": Citation(**citation_dict),
        "as_of_date": as_of_date,
        "freshness_warning": freshness_warning,
    }
    if response_version == "v1":
        response = IndicatorResponse(**common_fields)
    elif response_version == "v2":
        response = IndicatorResponseV2(
            **common_fields,
            trend_suppressed=meta.get("trend_suppressed"),
            series_breaks=[
                boundary
                for boundary in (bundle.get("series_breaks") or [])
                if isinstance(boundary, dict)
            ],
        )
    else:  # Defensive: public callers are rejected before this helper.
        raise ToolError(f"unsupported_version: {response_version!r}")

    payload = response.model_dump(mode="json")
    validate_tool_output(tool_name, payload)
    return payload


def run(slug: str) -> dict:
    """Fetch the original v1 response shape under its byte-stable schema.

    The raw 300+ point data series is intentionally omitted. Additive response
    fields never land here; callers that need comparison-safety metadata use
    ``get_indicator_v2`` explicitly.
    """
    validate_tool_input(TOOL_NAME, {"slug": slug})
    return _build_response(slug, response_version="v1", tool_name=TOOL_NAME)
