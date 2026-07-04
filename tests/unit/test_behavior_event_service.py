from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType
from app.core.enums import (
    BehaviorEventStatus,
    BehaviorResolutionReason,
    BehaviorType,
    DrivingState,
    LocationSource,
)
from app.models import BehaviorEvent
from app.policies.sliding_window_behavior_policy import (
    BehaviorTransition,
    BehaviorTransitionType,
)
from app.realtime.session_runtime import (
    LocationRuntimeUpdate,
    SessionRuntimeRegistry,
)
from app.repositories.behavior_event_repository import BehaviorEventRepository
from app.services.behavior_event_service import (
    BehaviorEventService,
    BehaviorEventWriteStatus,
)

BASE_TIME = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeBehaviorEventRepository:
    def __init__(self, open_events: list[BehaviorEvent] | None = None) -> None:
        self.open_events = open_events or []
        self.added_events: list[BehaviorEvent] = []

    async def get_open_by_id_for_update(self, event_id: str) -> BehaviorEvent | None:
        return next(
            (
                event
                for event in self.open_events
                if event.id == event_id and event.status == BehaviorEventStatus.ACTIVE.value
            ),
            None,
        )

    async def get_open_by_session_and_type_for_update(
        self,
        *,
        session_id: str,
        behavior_type: str,
    ) -> BehaviorEvent | None:
        return next(
            (
                event
                for event in reversed(self.open_events)
                if event.session_id == session_id
                and event.behavior_type == behavior_type
                and event.status == BehaviorEventStatus.ACTIVE.value
            ),
            None,
        )

    async def list_open_by_session_for_update(self, session_id: str) -> list[BehaviorEvent]:
        return [
            event
            for event in self.open_events
            if event.session_id == session_id and event.status == BehaviorEventStatus.ACTIVE.value
        ]

    def add(self, event: BehaviorEvent) -> None:
        self.added_events.append(event)
        self.open_events.append(event)

    def close(
        self,
        event: BehaviorEvent,
        *,
        ended_at: datetime,
        resolution_reason: BehaviorResolutionReason,
    ) -> None:
        BehaviorEventRepository.close(
            event,
            ended_at=ended_at,
            resolution_reason=resolution_reason,
        )


class FailingBehaviorEventRepository(FakeBehaviorEventRepository):
    async def list_open_by_session_for_update(self, session_id: str) -> list[BehaviorEvent]:
        raise RuntimeError("repository failed")


async def prepare_registry() -> tuple[SessionRuntimeRegistry, int]:
    registry = SessionRuntimeRegistry()
    runtime = await registry.get_or_create("session-1", connected_at=BASE_TIME)
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    runtime.active_event_behavior_type = BehaviorType.PHONE_USE
    runtime.active_behavior_started_at = BASE_TIME
    await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=37.5501,
            longitude=127.0734,
            speed_kph=42.3,
            accuracy_meters=5.0,
            source=LocationSource.GPS,
            driving_state=DrivingState.MOVING,
            occurred_at=BASE_TIME,
            received_at=BASE_TIME,
        ),
    )
    return registry, generation


def make_service(
    registry: SessionRuntimeRegistry,
    *,
    fake_session: FakeSession,
    fake_repository: FakeBehaviorEventRepository,
) -> BehaviorEventService:
    return BehaviorEventService(
        runtime_registry=registry,
        session_factory=lambda: FakeSessionContext(fake_session),
        repository_factory=lambda _: fake_repository,
    )


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


def active_event(
    *,
    event_id: str = "event-1",
    behavior_type: BehaviorType = BehaviorType.PHONE_USE,
    started_at: datetime | None = None,
) -> BehaviorEvent:
    return BehaviorEvent(
        id=event_id,
        session_id="session-1",
        behavior_type=behavior_type.value,
        status=BehaviorEventStatus.ACTIVE.value,
        started_at=started_at or BASE_TIME.replace(tzinfo=None),
        average_confidence=Decimal("0.8000"),
        maximum_confidence=Decimal("0.9000"),
        driving_state=DrivingState.MOVING.value,
        risk_level=0,
    )


@pytest.mark.asyncio
async def test_started_transition_creates_behavior_event_and_records_runtime_id() -> None:
    registry, generation = await prepare_registry()
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository()
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(),
    )
    snapshot = await registry.get_behavior_snapshot("session-1")

    assert result.status == BehaviorEventWriteStatus.STARTED_CREATED
    assert result.behavior_type == BehaviorType.PHONE_USE
    assert len(fake_repository.added_events) == 1
    event = fake_repository.added_events[0]
    assert event.behavior_type == BehaviorType.PHONE_USE.value
    assert event.average_confidence == Decimal("0.8500")
    assert event.maximum_confidence == Decimal("0.9100")
    assert event.driving_state == DrivingState.MOVING.value
    assert event.speed_kph == Decimal("42.30")
    assert event.latitude == 37.5501
    assert event.longitude == 127.0734
    assert event.risk_level == 0
    assert fake_session.flush_count == 1
    assert fake_session.commit_count == 1
    assert fake_session.rollback_count == 0
    assert snapshot is not None
    assert snapshot.active_behavior_event_id == result.behavior_event_id


@pytest.mark.asyncio
async def test_normal_and_updated_transitions_do_not_write_behavior_events() -> None:
    registry, generation = await prepare_registry()
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository()
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    none_result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(BehaviorTransitionType.NONE, event_behavior_type=None),
    )
    updated_result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(BehaviorTransitionType.UPDATED),
    )
    invalid_started = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(event_behavior_type=None),
    )

    assert none_result.status == BehaviorEventWriteStatus.IGNORED
    assert updated_result.status == BehaviorEventWriteStatus.IGNORED
    assert invalid_started.status == BehaviorEventWriteStatus.IGNORED
    assert fake_repository.added_events == []
    assert fake_session.flush_count == 1
    assert fake_session.commit_count == 1
    assert fake_session.rollback_count == 0


@pytest.mark.asyncio
async def test_duplicate_started_reuses_existing_open_behavior_event() -> None:
    registry, generation = await prepare_registry()
    existing_event = active_event()
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository([existing_event])
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(),
    )

    assert result.status == BehaviorEventWriteStatus.STARTED_REUSED
    assert result.behavior_event_id == existing_event.id
    assert fake_repository.added_events == []
    assert existing_event.status == BehaviorEventStatus.ACTIVE.value
    assert fake_session.commit_count == 1


@pytest.mark.asyncio
async def test_started_closes_other_active_behavior_before_creating_new_event() -> None:
    registry, generation = await prepare_registry()
    other_event = active_event(event_id="event-old", behavior_type=BehaviorType.DROWSINESS)
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository([other_event])
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(),
    )

    assert result.status == BehaviorEventWriteStatus.STARTED_CREATED
    assert len(fake_repository.added_events) == 1
    assert other_event.status == BehaviorEventStatus.RESOLVED.value
    assert other_event.resolution_reason == BehaviorResolutionReason.BEHAVIOR_CORRECTED.value
    assert other_event.ended_at == BASE_TIME.replace(tzinfo=None)
    assert other_event.duration_ms == 0


@pytest.mark.asyncio
async def test_cleared_transition_closes_open_behavior_event_by_id() -> None:
    registry, generation = await prepare_registry()
    existing_event = active_event()
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository([existing_event])
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(BehaviorTransitionType.CLEARED, event_behavior_type=None),
        previous_active_behavior_event_id=existing_event.id,
        previous_active_event_behavior_type=BehaviorType.PHONE_USE,
    )

    assert result.status == BehaviorEventWriteStatus.CLEARED
    assert result.behavior_event_id == existing_event.id
    assert existing_event.status == BehaviorEventStatus.RESOLVED.value
    assert existing_event.ended_at == (BASE_TIME + timedelta(seconds=2)).replace(tzinfo=None)
    assert existing_event.duration_ms == 2000
    assert existing_event.resolution_reason == BehaviorResolutionReason.BEHAVIOR_CORRECTED.value
    assert fake_session.commit_count == 1


@pytest.mark.asyncio
async def test_cleared_transition_without_open_event_is_idempotent_noop() -> None:
    registry, generation = await prepare_registry()
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository()
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(BehaviorTransitionType.CLEARED, event_behavior_type=None),
        previous_active_event_behavior_type=BehaviorType.PHONE_USE,
    )

    assert result.status == BehaviorEventWriteStatus.OPEN_EVENT_NOT_FOUND
    assert fake_repository.added_events == []
    assert fake_session.commit_count == 1


@pytest.mark.asyncio
async def test_stale_generation_does_not_open_db_session() -> None:
    registry, generation = await prepare_registry()
    await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    fake_session = FakeSession()
    fake_repository = FakeBehaviorEventRepository()
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    result = await service.handle_transition(
        session_id="session-1",
        connection_generation=generation,
        transition=make_transition(),
    )

    assert result.status == BehaviorEventWriteStatus.STALE_GENERATION
    assert fake_session.flush_count == 0
    assert fake_session.commit_count == 0
    assert fake_repository.added_events == []


@pytest.mark.asyncio
async def test_service_rolls_back_and_surfaces_unexpected_repository_errors() -> None:
    registry, generation = await prepare_registry()
    fake_session = FakeSession()
    fake_repository = FailingBehaviorEventRepository()
    service = make_service(registry, fake_session=fake_session, fake_repository=fake_repository)

    with pytest.raises(RuntimeError, match="repository failed"):
        await service.handle_transition(
            session_id="session-1",
            connection_generation=generation,
            transition=make_transition(),
        )

    assert fake_session.rollback_count == 1
    assert fake_session.commit_count == 0


def test_repository_does_not_own_transaction_boundary() -> None:
    assert not hasattr(BehaviorEventRepository, "commit")
    assert not hasattr(BehaviorEventRepository, "rollback")
