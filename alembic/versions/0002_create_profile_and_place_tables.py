"""create profile and place tables

Revision ID: 0002_profile_place_tables
Revises: 0001_create_accounts
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0002_profile_place_tables"
down_revision: str | None = "0001_create_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "driver_profiles",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("account_id", sa.CHAR(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=50), nullable=False),
        sa.Column("agent_call_name", sa.String(length=50), nullable=False),
        sa.Column("profile_image_url", sa.Text(), nullable=True),
        sa.Column("report_email", sa.String(length=320), nullable=True),
        sa.Column(
            "agent_personality",
            sa.String(length=20),
            server_default=sa.text("'FRIENDLY'"),
            nullable=False,
        ),
        sa.Column(
            "warning_sensitivity",
            sa.String(length=10),
            server_default=sa.text("'MEDIUM'"),
            nullable=False,
        ),
        sa.Column("tts_voice_id", sa.String(length=100), nullable=True),
        sa.Column(
            "tts_speed",
            mysql.DECIMAL(precision=3, scale=2),
            server_default=sa.text("1.00"),
            nullable=False,
        ),
        sa.Column(
            "guidance_volume",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("70"),
            nullable=False,
        ),
        sa.Column(
            "theme",
            sa.String(length=10),
            server_default=sa.text("'SYSTEM'"),
            nullable=False,
        ),
        sa.Column("last_used_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent_personality IN ('FRIENDLY', 'FORMAL', 'WARM', 'WITTY')",
            name="ck_driver_profiles_agent_personality",
        ),
        sa.CheckConstraint(
            "warning_sensitivity IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_driver_profiles_warning_sensitivity",
        ),
        sa.CheckConstraint("theme IN ('LIGHT', 'DARK', 'SYSTEM')", name="ck_driver_profiles_theme"),
        sa.CheckConstraint(
            "tts_speed BETWEEN 0.50 AND 2.00",
            name="ck_driver_profiles_tts_speed",
        ),
        sa.CheckConstraint(
            "guidance_volume BETWEEN 0 AND 100",
            name="ck_driver_profiles_guidance_volume",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(display_name)) > 0",
            name="ck_driver_profiles_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(agent_call_name)) > 0",
            name="ck_driver_profiles_agent_call_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_driver_profiles_account_id_accounts",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("idx_driver_profiles_account", "driver_profiles", ["account_id"])
    op.create_index(
        "idx_driver_profiles_account_last_used",
        "driver_profiles",
        ["account_id", sa.text("last_used_at DESC")],
    )

    op.create_table(
        "saved_places",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("profile_id", sa.CHAR(length=36), nullable=False),
        sa.Column("place_type", sa.String(length=20), nullable=False),
        sa.Column(
            "fixed_place_type",
            sa.String(length=20),
            sa.Computed(
                "CASE "
                "WHEN place_type IN ('HOME', 'WORK', 'SCHOOL') THEN place_type "
                "ELSE NULL "
                "END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=20),
            server_default=sa.text("'KAKAO'"),
            nullable=False,
        ),
        sa.Column("provider_place_id", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", mysql.DOUBLE(), nullable=False),
        sa.Column("longitude", mysql.DOUBLE(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "place_type IN ('HOME', 'WORK', 'SCHOOL', 'FAVORITE')",
            name="ck_saved_places_place_type",
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_saved_places_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_saved_places_longitude"),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(label)) > 0",
            name="ck_saved_places_label_not_blank",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(address)) > 0",
            name="ck_saved_places_address_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["driver_profiles.id"],
            name="fk_saved_places_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "fixed_place_type",
            name="uq_saved_places_profile_fixed_type",
        ),
        sa.UniqueConstraint(
            "profile_id",
            "place_type",
            "provider",
            "provider_place_id",
            name="uq_saved_places_provider_place",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("idx_saved_places_profile", "saved_places", ["profile_id"])

    op.create_table(
        "search_histories",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.CHAR(length=36), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=20),
            server_default=sa.text("'KAKAO'"),
            nullable=False,
        ),
        sa.Column("provider_place_id", sa.String(length=255), nullable=True),
        sa.Column("place_name", sa.String(length=200), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", mysql.DOUBLE(), nullable=True),
        sa.Column("longitude", mysql.DOUBLE(), nullable=True),
        sa.Column(
            "searched_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(TRIM(query)) > 0",
            name="ck_search_histories_query_not_blank",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_search_histories_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_search_histories_longitude",
        ),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) "
            "OR (latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_search_histories_coordinates_pair",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["driver_profiles.id"],
            name="fk_search_histories_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_search_histories_profile_time",
        "search_histories",
        ["profile_id", sa.text("searched_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("search_histories")

    op.drop_table("saved_places")

    op.drop_table("driver_profiles")
