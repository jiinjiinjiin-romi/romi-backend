from sqlalchemy import CHAR, String, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.models import Account


def test_account_model_matches_current_scope() -> None:
    table = Account.__table__

    assert table.name == "accounts"
    assert set(table.columns.keys()) == {"id", "display_name", "email", "created_at", "updated_at"}
    assert not table.foreign_keys


def test_account_model_column_types_and_nullability() -> None:
    table = Account.__table__

    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.type.length == 36
    assert table.c.id.primary_key
    assert not table.c.id.nullable

    assert isinstance(table.c.email.type, String)
    assert table.c.email.type.length == 320
    assert table.c.email.nullable
    assert isinstance(table.c.display_name.type, String)
    assert table.c.display_name.type.length == 50
    assert not table.c.display_name.nullable

    assert isinstance(table.c.created_at.type, mysql.DATETIME)
    assert table.c.created_at.type.fsp == 6
    assert not table.c.created_at.nullable

    assert isinstance(table.c.updated_at.type, mysql.DATETIME)
    assert table.c.updated_at.type.fsp == 6
    assert not table.c.updated_at.nullable


def test_account_model_constraints_and_mysql_options() -> None:
    table = Account.__table__

    unique_constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_accounts_email" in unique_constraints
    assert "ck_accounts_display_name_not_blank" in {
        constraint.name for constraint in table.constraints
    }
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    assert table.dialect_options["mysql"]["collate"] == "utf8mb4_0900_ai_ci"
