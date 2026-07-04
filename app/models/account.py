from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.driver_profile import DriverProfile


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("email", name="uq_accounts_email"),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(display_name)) > 0",
            name="ck_accounts_display_name_not_blank",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, nullable=False)
    display_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="안정현",
        server_default=text("'안정현'"),
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
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
    driver_profiles: Mapped[list["DriverProfile"]] = relationship(
        "DriverProfile",
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
