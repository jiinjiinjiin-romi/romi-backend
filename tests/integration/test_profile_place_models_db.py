import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, DriverProfile, SavedPlace, SearchHistory

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


def make_account(email_prefix: str = "profile-model") -> Account:
    return Account(id=str(uuid4()), email=f"{email_prefix}-{uuid4().hex}@example.com")


def make_profile(account_id: str, display_name: str = "Test Driver") -> DriverProfile:
    return DriverProfile(
        account_id=account_id,
        display_name=display_name,
        agent_call_name=display_name,
    )


def make_place(
    profile_id: str,
    place_type: str = "HOME",
    label: str = "Home",
    provider_place_id: str | None = None,
    latitude: float = 37.5501,
    longitude: float = 127.0734,
) -> SavedPlace:
    return SavedPlace(
        profile_id=profile_id,
        place_type=place_type,
        label=label,
        provider_place_id=provider_place_id,
        address=f"{label} address",
        latitude=latitude,
        longitude=longitude,
    )


def make_history(
    profile_id: str,
    query: str = "coffee",
    latitude: float | None = 37.5501,
    longitude: float | None = 127.0734,
) -> SearchHistory:
    return SearchHistory(
        profile_id=profile_id,
        query=query,
        provider_place_id=str(uuid4()),
        place_name="Coffee Place",
        address="Coffee Place address",
        latitude=latitude,
        longitude=longitude,
    )


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


async def assert_integrity_error(instance: object) -> None:
    async with AsyncSessionLocal() as session:
        session.add(instance)
        with pytest.raises((IntegrityError, OperationalError)):
            await session.commit()
        await session.rollback()


async def create_account_and_profile() -> tuple[str, str]:
    account = make_account()
    profile = make_profile(account.id)

    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.flush()
        session.add(profile)
        await session.commit()

    return account.id, profile.id


async def test_profile_place_and_search_history_can_be_created_under_test_account() -> None:
    account_id = str(uuid4())
    profile_id: str | None = None

    try:
        async with AsyncSessionLocal() as session:
            account = Account(id=account_id, email=f"profile-create-{uuid4().hex}@example.com")
            session.add(account)
            await session.flush()

            profile = make_profile(account_id)
            session.add(profile)
            await session.flush()
            profile_id = profile.id

            place = make_place(profile_id, provider_place_id=str(uuid4()))
            history = make_history(profile_id)
            session.add_all([place, history])
            await session.commit()

        async with AsyncSessionLocal() as session:
            profile_count = await session.scalar(
                select(func.count())
                .select_from(DriverProfile)
                .where(DriverProfile.id == profile_id)
            )
            place_count = await session.scalar(
                select(func.count())
                .select_from(SavedPlace)
                .where(SavedPlace.profile_id == profile_id)
            )
            history_count = await session.scalar(
                select(func.count())
                .select_from(SearchHistory)
                .where(SearchHistory.profile_id == profile_id)
            )

        assert profile_count == 1
        assert place_count == 1
        assert history_count == 1
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_saved_place_fixed_type_generated_column_and_unique_rules() -> None:
    account_id, profile_id = await create_account_and_profile()

    try:
        async with AsyncSessionLocal() as session:
            session.add(make_place(profile_id, "HOME", "Home", str(uuid4())))
            await session.commit()

        await assert_integrity_error(make_place(profile_id, "HOME", "Another Home", str(uuid4())))

        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    make_place(profile_id, "WORK", "Work", str(uuid4())),
                    make_place(profile_id, "SCHOOL", "School", str(uuid4())),
                    make_place(profile_id, "FAVORITE", "Favorite 1", str(uuid4())),
                    make_place(profile_id, "FAVORITE", "Favorite 2", str(uuid4())),
                ]
            )
            await session.commit()

            fixed_values = (
                await session.execute(
                    text(
                        "SELECT place_type, fixed_place_type "
                        "FROM saved_places "
                        "WHERE profile_id = :profile_id "
                        "ORDER BY place_type, label"
                    ),
                    {"profile_id": profile_id},
                )
            ).all()

        assert ("HOME", "HOME") in fixed_values
        assert ("WORK", "WORK") in fixed_values
        assert ("SCHOOL", "SCHOOL") in fixed_values
        assert fixed_values.count(("FAVORITE", None)) == 2
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_saved_place_duplicate_provider_place_fails() -> None:
    account_id, profile_id = await create_account_and_profile()
    provider_place_id = str(uuid4())

    try:
        async with AsyncSessionLocal() as session:
            session.add(make_place(profile_id, "FAVORITE", "Favorite", provider_place_id))
            await session.commit()

        await assert_integrity_error(
            make_place(profile_id, "FAVORITE", "Favorite Duplicate", provider_place_id)
        )
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_coordinate_and_profile_setting_checks_are_enforced() -> None:
    account_id, profile_id = await create_account_and_profile()

    try:
        await assert_integrity_error(
            make_place(profile_id, "FAVORITE", "Bad Latitude", str(uuid4()), latitude=91.0)
        )
        await assert_integrity_error(
            make_place(profile_id, "FAVORITE", "Bad Longitude", str(uuid4()), longitude=181.0)
        )
        await assert_integrity_error(make_history(profile_id, latitude=37.0, longitude=None))
        await assert_integrity_error(
            DriverProfile(
                account_id=account_id,
                display_name="Bad Speed",
                agent_call_name="Bad Speed",
                tts_speed=2.01,
            )
        )
        await assert_integrity_error(
            DriverProfile(
                account_id=account_id,
                display_name="Bad Volume",
                agent_call_name="Bad Volume",
                guidance_volume=101,
            )
        )
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_profile_delete_cascades_to_saved_places_and_search_histories() -> None:
    account_id, profile_id = await create_account_and_profile()

    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    make_place(profile_id, "HOME", "Home", str(uuid4())),
                    make_history(profile_id),
                ]
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            await session.execute(delete(DriverProfile).where(DriverProfile.id == profile_id))
            await session.commit()

        async with AsyncSessionLocal() as session:
            profile_count = await session.scalar(
                select(func.count())
                .select_from(DriverProfile)
                .where(DriverProfile.id == profile_id)
            )
            place_count = await session.scalar(
                select(func.count())
                .select_from(SavedPlace)
                .where(SavedPlace.profile_id == profile_id)
            )
            history_count = await session.scalar(
                select(func.count())
                .select_from(SearchHistory)
                .where(SearchHistory.profile_id == profile_id)
            )

        assert profile_count == 0
        assert place_count == 0
        assert history_count == 0
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_account_delete_cascades_to_profile_tree_without_touching_admin() -> None:
    account_id, profile_id = await create_account_and_profile()

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                make_place(profile_id, "HOME", "Home", str(uuid4())),
                make_history(profile_id),
            ]
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Account).where(Account.id == account_id))
        await session.commit()

    async with AsyncSessionLocal() as session:
        profile_count = await session.scalar(
            select(func.count()).select_from(DriverProfile).where(DriverProfile.id == profile_id)
        )
        place_count = await session.scalar(
            select(func.count()).select_from(SavedPlace).where(SavedPlace.profile_id == profile_id)
        )
        history_count = await session.scalar(
            select(func.count())
            .select_from(SearchHistory)
            .where(SearchHistory.profile_id == profile_id)
        )
        admin_count = await session.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.id == "00000000-0000-0000-0000-000000000001")
        )

    assert profile_count == 0
    assert place_count == 0
    assert history_count == 0
    assert admin_count == 1
    await dispose_engine()
