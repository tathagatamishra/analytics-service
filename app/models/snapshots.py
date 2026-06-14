"""
Read-only SQLAlchemy models for tables owned by aitools-service.
aianalytics-service never writes to these tables.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, BigInteger, Integer, DECIMAL,
    Boolean, TIMESTAMP, Index, text,
)
from sqlalchemy.dialects.mysql import BINARY
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


def _bin16():
    """BINARY(16) column type shorthand."""
    return BINARY(16)


class AiTool(Base):
    """ai_tools — one row per API key a customer registers."""
    __tablename__ = "ai_tools"

    id:           Mapped[bytes] = mapped_column(_bin16(), primary_key=True)
    user_id:      Mapped[bytes] = mapped_column(_bin16(), nullable=False)
    org_id:       Mapped[bytes] = mapped_column(_bin16(), nullable=False)
    ai_name:      Mapped[str]   = mapped_column(String(100), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    key_type:     Mapped[str]   = mapped_column(String(50), nullable=False, default="default")
    is_active:    Mapped[bool]  = mapped_column(Boolean, nullable=False, default=True)
    created_at:   Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    updated_at:   Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)

    # encrypted_key intentionally excluded — analytics never needs it


class AiUsageSnapshot(Base):
    """ai_usage_snapshots — raw usage/cost records written by aitools-service."""
    __tablename__ = "ai_usage_snapshots"
    __table_args__ = (
        Index("idx_snapshots_org_bucket",   "org_id", "bucket_start_time"),
        Index("idx_snapshots_tool_id",      "ai_tool_id"),
        Index("idx_snapshots_provider",     "provider", "model_id"),
        Index("idx_snapshots_org_provider", "org_id", "provider", "bucket_start_time"),
    )

    id:                  Mapped[bytes] = mapped_column(_bin16(), primary_key=True)
    org_id:              Mapped[bytes] = mapped_column(_bin16(), nullable=False)
    ai_tool_id:          Mapped[bytes] = mapped_column(_bin16(), nullable=False)
    provider:            Mapped[str]   = mapped_column(String(100), nullable=False)
    model_id:            Mapped[Optional[str]] = mapped_column(String(255))
    snapshot_type:       Mapped[str]   = mapped_column(String(100), nullable=False)
    source_type:         Mapped[str]   = mapped_column(String(50), nullable=False)
    bucket_start_time:   Mapped[int]   = mapped_column(BigInteger, nullable=False)
    input_tokens:        Mapped[Optional[int]] = mapped_column(BigInteger)
    output_tokens:       Mapped[Optional[int]] = mapped_column(BigInteger)
    input_cached_tokens: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_requests:      Mapped[Optional[int]] = mapped_column(BigInteger)
    cost_usd:            Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 10))
    total_seats:         Mapped[Optional[int]] = mapped_column(Integer)
    active_seats:        Mapped[Optional[int]] = mapped_column(Integer)
    ingested_at:         Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
