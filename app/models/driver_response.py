from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, Boolean, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.intervention import Intervention


class DriverResponse(Base):
    __tablename__ = "driver_responses"
    __table_args__ = (
        CheckConstraint(
            "response_type IN ("
            "'BEHAVIOR_CORRECTED', 'VOICE_ACCEPTED', 'VOICE_REJECTED', "
            "'BUTTON_ACCEPTED', 'BUTTON_DISMISSED', 'NO_RESPONSE', 'BEHAVIOR_REPEATED'"
            ")",
            name="ck_driver_responses_response_type",
        ),
        Index("idx_driver_responses_intervention_time", "intervention_id", "responded_at"),
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
    intervention_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "interventions.id",
            name="fk_driver_responses_intervention_id_interventions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    response_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    behavior_corrected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    response_latency_ms: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=True,
    )
    responded_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )

    intervention: Mapped[Intervention] = relationship(
        "Intervention",
        back_populates="driver_responses",
    )
