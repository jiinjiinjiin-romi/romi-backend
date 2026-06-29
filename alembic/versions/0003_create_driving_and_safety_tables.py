"""create driving and safety tables

Revision ID: 0003_driving_safety_tables
Revises: 0002_profile_place_tables
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0003_driving_safety_tables"
down_revision: str | None = "0002_profile_place_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "driving_sessions",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("profile_id", sa.CHAR(length=36), nullable=False),
        sa.Column(
            "active_profile_id",
            sa.CHAR(length=36),
            sa.Computed(
                "CASE WHEN status = 'ACTIVE' THEN profile_id ELSE NULL END",
                persisted=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("ended_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column("end_reason", sa.String(length=30), nullable=True),
        sa.Column("start_latitude", mysql.DOUBLE(), nullable=True),
        sa.Column("start_longitude", mysql.DOUBLE(), nullable=True),
        sa.Column("end_latitude", mysql.DOUBLE(), nullable=True),
        sa.Column("end_longitude", mysql.DOUBLE(), nullable=True),
        sa.Column("destination_name", sa.String(length=200), nullable=True),
        sa.Column("destination_place_id", sa.String(length=255), nullable=True),
        sa.Column(
            "distance_meters",
            mysql.BIGINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "duration_seconds",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("average_speed_kph", mysql.DECIMAL(precision=6, scale=2), nullable=True),
        sa.Column("safety_score", mysql.TINYINT(unsigned=True), nullable=True),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
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
            "status IN ('ACTIVE', 'COMPLETED', 'ABORTED')",
            name="ck_driving_sessions_status",
        ),
        sa.CheckConstraint(
            "end_reason IS NULL OR end_reason IN ("
            "'USER_REQUEST', 'CAMERA_LOST', 'LOCATION_LOST', "
            "'CONNECTION_LOST', 'SERVER_ERROR', 'UNKNOWN'"
            ")",
            name="ck_driving_sessions_end_reason",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_driving_sessions_ended_at_after_started_at",
        ),
        sa.CheckConstraint(
            "((status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR "
            "(status IN ('COMPLETED', 'ABORTED') "
            "AND ended_at IS NOT NULL AND end_reason IS NOT NULL))",
            name="ck_driving_sessions_status_end_state",
        ),
        sa.CheckConstraint(
            "safety_score IS NULL OR safety_score BETWEEN 0 AND 100",
            name="ck_driving_sessions_safety_score",
        ),
        sa.CheckConstraint(
            "average_speed_kph IS NULL OR average_speed_kph >= 0",
            name="ck_driving_sessions_average_speed_kph",
        ),
        sa.CheckConstraint(
            "start_latitude IS NULL OR start_latitude BETWEEN -90 AND 90",
            name="ck_driving_sessions_start_latitude",
        ),
        sa.CheckConstraint(
            "start_longitude IS NULL OR start_longitude BETWEEN -180 AND 180",
            name="ck_driving_sessions_start_longitude",
        ),
        sa.CheckConstraint(
            "end_latitude IS NULL OR end_latitude BETWEEN -90 AND 90",
            name="ck_driving_sessions_end_latitude",
        ),
        sa.CheckConstraint(
            "end_longitude IS NULL OR end_longitude BETWEEN -180 AND 180",
            name="ck_driving_sessions_end_longitude",
        ),
        sa.CheckConstraint(
            "(start_latitude IS NULL AND start_longitude IS NULL) OR "
            "(start_latitude IS NOT NULL AND start_longitude IS NOT NULL)",
            name="ck_driving_sessions_start_coordinates_pair",
        ),
        sa.CheckConstraint(
            "(end_latitude IS NULL AND end_longitude IS NULL) OR "
            "(end_latitude IS NOT NULL AND end_longitude IS NOT NULL)",
            name="ck_driving_sessions_end_coordinates_pair",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["driver_profiles.id"],
            name="fk_driving_sessions_profile_id_driver_profiles",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "active_profile_id",
            name="uq_driving_sessions_active_profile",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_driving_sessions_profile_time",
        "driving_sessions",
        ["profile_id", sa.text("started_at DESC")],
    )
    op.create_index("idx_driving_sessions_status", "driving_sessions", ["status"])

    op.create_table(
        "location_samples",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.CHAR(length=36), nullable=False),
        sa.Column("latitude", mysql.DOUBLE(), nullable=False),
        sa.Column("longitude", mysql.DOUBLE(), nullable=False),
        sa.Column("speed_kph", mysql.DECIMAL(precision=6, scale=2), nullable=True),
        sa.Column("driving_state", sa.String(length=20), nullable=False),
        sa.Column("accuracy_meters", mysql.DECIMAL(precision=8, scale=2), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default=sa.text("'GPS'"),
            nullable=False,
        ),
        sa.Column("recorded_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_location_samples_latitude",
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_location_samples_longitude",
        ),
        sa.CheckConstraint(
            "speed_kph IS NULL OR speed_kph >= 0",
            name="ck_location_samples_speed_kph",
        ),
        sa.CheckConstraint(
            "accuracy_meters IS NULL OR accuracy_meters >= 0",
            name="ck_location_samples_accuracy_meters",
        ),
        sa.CheckConstraint(
            "driving_state IN ('MOVING', 'TEMPORARY_STOP', 'PARKED', 'UNKNOWN')",
            name="ck_location_samples_driving_state",
        ),
        sa.CheckConstraint(
            "source IN ('GPS', 'SIMULATION')",
            name="ck_location_samples_source",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name="fk_location_samples_session_id_driving_sessions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "recorded_at", name="uq_location_samples_time"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "behavior_events",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("session_id", sa.CHAR(length=36), nullable=False),
        sa.Column("behavior_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default=sa.text("'MODEL'"),
            nullable=False,
        ),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("ended_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("average_confidence", mysql.DECIMAL(precision=5, scale=4), nullable=False),
        sa.Column("maximum_confidence", mysql.DECIMAL(precision=5, scale=4), nullable=False),
        sa.Column("driving_state", sa.String(length=20), nullable=False),
        sa.Column("speed_kph", mysql.DECIMAL(precision=6, scale=2), nullable=True),
        sa.Column("latitude", mysql.DOUBLE(), nullable=True),
        sa.Column("longitude", mysql.DOUBLE(), nullable=True),
        sa.Column(
            "risk_level",
            mysql.TINYINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "recurrence_count",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("resolution_reason", sa.String(length=30), nullable=True),
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
            "behavior_type IN ('DROWSINESS', 'PHONE_USE', 'FOOD_OR_DRINK', 'GAZE_AWAY')",
            name="ck_behavior_events_behavior_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RESOLVED', 'CANCELLED')",
            name="ck_behavior_events_status",
        ),
        sa.CheckConstraint(
            "source IN ('MODEL', 'SIMULATION')",
            name="ck_behavior_events_source",
        ),
        sa.CheckConstraint(
            "driving_state IN ('MOVING', 'TEMPORARY_STOP', 'PARKED', 'UNKNOWN')",
            name="ck_behavior_events_driving_state",
        ),
        sa.CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN ("
            "'BEHAVIOR_CORRECTED', 'SESSION_ENDED', 'TIMEOUT', "
            "'FALSE_POSITIVE', 'USER_DISMISSED'"
            ")",
            name="ck_behavior_events_resolution_reason",
        ),
        sa.CheckConstraint(
            "average_confidence BETWEEN 0 AND 1",
            name="ck_behavior_events_average_confidence",
        ),
        sa.CheckConstraint(
            "maximum_confidence BETWEEN 0 AND 1",
            name="ck_behavior_events_maximum_confidence",
        ),
        sa.CheckConstraint(
            "maximum_confidence >= average_confidence",
            name="ck_behavior_events_confidence_order",
        ),
        sa.CheckConstraint(
            "risk_level BETWEEN 0 AND 3",
            name="ck_behavior_events_risk_level",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_behavior_events_ended_at_after_started_at",
        ),
        sa.CheckConstraint(
            "((status = 'ACTIVE' AND ended_at IS NULL) OR "
            "(status IN ('RESOLVED', 'CANCELLED') AND ended_at IS NOT NULL))",
            name="ck_behavior_events_status_end_state",
        ),
        sa.CheckConstraint(
            "speed_kph IS NULL OR speed_kph >= 0",
            name="ck_behavior_events_speed_kph",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_behavior_events_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_behavior_events_longitude",
        ),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_behavior_events_coordinates_pair",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name="fk_behavior_events_session_id_driving_sessions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_behavior_events_session_time",
        "behavior_events",
        ["session_id", "started_at"],
    )
    op.create_index(
        "idx_behavior_events_type_time",
        "behavior_events",
        ["session_id", "behavior_type", "started_at"],
    )
    op.create_index("idx_behavior_events_status", "behavior_events", ["status"])

    op.create_table(
        "interventions",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("behavior_event_id", sa.CHAR(length=36), nullable=False),
        sa.Column("level", mysql.TINYINT(unsigned=True), nullable=False),
        sa.Column("intervention_type", sa.String(length=30), nullable=False),
        sa.Column("speech_text", sa.Text(), nullable=True),
        sa.Column("ui_text", sa.Text(), nullable=False),
        sa.Column(
            "generated_by",
            sa.String(length=20),
            server_default=sa.text("'TEMPLATE'"),
            nullable=False,
        ),
        sa.Column("channels_json", mysql.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'CREATED'"),
            nullable=False,
        ),
        sa.Column("next_check_after_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column(
            "started_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("ended_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_interventions_level"),
        sa.CheckConstraint(
            "intervention_type IN ('WARNING', 'RECOMMENDATION', 'TOOL_OFFER')",
            name="ck_interventions_intervention_type",
        ),
        sa.CheckConstraint(
            "generated_by IN ('TEMPLATE', 'GEMINI')",
            name="ck_interventions_generated_by",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'CREATED', 'DELIVERED', 'WAITING_RESPONSE', 'RESOLVED', "
            "'ESCALATED', 'FAILED', 'CANCELLED'"
            ")",
            name="ck_interventions_status",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_interventions_ended_at_after_started_at",
        ),
        sa.ForeignKeyConstraint(
            ["behavior_event_id"],
            ["behavior_events.id"],
            name="fk_interventions_behavior_event_id_behavior_events",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_interventions_event_time",
        "interventions",
        ["behavior_event_id", "started_at"],
    )
    op.create_index("idx_interventions_status", "interventions", ["status"])

    op.create_table(
        "driver_responses",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("intervention_id", sa.CHAR(length=36), nullable=False),
        sa.Column("response_type", sa.String(length=30), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("behavior_corrected", sa.Boolean(), nullable=True),
        sa.Column("response_latency_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column(
            "responded_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "response_type IN ("
            "'BEHAVIOR_CORRECTED', 'VOICE_ACCEPTED', 'VOICE_REJECTED', "
            "'BUTTON_ACCEPTED', 'BUTTON_DISMISSED', 'NO_RESPONSE', 'BEHAVIOR_REPEATED'"
            ")",
            name="ck_driver_responses_response_type",
        ),
        sa.ForeignKeyConstraint(
            ["intervention_id"],
            ["interventions.id"],
            name="fk_driver_responses_intervention_id_interventions",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "idx_driver_responses_intervention_time",
        "driver_responses",
        ["intervention_id", "responded_at"],
    )


def downgrade() -> None:
    op.drop_table("driver_responses")

    op.drop_table("interventions")

    op.drop_table("behavior_events")

    op.drop_table("location_samples")

    op.drop_table("driving_sessions")
