from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import BehaviorEventSource, BehaviorEventStatus
from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.agent_conversation import AgentConversation
    from app.models.driving_session import DrivingSession
    from app.models.intervention import Intervention


class BehaviorEvent(Base):
    __tablename__ = "behavior_events"
    __table_args__ = (
        CheckConstraint(
            "behavior_type IN ("
            "'DROWSINESS', 'PHONE_USE', 'FOOD_OR_DRINK', 'GAZE_AWAY', "
            "'SECONDARY_TASK', 'REACHING_BEHIND', 'SMOKING'"
            ")",
            name="ck_behavior_events_behavior_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'RESOLVED', 'CANCELLED')",
            name="ck_behavior_events_status",
        ),
        CheckConstraint(
            "source IN ('MODEL', 'SIMULATION')",
            name="ck_behavior_events_source",
        ),
        CheckConstraint(
            "driving_state IN ('MOVING', 'TEMPORARY_STOP', 'PARKED', 'UNKNOWN')",
            name="ck_behavior_events_driving_state",
        ),
        CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN ("
            "'BEHAVIOR_CORRECTED', 'SESSION_ENDED', 'TIMEOUT', "
            "'FALSE_POSITIVE', 'USER_DISMISSED'"
            ")",
            name="ck_behavior_events_resolution_reason",
        ),
        CheckConstraint(
            "average_confidence BETWEEN 0 AND 1",
            name="ck_behavior_events_average_confidence",
        ),
        CheckConstraint(
            "maximum_confidence BETWEEN 0 AND 1",
            name="ck_behavior_events_maximum_confidence",
        ),
        CheckConstraint(
            "maximum_confidence >= average_confidence",
            name="ck_behavior_events_confidence_order",
        ),
        CheckConstraint(
            "risk_level BETWEEN 0 AND 3",
            name="ck_behavior_events_risk_level",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_behavior_events_ended_at_after_started_at",
        ),
        CheckConstraint(
            "((status = 'ACTIVE' AND ended_at IS NULL) OR "
            "(status IN ('RESOLVED', 'CANCELLED') AND ended_at IS NOT NULL))",
            name="ck_behavior_events_status_end_state",
        ),
        CheckConstraint(
            "speed_kph IS NULL OR speed_kph >= 0",
            name="ck_behavior_events_speed_kph",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_behavior_events_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_behavior_events_longitude",
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_behavior_events_coordinates_pair",
        ),
        Index("idx_behavior_events_session_time", "session_id", "started_at"),
        Index("idx_behavior_events_type_time", "session_id", "behavior_type", "started_at"),
        Index("idx_behavior_events_status", "status"),
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
    session_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "driving_sessions.id",
            name="fk_behavior_events_session_id_driving_sessions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    behavior_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=BehaviorEventStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=BehaviorEventSource.MODEL.value,
        server_default=text("'MODEL'"),
    )
    started_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True), nullable=True)
    average_confidence: Mapped[Decimal] = mapped_column(
        mysql.DECIMAL(precision=5, scale=4),
        nullable=False,
    )
    maximum_confidence: Mapped[Decimal] = mapped_column(
        mysql.DECIMAL(precision=5, scale=4),
        nullable=False,
    )
    driving_state: Mapped[str] = mapped_column(String(20), nullable=False)
    speed_kph: Mapped[Decimal | None] = mapped_column(
        mysql.DECIMAL(precision=6, scale=2),
        nullable=True,
    )
    latitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    longitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    risk_level: Mapped[int] = mapped_column(
        mysql.TINYINT(unsigned=True),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    recurrence_count: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    resolution_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
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

    session: Mapped[DrivingSession] = relationship(
        "DrivingSession",
        back_populates="behavior_events",
    )
    interventions: Mapped[list[Intervention]] = relationship(
        "Intervention",
        back_populates="behavior_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    agent_conversations: Mapped[list[AgentConversation]] = relationship(
        "AgentConversation",
        back_populates="trigger_behavior_event",
        passive_deletes=True,
    )
