"""Tool: search_indicators(query, limit) -> ranked list of matching indicators.

Scoring uses a custom substring + token-prefix ladder — no new deps
(rapidfuzz is not in requirements.txt, BM25 would require an index).
The ladder (highest wins across all searched fields):

    exact(slug|branded_name) = 1.0
    slug-starts-with          = 0.95
    exact token match         = 0.9
    token starts with query   = 0.8
    query starts with token   = 0.7   (handles "savings" vs "saving")
    raw substring             = 0.5

Each field is multiplied by its weight (slug 1.0, branded_name 0.95,
name 0.85, category 0.35) and the best is returned. Ties are broken
first by branded_name-or-name length (shorter wins — more specific),
then by slug ascending for determinism.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from scripts.machine_layer.data_loaders import (
    load_indicator_registry,
    load_registry_freshness,
)
from scripts.machine_layer.freshness import _parse_iso_date
from scripts.machine_layer.schemas import SearchResponse, SearchResult
from scripts.machine_layer.validators import validate_tool_input, validate_tool_output

logger = logging.getLogger(__name__)

TOOL_NAME = "search_indicators"
MAX_LIMIT = 50
DEFAULT_LIMIT = 10


def _norm(s: str) -> str:
    """Lowercase + hyphens→spaces + strip. Whitespace-collapsed."""
    return " ".join(s.lower().replace("-", " ").split())


def _field_match(q_norm: str, text: str) -> float:
    """Score a single field against the normalized query.

    Returns 0.0 for no match. Best-ladder-rung for any match.
    """
    if not text:
        return 0.0
    t = _norm(text)
    if not t:
        return 0.0

    if q_norm == t:
        return 1.0
    if t.startswith(q_norm + " "):
        return 0.95
    tokens = t.split()
    if q_norm in tokens:
        return 0.9
    # Token starts with query — "inflation" matches "inflat"
    if len(q_norm) >= 3:
        for tok in tokens:
            if tok.startswith(q_norm) and tok != q_norm:
                return 0.8
    # Query starts with token — "savings" matches field "saving"
    for tok in tokens:
        if len(tok) >= 4 and q_norm.startswith(tok) and q_norm != tok:
            return 0.7
    # Raw substring (weakest signal)
    if q_norm in t:
        return 0.5
    return 0.0


def _score(q_norm: str, meta: dict[str, Any]) -> float:
    """Return the best field-weighted score across slug / branded_name /
    name / category. 0 = no match."""
    best = 0.0

    # Slug (kebab), weight 1.0
    slug_score = _field_match(q_norm, meta["slug"])
    if slug_score > 0:
        best = max(best, slug_score * 1.0)

    # Branded name, weight 0.95
    branded = meta.get("branded_name")
    if branded:
        branded_score = _field_match(q_norm, branded)
        if branded_score > 0:
            best = max(best, branded_score * 0.95)

    # Name, weight 0.85
    name = meta.get("name", "")
    if name:
        name_score = _field_match(q_norm, name)
        if name_score > 0:
            best = max(best, name_score * 0.85)

    # Category (door label), weight 0.35
    category = meta.get("category") or ""
    if category:
        cat_score = _field_match(q_norm, category)
        if cat_score > 0:
            best = max(best, cat_score * 0.35)

    return best


def run(query: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Substring+prefix search over the indicator registry.

    Raises ToolError("invalid_input") for empty or non-string query, or
    out-of-range limit. The schema permits up to limit=1000; the tool
    clamps to MAX_LIMIT internally so a generous client gets at most 50
    results, but a clearly-abusive client (limit > 1000) is rejected at
    the validator boundary.
    """
    # Build the args dict in a way that the schema can validate. Empty
    # query (after trim) is caught here rather than the schema so the
    # error message remains "invalid_input: query must be a non-empty
    # string" — agents pinned on that exact text don't break.
    if not isinstance(query, str):
        raise ToolError("invalid_input: query must be a string")
    q_pre = query.strip()
    if not q_pre:
        raise ToolError("invalid_input: query must be a non-empty string")

    args: dict[str, object] = {"query": query}
    if limit is not None:
        args["limit"] = limit
    validate_tool_input(TOOL_NAME, args)

    q = q_pre
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    q_norm = _norm(q)
    registry = load_indicator_registry()

    scored: list[tuple[float, int, str, dict[str, Any]]] = []
    for slug, meta in registry["by_slug"].items():
        s = _score(q_norm, meta)
        if s <= 0:
            continue
        # Tie-break tuple: (-score, len(display), slug) — shorter names first
        display = meta.get("branded_name") or meta.get("name", "")
        scored.append((s, len(display), slug, meta))

    # Sort: score DESC, display-length ASC, slug ASC
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))

    top = scored[:limit]
    results = [
        SearchResult(
            slug=slug,
            branded_name=(meta.get("branded_name") or meta.get("name", "")),
            name=meta.get("name", ""),
            category=meta.get("category"),
            url=f"https://americandefault.org/indicators/{slug}/",
        )
        for (_score_val, _len, slug, meta) in top
    ]

    # `as_of_date` is the latest `$generated_at` across loaded bundles
    # — closes the 2026-05-03 BONUS finding (spec promised registry-
    # earliest-bundle timestamp; we surface registry-latest, which is
    # more honest about "this listing reflects bundles as of X").
    # `freshness_warning` is False by construction: the listing is
    # metadata. Per-result freshness is the caller's responsibility
    # via `get_indicator(slug)`, which carries the indicator-level
    # `as_of_date` + `freshness_warning`.
    bundle_iso = load_registry_freshness()
    parsed = _parse_iso_date(bundle_iso) if bundle_iso else None
    as_of_date = parsed.isoformat() if parsed else None

    response = SearchResponse(
        query=q,
        count=len(results),
        results=results,
        as_of_date=as_of_date,
        freshness_warning=False,
    )
    payload = response.model_dump(mode="json")
    validate_tool_output(TOOL_NAME, payload)
    return payload
