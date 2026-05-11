"""Data loaders + slug registry for the MCP server.

All readers are `@lru_cache`d module-level — first call reads from disk,
subsequent calls hit memory. The indicator registry is the one subtlety:
91 of 96 bundle slugs do NOT mechanically transform from their snake_case
`indicator_id` (e.g. `savings_rate` → `the-buffer`), so a boot-time scan
of the source JSONs produces a bidirectional map.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# scripts/machine_layer/data_loaders.py → parents[2] = repo root
ROOT = Path(__file__).resolve().parents[2]
DATA_INDICATORS_DIR = ROOT / "data" / "indicators"
DATA_INDEXES_DIR = ROOT / "data" / "indexes"
DATA_RESEARCH_DIR = ROOT / "data" / "research"
SITE_BUNDLES_DIR = ROOT / "site" / "src" / "data" / "indicator-bundles"
SITE_SCORECARDS_DIR = ROOT / "site" / "src" / "data" / "scorecard-blobs"


class IndicatorMeta(TypedDict, total=False):
    slug: str
    indicator_id: str
    name: str
    branded_name: Optional[str]
    source: str
    source_url: str
    unit: str
    frequency: str
    direction: str
    door: Optional[int]
    category: Optional[str]
    fred_series_id: Optional[str]
    bls_series_id: Optional[str]


# Categories derived from the `door` number — the source JSONs do not carry a
# `category` string, but the door organizes indicators by ADI component.
_DOOR_CATEGORY_MAP: dict[int, str] = {
    0: "pressure",
    1: "debt_stress",
    2: "legal_filings",
    3: "buffer_depletion",
    4: "labor_market",
}


@lru_cache(maxsize=1)
def load_indicator_registry() -> dict[str, Any]:
    """Scan every source indicator JSON once; build slug↔id maps.

    Returns a dict with:
      - `by_slug`: slug → IndicatorMeta
      - `by_id`: indicator_id → IndicatorMeta
      - `slug_to_id`: slug → indicator_id
      - `id_to_slug`: indicator_id → slug

    Subsequent calls are O(1) (lru_cache).
    """
    by_slug: dict[str, IndicatorMeta] = {}
    by_id: dict[str, IndicatorMeta] = {}
    slug_to_id: dict[str, str] = {}
    id_to_slug: dict[str, str] = {}

    for path in sorted(DATA_INDICATORS_DIR.rglob("*.json")):
        try:
            d = json.loads(path.read_text())
        except Exception as exc:
            logger.warning("indicator-parse-failed path=%s err=%s", path, exc)
            continue

        iid = d.get("indicator_id")
        slug = d.get("slug")
        if not iid or not slug:
            continue

        door = d.get("door")
        category = _DOOR_CATEGORY_MAP.get(door) if door is not None else None

        meta: IndicatorMeta = {
            "slug": slug,
            "indicator_id": iid,
            "name": d.get("name", ""),
            "branded_name": d.get("branded_name"),
            "source": d.get("source", ""),
            "source_url": d.get("source_url", ""),
            "unit": d.get("unit", ""),
            "frequency": d.get("frequency", ""),
            "direction": d.get("direction", ""),
            "door": door,
            "category": category,
            "fred_series_id": d.get("fred_series_id"),
            "bls_series_id": d.get("bls_series_id"),
        }
        by_slug[slug] = meta
        by_id[iid] = meta
        slug_to_id[slug] = iid
        id_to_slug[iid] = slug

    logger.info("indicator-registry-loaded count=%d", len(by_slug))
    return {
        "by_slug": by_slug,
        "by_id": by_id,
        "slug_to_id": slug_to_id,
        "id_to_slug": id_to_slug,
    }


@lru_cache(maxsize=128)
def load_indicator_bundle(slug: str) -> Optional[dict[str, Any]]:
    """Load a single indicator bundle from site/src/data/indicator-bundles/."""
    path = SITE_BUNDLES_DIR / f"{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


@lru_cache(maxsize=256)
def load_scorecard_blob(fips: str) -> Optional[dict[str, Any]]:
    """Load a single county scorecard blob. Caller must pre-normalize FIPS."""
    path = SITE_SCORECARDS_DIR / f"{fips}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def load_adi_composite() -> dict[str, Any]:
    """Load the ADI composite index JSON."""
    path = DATA_INDEXES_DIR / "adi_4d_e.json"
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def load_leading_indicators() -> dict[str, Any]:
    """Load validated leading-indicator pairs (Session 2 consumer)."""
    path = DATA_RESEARCH_DIR / "leading_indicators.json"
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def load_registry_freshness() -> Optional[str]:
    """Return the latest `$generated_at` across loaded indicator bundles.

    Used by `search_indicators` to set `as_of_date` to the registry's
    most-recent bundle build timestamp — a meaningful proxy for "this
    listing reflects bundles as of X." Returns the maximum ISO string
    or None if no bundles carry a timestamp.

    Closes the BONUS finding from the 2026-05-03 cold review: the
    threat model named registry-build timestamp as the as_of_date for
    search results; the prior implementation hardcoded None.
    """
    latest_iso: Optional[str] = None
    for path in SITE_BUNDLES_DIR.glob("*.json"):
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        ts = d.get("$generated_at")
        if not isinstance(ts, str):
            continue
        if latest_iso is None or ts > latest_iso:
            latest_iso = ts
    return latest_iso


@lru_cache(maxsize=1)
def load_cdi_dataset_metadata() -> dict[str, Any]:
    """Load just the top-level metadata of county_dci.json (no per-county dict).

    Used by `get_county_scorecard` for dataset-level freshness without
    paying the cost of parsing all 3,144 county records on every call.
    The full county_dci.json is large; we only need `last_updated`.
    Reads the file as a JSON stream and returns a metadata dict.
    """
    path = ROOT / "data" / "county" / "indexes" / "county_dci.json"
    if not path.exists():
        return {}
    # Full parse is fine here — file is ~5MB, parsed once, cached for
    # the process lifetime. The lru_cache ensures we don't reparse.
    full = json.loads(path.read_text())
    return {
        "version": full.get("version"),
        "source": full.get("source"),
        "last_updated": full.get("last_updated"),
    }


def normalize_fips(raw: Any) -> Optional[str]:
    """Accept a 5-char or 4-char numeric FIPS, zero-pad to 5. Reject others."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if len(s) == 4 and s.isdigit():
        return "0" + s
    if len(s) == 5 and s.isdigit():
        return s
    return None
