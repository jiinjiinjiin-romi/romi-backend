from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DrivingSessionStatus
from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.behavior_event import BehaviorEvent
    from app.models.driver_profile import DriverProfile
    from app.models.location_sample import LocationSample


ACTIVE_PROFILE_ID_SQL = (
    "CASE "
    "WHEN status = 'ACTIVE' THEN profile_id "
    "ELSE NULL "
    "END"
)


class DrivingSession(Base):
    __tablename__ = "driving_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'COMPLETED', 'ABORTED')",
            name="ck_driving_sessions_status",
        ),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ("
            "'USER_REQUEST', 'CAMERA_LOST', 'LOCATION_LOST', "
            "'CONNECTION_LOST', 'SERVER_ERROR', 'UNKNOWN'"
            ")",
            name="ck_driving_sessions_end_reason",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_driving_sessions_ended_at_after_started_at",
        ),
        CheckConstraint(
            "((status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR "
            "(status IN ('COMPLETED', 'ABORTED') "
            "AND ended_at IS NOT NULL AND end_reason IS NOT NULL))",
            name="ck_driving_sessions_status_end_state",
        ),
        CheckConstraint(
            "safety_score IS NULL OR safety_score BETWEEN 0 AND 100",
            name="ck_driving_sessions_safety_score",
        ),
        CheckConstraint(
            "average_speed_kph IS NULL OR average_speed_kph >= 0",
            name="ck_driving_sessions_average_speed_kph",
        ),
        CheckConstraint(
            "start_latitude IS NULL OR start_latitude BETWEEN -90 AND 90",
            name="ck_driving_sessions_start_latitude",
        ),
        CheckConstraint(
            "start_longitude IS NULL OR start_longitude BETWEEN -180 AND 180",
            name="ck_driving_sessions_start_longitude",
        ),
        CheckConstraint(
            "end_latitude IS NULL OR end_latitude BETWEEN -90 AND 90",
            name="ck_driving_sessions_end_latitude",
        ),
        CheckConstraint(
            "end_longitude IS NULL OR end_longitude BETWEEN -180 AND 180",
            name="ck_driving_sessions_end_longitude",
        ),
        CheckConstraint(
            "(start_latitude IS NULL AND start_longitude IS NULL) OR "
            "(start_latitude IS NOT NULL AND start_longitude IS NOT NULL)",
            name="ck_driving_sessions_start_coordinates_pair",
        ),
        CheckConstraint(
            "(end_latitude IS NULL AND end_longitude IS NULL) OR "
            "(end_latitude IS NOT NULL AND end_longitude IS NOT NULL)",
            name="ck_driving_sessions_end_coordinates_pair",
        ),
        UniqueConstraint(
            "active_profile_id",
            name="uq_driving_sessions_active_profile",
        ),
        Index("idx_driving_sessions_profile_time", "profile_id", text("started_at DESC")),
        Index("idx_driving_sessions_status", "status"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        nullable=False,
        default=generate_uuid4,
    )
    profile_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "driver_profiles.id",
            name="fk_driving_sessions_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    active_profile_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        Computed(ACTIVE_PROFILE_ID_SQL, persisted=False),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    ended_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DrivingSessionStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )
    end_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_latitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    start_longitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    end_latitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    end_longitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    destination_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    distance_meters: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    duration_seconds: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    average_speed_kph: Mapped[Decimal | None] = mapped_column(
        mysql.DECIMAL(precision=6, scale=2),
        nullable=True,
    )
    safety_score: Mapped[int | None] = mapped_column(mysql.TINYINT(unsigned=True), nullable=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )

    profile: Mapped[DriverProfile] = relationship(
        "DriverProfile",
        back_populates="driving_sessions",
    )
    location_samples: Mapped[list[LocationSample]] = relationship(
        "LocationSample",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    behavior_events: Mapped[list[BehaviorEvent]] = relationship(
        "BehaviorEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
