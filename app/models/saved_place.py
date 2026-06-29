from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.uuid import generate_uuid4

if TYPE_CHECKING:
    from app.models.driver_profile import DriverProfile


FIXED_PLACE_TYPE_SQL = (
    "CASE "
    "WHEN place_type IN ('HOME', 'WORK', 'SCHOOL') THEN place_type "
    "ELSE NULL "
    "END"
)


class SavedPlace(Base):
    __tablename__ = "saved_places"
    __table_args__ = (
        CheckConstraint(
            "place_type IN ('HOME', 'WORK', 'SCHOOL', 'FAVORITE')",
            name="ck_saved_places_place_type",
        ),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_saved_places_latitude",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_saved_places_longitude",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(label)) > 0",
            name="ck_saved_places_label_not_blank",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(address)) > 0",
            name="ck_saved_places_address_not_blank",
        ),
        UniqueConstraint(
            "profile_id",
            "fixed_place_type",
            name="uq_saved_places_profile_fixed_type",
        ),
        UniqueConstraint(
            "profile_id",
            "place_type",
            "provider",
            "provider_place_id",
            name="uq_saved_places_provider_place",
        ),
        Index("idx_saved_places_profile", "profile_id"),
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
            name="fk_saved_places_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    place_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fixed_place_type: Mapped[str | None] = mapped_column(
        String(20),
        Computed(FIXED_PLACE_TYPE_SQL, persisted=True),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="KAKAO",
        server_default=text("'KAKAO'"),
    )
    provider_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(mysql.DOUBLE, nullable=False)
    longitude: Mapped[float] = mapped_column(mysql.DOUBLE, nullable=False)
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
        back_populates="saved_places",
    )
