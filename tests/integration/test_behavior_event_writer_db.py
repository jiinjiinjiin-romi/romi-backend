import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType
from app.core.enums import (
    BehaviorEventStatus,
    BehaviorResolutionReason,
    BehaviorType,
    DrivingState,
    LocationSource,
)
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, BehaviorEvent, DriverProfile, DrivingSession
from app.policies.sliding_window_behavior_policy import (
    BehaviorTransition,
    BehaviorTransitionType,
)
from app.realtime.session_runtime import LocationRuntimeUpdate, SessionRuntimeRegistry
from app.services.behavior_event_service import BehaviorEventService, BehaviorEventWriteStatus

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)

BASE_TIME = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)


def make_transition(
    transition_type: BehaviorTransitionType = BehaviorTransitionType.STARTED,
    *,
    event_behavior_type: BehaviorType | None = BehaviorType.PHONE_USE,
    captured_at: datetime = BASE_TIME + timedelta(seconds=2),
) -> BehaviorTransition:
    return BehaviorTransition(
        transition_type=transition_type,
        detection_behavior_type=(
            DetectionBehaviorType.NORMAL
            if transition_type == BehaviorTransitionType.CLEARED
            else DetectionBehaviorType.PHONE_USE
        ),
        event_behavior_type=event_behavior_type,
        dominant_model_action_type=(
            ModelActionType.SAFE_DRIVING
            if transition_type == BehaviorTransitionType.CLEARED
            else ModelActionType.WRITING_MSG_RIGHT
        ),
        dominant_model_class_code="AC5",
        dominant_model_class_label="writing_msg_right",
        confidence=0.85,
        average_confidence=0.85,
        maximum_confidence=0.91,
        hit_ratio=0.6,
        hit_count=3,
        sample_count=5,
        started_at=BASE_TIME,
        last_seen_at=captured_at,
        frame_id="frame-3",
        captured_at=captured_at,
    )


async def create_active_session() -> tuple[str, str]:
    account = Account(id=str(uuid4()), email=f"behavior-writer-{uuid4().hex}@example.com")
    profile_id = str(uuid4())
    session_id = str(uuid4())
    profile = DriverProfile(
        id=profile_id,
        account_id=account.id,
        display_name="Behavior Writer",
        agent_call_name="Behavior Writer",
    )
    driving_session = DrivingSession(
        id=session_id,
        profile_id=profile_id,
        status="ACTIVE",
        started_at=BASE_TIME.replace(tzinfo=None) - timedelta(minutes=1),
        model_version="vit-test",
        policy_version="policy-test",
    )

    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.flush()
        session.add(profile)
        await session.flush()
        session.add(driving_session)
        await session.commit()

    return account.id, session_id


async def delete_test_account(account_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Account).where(Account.id == account_id))
        await session.commit()


async def prepare_runtime(session_id: str) -> tuple[SessionRuntimeRegistry, int]:
    registry = SessionRuntimeRegistry()
    runtime = await registry.get_or_create(session_id, connected_at=BASE_TIME)
    generation = await registry.prepare_connection(
        session_id,
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    runtime.active_event_behavior_type = BehaviorType.PHONE_USE
    await registry.apply_location_update(
        session_id,
        LocationRuntimeUpdate(
            latitude=37.5501,
            longitude=127.0734,
            speed_kph=35.2,
            accuracy_meters=4.0,
            source=LocationSource.GPS,
            driving_state=DrivingState.MOVING,
            occurred_at=BASE_TIME,
            received_at=BASE_TIME,
        ),
    )
    return registry, generation


async def count_behavior_events(session_id: str) -> int:
    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BehaviorEvent)
            .where(BehaviorEvent.session_id == session_id)
        )
        return int(count or 0)


async def get_behavior_event(event_id: str) -> BehaviorEvent:
    async with AsyncSessionLocal() as session:
        event = await session.get(BehaviorEvent, event_id)
        assert event is not None
        return event


async def test_behavior_event_writer_inserts_reuses_and_clears_open_event() -> None:
    account_id, session_id = await create_active_session()
    registry, generation = await prepare_runtime(session_id)
    service = BehaviorEventService(runtime_registry=registry)

    try:
        started = await service.handle_transition(
            session_id=session_id,
            connection_generation=generation,
            transition=make_transition(),
        )
        duplicate_started = await service.handle_transition(
            session_id=session_id,
            connection_generation=generation,
            transition=make_transition(captured_at=BASE_TIME + timedelta(seconds=3)),
        )
        ignored_normal = await service.handle_transition(
            session_id=session_id,
            connection_generation=generation,
            transition=make_transition(event_behavior_type=None),
        )
        cleared = await service.handle_transition(
            session_id=session_id,
            connection_generation=generation,
            transition=make_transition(
                BehaviorTransitionType.CLEARED,
                event_behavior_type=None,
                captured_at=BASE_TIME + timedelta(seconds=5),
            ),
            previous_active_behavior_event_id=started.behavior_event_id,
            previous_active_event_behavior_type=BehaviorType.PHONE_USE,
        )
        event = await get_behavior_event(started.behavior_event_id or "")

        assert started.status == BehaviorEventWriteStatus.STARTED_CREATED
        assert started.behavior_event_id is not None
        assert duplicate_started.status == BehaviorEventWriteStatus.STARTED_REUSED
        assert duplicate_started.behavior_event_id == started.behavior_event_id
        assert ignored_normal.status == BehaviorEventWriteStatus.IGNORED
        assert cleared.status == BehaviorEventWriteStatus.CLEARED
        assert await count_behavior_events(session_id) == 1
        assert event.behavior_type == BehaviorType.PHONE_USE.value
        assert event.status == BehaviorEventStatus.RESOLVED.value
        assert event.ended_at == (BASE_TIME + timedelta(seconds=5)).replace(tzinfo=None)
        assert event.duration_ms == 5000
        assert event.resolution_reason == BehaviorResolutionReason.BEHAVIOR_CORRECTED.value
        assert event.driving_state == DrivingState.MOVING.value
        assert float(event.speed_kph or 0) == 35.2
        assert float(event.latitude or 0) == 37.5501
        assert float(event.longitude or 0) == 127.0734
    finally:
        await delete_test_account(account_id)
        await dispose_engine()
