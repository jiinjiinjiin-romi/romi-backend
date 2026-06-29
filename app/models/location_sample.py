from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import LocationSource
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.driving_session import DrivingSession


class LocationSample(Base):
    __tablename__ = "location_samples"
    __table_args__ = (
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_location_samples_latitude",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_location_samples_longitude",
        ),
        CheckConstraint(
            "speed_kph IS NULL OR speed_kph >= 0",
            name="ck_location_samples_speed_kph",
        ),
        CheckConstraint(
            "accuracy_meters IS NULL OR accuracy_meters >= 0",
            name="ck_location_samples_accuracy_meters",
        ),
        CheckConstraint(
            "driving_state IN ('MOVING', 'TEMPORARY_STOP', 'PARKED', 'UNKNOWN')",
            name="ck_location_samples_driving_state",
        ),
        CheckConstraint(
            "source IN ('GPS', 'SIMULATION')",
            name="ck_location_samples_source",
        ),
        UniqueConstraint(
            "session_id",
            "recorded_at",
            name="uq_location_samples_time",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "driving_sessions.id",
            name="fk_location_samples_session_id_driving_sessions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(mysql.DOUBLE, nullable=False)
    longitude: Mapped[float] = mapped_column(mysql.DOUBLE, nullable=False)
    speed_kph: Mapped[Decimal | None] = mapped_column(
        mysql.DECIMAL(precision=6, scale=2),
        nullable=True,
    )
    driving_state: Mapped[str] = mapped_column(String(20), nullable=False)
    accuracy_meters: Mapped[Decimal | None] = mapped_column(
        mysql.DECIMAL(precision=8, scale=2),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=LocationSource.GPS.value,
        server_default=text("'GPS'"),
    )
    recorded_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)

    session: Mapped[DrivingSession] = relationship(
        "DrivingSession",
        back_populates="location_samples",
    )
