"""Tool: get_adi_composite() → latest ADI quarter + 5-component breakdown."""
from __future__ import annotations

import logging

from mcp.server.fastmcp.exceptions import ToolError

from scripts.machine_layer.citation import build_adi_citation
from scripts.machine_layer.data_loaders import load_adi_composite
from scripts.machine_layer.freshness import freshness_for_dataset
from scripts.machine_layer.schemas import (
    ADIComponents,
    ADICompositeResponse,
    Citation,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_adi_composite"
ADI_CADENCE = "quarterly"


def run() -> dict:
    """Return latest ADI composite + 5-component breakdown + citation.

    Takes no arguments. Raises ToolError("no_data") when the index is
    empty (should never happen in practice — the file is checked into
    git and ships with 100+ quarters).
    """
    validate_tool_input(TOOL_NAME, {})

    data = load_adi_composite()
    history = data.get("data") or []
    if not history:
        raise ToolError("no_data: ADI index is empty")

    latest = history[-1]

    components = ADIComponents(
        buffer_z=float(latest["buffer_z"]),
        debt_stress_z=float(latest["debt_stress_z"]),
        financial_conditions_z=float(latest["financial_conditions_z"]),
        cost_pressure_z=float(latest["cost_pressure_z"]),
        labor_z=float(latest["labor_z"]),
        buffer_contribution=float(latest["buffer_contribution"]),
        debt_stress_contribution=float(latest["debt_stress_contribution"]),
        financial_conditions_contribution=float(latest["financial_conditions_contribution"]),
        cost_pressure_contribution=float(latest["cost_pressure_contribution"]),
        labor_contribution=float(latest["labor_contribution"]),
    )

    citation_dict = build_adi_citation(
        quarter=latest["quarter"],
        composite_score=float(latest["composite_score"]),
        zone=latest["zone"],
    )
    citation = Citation(**citation_dict)

    # Freshness — use the latest quarter's date (more honest than the
    # file's last_updated timestamp, which can drift if the index is
    # re-serialized without new data).
    as_of_date, freshness_warning = freshness_for_dataset(
        latest.get("date"),
        ADI_CADENCE,
    )

    response = ADICompositeResponse(
        quarter=latest["quarter"],
        date=latest["date"],
        composite_score=float(latest["composite_score"]),
        composite_z=float(latest["composite_z"]),
        zone=latest["zone"],
        components=components,
        citation=citation,
        as_of_date=as_of_date,
        freshness_warning=freshness_warning,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
