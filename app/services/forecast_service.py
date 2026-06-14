"""
ForecastingService — 30-day cost/token forecasts using scikit-learn.

Strategy:
  1. Build a daily cost series from snapshots (last N training days).
  2. If >= 14 data points → Linear Regression with day-index as feature.
  3. If 7–13 points → simple exponential weighted mean projection.
  4. < 7 points → average of available days.

Confidence interval: ±1.5 * std of residuals (covers ~85% of observations),
clamped to [0, 3× predicted].
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy.orm import Session

from app.models.snapshots import AiUsageSnapshot
from app.schemas.analytics import ForecastDataPoint, ForecastResponse
from app.services.analytics_service import _str_to_bin, _safe_float, _epoch


def _build_daily_series(
    db: Session,
    org_id: str,
    start: date,
    end: date,
    provider: Optional[str],
) -> dict[date, float]:
    org_bytes = _str_to_bin(org_id)
    epoch_start = _epoch(start)
    epoch_end = _epoch(end) + 86400 - 1

    q = db.query(AiUsageSnapshot).filter(
        AiUsageSnapshot.org_id == org_bytes,
        AiUsageSnapshot.source_type == "cost",
        AiUsageSnapshot.bucket_start_time >= epoch_start,
        AiUsageSnapshot.bucket_start_time <= epoch_end,
    )
    if provider:
        q = q.filter(AiUsageSnapshot.provider == provider)

    daily: dict[date, float] = {}
    for row in q.all():
        d = datetime.utcfromtimestamp(row.bucket_start_time).date()
        daily[d] = daily.get(d, 0.0) + _safe_float(row.cost_usd)

    # Fill gaps with 0
    current = start
    while current <= end:
        if current not in daily:
            daily[current] = 0.0
        current += timedelta(days=1)

    return daily


def get_forecast(
    db: Session,
    org_id: str,
    provider: Optional[str] = None,
    horizon_days: int = 30,
    training_days: int = 60,
) -> ForecastResponse:
    today = date.today()
    train_start = today - timedelta(days=training_days)
    train_end = today - timedelta(days=1)  # yesterday; today not complete yet

    series = _build_daily_series(db, org_id, train_start, train_end, provider)
    sorted_dates = sorted(series.keys())
    costs = [series[d] for d in sorted_dates]
    n = len(costs)

    # Choose model based on data availability
    if n >= 14:
        model_name = "linear_regression"
        X = np.array(range(n)).reshape(-1, 1)
        y = np.array(costs)
        reg = LinearRegression().fit(X, y)
        residuals = y - reg.predict(X)
        std = float(np.std(residuals))

        forecast_points = []
        monthly_total = 0.0
        for i in range(horizon_days):
            future_day = today + timedelta(days=i)
            x_val = np.array([[n + i]])
            pred = float(reg.predict(x_val)[0])
            pred = max(pred, 0.0)
            lo = max(pred - 1.5 * std, 0.0)
            hi = min(pred + 1.5 * std, pred * 3)
            if i < 30:
                monthly_total += pred
            forecast_points.append(
                ForecastDataPoint(
                    date=future_day,
                    predicted_cost_usd=round(pred, 6),
                    lower_bound=round(lo, 6),
                    upper_bound=round(hi, 6),
                )
            )

    elif n >= 7:
        model_name = "exponential_weighted_mean"
        arr = np.array(costs)
        # EWM: more recent days get higher weight
        weights = np.exp(np.linspace(0, 1, n))
        weights /= weights.sum()
        baseline = float(np.dot(weights, arr))
        std = float(np.std(arr))

        forecast_points = []
        monthly_total = 0.0
        for i in range(horizon_days):
            future_day = today + timedelta(days=i)
            pred = max(baseline, 0.0)
            lo = max(pred - 1.5 * std, 0.0)
            hi = pred + 1.5 * std
            if i < 30:
                monthly_total += pred
            forecast_points.append(
                ForecastDataPoint(
                    date=future_day,
                    predicted_cost_usd=round(pred, 6),
                    lower_bound=round(lo, 6),
                    upper_bound=round(hi, 6),
                )
            )

    else:
        model_name = "daily_average"
        baseline = float(np.mean(costs)) if costs else 0.0
        forecast_points = []
        monthly_total = 0.0
        for i in range(horizon_days):
            future_day = today + timedelta(days=i)
            pred = max(baseline, 0.0)
            if i < 30:
                monthly_total += pred
            forecast_points.append(
                ForecastDataPoint(
                    date=future_day,
                    predicted_cost_usd=round(pred, 6),
                    lower_bound=0.0,
                    upper_bound=round(pred * 2, 6),
                )
            )

    return ForecastResponse(
        org_id=org_id,
        provider=provider,
        horizon_days=horizon_days,
        model_used=model_name,
        training_days=n,
        forecast=forecast_points,
        monthly_projection_usd=round(monthly_total, 6),
    )
