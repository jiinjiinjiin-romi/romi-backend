"""add account display name

Revision ID: 0007_account_display_name
Revises: 0006_profile_behavior_warning
Create Date: 2026-07-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_account_display_name"
down_revision: str | Sequence[str] | None = "0006_profile_behavior_warning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("accounts")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("accounts")}

    if "display_name" not in columns:
        op.add_column(
            "accounts",
            sa.Column(
                "display_name",
                sa.String(length=50),
                server_default=sa.text("'안정현'"),
                nullable=True,
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET display_name = '안정현'
            WHERE display_name IS NULL OR CHAR_LENGTH(TRIM(display_name)) = 0
            """
        )
    )

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("accounts")}
    if columns["display_name"].get("nullable", True):
        op.alter_column(
            "accounts",
            "display_name",
            existing_type=sa.String(length=50),
            nullable=False,
            server_default=sa.text("'안정현'"),
        )

    if "ck_accounts_display_name_not_blank" not in constraints:
        op.create_check_constraint(
            "ck_accounts_display_name_not_blank",
            "accounts",
            sa.text("CHAR_LENGTH(TRIM(display_name)) > 0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("accounts")}

    if "ck_accounts_display_name_not_blank" in constraints:
        op.drop_constraint("ck_accounts_display_name_not_blank", "accounts", type_="check")

    columns = {column["name"] for column in sa.inspect(bind).get_columns("accounts")}
    if "display_name" in columns:
        op.drop_column("accounts", "display_name")
