from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import InterventionGeneratedBy, InterventionStatus
from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.behavior_event import BehaviorEvent
    from app.models.driver_response import DriverResponse


class Intervention(Base):
    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint(
            "level BETWEEN 1 AND 3",
            name="ck_interventions_level",
        ),
        CheckConstraint(
            "intervention_type IN ('WARNING', 'RECOMMENDATION', 'TOOL_OFFER')",
            name="ck_interventions_intervention_type",
        ),
        CheckConstraint(
            "generated_by IN ('TEMPLATE', 'GEMINI')",
            name="ck_interventions_generated_by",
        ),
        CheckConstraint(
            "status IN ("
            "'CREATED', 'DELIVERED', 'WAITING_RESPONSE', 'RESOLVED', "
            "'ESCALATED', 'FAILED', 'CANCELLED'"
            ")",
            name="ck_interventions_status",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_interventions_ended_at_after_started_at",
        ),
        Index("idx_interventions_event_time", "behavior_event_id", "started_at"),
        Index("idx_interventions_status", "status"),
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
    behavior_event_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "behavior_events.id",
            name="fk_interventions_behavior_event_id_behavior_events",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), nullable=False)
    intervention_type: Mapped[str] = mapped_column(String(30), nullable=False)
    speech_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ui_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InterventionGeneratedBy.TEMPLATE.value,
        server_default=text("'TEMPLATE'"),
    )
    channels_json: Mapped[list[str]] = mapped_column(mysql.JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=InterventionStatus.CREATED.value,
        server_default=text("'CREATED'"),
    )
    next_check_after_ms: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    ended_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )

    behavior_event: Mapped[BehaviorEvent] = relationship(
        "BehaviorEvent",
        back_populates="interventions",
    )
    driver_responses: Mapped[list[DriverResponse]] = relationship(
        "DriverResponse",
        back_populates="intervention",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
