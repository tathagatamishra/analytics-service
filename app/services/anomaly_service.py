"""
AnomalyService — detects cost spikes using a rolling z-score.

Algorithm:
  For each day in the window, compute z = (cost - rolling_mean) / rolling_std
  using a 7-day look-back window (min 3 observations).
  |z| > 2.0  → warning
  |z| > 3.0  → critical
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from app.schemas.analytics import AnomalyPoint, AnomalyResponse
from app.services.analytics_service import _safe_float, _str_to_bin, _epoch
from app.models.snapshots import AiUsageSnapshot


def get_anomalies(
    db: Session,
    org_id: str,
    start: date,
    end: date,
    provider: Optional[str] = None,
    z_warning: float = 2.0,
    z_critical: float = 3.0,
) -> AnomalyResponse:
    org_bytes = _str_to_bin(org_id)
    # Fetch extra 14 days before window to have enough look-back data
    fetch_start = start - timedelta(days=14)
    epoch_start = _epoch(fetch_start)
    epoch_end = _epoch(end) + 86400 - 1

    q = db.query(AiUsageSnapshot).filter(
        AiUsageSnapshot.org_id == org_bytes,
        AiUsageSnapshot.source_type == "cost",
        AiUsageSnapshot.bucket_start_time >= epoch_start,
        AiUsageSnapshot.bucket_start_time <= epoch_end,
    )
    if provider:
        q = q.filter(AiUsageSnapshot.provider == provider)

    # Build daily cost dict
    daily: dict[date, float] = {}
    current = fetch_start
    while current <= end:
        daily[current] = 0.0
        current += timedelta(days=1)

    for row in q.all():
        d = datetime.utcfromtimestamp(row.bucket_start_time).date()
        if d in daily:
            daily[d] += _safe_float(row.cost_usd)

    sorted_dates = sorted(daily.keys())
    costs = [daily[d] for d in sorted_dates]

    # Rolling z-score with 7-day window
    points: list[AnomalyPoint] = []
    anomaly_count = 0
    window = 7

    for i, d in enumerate(sorted_dates):
        if d < start:
            continue  # pre-window data used only for look-back

        lookback = costs[max(0, i - window): i]
        cost = costs[i]

        if len(lookback) < 3:
            # Not enough history — mark as unknown, not anomaly
            points.append(
                AnomalyPoint(
                    date=d,
                    cost_usd=round(cost, 6),
                    expected_cost_usd=round(cost, 6),
                    z_score=0.0,
                    is_anomaly=False,
                    severity=None,
                )
            )
            continue

        mean = float(np.mean(lookback))
        std = float(np.std(lookback))

        if std < 1e-9:
            z = 0.0
        else:
            z = (cost - mean) / std

        is_anomaly = abs(z) >= z_warning
        if is_anomaly:
            anomaly_count += 1

        severity = None
        if abs(z) >= z_critical:
            severity = "critical"
        elif abs(z) >= z_warning:
            severity = "warning"

        points.append(
            AnomalyPoint(
                date=d,
                cost_usd=round(cost, 6),
                expected_cost_usd=round(mean, 6),
                z_score=round(z, 3),
                is_anomaly=is_anomaly,
                severity=severity,
            )
        )

    return AnomalyResponse(
        org_id=org_id,
        provider=provider,
        period_start=start,
        period_end=end,
        anomalies_detected=anomaly_count,
        points=points,
    )
