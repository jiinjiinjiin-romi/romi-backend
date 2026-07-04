"""expand behavior event taxonomy

Revision ID: 0005_behavior_event_taxonomy
Revises: 0004_agent_report_tables
Create Date: 2026-07-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_behavior_event_taxonomy"
down_revision: str | Sequence[str] | None = "0004_agent_report_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ck_behavior_events_behavior_type"
TABLE_NAME = "behavior_events"

OLD_BEHAVIOR_TYPE_CHECK = (
    "behavior_type IN ('DROWSINESS', 'PHONE_USE', 'FOOD_OR_DRINK', 'GAZE_AWAY')"
)
NEW_BEHAVIOR_TYPE_CHECK = (
    "behavior_type IN ("
    "'DROWSINESS', 'PHONE_USE', 'FOOD_OR_DRINK', 'GAZE_AWAY', "
    "'SECONDARY_TASK', 'REACHING_BEHIND', 'SMOKING'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        sa.text(NEW_BEHAVIOR_TYPE_CHECK),
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        sa.text(OLD_BEHAVIOR_TYPE_CHECK),
    )
