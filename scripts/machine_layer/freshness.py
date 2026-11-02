"""Freshness computation for MCP tool responses.

Every response carries `as_of_date` (ISO-8601 date of the latest data
point) and `freshness_warning: bool` (true when the data is older
than the indicator's expected refresh cadence).

Closes threat A5 in `docs/machine_layer/MCP_THREAT_MODEL_2026-05-03.md`:
agents can no longer cite stale data without a structured warning, and
journalists re-reading a citation can independently verify currency.

Cadence thresholds (days since `as_of_date` before warning fires):
    weekly      ->  21
    monthly     ->  60
    quarterly   -> 150
    semi_annual -> 240
    annual      -> 545
    irregular   -> never warn (special-cased)

Today's date is read via `datetime.now(timezone.utc).date()` — tests
inject a frozen `today` for determinism.
"""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Refresh thresholds in days. After this many days since `as_of_date`,
# the response carries `freshness_warning: True`. Calibrated to be
# generous — well above the indicator's nominal refresh cadence — so
# warnings fire on real data drift, not on routine release latency.
#
# Class B-cadence (HIGH-1 from 2026-05-03 cold review): every frequency
# value present in any indicator JSON must resolve to a threshold here.
# Adding a new cadence to a bundle WITHOUT also adding it here is
# exactly the silent-failure path threat A5 was supposed to close.
# `test_every_registry_frequency_has_threshold` regression-locks this
# class: if a future indicator JSON lands a new frequency string, CI
# fails until the table is updated.
STALE_THRESHOLDS: dict[str, int] = {
    "daily": 7,
    "weekly": 21,
    "biweekly": 30,    # canonical (Census Pulse uses this)
    "bi-weekly": 30,   # legacy synonym — keep for back-compat
    "monthly": 60,
    "quarterly": 150,
    "semi_annual": 240,
    "annual": 545,
    "biennial": 800,
    # Event-driven cadence (METR autonomous-task-horizon, release-anchored
    # sources). The freshness gate accepts gaps up to ~1y as normal — see
    # scripts/indicators/freshness.py STALENESS_THRESHOLDS["as_published"]
    # for the calendar-side rationale. The MCP server uses this looser
    # threshold (~500d) so a normal release cadence doesn't carry a
    # stale-warning flag.
    "as_published": 500,
}

# Cadences that are present in registry data but for which staleness
# can't be meaningfully judged on calendar age. These are accepted as
# silent-pass — the response carries `as_of_date` but no warning.
KNOWN_IRREGULAR_CADENCES: set[str] = {
    "irregular",
    "ad-hoc",
    "intraday",
    "",
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Parse an ISO date or ISO datetime string. Return None on failure.

    Accepts "YYYY-MM-DD", "YYYY-MM-DDTHH:MM:SS", "YYYY-MM-DDTHH:MM:SS.ffffff+00:00",
    and "YYYY-MM-DDTHH:MM:SSZ".
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Strip a trailing Z (Python <3.11 fromisoformat doesn't accept it)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        if "T" in s:
            return datetime.fromisoformat(s).date()
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def compute_freshness(
    as_of_date_str: Optional[str],
    frequency: Optional[str],
    *,
    today: Optional[date] = None,
    observation_frequency: Optional[str] = None,
) -> tuple[Optional[str], bool]:
    """Return (as_of_date_iso_or_None, freshness_warning_bool).

    - If `as_of_date_str` is None or unparseable, returns (None, False).
      No data means no warning — the empty-data guard (A4) carries that
      signal via `status: "awaiting_population"` instead.
    - If `frequency` is unrecognized or "irregular", returns the parsed
      date but `freshness_warning=False`. Irregular series can't be
      meaningfully judged stale by calendar age.
    """
    parsed = _parse_iso_date(as_of_date_str)
    if parsed is None:
        return None, False

    iso_str = parsed.isoformat()

    freq_norm = (frequency or "").lower()
    threshold = STALE_THRESHOLDS.get(freq_norm)
    if threshold is None:
        if freq_norm not in KNOWN_IRREGULAR_CADENCES:
            # Unknown frequency string is suspicious — the registry has
            # introduced a value the threshold table doesn't recognize.
            # Surface it via stderr so the next CI run shows it; do not
            # silently swallow stale data on an unfamiliar cadence.
            logger.warning(
                "freshness-unknown-cadence freq=%r — treating as irregular "
                "(no warning); add to STALE_THRESHOLDS to gate",
                freq_norm,
            )
        return iso_str, False

    base_today = today or _today()
    # Monthly observations are conventionally dated on the month's first day,
    # but describe the whole month. Starting the clock there declared the latest
    # September release stale on November 1. Keep the published observation date
    # intact and measure its age from the end of its reporting month instead.
    reference = parsed
    if (observation_frequency or freq_norm).lower() == "monthly":
        reference = parsed.replace(day=monthrange(parsed.year, parsed.month)[1])
    age_days = (base_today - reference).days
    return iso_str, age_days > threshold


def freshness_for_dataset(
    last_updated_str: Optional[str],
    cadence: str,
    *,
    today: Optional[date] = None,
) -> tuple[Optional[str], bool]:
    """Convenience wrapper for dataset-level freshness (CDI, leading-indicators).

    Same semantics as compute_freshness but takes a known cadence string
    rather than reading it from data.
    """
    return compute_freshness(last_updated_str, cadence, today=today)
