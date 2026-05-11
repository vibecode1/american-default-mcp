"""Tool: get_county_scorecard(fips) → CDI scorecard + pre-baked citations."""
from __future__ import annotations

import logging

from mcp.server.fastmcp.exceptions import ToolError

from scripts.machine_layer.data_loaders import (
    load_cdi_dataset_metadata,
    load_scorecard_blob,
    normalize_fips,
)
from scripts.machine_layer.freshness import freshness_for_dataset
from scripts.machine_layer.schemas import (
    Citation,
    ScorecardDomain,
    ScorecardResponse,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_county_scorecard"

# CDI is recomputed annually (gated on Census ACS + Urban Institute Debt in
# America releases). Use the dataset cadence rather than per-county dates.
CDI_CADENCE = "annual"


def run(fips: str) -> dict:
    """Fetch a county scorecard + domain breakdown + pre-baked citations.

    The blob's `press_kit.citation` is pre-baked by C2 — we pass the
    strings through without regeneration.

    Raises ToolError("fips_not_found" | "invalid_input" |
    "output_schema_violation").
    """
    # Two-stage validation: the schema enforces the regex shape, then
    # normalize_fips zero-pads the 4-digit form. Schema rejects
    # anything that's not 4 or 5 digits — normalize handles the
    # zero-pad. Garbage input (alpha, punctuation) fails the schema
    # with `invalid_input`.
    validate_tool_input(TOOL_NAME, {"fips": fips})

    normalized = normalize_fips(fips)
    if normalized is None:
        # Unreachable in practice — schema regex ^[0-9]{4,5}$ already
        # rejects non-numeric input. Defensive guard for direct callers
        # that bypass the validator (none in our codebase, but third-
        # party tooling might).
        raise ToolError(
            f"invalid_input: fips must be a 4- or 5-digit numeric string, got {fips!r}"
        )

    blob = load_scorecard_blob(normalized)
    if blob is None:
        raise ToolError(f"fips_not_found: no scorecard for FIPS '{normalized}'")

    # Pre-baked citations (C2)
    cit = (blob.get("press_kit") or {}).get("citation") or {}
    citation = Citation(
        newscopy=cit.get("newscopy", ""),
        apa=cit.get("apa", ""),
        mla=cit.get("mla", ""),
        chicago=cit.get("chicago", ""),
        source_attribution="American Default Research (County Distress Index)",
    )

    # Domain breakdown — shape is `domain_breakdown.domains[]`
    domain_data = (blob.get("domain_breakdown") or {}).get("domains") or []
    domains = [
        ScorecardDomain(
            name=d.get("name", ""),
            score=float(d.get("score", 0)),
            weight_pct=float(d.get("weight_pct", 0)),
            rank=d.get("rank"),
            percentile=d.get("percentile"),
            primary_driver=bool(d.get("primary_driver", False)),
        )
        for d in domain_data
    ]

    key_findings_raw = blob.get("key_findings") or []
    key_findings = [
        kf if isinstance(kf, str) else (kf.get("text", "") if isinstance(kf, dict) else "")
        for kf in key_findings_raw
    ]

    state_slug = blob.get("state_slug", "")
    county_slug = blob.get("county_slug", "")
    url = (
        f"https://americandefault.org/counties/{state_slug}/{county_slug}/"
        if state_slug and county_slug
        else ""
    )

    cdi_meta = load_cdi_dataset_metadata()
    as_of_date, freshness_warning = freshness_for_dataset(
        cdi_meta.get("last_updated"),
        CDI_CADENCE,
    )

    response = ScorecardResponse(
        fips=blob.get("fips", normalized),
        county_name=blob.get("county_name", ""),
        state_name=blob.get("state_name", ""),
        state_abbr=blob.get("state_abbr", ""),
        composite_score=float(blob.get("composite_score", 0)),
        zone=blob.get("zone", ""),
        zone_color=blob.get("zone_color", ""),
        national_rank=int(blob.get("national_rank", 0)),
        national_rank_ordinal=blob.get("national_rank_ordinal", ""),
        state_rank=int(blob.get("state_rank", 0)),
        population=blob.get("population"),
        domain_breakdown=domains,
        key_findings=key_findings,
        url=url,
        citation=citation,
        as_of_date=as_of_date,
        freshness_warning=freshness_warning,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
