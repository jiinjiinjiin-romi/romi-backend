"""convert behavior warning sensitivity to numeric values

Revision ID: 0008_numeric_behavior_warning
Revises: 0007_account_display_name
Create Date: 2026-07-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_numeric_behavior_warning"
down_revision: str | Sequence[str] | None = "0007_account_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE driver_profiles
            SET behavior_warning_sensitivity = JSON_OBJECT(
                'DROWSINESS',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.DROWSINESS'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.DROWSINESS'))
                        AS UNSIGNED
                    )
                END,
                'PHONE_USE',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.PHONE_USE'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.PHONE_USE'))
                        AS UNSIGNED
                    )
                END,
                'FOOD_OR_DRINK',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.FOOD_OR_DRINK'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.FOOD_OR_DRINK'))
                        AS UNSIGNED
                    )
                END,
                'GAZE_AWAY',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.GAZE_AWAY'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.GAZE_AWAY'))
                        AS UNSIGNED
                    )
                END,
                'SECONDARY_TASK',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.SECONDARY_TASK'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.SECONDARY_TASK'))
                        AS UNSIGNED
                    )
                END,
                'REACHING_BEHIND',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.REACHING_BEHIND'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(
                            JSON_EXTRACT(behavior_warning_sensitivity, '$.REACHING_BEHIND')
                        )
                        AS UNSIGNED
                    )
                END,
                'SMOKING',
                CASE JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.SMOKING'))
                    WHEN 'LOW' THEN 4
                    WHEN 'MEDIUM' THEN 7
                    WHEN 'HIGH' THEN 9
                    ELSE CAST(
                        JSON_UNQUOTE(JSON_EXTRACT(behavior_warning_sensitivity, '$.SMOKING'))
                        AS UNSIGNED
                    )
                END
            )
            WHERE JSON_TYPE(behavior_warning_sensitivity) = 'OBJECT'
            """
        )
    )


def downgrade() -> None:
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
            WHERE JSON_TYPE(behavior_warning_sensitivity) = 'OBJECT'
            """
        )
    )
