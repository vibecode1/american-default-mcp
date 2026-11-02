"""Tool: get_adi_composite() → latest ADI quarter + five-domain breakdown.

Family-v1 shape (cutover 2026-06-11): composite, band, band_label,
rank_in_history, the inputs-average reading gloss, domain scores, and member
percentiles. The band label never ships without a reading beside it; the
news-copy citation quotes rank_in_history.reading, the one public history
reading (Ross 2026-09-29). `reading` stays in the v1 response for existing
clients.
"""
from __future__ import annotations

import logging

from mcp.server.mcpserver.exceptions import ToolError

from scripts.machine_layer.citation import build_adi_citation
from scripts.machine_layer.data_loaders import load_adi_composite, load_adi_latest
from scripts.machine_layer.freshness import freshness_for_dataset
from scripts.machine_layer.schemas import (
    ADICompositeResponse,
    ADIDomainScore,
    ADIRankInHistory,
    Citation,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_adi_composite"
ADI_CADENCE = "quarterly"

# Family-v1 rows are quarter-keyed; the freshness reference date for a
# quarter is its last day (same rule as the source-data timestamps audit).
_QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}


def _quarter_end_iso(quarter: str) -> str:
    return f"{quarter[:4]}-{_QUARTER_END[quarter[6]]}"


def run() -> dict:
    """Return latest ADI composite + five-domain breakdown + citation.

    Takes no arguments. Raises ToolError("no_data") when the index is
    empty (should never happen in practice — the file is checked into
    git and ships with 80+ quarters).
    """
    validate_tool_input(TOOL_NAME, {})

    data = load_adi_composite()
    history = data.get("data") or []
    if not history:
        raise ToolError("no_data: ADI index is empty")

    latest_row = history[-1]
    latest = load_adi_latest()
    if not latest or latest.get("as_of") != latest_row.get("quarter"):
        raise ToolError(
            "inconsistent_data: canonical adi.composite.latest disagrees "
            "with the last history row"
        )

    domains = {
        name: ADIDomainScore(
            score=float(d["score"]),
            members_present=int(d["members_present"]),
        )
        for name, d in (latest_row.get("domains") or {}).items()
    }
    members = {k: float(v) for k, v in (latest_row.get("members") or {}).items()}

    rank = latest.get("rank_in_history") or {}
    rank_in_history = ADIRankInHistory(
        percent_of_quarters_below=float(rank["percent_of_quarters_below"]),
        reading=str(rank["reading"]),
    )

    citation_dict = build_adi_citation(
        quarter=latest_row["quarter"],
        composite=float(latest_row["composite"]),
        band=int(latest_row["band"]),
        band_label=latest_row["band_label"],
        rank_reading=rank_in_history.reading,
    )
    citation = Citation(**citation_dict)

    # Freshness — use the latest quarter's end date (more honest than the
    # file's last_updated timestamp, which can drift if the index is
    # re-serialized without new data).
    as_of_date, freshness_warning = freshness_for_dataset(
        _quarter_end_iso(latest_row["quarter"]),
        ADI_CADENCE,
    )

    response = ADICompositeResponse(
        quarter=latest_row["quarter"],
        composite=float(latest_row["composite"]),
        band=int(latest_row["band"]),
        band_label=latest_row["band_label"],
        reading=str(latest["reading"]),
        rank_in_history=rank_in_history,
        domains=domains,
        members=members,
        citation=citation,
        as_of_date=as_of_date,
        freshness_warning=freshness_warning,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
