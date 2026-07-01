import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import DrivingState, LocationSource
from app.realtime.session_runtime import (
    LocationRuntimeApplyStatus,
    LocationRuntimeUpdate,
    SessionRuntimeRegistry,
)


@pytest.mark.asyncio
async def test_runtime_initial_fields_and_touch_methods() -> None:
    registry = SessionRuntimeRegistry()
    connected_at = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)

    runtime = await registry.get_or_create("session-1", connected_at=connected_at)

    assert runtime.session_id == "session-1"
    assert runtime.connected_at == connected_at
    assert runtime.last_message_at == connected_at
    assert runtime.last_heartbeat_at == connected_at
    assert runtime.current_latitude is None
    assert runtime.current_longitude is None
    assert runtime.current_speed_kph is None
    assert runtime.current_accuracy_meters is None
    assert runtime.current_location_source is None
    assert runtime.driving_state == DrivingState.UNKNOWN
    assert runtime.last_location_occurred_at is None
    assert runtime.last_location_persisted_at is None
    assert runtime.last_location_persisted_monotonic is None
    assert runtime.active_behavior_event_id is None
    assert runtime.current_intervention_id is None
    assert runtime.active_conversation_id is None
    assert registry.count == 1

    message_at = connected_at + timedelta(seconds=3)
    heartbeat_at = connected_at + timedelta(seconds=5)

    await registry.touch_message("session-1", message_at)
    assert runtime.last_message_at == message_at
    assert runtime.last_heartbeat_at == connected_at

    await registry.touch_heartbeat("session-1", heartbeat_at)
    assert runtime.last_message_at == heartbeat_at
    assert runtime.last_heartbeat_at == heartbeat_at


@pytest.mark.asyncio
async def test_runtime_applies_location_update_and_marks_persisted() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", connected_at=datetime(2026, 6, 28, 3, 10, tzinfo=UTC))
    occurred_at = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    received_at = occurred_at + timedelta(milliseconds=100)

    result = await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=37.5501,
            longitude=127.0734,
            speed_kph=32.4,
            accuracy_meters=8.2,
            source=LocationSource.GPS,
            driving_state=DrivingState.MOVING,
            occurred_at=occurred_at,
            received_at=received_at,
        ),
    )

    assert result.status == LocationRuntimeApplyStatus.APPLIED
    assert result.snapshot is not None
    assert result.snapshot.current_latitude == 37.5501
    assert result.snapshot.current_longitude == 127.0734
    assert result.snapshot.current_speed_kph == 32.4
    assert result.snapshot.current_accuracy_meters == 8.2
    assert result.snapshot.current_location_source == LocationSource.GPS
    assert result.snapshot.driving_state == DrivingState.MOVING
    assert result.snapshot.last_location_occurred_at == occurred_at

    persisted = await registry.mark_location_persisted(
        "session-1",
        occurred_at=occurred_at,
        monotonic_value=123.45,
    )

    assert persisted is not None
    assert persisted.last_location_persisted_at == occurred_at
    assert persisted.last_location_persisted_monotonic == 123.45


@pytest.mark.asyncio
async def test_runtime_ignores_stale_and_duplicate_location_updates() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", connected_at=datetime(2026, 6, 28, 3, 10, tzinfo=UTC))
    first_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    received_at = first_time + timedelta(milliseconds=100)

    first = await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=37.5501,
            longitude=127.0734,
            speed_kph=32.4,
            accuracy_meters=8.2,
            source=LocationSource.GPS,
            driving_state=DrivingState.MOVING,
            occurred_at=first_time,
            received_at=received_at,
        ),
    )
    duplicate = await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=38.0,
            longitude=128.0,
            speed_kph=0.0,
            accuracy_meters=9.0,
            source=LocationSource.GPS,
            driving_state=DrivingState.TEMPORARY_STOP,
            occurred_at=first_time,
            received_at=received_at + timedelta(seconds=1),
        ),
    )
    stale = await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=39.0,
            longitude=129.0,
            speed_kph=0.0,
            accuracy_meters=9.0,
            source=LocationSource.GPS,
            driving_state=DrivingState.TEMPORARY_STOP,
            occurred_at=first_time - timedelta(seconds=1),
            received_at=received_at + timedelta(seconds=2),
        ),
    )

    snapshot = await registry.get_location_snapshot("session-1")

    assert first.status == LocationRuntimeApplyStatus.APPLIED
    assert duplicate.status == LocationRuntimeApplyStatus.DUPLICATE
    assert stale.status == LocationRuntimeApplyStatus.STALE
    assert snapshot is not None
    assert snapshot.current_latitude == 37.5501
    assert snapshot.current_longitude == 127.0734
    assert snapshot.last_location_occurred_at == first_time


@pytest.mark.asyncio
async def test_registry_reuses_removes_and_clears_runtime() -> None:
    registry = SessionRuntimeRegistry()

    first = await registry.get_or_create("session-1")
    second = await registry.get_or_create("session-1")

    assert first is second
    assert registry.count == 1
    assert await registry.get("session-1") is first

    assert await registry.remove("missing") is False
    assert await registry.remove("session-1") is True
    assert registry.count == 0

    await registry.get_or_create("session-1")
    await registry.get_or_create("session-2")
    assert registry.count == 2
    await registry.clear()
    assert registry.count == 0


@pytest.mark.asyncio
async def test_concurrent_get_or_create_creates_one_runtime() -> None:
    registry = SessionRuntimeRegistry()

    runtimes = await asyncio.gather(
        *(registry.get_or_create("session-1") for _ in range(20)),
    )

    assert len({id(runtime) for runtime in runtimes}) == 1
    assert registry.count == 1
