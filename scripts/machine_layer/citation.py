"""Canonical citation builder — three-tier naming enforced.

Three-tier naming (from `.claude/rules` and llms.txt):
  - "American Default Research" — institutional (citations, source lists)
  - "American Default" — brand (URLs, casual references)
  - "American Distress Index" (ADI) — product name (composite score only)

Indicator citations build from bundle metadata at request time; county
citations pass through pre-baked strings already on scorecard blobs
(produced by C2 — `press_kit.citation`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, TypedDict

CANONICAL_INSTITUTION = "American Default Research"
CANONICAL_BRAND = "American Default"
CANONICAL_PRODUCT = "American Distress Index"
BASE_URL = "https://americandefault.org"


def _current_year() -> int:
    return datetime.now(timezone.utc).year


class IndicatorCitation(TypedDict):
    newscopy: str
    apa: str
    mla: str
    chicago: str
    source_attribution: str


def _format_value(value: Optional[float], unit: str) -> str:
    """Format a scalar for news-copy use, unit-aware."""
    if value is None:
        return "N/A"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "dollars":
        return f"${value:,.0f}"
    if unit == "index":
        return f"{value:.1f}"
    if unit == "hours":
        return f"{value:.1f} hours"
    if unit == "number":
        return f"{value:,.0f}"
    return f"{value:.2f} {unit}"


def build_indicator_citation(
    *,
    name: str,
    branded_name: Optional[str],
    source: str,
    source_url: str,
    slug: str,
    latest_value: Optional[float],
    latest_period: Optional[str],
    unit: str,
    year: Optional[int] = None,
) -> IndicatorCitation:
    """Build APA / MLA / Chicago / news-copy citations for one indicator."""
    if year is None:
        year = _current_year()
    display = branded_name or name
    url = f"{BASE_URL}/indicators/{slug}/"
    val_str = _format_value(latest_value, unit)
    period = latest_period or "current period"

    newscopy = (
        f"According to {CANONICAL_INSTITUTION}, {display} stands at {val_str} "
        f"as of {period}. Source: {source}. "
        f"({CANONICAL_BRAND} — {url})"
    )
    apa = (
        f"{CANONICAL_INSTITUTION}. ({year}). {display} [Data set]. "
        f"{url}"
    )
    mla = (
        f'"{display}." {CANONICAL_INSTITUTION}, {year}, '
        f"{url.replace('https://', '')}."
    )
    chicago = (
        f'{CANONICAL_INSTITUTION}. "{display}." Accessed {year}. '
        f"{url}."
    )
    return {
        "newscopy": newscopy,
        "apa": apa,
        "mla": mla,
        "chicago": chicago,
        "source_attribution": source,
    }


def build_adi_citation(
    *,
    quarter: str,
    composite_score: float,
    zone: str,
    year: Optional[int] = None,
) -> IndicatorCitation:
    """Build citations for the ADI composite itself (uses product name)."""
    if year is None:
        year = _current_year()
    url = f"{BASE_URL}/adi/"
    display = CANONICAL_PRODUCT
    newscopy = (
        f"The {display}, computed by {CANONICAL_INSTITUTION}, "
        f"stood at {composite_score:.1f} ({zone}) in {quarter}. "
        f"({CANONICAL_BRAND} — {url})"
    )
    apa = (
        f"{CANONICAL_INSTITUTION}. ({year}). {display} [Data set]. "
        f"{url}"
    )
    mla = (
        f'"{display}." {CANONICAL_INSTITUTION}, {year}, '
        f"{url.replace('https://', '')}."
    )
    chicago = (
        f'{CANONICAL_INSTITUTION}. "{display}." Accessed {year}. '
        f"{url}."
    )
    return {
        "newscopy": newscopy,
        "apa": apa,
        "mla": mla,
        "chicago": chicago,
        "source_attribution": f"{CANONICAL_INSTITUTION} (PCA-derived composite)",
    }
