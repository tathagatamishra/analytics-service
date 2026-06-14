"""
Response schemas for aianalytics-service.
All UUIDs are returned as strings (hex from BINARY(16)).
All monetary values are in USD.
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class TokenBreakdown(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0


# ── Summary ───────────────────────────────────────────────────────────────────

class OrgSummary(BaseModel):
    """Top-level KPI cards — the first thing the dashboard shows."""
    org_id: str
    period_start: date
    period_end: date
    total_cost_usd: float
    total_requests: int
    tokens: TokenBreakdown
    active_providers: list[str]
    active_tools: int


# ── Daily timeseries ──────────────────────────────────────────────────────────

class DailyDataPoint(BaseModel):
    date: date
    cost_usd: float
    requests: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    total_tokens: int


class DailyUsageResponse(BaseModel):
    org_id: str
    provider: Optional[str] = None   # None = all providers combined
    days: list[DailyDataPoint]


# ── Model breakdown ───────────────────────────────────────────────────────────

class ModelBreakdownItem(BaseModel):
    provider: str
    model_id: Optional[str]
    cost_usd: float
    requests: int
    total_tokens: int
    cost_share_pct: float            # % of total cost for this org/period


class ModelBreakdownResponse(BaseModel):
    org_id: str
    period_start: date
    period_end: date
    breakdown: list[ModelBreakdownItem]


# ── Provider breakdown ────────────────────────────────────────────────────────

class ProviderBreakdownItem(BaseModel):
    provider: str
    cost_usd: float
    requests: int
    total_tokens: int
    cost_share_pct: float


class ProviderBreakdownResponse(BaseModel):
    org_id: str
    period_start: date
    period_end: date
    breakdown: list[ProviderBreakdownItem]


# ── Forecast ──────────────────────────────────────────────────────────────────

class ForecastDataPoint(BaseModel):
    date: date
    predicted_cost_usd: float
    lower_bound: float
    upper_bound: float


class ForecastResponse(BaseModel):
    org_id: str
    provider: Optional[str] = None
    horizon_days: int
    model_used: str                  # e.g. "linear_regression", "holt_winters"
    training_days: int
    forecast: list[ForecastDataPoint]
    monthly_projection_usd: float    # sum of next-30-day forecast


# ── Burn rate ─────────────────────────────────────────────────────────────────

class BurnRateResponse(BaseModel):
    org_id: str
    provider: Optional[str] = None
    period_start: date
    today: date
    budget_usd: Optional[float]
    spent_usd: float
    daily_avg_usd: float
    days_elapsed: int
    days_in_period: int
    projected_period_spend_usd: float
    projected_overage_usd: Optional[float]   # None if no budget set
    burn_rate_pct: Optional[float]           # spent / budget * 100


# ── Anomaly detection ─────────────────────────────────────────────────────────

class AnomalyPoint(BaseModel):
    date: date
    cost_usd: float
    expected_cost_usd: float
    z_score: float
    is_anomaly: bool
    severity: Optional[str] = None   # "warning" | "critical"


class AnomalyResponse(BaseModel):
    org_id: str
    provider: Optional[str] = None
    period_start: date
    period_end: date
    anomalies_detected: int
    points: list[AnomalyPoint]


# ── Copilot seats ─────────────────────────────────────────────────────────────

class CopilotSeatDataPoint(BaseModel):
    date: date
    total_seats: int
    active_seats: int
    utilisation_pct: float


class CopilotSeatsResponse(BaseModel):
    org_id: str
    days: list[CopilotSeatDataPoint]
