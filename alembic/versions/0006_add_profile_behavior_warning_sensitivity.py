"""add profile behavior warning sensitivity

Revision ID: 0006_profile_behavior_warning
Revises: 0005_behavior_event_taxonomy
Create Date: 2026-07-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0006_profile_behavior_warning"
down_revision: str | Sequence[str] | None = "0005_behavior_event_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("driver_profiles")}

    if "behavior_warning_sensitivity" not in columns:
        op.add_column(
            "driver_profiles",
            sa.Column("behavior_warning_sensitivity", mysql.JSON(), nullable=True),
        )
    op.execute(
        sa.text(
            """
            UPDATE driver_profiles
            SET behavior_warning_sensitivity = JSON_OBJECT(
                'DROWSINESS', 'HIGH',
                'PHONE_USE', 'HIGH',
                'FOOD_OR_DRINK', 'MEDIUM',
                'GAZE_AWAY', 'HIGH',
                'SECONDARY_TASK', 'MEDIUM',
                'REACHING_BEHIND', 'MEDIUM',
                'SMOKING', 'MEDIUM'
            )
            WHERE behavior_warning_sensitivity IS NULL
            """
        )
    )
    columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("driver_profiles")
    }
    if columns["behavior_warning_sensitivity"].get("nullable", True):
        op.alter_column(
            "driver_profiles",
            "behavior_warning_sensitivity",
            existing_type=mysql.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("driver_profiles", "behavior_warning_sensitivity")
