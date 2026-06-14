"""
AnalyticsService — reads ai_usage_snapshots and produces aggregations.

Design notes:
- All queries scope by org_id first (security boundary).
- bucket_start_time is Unix epoch seconds (from aitools-service).
- BINARY(16) UUIDs are stored as raw bytes; we convert to/from hex strings at the boundary.
- provider slugs: openai | claude | gemini | github_copilot
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import func, text, and_
from sqlalchemy.orm import Session

from app.models.snapshots import AiUsageSnapshot, AiTool
from app.schemas.analytics import (
    OrgSummary,
    DailyDataPoint,
    DailyUsageResponse,
    ModelBreakdownItem,
    ModelBreakdownResponse,
    ProviderBreakdownItem,
    ProviderBreakdownResponse,
    TokenBreakdown,
    BurnRateResponse,
    CopilotSeatDataPoint,
    CopilotSeatsResponse,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str_to_bin(uid: str) -> bytes:
    """Convert UUID string (with or without dashes) to 16-byte BINARY."""
    return uuid.UUID(uid).bytes


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _date_range_epochs(start: date, end: date) -> tuple[int, int]:
    return _epoch(start), _epoch(end) + 86400 - 1  # inclusive end-of-day


def _safe_float(v) -> float:
    if v is None:
        return 0.0
    return float(v)


def _safe_int(v) -> int:
    if v is None:
        return 0
    return int(v)


def _base_query(db: Session, org_id: str, start: date, end: date, provider: Optional[str] = None):
    """Shared filter — always applied first so every query is org-scoped."""
    org_bytes = _str_to_bin(org_id)
    epoch_start, epoch_end = _date_range_epochs(start, end)

    q = db.query(AiUsageSnapshot).filter(
        AiUsageSnapshot.org_id == org_bytes,
        AiUsageSnapshot.bucket_start_time >= epoch_start,
        AiUsageSnapshot.bucket_start_time <= epoch_end,
    )
    if provider:
        q = q.filter(AiUsageSnapshot.provider == provider)
    return q


# ── Summary ───────────────────────────────────────────────────────────────────

def get_summary(
    db: Session,
    org_id: str,
    start: date,
    end: date,
    provider: Optional[str] = None,
) -> OrgSummary:
    rows = _base_query(db, org_id, start, end, provider).all()

    total_cost = sum(_safe_float(r.cost_usd) for r in rows if r.source_type == "cost")
    total_requests = sum(_safe_int(r.total_requests) for r in rows)
    input_tokens = sum(_safe_int(r.input_tokens) for r in rows)
    output_tokens = sum(_safe_int(r.output_tokens) for r in rows)
    cached_tokens = sum(_safe_int(r.input_cached_tokens) for r in rows)
    providers = list({r.provider for r in rows})

    # Count distinct active tools in the org
    org_bytes = _str_to_bin(org_id)
    active_tools = (
        db.query(func.count(AiTool.id))
        .filter(AiTool.org_id == org_bytes, AiTool.is_active == True)
        .scalar()
        or 0
    )

    return OrgSummary(
        org_id=org_id,
        period_start=start,
        period_end=end,
        total_cost_usd=round(total_cost, 6),
        total_requests=total_requests,
        tokens=TokenBreakdown(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        active_providers=sorted(providers),
        active_tools=active_tools,
    )


# ── Daily timeseries ──────────────────────────────────────────────────────────

def get_daily_usage(
    db: Session,
    org_id: str,
    start: date,
    end: date,
    provider: Optional[str] = None,
) -> DailyUsageResponse:
    rows = _base_query(db, org_id, start, end, provider).all()

    # Build a dict keyed by date
    daily: dict[date, dict] = {}
    current = start
    while current <= end:
        daily[current] = {
            "cost_usd": 0.0,
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
        }
        current += timedelta(days=1)

    for row in rows:
        bucket_date = datetime.utcfromtimestamp(row.bucket_start_time).date()
        if bucket_date not in daily:
            continue
        d = daily[bucket_date]
        if row.source_type == "cost":
            d["cost_usd"] += _safe_float(row.cost_usd)
        d["requests"] += _safe_int(row.total_requests)
        d["input_tokens"] += _safe_int(row.input_tokens)
        d["output_tokens"] += _safe_int(row.output_tokens)
        d["cached_tokens"] += _safe_int(row.input_cached_tokens)

    points = [
        DailyDataPoint(
            date=d,
            cost_usd=round(v["cost_usd"], 6),
            requests=v["requests"],
            input_tokens=v["input_tokens"],
            output_tokens=v["output_tokens"],
            cached_tokens=v["cached_tokens"],
            total_tokens=v["input_tokens"] + v["output_tokens"],
        )
        for d, v in sorted(daily.items())
    ]

    return DailyUsageResponse(org_id=org_id, provider=provider, days=points)


# ── Model breakdown ───────────────────────────────────────────────────────────

def get_model_breakdown(
    db: Session,
    org_id: str,
    start: date,
    end: date,
    provider: Optional[str] = None,
) -> ModelBreakdownResponse:
    rows = _base_query(db, org_id, start, end, provider).all()

    # Aggregate by (provider, model_id)
    agg: dict[tuple, dict] = {}
    for row in rows:
        key = (row.provider, row.model_id)
        if key not in agg:
            agg[key] = {"cost_usd": 0.0, "requests": 0, "total_tokens": 0}
        if row.source_type == "cost":
            agg[key]["cost_usd"] += _safe_float(row.cost_usd)
        agg[key]["requests"] += _safe_int(row.total_requests)
        agg[key]["total_tokens"] += (
            _safe_int(row.input_tokens) + _safe_int(row.output_tokens)
        )

    total_cost = sum(v["cost_usd"] for v in agg.values()) or 1  # avoid div/0

    breakdown = sorted(
        [
            ModelBreakdownItem(
                provider=k[0],
                model_id=k[1],
                cost_usd=round(v["cost_usd"], 6),
                requests=v["requests"],
                total_tokens=v["total_tokens"],
                cost_share_pct=round(v["cost_usd"] / total_cost * 100, 2),
            )
            for k, v in agg.items()
        ],
        key=lambda x: x.cost_usd,
        reverse=True,
    )

    return ModelBreakdownResponse(
        org_id=org_id, period_start=start, period_end=end, breakdown=breakdown
    )


# ── Provider breakdown ────────────────────────────────────────────────────────

def get_provider_breakdown(
    db: Session,
    org_id: str,
    start: date,
    end: date,
) -> ProviderBreakdownResponse:
    rows = _base_query(db, org_id, start, end).all()

    agg: dict[str, dict] = {}
    for row in rows:
        p = row.provider
        if p not in agg:
            agg[p] = {"cost_usd": 0.0, "requests": 0, "total_tokens": 0}
        if row.source_type == "cost":
            agg[p]["cost_usd"] += _safe_float(row.cost_usd)
        agg[p]["requests"] += _safe_int(row.total_requests)
        agg[p]["total_tokens"] += (
            _safe_int(row.input_tokens) + _safe_int(row.output_tokens)
        )

    total_cost = sum(v["cost_usd"] for v in agg.values()) or 1

    breakdown = sorted(
        [
            ProviderBreakdownItem(
                provider=p,
                cost_usd=round(v["cost_usd"], 6),
                requests=v["requests"],
                total_tokens=v["total_tokens"],
                cost_share_pct=round(v["cost_usd"] / total_cost * 100, 2),
            )
            for p, v in agg.items()
        ],
        key=lambda x: x.cost_usd,
        reverse=True,
    )

    return ProviderBreakdownResponse(
        org_id=org_id, period_start=start, period_end=end, breakdown=breakdown
    )


# ── Burn rate ─────────────────────────────────────────────────────────────────

def get_burn_rate(
    db: Session,
    org_id: str,
    period_start: date,
    budget_usd: Optional[float] = None,
    provider: Optional[str] = None,
) -> BurnRateResponse:
    today = date.today()
    rows = _base_query(db, org_id, period_start, today, provider).all()

    spent = sum(
        _safe_float(r.cost_usd) for r in rows if r.source_type == "cost"
    )

    days_elapsed = max((today - period_start).days, 1)
    days_in_period = (
        (date(today.year, today.month + 1, 1) if today.month < 12
         else date(today.year + 1, 1, 1)) - period_start
    ).days
    daily_avg = spent / days_elapsed
    projected = daily_avg * days_in_period

    overage = (projected - budget_usd) if budget_usd else None
    burn_pct = (spent / budget_usd * 100) if budget_usd else None

    return BurnRateResponse(
        org_id=org_id,
        provider=provider,
        period_start=period_start,
        today=today,
        budget_usd=budget_usd,
        spent_usd=round(spent, 6),
        daily_avg_usd=round(daily_avg, 6),
        days_elapsed=days_elapsed,
        days_in_period=days_in_period,
        projected_period_spend_usd=round(projected, 6),
        projected_overage_usd=round(overage, 6) if overage is not None else None,
        burn_rate_pct=round(burn_pct, 2) if burn_pct is not None else None,
    )


# ── Copilot seats ─────────────────────────────────────────────────────────────

def get_copilot_seats(
    db: Session,
    org_id: str,
    start: date,
    end: date,
) -> CopilotSeatsResponse:
    rows = (
        _base_query(db, org_id, start, end, provider="github_copilot")
        .filter(AiUsageSnapshot.source_type == "seats")
        .all()
    )

    daily: dict[date, dict] = {}
    for row in rows:
        bucket_date = datetime.utcfromtimestamp(row.bucket_start_time).date()
        if bucket_date not in daily:
            daily[bucket_date] = {"total": 0, "active": 0}
        # Take the max within a day (multiple snapshots per day possible)
        daily[bucket_date]["total"] = max(
            daily[bucket_date]["total"], _safe_int(row.total_seats)
        )
        daily[bucket_date]["active"] = max(
            daily[bucket_date]["active"], _safe_int(row.active_seats)
        )

    points = [
        CopilotSeatDataPoint(
            date=d,
            total_seats=v["total"],
            active_seats=v["active"],
            utilisation_pct=(
                round(v["active"] / v["total"] * 100, 1) if v["total"] else 0.0
            ),
        )
        for d, v in sorted(daily.items())
    ]

    return CopilotSeatsResponse(org_id=org_id, days=points)
