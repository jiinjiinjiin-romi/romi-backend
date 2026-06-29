from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AgentPersonality, Theme, WarningSensitivity
from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.driving_session import DrivingSession
    from app.models.saved_place import SavedPlace
    from app.models.search_history import SearchHistory


class DriverProfile(Base):
    __tablename__ = "driver_profiles"
    __table_args__ = (
        CheckConstraint(
            "agent_personality IN ('FRIENDLY', 'FORMAL', 'WARM', 'WITTY')",
            name="ck_driver_profiles_agent_personality",
        ),
        CheckConstraint(
            "warning_sensitivity IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_driver_profiles_warning_sensitivity",
        ),
        CheckConstraint(
            "theme IN ('LIGHT', 'DARK', 'SYSTEM')",
            name="ck_driver_profiles_theme",
        ),
        CheckConstraint(
            "tts_speed BETWEEN 0.50 AND 2.00",
            name="ck_driver_profiles_tts_speed",
        ),
        CheckConstraint(
            "guidance_volume BETWEEN 0 AND 100",
            name="ck_driver_profiles_guidance_volume",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(display_name)) > 0",
            name="ck_driver_profiles_display_name_not_blank",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(agent_call_name)) > 0",
            name="ck_driver_profiles_agent_call_name_not_blank",
        ),
        Index("idx_driver_profiles_account", "account_id"),
        Index("idx_driver_profiles_account_last_used", "account_id", text("last_used_at DESC")),
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
    account_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "accounts.id",
            name="fk_driver_profiles_account_id_accounts",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_call_name: Mapped[str] = mapped_column(String(50), nullable=False)
    profile_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    agent_personality: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AgentPersonality.FRIENDLY.value,
        server_default=text("'FRIENDLY'"),
    )
    warning_sensitivity: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=WarningSensitivity.MEDIUM.value,
        server_default=text("'MEDIUM'"),
    )
    tts_voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tts_speed: Mapped[Decimal] = mapped_column(
        mysql.DECIMAL(precision=3, scale=2),
        nullable=False,
        default=Decimal("1.00"),
        server_default=text("1.00"),
    )
    guidance_volume: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True),
        nullable=False,
        default=70,
        server_default=text("70"),
    )
    theme: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=Theme.SYSTEM.value,
        server_default=text("'SYSTEM'"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
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

    account: Mapped[Account] = relationship("Account", back_populates="driver_profiles")
    saved_places: Mapped[list[SavedPlace]] = relationship(
        "SavedPlace",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    search_histories: Mapped[list[SearchHistory]] = relationship(
        "SearchHistory",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    driving_sessions: Mapped[list[DrivingSession]] = relationship(
        "DrivingSession",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
