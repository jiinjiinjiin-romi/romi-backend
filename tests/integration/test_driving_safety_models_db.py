import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.enums import BehaviorType
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import (
    Account,
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
    LocationSample,
)
from app.repositories.location_sample_repository import LocationSampleRepository

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


def now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def make_account() -> Account:
    return Account(id=str(uuid4()), email=f"driving-safety-{uuid4().hex}@example.com")


def make_profile(account_id: str, display_name: str = "Safety Driver") -> DriverProfile:
    return DriverProfile(
        account_id=account_id,
        display_name=display_name,
        agent_call_name=display_name,
    )


def make_session(
    profile_id: str,
    status: str = "ACTIVE",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    end_reason: str | None = None,
) -> DrivingSession:
    return DrivingSession(
        profile_id=profile_id,
        started_at=started_at or now_utc_naive(),
        ended_at=ended_at,
        status=status,
        end_reason=end_reason,
        model_version="vit-test",
        policy_version="policy-test",
    )


def make_location_sample(
    session_id: str,
    recorded_at: datetime | None = None,
    latitude: float = 37.5501,
    longitude: float = 127.0734,
) -> LocationSample:
    return LocationSample(
        session_id=session_id,
        latitude=latitude,
        longitude=longitude,
        speed_kph=Decimal("35.50"),
        driving_state="MOVING",
        accuracy_meters=Decimal("5.20"),
        recorded_at=recorded_at or now_utc_naive(),
    )


def make_behavior_event(
    session_id: str,
    behavior_type: str = "PHONE_USE",
    average_confidence: Decimal = Decimal("0.8000"),
    maximum_confidence: Decimal = Decimal("0.9000"),
    risk_level: int = 2,
) -> BehaviorEvent:
    return BehaviorEvent(
        session_id=session_id,
        behavior_type=behavior_type,
        started_at=now_utc_naive(),
        average_confidence=average_confidence,
        maximum_confidence=maximum_confidence,
        driving_state="MOVING",
        speed_kph=Decimal("35.50"),
        risk_level=risk_level,
    )


def make_intervention(behavior_event_id: str, level: int = 1) -> Intervention:
    return Intervention(
        behavior_event_id=behavior_event_id,
        level=level,
        intervention_type="WARNING",
        speech_text="Please watch the road.",
        ui_text="Phone use detected.",
        channels_json=["VOICE", "VISUAL"],
        next_check_after_ms=3000,
    )


def make_driver_response(intervention_id: str, response_type: str = "BEHAVIOR_CORRECTED"):
    return DriverResponse(
        intervention_id=intervention_id,
        response_type=response_type,
        behavior_corrected=True,
        response_latency_ms=2500,
    )


async def assert_integrity_error(instance: object) -> None:
    async with AsyncSessionLocal() as session:
        session.add(instance)
        with pytest.raises((IntegrityError, OperationalError)):
            await session.commit()
        await session.rollback()


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


async def create_account_and_profiles(count: int = 1) -> tuple[str, list[str]]:
    account = make_account()
    profiles = [make_profile(account.id, f"Safety Driver {index}") for index in range(count)]

    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.flush()
        session.add_all(profiles)
        await session.commit()

    return account.id, [profile.id for profile in profiles]


async def create_active_session(profile_id: str) -> str:
    driving_session = make_session(profile_id)

    async with AsyncSessionLocal() as session:
        session.add(driving_session)
        await session.commit()

    return driving_session.id


async def test_one_active_session_per_profile_and_reactivation_after_completion() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    profile_id = profile_ids[0]

    try:
        first_session_id = await create_active_session(profile_id)
        await assert_integrity_error(make_session(profile_id))

        completed_at = now_utc_naive() + timedelta(minutes=5)
        async with AsyncSessionLocal() as session:
            driving_session = await session.get(DrivingSession, first_session_id)
            assert driving_session is not None
            driving_session.status = "COMPLETED"
            driving_session.ended_at = completed_at
            driving_session.end_reason = "USER_REQUEST"
            await session.commit()

        second_session_id = await create_active_session(profile_id)

        async with AsyncSessionLocal() as session:
            active_count = await session.scalar(
                select(func.count())
                .select_from(DrivingSession)
                .where(DrivingSession.profile_id == profile_id, DrivingSession.status == "ACTIVE")
            )

        assert first_session_id != second_session_id
        assert active_count == 1
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_different_profiles_can_each_have_active_session() -> None:
    account_id, profile_ids = await create_account_and_profiles(count=2)

    try:
        first_session_id = await create_active_session(profile_ids[0])
        second_session_id = await create_active_session(profile_ids[1])

        assert first_session_id != second_session_id
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_driving_session_status_coordinate_and_score_checks_are_enforced() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    profile_id = profile_ids[0]

    try:
        await assert_integrity_error(
            make_session(
                profile_id,
                status="ACTIVE",
                ended_at=now_utc_naive() + timedelta(minutes=1),
                end_reason="USER_REQUEST",
            )
        )
        await assert_integrity_error(make_session(profile_id, status="COMPLETED"))
        await assert_integrity_error(
            DrivingSession(
                profile_id=profile_id,
                status="ACTIVE",
                started_at=now_utc_naive(),
                start_latitude=37.0,
                model_version="vit-test",
                policy_version="policy-test",
            )
        )
        await assert_integrity_error(
            DrivingSession(
                profile_id=profile_id,
                status="ACTIVE",
                started_at=now_utc_naive(),
                safety_score=101,
                model_version="vit-test",
                policy_version="policy-test",
            )
        )
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_location_sample_unique_and_coordinate_checks_are_enforced() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    session_id = await create_active_session(profile_ids[0])
    recorded_at = now_utc_naive()

    try:
        async with AsyncSessionLocal() as session:
            session.add(make_location_sample(session_id, recorded_at=recorded_at))
            await session.commit()

        await assert_integrity_error(make_location_sample(session_id, recorded_at=recorded_at))
        await assert_integrity_error(make_location_sample(session_id, latitude=91.0))
        await assert_integrity_error(make_location_sample(session_id, longitude=181.0))
        await assert_integrity_error(
            LocationSample(
                session_id=session_id,
                latitude=37.0,
                longitude=127.0,
                driving_state="FLYING",
                recorded_at=now_utc_naive() + timedelta(seconds=5),
            )
        )
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_location_sample_repository_add_exists_and_allows_same_time_other_session() -> None:
    account_id, profile_ids = await create_account_and_profiles(count=2)
    first_session_id = await create_active_session(profile_ids[0])
    second_session_id = await create_active_session(profile_ids[1])
    recorded_at = now_utc_naive()

    try:
        async with AsyncSessionLocal() as session:
            repository = LocationSampleRepository(session)
            repository.add(make_location_sample(first_session_id, recorded_at=recorded_at))
            repository.add(
                make_location_sample(
                    second_session_id,
                    recorded_at=recorded_at,
                    latitude=37.6,
                    longitude=127.1,
                )
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            repository = LocationSampleRepository(session)

            assert await repository.exists_at(
                session_id=first_session_id,
                recorded_at=recorded_at,
            )
            assert await repository.exists_at(
                session_id=second_session_id,
                recorded_at=recorded_at,
            )
            assert not await repository.exists_at(
                session_id=first_session_id,
                recorded_at=recorded_at + timedelta(seconds=1),
            )
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_behavior_event_checks_are_enforced() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    session_id = await create_active_session(profile_ids[0])

    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    make_behavior_event(session_id, behavior_type=behavior_type.value)
                    for behavior_type in BehaviorType
                ]
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            allowed_count = await session.scalar(
                select(func.count())
                .select_from(BehaviorEvent)
                .where(BehaviorEvent.session_id == session_id)
            )

        assert allowed_count == len(BehaviorType)
        await assert_integrity_error(make_behavior_event(session_id, behavior_type="NORMAL"))
        await assert_integrity_error(
            make_behavior_event(session_id, average_confidence=Decimal("1.1000"))
        )
        await assert_integrity_error(
            make_behavior_event(
                session_id,
                average_confidence=Decimal("0.9000"),
                maximum_confidence=Decimal("0.8000"),
            )
        )
        await assert_integrity_error(make_behavior_event(session_id, risk_level=4))
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_intervention_and_driver_response_checks_are_enforced() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    session_id = await create_active_session(profile_ids[0])

    try:
        async with AsyncSessionLocal() as session:
            event = make_behavior_event(session_id)
            session.add(event)
            await session.commit()
            behavior_event_id = event.id

        await assert_integrity_error(make_intervention(behavior_event_id, level=4))

        async with AsyncSessionLocal() as session:
            intervention = make_intervention(behavior_event_id)
            session.add(intervention)
            await session.commit()
            intervention_id = intervention.id

        await assert_integrity_error(make_driver_response(intervention_id, response_type="MAYBE"))
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_driving_session_delete_cascades_to_safety_tree() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    session_id = await create_active_session(profile_ids[0])

    try:
        async with AsyncSessionLocal() as session:
            location_sample = make_location_sample(session_id)
            event = make_behavior_event(session_id)
            session.add_all([location_sample, event])
            await session.flush()
            intervention = make_intervention(event.id)
            session.add(intervention)
            await session.flush()
            response = make_driver_response(intervention.id)
            session.add(response)
            await session.commit()
            event_id = event.id
            intervention_id = intervention.id

        async with AsyncSessionLocal() as session:
            await session.execute(delete(DrivingSession).where(DrivingSession.id == session_id))
            await session.commit()

        async with AsyncSessionLocal() as session:
            location_count = await session.scalar(
                select(func.count())
                .select_from(LocationSample)
                .where(LocationSample.session_id == session_id)
            )
            event_count = await session.scalar(
                select(func.count())
                .select_from(BehaviorEvent)
                .where(BehaviorEvent.session_id == session_id)
            )
            intervention_count = await session.scalar(
                select(func.count())
                .select_from(Intervention)
                .where(Intervention.behavior_event_id == event_id)
            )
            response_count = await session.scalar(
                select(func.count())
                .select_from(DriverResponse)
                .where(DriverResponse.intervention_id == intervention_id)
            )

        assert location_count == 0
        assert event_count == 0
        assert intervention_count == 0
        assert response_count == 0
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()


async def test_driver_profile_delete_cascades_to_driving_and_safety_tree() -> None:
    account_id, profile_ids = await create_account_and_profiles()
    profile_id = profile_ids[0]
    session_id = await create_active_session(profile_id)

    try:
        async with AsyncSessionLocal() as session:
            location_sample = make_location_sample(session_id)
            event = make_behavior_event(session_id)
            session.add_all([location_sample, event])
            await session.flush()
            intervention = make_intervention(event.id)
            session.add(intervention)
            await session.flush()
            response = make_driver_response(intervention.id)
            session.add(response)
            await session.commit()
            event_id = event.id
            intervention_id = intervention.id

        async with AsyncSessionLocal() as session:
            await session.execute(delete(DriverProfile).where(DriverProfile.id == profile_id))
            await session.commit()

        async with AsyncSessionLocal() as session:
            session_count = await session.scalar(
                select(func.count())
                .select_from(DrivingSession)
                .where(DrivingSession.profile_id == profile_id)
            )
            location_count = await session.scalar(
                select(func.count())
                .select_from(LocationSample)
                .where(LocationSample.session_id == session_id)
            )
            event_count = await session.scalar(
                select(func.count())
                .select_from(BehaviorEvent)
                .where(BehaviorEvent.session_id == session_id)
            )
            intervention_count = await session.scalar(
                select(func.count())
                .select_from(Intervention)
                .where(Intervention.behavior_event_id == event_id)
            )
            response_count = await session.scalar(
                select(func.count())
                .select_from(DriverResponse)
                .where(DriverResponse.intervention_id == intervention_id)
            )

        assert session_count == 0
        assert location_count == 0
        assert event_count == 0
        assert intervention_count == 0
        assert response_count == 0
    finally:
        await delete_test_accounts(account_id)
        await dispose_engine()
