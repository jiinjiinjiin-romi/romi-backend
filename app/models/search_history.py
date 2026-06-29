from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.driver_profile import DriverProfile


class SearchHistory(Base):
    __tablename__ = "search_histories"
    __table_args__ = (
        CheckConstraint(
            "CHAR_LENGTH(TRIM(query)) > 0",
            name="ck_search_histories_query_not_blank",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_search_histories_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_search_histories_longitude",
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) "
            "OR (latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_search_histories_coordinates_pair",
        ),
        Index("idx_search_histories_profile_time", "profile_id", text("searched_at DESC")),
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
    profile_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey(
            "driver_profiles.id",
            name="fk_search_histories_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="KAKAO",
        server_default=text("'KAKAO'"),
    )
    provider_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    longitude: Mapped[float | None] = mapped_column(mysql.DOUBLE, nullable=True)
    searched_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )

    profile: Mapped[DriverProfile] = relationship(
        "DriverProfile",
        back_populates="search_histories",
    )
