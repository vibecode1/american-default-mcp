"""Data loaders + slug registry for the MCP server.

Readers are cached by the underlying file/directory signature. Repeated
calls hit memory, but a long-running HTTP process re-reads data after the
committed JSON surfaces change. The indicator registry is the one subtlety:
Most bundle slugs do NOT mechanically transform from their snake_case
`indicator_id` (e.g. `savings_rate` -> `the-buffer`), so a scan of the
source JSONs produces a bidirectional map.
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
DATA_RESEARCH_DIR = ROOT / "data" / "research"
CANONICAL_FACTS_PATH = ROOT / "data" / "canonical_facts.json"
SITE_BUNDLES_DIR = ROOT / "site" / "src" / "data" / "indicator-bundles"
SITE_SCORECARDS_DIR = ROOT / "site" / "src" / "data" / "scorecard-blobs"

FileSignature = tuple[bool, int, int]
DirectorySignature = tuple[tuple[str, int, int], ...]


class IndicatorMeta(TypedDict, total=False):
    slug: str
    indicator_id: str
    name: str
    branded_name: Optional[str]
    source: str
    source_url: str
    unit: str
    frequency: str
    freshness_cadence: Optional[str]
    direction: str
    trend_suppressed: Optional[str]
    door: Optional[int]
    category: Optional[str]
    fred_series_id: Optional[str]
    fred_edge_series_id: Optional[str]
    bls_series_id: Optional[str]
    data_status: Optional[str]


# Categories derived from the `door` number — the source JSONs do not carry a
# `category` string, but the door organizes indicators by ADI component.
_DOOR_CATEGORY_MAP: dict[int, str] = {
    0: "pressure",
    1: "debt_stress",
    2: "legal_filings",
    3: "buffer_depletion",
    4: "labor_market",
}


def _file_signature(path: Path) -> FileSignature:
    """Return the cache key for a JSON file."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (False, 0, 0)
    return (True, stat.st_mtime_ns, stat.st_size)


def _directory_signature(root: Path, *, recursive: bool = False) -> DirectorySignature:
    """Return a deterministic cache key for a directory of JSON files."""
    iterator = root.rglob("*.json") if recursive else root.glob("*.json")
    entries: list[tuple[str, int, int]] = []
    for path in sorted(iterator):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if not path.is_file():
            continue
        entries.append(
            (path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size)
        )
    return tuple(entries)


def load_indicator_registry() -> dict[str, Any]:
    """Scan every source indicator JSON once; build slug↔id maps.

    Returns a dict with:
      - `by_slug`: slug → IndicatorMeta
      - `by_id`: indicator_id → IndicatorMeta
      - `slug_to_id`: slug → indicator_id
      - `id_to_slug`: indicator_id → slug

    Subsequent calls are O(1) until an indicator JSON is added, removed,
    or modified.
    """
    return _load_indicator_registry_cached(
        _directory_signature(DATA_INDICATORS_DIR, recursive=True)
    )


@lru_cache(maxsize=8)
def _load_indicator_registry_cached(
    _signature: DirectorySignature,
) -> dict[str, Any]:
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
            "freshness_cadence": d.get("freshness_cadence"),
            "direction": d.get("direction", ""),
            "trend_suppressed": d.get("trend_suppressed"),
            "door": door,
            "category": category,
            "fred_series_id": d.get("fred_series_id"),
            "fred_edge_series_id": d.get("fred_edge_series_id"),
            "bls_series_id": d.get("bls_series_id"),
            "data_status": d.get("data_status"),
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


def load_indicator_bundle(slug: str) -> Optional[dict[str, Any]]:
    """Load a single indicator bundle from site/src/data/indicator-bundles/."""
    path = SITE_BUNDLES_DIR / f"{slug}.json"
    return _load_indicator_bundle_cached(slug, _file_signature(path))


@lru_cache(maxsize=128)
def _load_indicator_bundle_cached(
    slug: str,
    _signature: FileSignature,
) -> Optional[dict[str, Any]]:
    path = SITE_BUNDLES_DIR / f"{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_scorecard_blob(fips: str) -> Optional[dict[str, Any]]:
    """Load a single county scorecard blob. Caller must pre-normalize FIPS."""
    path = SITE_SCORECARDS_DIR / f"{fips}.json"
    return _load_scorecard_blob_cached(fips, _file_signature(path))


@lru_cache(maxsize=256)
def _load_scorecard_blob_cached(
    fips: str,
    _signature: FileSignature,
) -> Optional[dict[str, Any]]:
    path = SITE_SCORECARDS_DIR / f"{fips}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_adi_composite() -> dict[str, Any]:
    """Load the ADI composite history from the canonical-facts artifact (R3-011).

    Returns the shape `{ "data": [...] }` for backward-compat with the prior
    direct-read consumers; the family-v1 entries pass through unchanged so
    domain scores and member percentiles remain accessible. The latest
    composite value the consumers extract is guaranteed to match
    canonical_facts.json — the cross-surface reconciliation gate (R3-013)
    verifies this on every PR.
    """
    return _load_adi_composite_cached(_file_signature(CANONICAL_FACTS_PATH))


@lru_cache(maxsize=4)
def _load_adi_composite_cached(_signature: FileSignature) -> dict[str, Any]:
    facts = json.loads(CANONICAL_FACTS_PATH.read_text())
    return {"data": list(facts.get("adi.composite.history") or [])}


def load_adi_latest() -> dict[str, Any]:
    """Load the latest ADI composite object (band, label, reading,
    rank_in_history) from the canonical-facts artifact."""
    return _load_adi_latest_cached(_file_signature(CANONICAL_FACTS_PATH))


@lru_cache(maxsize=4)
def _load_adi_latest_cached(_signature: FileSignature) -> dict[str, Any]:
    facts = json.loads(CANONICAL_FACTS_PATH.read_text())
    return dict(facts.get("adi.composite.latest") or {})


def load_leading_indicators() -> dict[str, Any]:
    """Load validated leading-indicator pairs (Session 2 consumer)."""
    path = DATA_RESEARCH_DIR / "leading_indicators.json"
    return _load_leading_indicators_cached(_file_signature(path))


@lru_cache(maxsize=4)
def _load_leading_indicators_cached(_signature: FileSignature) -> dict[str, Any]:
    path = DATA_RESEARCH_DIR / "leading_indicators.json"
    return json.loads(path.read_text())


def load_registry_freshness() -> Optional[str]:
    """Return the most recent data date across loaded indicator bundles.

    Used by `search_indicators` to set `as_of_date` to the registry's
    freshest data point — a deterministic, content-derived proxy for
    "this listing reflects data as of X." Reads each bundle's `latest_date`
    (the last observation date, falling back to `data_end`); both are
    `YYYY-MM-DD` strings, so a lexical max is a chronological max. Returns
    the maximum or None if no bundle carries a date.

    Closes the BONUS finding from the 2026-05-03 cold review (the threat
    model named a registry freshness date as the as_of_date for search
    results; the prior implementation hardcoded None). Derived from data
    content rather than a build wall-clock so an unchanged rebuild yields
    the same value — see scripts/indicators/generate_indicator_bundles.py.
    """
    return _load_registry_freshness_cached(_directory_signature(SITE_BUNDLES_DIR))


@lru_cache(maxsize=8)
def _load_registry_freshness_cached(_signature: DirectorySignature) -> Optional[str]:
    latest_iso: Optional[str] = None
    for path in SITE_BUNDLES_DIR.glob("*.json"):
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        ts = d.get("latest_date") or d.get("data_end")
        if not isinstance(ts, str):
            continue
        if latest_iso is None or ts > latest_iso:
            latest_iso = ts
    return latest_iso


def load_cdi_dataset_metadata() -> dict[str, Any]:
    """Load CDI metadata from the canonical-facts artifact.

    Used by `get_county_scorecard` for dataset-level freshness without
    paying the cost of parsing all 3,144 county records on every call. The
    metadata is emitted by `scripts/data/build_canonical_facts.py`, so the MCP
    path no longer needs a raw `county_dci.json` read.
    """
    return _load_cdi_dataset_metadata_cached(_file_signature(CANONICAL_FACTS_PATH))


@lru_cache(maxsize=4)
def _load_cdi_dataset_metadata_cached(_signature: FileSignature) -> dict[str, Any]:
    if not CANONICAL_FACTS_PATH.exists():
        return {}
    facts = json.loads(CANONICAL_FACTS_PATH.read_text())
    summary = facts.get("cdi.summary")
    if not isinstance(summary, dict):
        return {}
    return {
        "version": facts.get("$schema_version"),
        "source": (facts.get("$sources") or {}).get("cdi"),
        "last_updated": summary.get("as_of") or summary.get("last_updated"),
    }


def clear_loader_caches() -> None:
    """Clear MCP data-loader caches.

    Tests and emergency reload hooks can use this, but normal operation relies
    on mtime-keyed cache invalidation.
    """
    _load_indicator_registry_cached.cache_clear()
    _load_indicator_bundle_cached.cache_clear()
    _load_scorecard_blob_cached.cache_clear()
    _load_adi_composite_cached.cache_clear()
    _load_adi_latest_cached.cache_clear()
    _load_leading_indicators_cached.cache_clear()
    _load_registry_freshness_cached.cache_clear()
    _load_cdi_dataset_metadata_cached.cache_clear()


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
