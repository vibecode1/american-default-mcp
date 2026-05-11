"""Pydantic response models for the MCP tool endpoints.

Every response carries `schema_version: "v1"`. Breaking changes ship as
a new tool name (e.g. `get_indicator_v2`) rather than mutating v1 — so
clients can pin to a known contract.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "v1"


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


class ADIComponents(BaseModel):
    buffer_z: float
    debt_stress_z: float
    financial_conditions_z: float
    cost_pressure_z: float
    labor_z: float
    buffer_contribution: float
    debt_stress_contribution: float
    financial_conditions_contribution: float
    cost_pressure_contribution: float
    labor_contribution: float


class ADICompositeResponse(BaseModel):
    schema_version: Literal["v1"] = SCHEMA_VERSION
    quarter: str
    date: str
    composite_score: float
    composite_z: float
    zone: str
    components: ADIComponents
    methodology_url: str = "https://americandefault.org/methodology/"
    url: str = "https://americandefault.org/adi/"
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
