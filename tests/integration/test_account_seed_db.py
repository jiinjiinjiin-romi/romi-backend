import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.core.config import Settings
from app.db.seed import SeedError, run_seed
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


def make_test_settings(account_id: str, email: str | None) -> Settings:
    return Settings(default_admin_account_id=account_id, default_admin_email=email)


async def delete_test_accounts(*account_ids: str, emails: str | list[str] | None = None) -> None:
    email_values = [emails] if isinstance(emails, str) else (emails or [])

    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        if email_values:
            await session.execute(delete(Account).where(Account.email.in_(email_values)))
        await session.commit()


async def test_accounts_table_matches_mysql_spec() -> None:
    async with AsyncSessionLocal() as session:
        table_result = await session.execute(text("SHOW CREATE TABLE accounts"))
        create_sql = table_result.one()[1].lower()
        tables_result = await session.execute(text("SHOW TABLES"))
        tables = set(tables_result.scalars().all())

    assert "`id` char(36)" in create_sql
    assert "`email` varchar(320)" in create_sql
    assert "`created_at` datetime(6) not null" in create_sql
    assert "`updated_at` datetime(6) not null" in create_sql
    assert "default current_timestamp(6)" in create_sql
    assert "on update current_timestamp(6)" in create_sql
    assert "unique key `uq_accounts_email`" in create_sql
    assert "engine=innodb" in create_sql
    assert "default charset=utf8mb4" in create_sql
    assert "collate=utf8mb4_0900_ai_ci" in create_sql
    assert "accounts" in tables
    assert "driver_profiles" in tables
    assert "saved_places" in tables
    assert "search_histories" in tables
    assert "driving_sessions" not in tables

    await dispose_engine()


async def test_seed_creates_updates_and_remains_idempotent_in_database() -> None:
    account_id = str(uuid4())
    first_email = f"seed-{uuid4().hex}@example.com"
    second_email = f"seed-{uuid4().hex}@example.com"

    try:
        first_result = await run_seed(make_test_settings(account_id, first_email))
        second_result = await run_seed(make_test_settings(account_id, first_email))
        update_result = await run_seed(make_test_settings(account_id, second_email))

        async with AsyncSessionLocal() as session:
            account = await session.get(Account, account_id)
            count = await session.scalar(
                select(func.count()).select_from(Account).where(Account.id == account_id)
            )

        assert first_result == "created"
        assert second_result == "unchanged"
        assert update_result == "updated"
        assert count == 1
        assert account is not None
        assert account.email == second_email
    finally:
        await delete_test_accounts(account_id, emails=[first_email, second_email])
        await dispose_engine()


async def test_seed_fails_without_changing_pk_when_email_belongs_to_another_id() -> None:
    existing_id = str(uuid4())
    requested_id = str(uuid4())
    email = f"seed-conflict-{uuid4().hex}@example.com"

    try:
        async with AsyncSessionLocal() as session:
            session.add(Account(id=existing_id, email=email))
            await session.commit()

        with pytest.raises(SeedError):
            await run_seed(make_test_settings(requested_id, email))

        async with AsyncSessionLocal() as session:
            existing_account = await session.get(Account, existing_id)
            requested_account = await session.get(Account, requested_id)

        assert existing_account is not None
        assert existing_account.email == email
        assert requested_account is None
    finally:
        await delete_test_accounts(existing_id, requested_id, emails=email)
        await dispose_engine()
