"""
Analytics router — all endpoints scoped to the calling user's org_id from JWT.

Base path: /api/analytics

Endpoints:
  GET /summary                  KPI summary cards
  GET /daily                    Daily usage timeseries
  GET /breakdown/models         Cost by model
  GET /breakdown/providers      Cost by provider
  GET /forecast                 30-day cost forecast
  GET /burn-rate                Budget burn rate
  GET /anomalies                Cost anomaly detection
  GET /copilot/seats            GitHub Copilot seat utilisation
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.auth import OrgId
from app.services import analytics_service as svc
from app.services import forecast_service as fsvc
from app.services import anomaly_service as asvc
from app.schemas.analytics import (
    OrgSummary,
    DailyUsageResponse,
    ModelBreakdownResponse,
    ProviderBreakdownResponse,
    ForecastResponse,
    BurnRateResponse,
    AnomalyResponse,
    CopilotSeatsResponse,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

SUPPORTED_PROVIDERS = {"openai", "claude", "gemini", "github_copilot"}


def _default_start() -> date:
    return date.today() - timedelta(days=29)


def _default_end() -> date:
    return date.today()


def _validate_provider(provider: Optional[str]) -> Optional[str]:
    if provider and provider not in SUPPORTED_PROVIDERS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"provider must be one of {sorted(SUPPORTED_PROVIDERS)}",
        )
    return provider


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=OrgSummary)
def summary(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start, description="Start date (inclusive)"),
    end: date = Query(default_factory=_default_end, description="End date (inclusive)"),
    provider: Optional[str] = Query(None, description="Filter by provider slug"),
):
    """KPI summary cards: total cost, requests, tokens, active providers."""
    return svc.get_summary(db, org_id, start, end, _validate_provider(provider))


# ── Daily timeseries ──────────────────────────────────────────────────────────

@router.get("/daily", response_model=DailyUsageResponse)
def daily_usage(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start),
    end: date = Query(default_factory=_default_end),
    provider: Optional[str] = Query(None),
):
    """Daily cost + token usage timeseries. Use for line/bar charts."""
    return svc.get_daily_usage(db, org_id, start, end, _validate_provider(provider))


# ── Model breakdown ───────────────────────────────────────────────────────────

@router.get("/breakdown/models", response_model=ModelBreakdownResponse)
def model_breakdown(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start),
    end: date = Query(default_factory=_default_end),
    provider: Optional[str] = Query(None),
):
    """Cost & usage broken down by (provider, model). Use for pie/donut charts."""
    return svc.get_model_breakdown(db, org_id, start, end, _validate_provider(provider))


# ── Provider breakdown ────────────────────────────────────────────────────────

@router.get("/breakdown/providers", response_model=ProviderBreakdownResponse)
def provider_breakdown(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start),
    end: date = Query(default_factory=_default_end),
):
    """Cost & usage broken down by provider (openai / claude / gemini / github_copilot)."""
    return svc.get_provider_breakdown(db, org_id, start, end)


# ── Forecast ──────────────────────────────────────────────────────────────────

@router.get("/forecast", response_model=ForecastResponse)
def forecast(
    org_id: OrgId,
    db: Session = Depends(get_db),
    provider: Optional[str] = Query(None),
    horizon_days: int = Query(30, ge=7, le=90, description="Number of days to forecast"),
    training_days: int = Query(60, ge=7, le=365, description="Training window in days"),
):
    """
    Cost forecast using linear regression (≥14 days data),
    exponential weighted mean (7-13 days), or daily average (<7 days).
    Returns daily predictions with confidence bounds.
    """
    return fsvc.get_forecast(
        db, org_id, _validate_provider(provider), horizon_days, training_days
    )


# ── Burn rate ─────────────────────────────────────────────────────────────────

@router.get("/burn-rate", response_model=BurnRateResponse)
def burn_rate(
    org_id: OrgId,
    db: Session = Depends(get_db),
    period_start: date = Query(
        default_factory=lambda: date.today().replace(day=1),
        description="Start of billing period (default: first of current month)",
    ),
    budget_usd: Optional[float] = Query(None, gt=0, description="Monthly budget in USD"),
    provider: Optional[str] = Query(None),
):
    """
    Budget burn rate for the current period.
    Provides: spent so far, daily average, projected end-of-period spend,
    projected overage, and burn rate % (if budget provided).
    """
    return svc.get_burn_rate(
        db, org_id, period_start, budget_usd, _validate_provider(provider)
    )


# ── Anomaly detection ─────────────────────────────────────────────────────────

@router.get("/anomalies", response_model=AnomalyResponse)
def anomalies(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start),
    end: date = Query(default_factory=_default_end),
    provider: Optional[str] = Query(None),
    z_warning: float = Query(2.0, ge=1.0, le=5.0, description="Z-score threshold for warning"),
    z_critical: float = Query(3.0, ge=1.5, le=6.0, description="Z-score threshold for critical"),
):
    """
    Detect cost anomalies using rolling 7-day z-score.
    Returns all daily points with is_anomaly flag, severity, and expected cost.
    """
    return asvc.get_anomalies(
        db, org_id, start, end, _validate_provider(provider), z_warning, z_critical
    )


# ── GitHub Copilot seats ──────────────────────────────────────────────────────

@router.get("/copilot/seats", response_model=CopilotSeatsResponse)
def copilot_seats(
    org_id: OrgId,
    db: Session = Depends(get_db),
    start: date = Query(default_factory=_default_start),
    end: date = Query(default_factory=_default_end),
):
    """GitHub Copilot seat utilisation — total vs active seats per day."""
    return svc.get_copilot_seats(db, org_id, start, end)
