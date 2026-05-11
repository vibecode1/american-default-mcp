"""Tool: get_cross_correlations(slug) -> validated leading/following pairs.

Reads `data/research/leading_indicators.json` — produced by the five-filter
leading-indicator scanner (cross-correlation → first-differenced CCF →
multi-crisis validation → Granger causality → out-of-sample validation).
Only the `summary.fully_validated` list is exposed: those six (currently)
pairs have passed all five filters, including Granger p < 0.05 and OOS
r > 0.3. Partial matches are not returned — clients that want the raw
universe can hit
`https://americandefault.org/api/research/leading-indicators.json` for
every scored pair.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from scripts.machine_layer.data_loaders import (
    load_indicator_registry,
    load_leading_indicators,
)
from scripts.machine_layer.freshness import freshness_for_dataset
from scripts.machine_layer.schemas import (
    CrossCorrelationPair,
    CrossCorrelationResponse,
)
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "get_cross_correlations"
# Cross-correlation research output is regenerated annually (sometimes
# more often when new indicators land). Use the dataset cadence for
# the freshness warning.
LEADING_CADENCE = "annual"


def _build_pair(
    record: dict[str, Any],
    id_to_slug: dict[str, str],
) -> CrossCorrelationPair | None:
    """Convert a scanner record to the MCP response shape.

    Returns None when either leg's indicator_id cannot be mapped to a
    known slug — the registry is the source of truth and silently
    dropping an unknown id is safer than fabricating one.
    """
    leader_id = record.get("leader_id")
    follower_id = record.get("follower_id")
    leader_slug = id_to_slug.get(leader_id) if leader_id else None
    follower_slug = id_to_slug.get(follower_id) if follower_id else None
    if not leader_slug or not follower_slug:
        logger.warning(
            "cross-corr-pair-unmapped leader_id=%s follower_id=%s",
            leader_id,
            follower_id,
        )
        return None

    return CrossCorrelationPair(
        leader_slug=leader_slug,
        leader_name=record.get("leader_name", ""),
        follower_slug=follower_slug,
        follower_name=record.get("follower_name", ""),
        lag_quarters=int(record.get("optimal_lag", 0)),
        correlation_r=float(record.get("raw_r", 0.0)),
        crises_validated=int(record.get("crisis_validations", 0)),
        granger_p=float(record.get("granger_p", 1.0)),
        oos_validation_r=float(record.get("oos_val_r", 0.0)),
    )


def run(slug: str) -> dict:
    """Return the fully-validated pairs this indicator participates in.

    The response carries two lists:
      - as_leader: pairs where this indicator precedes its follower
      - as_follower: pairs where another indicator precedes this one

    Raises ToolError("invalid_input") on non-string/empty slug,
    ToolError("slug_not_found") when the slug is not in the registry.
    An indicator that is in the registry but does not appear in any
    fully-validated pair returns two empty lists — this is the normal
    case for most of the 96 indicators (only six pairs currently
    clear the full five-filter gauntlet).
    """
    if not isinstance(slug, str) or not slug:
        raise ToolError("invalid_input: slug must be a non-empty string")

    validate_tool_input(TOOL_NAME, {"slug": slug})

    registry = load_indicator_registry()
    if slug not in registry["by_slug"]:
        raise ToolError(f"slug_not_found: unknown indicator slug '{slug}'")

    indicator_id = registry["slug_to_id"][slug]
    id_to_slug = registry["id_to_slug"]

    leading = load_leading_indicators()
    validated = (leading.get("summary") or {}).get("fully_validated") or []

    as_leader: list[CrossCorrelationPair] = []
    as_follower: list[CrossCorrelationPair] = []

    for rec in validated:
        pair = _build_pair(rec, id_to_slug)
        if pair is None:
            continue
        leader_match = rec.get("leader_id") == indicator_id
        follower_match = rec.get("follower_id") == indicator_id
        if leader_match and follower_match:
            # Self-pair: not possible in the current scanner output
            # (same-id pairs are filtered upstream), but guard against
            # future data drift. Drop cleanly rather than double-counting.
            logger.warning(
                "cross-corr-self-pair-dropped indicator_id=%s", indicator_id
            )
            continue
        if leader_match:
            as_leader.append(pair)
        elif follower_match:
            as_follower.append(pair)

    # Sort each list: stronger validation first (more crises, then |r|)
    def _sort_key(p: CrossCorrelationPair) -> tuple[int, float, int]:
        # Higher crisis count first; then tighter OOS r; then shorter lag
        return (-p.crises_validated, -abs(p.correlation_r), p.lag_quarters)

    as_leader.sort(key=_sort_key)
    as_follower.sort(key=_sort_key)

    as_of_date, freshness_warning = freshness_for_dataset(
        leading.get("generated_at"),
        LEADING_CADENCE,
    )

    response = CrossCorrelationResponse(
        indicator_slug=slug,
        as_leader=as_leader,
        as_follower=as_follower,
        as_of_date=as_of_date,
        freshness_warning=freshness_warning,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
