"""Tool: get_county_scorecard(fips) → CDI scorecard + pre-baked citations."""
from __future__ import annotations

import logging

from mcp.server.mcpserver.exceptions import ToolError

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

# Approved CDI releases are expected twice yearly; candidates may be computed
# more often. Use the public release cadence rather than per-county dates.
CDI_CADENCE = "semi_annual"

# v1 rank-fifth labels, keyed by the CDI quintile int (1 = least distressed .. 5
# = most). The v1 output schema enum-locks `distress_fifth` / `zone` to these
# strings. The scorecard blob dropped its own fifth fields (the site now shows
# the score-gloss label), so the tool reconstructs the v1 value from the retained
# `quintile` int — the SAME value the blob used to carry. Migrating these v1
# fields to the score-gloss vocabulary is the parked v2 change (PARKING LOT
# "Fifths → score-label vocabulary sweep"); changing a v1 enum in place would
# break clients pinned to v1 that switch on the old strings.
_RANK_FIFTH_LABELS = {
    1: "Least distressed fifth",
    2: "Second-least distressed fifth",
    3: "Middle fifth",
    4: "Second-most distressed fifth",
    5: "Most distressed fifth",
}

# The v1 rank-fifth swatch color that paired with each label (the blob's old
# FIFTH_COLORS). Reconstructed alongside the label so a v1 client that renders
# `distress_fifth_color` / `zone_color` next to the label still gets the matching
# fifth color, not the score-gloss palette — a byte-identical v1 response.
_RANK_FIFTH_COLORS = {
    1: "#22c55e",
    2: "#3b82f6",
    3: "#eab308",
    4: "#f97316",
    5: "#ef4444",
}


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
    score_gloss = blob.get("score_gloss") or blob.get("zone", "")
    score_gloss_color = blob.get("score_gloss_color") or blob.get("zone_color", "")
    # v1 stability: keep emitting the rank-fifth label + its matching swatch color
    # the v1 schema expects, both reconstructed from the retained `quintile` int
    # (the same label+color the blob used to carry) — a byte-identical v1 response.
    quintile = blob.get("quintile")
    distress_fifth = _RANK_FIFTH_LABELS.get(quintile, "Middle fifth")
    distress_fifth_color = _RANK_FIFTH_COLORS.get(quintile, score_gloss_color)

    response = ScorecardResponse(
        fips=blob.get("fips", normalized),
        county_name=blob.get("county_name", ""),
        state_name=blob.get("state_name", ""),
        state_abbr=blob.get("state_abbr", ""),
        composite_score=float(blob.get("composite_score", 0)),
        score_gloss=score_gloss,
        score_gloss_color=score_gloss_color,
        distress_fifth=distress_fifth,
        distress_fifth_color=distress_fifth_color,
        zone=distress_fifth,
        zone_color=distress_fifth_color,
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
