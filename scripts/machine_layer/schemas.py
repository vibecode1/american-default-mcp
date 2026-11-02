"""Pydantic response models for the MCP tool endpoints.

Every legacy response carries `schema_version: "v1"`. Breaking changes ship
as a new tool name (e.g. `get_indicator_v2`) and explicit schema version rather
than mutating v1, so clients can pin to a known contract.
"""
from __future__ import annotations

from typing import Dict, Any, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "v1"
SCHEMA_VERSION_V2 = "v2"


class Citation(BaseModel):
    newscopy: str
    apa: str
    mla: str
    chicago: str
    source_attribution: str


# ----------------------------------------------------------------------
# get_indicator
# ----------------------------------------------------------------------


class IndicatorAggregates(BaseModel):
    """Pre-computed aggregate views surfaced to MCP clients.

    The bundle carries many more aggregate buckets (epoch-bounded extremes,
    trailing windows, crisis deltas). We surface a forgiving, permissive
    shape: clients that need rigorous typing read the raw bundle via
    `https://americandefault.org/api/indicators/{slug}.json`.
    """
    period_averages: dict[str, Any] = Field(default_factory=dict)
    extremes: dict[str, Any] = Field(default_factory=dict)
    sustained_runs: list[dict[str, Any]] = Field(default_factory=list)


class IndicatorProse(BaseModel):
    headline: Optional[str] = None
    card_context: Optional[str] = None
    card_verdict: Optional[str] = None


class IndicatorResponse(BaseModel):
    schema_version: Literal["v1"] = SCHEMA_VERSION
    status: Literal["ok", "awaiting_population"] = "ok"
    slug: str
    branded_name: str
    name: str
    unit: str
    frequency: str
    direction: str
    category: Optional[str] = None
    latest_value: Optional[float] = None
    latest_period: Optional[str] = None
    source: str
    source_url: str
    url: str
    aggregates: Optional[IndicatorAggregates] = None
    prose: Optional[IndicatorProse] = None
    citation: Citation
    as_of_date: Optional[str] = None
    freshness_warning: bool = False


class IndicatorResponseV2(IndicatorResponse):
    """Versioned indicator response with comparison-safety metadata.

    The original ``IndicatorResponse`` remains the byte/shape-stable v1
    contract. Additions belong here (and in ``get_indicator_v2``), never in
    the legacy model.
    """

    schema_version: Literal["v2"] = SCHEMA_VERSION_V2
    trend_suppressed: Optional[str] = None
    # Comparability boundaries for source redesigns. Aggregate windows are
    # restricted to the current basis when this list is non-empty.
    series_breaks: list[dict[str, Any]] = Field(default_factory=list)


# ----------------------------------------------------------------------
# get_county_scorecard
# ----------------------------------------------------------------------


class ScorecardDomain(BaseModel):
    name: str
    score: float
    weight_pct: float
    rank: Optional[int] = None
    percentile: Optional[float] = None
    primary_driver: bool = False


class ScorecardResponse(BaseModel):
    schema_version: Literal["v1"] = SCHEMA_VERSION
    fips: str
    county_name: str
    state_name: str
    state_abbr: str
    composite_score: float
    score_gloss: str
    score_gloss_color: str
    # v1 rank-fifth label (enum-locked in get_county_scorecard_output.json) + its
    # matching swatch color, both reconstructed from the retained `quintile` int
    # after the blob dropped its fifth fields — a byte-identical v1 response. The
    # score-gloss migration of these v1 fields is parked (PARKING LOT
    # "Fifths → score-label sweep").
    distress_fifth: str
    distress_fifth_color: str
    zone: str
    zone_color: str
    national_rank: int
    national_rank_ordinal: str
    state_rank: int
    population: Optional[int] = None
    domain_breakdown: list[ScorecardDomain]
    key_findings: list[str] = Field(default_factory=list)
    url: str
    citation: Citation
    as_of_date: Optional[str] = None
    freshness_warning: bool = False


# ----------------------------------------------------------------------
# get_adi_composite
# ----------------------------------------------------------------------


class ADIDomainScore(BaseModel):
    score: float
    members_present: int


class ADIRankInHistory(BaseModel):
    """The share of the other published quarters below the composite — distinct
    from the composite value, which is a mean of input percentiles, not
    itself a percentile of quarters."""

    percent_of_quarters_below: float
    reading: str


class ADICompositeResponse(BaseModel):
    """Family-v1 shape (cutover 2026-06-11). The band label never ships
    without a reading beside it. `rank_in_history.reading` is the public
    history reading (Ross 2026-09-29); `reading` is the inputs-average gloss
    the methodology page explains, kept for v1 clients."""

    schema_version: Literal["v1"] = SCHEMA_VERSION
    quarter: str
    composite: float
    band: int
    band_label: str
    reading: str
    rank_in_history: ADIRankInHistory
    domains: Dict[str, ADIDomainScore]
    members: Dict[str, float]
    methodology_url: str = "https://americandefault.org/methodology/"
    url: str = "https://americandefault.org/methodology/"
    citation: Citation
    as_of_date: Optional[str] = None
    freshness_warning: bool = False


# ----------------------------------------------------------------------
# Session 2 schemas (defined now so the contract is visible; consumers
# are added in Session 2).
# ----------------------------------------------------------------------


class SearchResult(BaseModel):
    slug: str
    branded_name: str
    name: str
    category: Optional[str]
    url: str


class SearchResponse(BaseModel):
    schema_version: Literal["v1"] = SCHEMA_VERSION
    query: str
    count: int
    results: list[SearchResult]
    as_of_date: Optional[str] = None
    freshness_warning: bool = False


class CrossCorrelationPair(BaseModel):
    leader_slug: str
    leader_name: str
    follower_slug: str
    follower_name: str
    lag_quarters: int
    correlation_r: float
    crises_validated: int
    granger_p: float
    oos_validation_r: float


class CrossCorrelationResponse(BaseModel):
    schema_version: Literal["v1"] = SCHEMA_VERSION
    indicator_slug: str
    as_leader: list[CrossCorrelationPair]
    as_follower: list[CrossCorrelationPair]
    as_of_date: Optional[str] = None
    freshness_warning: bool = False
