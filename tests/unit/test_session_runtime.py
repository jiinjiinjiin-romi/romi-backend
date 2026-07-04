import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.driver_monitoring import DetectionResult, ModelActionType
from app.ai.prediction_mapper import metadata_from_class_index
from app.core.enums import BehaviorType, DrivingState, LocationSource
from app.policies.sliding_window_behavior_policy import BehaviorTransitionType
from app.realtime.session_runtime import (
    AcceptedFrame,
    BehaviorRuntimeObserveStatus,
    FrameAcceptStatus,
    FrameMetadata,
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
    assert runtime.connection_generation == 0
    assert runtime.last_detection_result is None
    assert runtime.last_inference_completed_at is None
    assert runtime.last_inference_latency_ms is None
    assert runtime.processed_frame_count == 0
    assert runtime.inference_failure_count == 0
    assert runtime.last_behavior_transition is None
    assert runtime.active_detection_behavior_type is None
    assert runtime.active_event_behavior_type is None
    assert runtime.dominant_model_action_type is None
    assert runtime.active_behavior_started_at is None
    assert runtime.last_behavior_seen_at is None
    assert runtime.last_behavior_transition_at is None
    assert runtime.behavior_policy.sample_count == 0
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


def accepted_frame(frame_id: str, captured_at: datetime | None = None) -> AcceptedFrame:
    timestamp = captured_at or datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    return AcceptedFrame(
        metadata=FrameMetadata(
            frame_id=frame_id,
            request_id="6a972e7b-2151-4997-acbd-19b01facb6b0",
            occurred_at=timestamp,
            format="JPEG",
            width=640,
            height=360,
            captured_at=timestamp,
        ),
        jpeg_bytes=b"\xff\xd8\xff\xd9",
        received_at=timestamp,
    )


def detection_result(frame_id: str = "frame-1") -> DetectionResult:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    metadata = metadata_from_class_index(0)
    return DetectionResult(
        session_id="session-1",
        frame_id=frame_id,
        model_action_type=metadata.action_type,
        model_class_code=metadata.class_code,
        model_class_label=metadata.class_label,
        behavior_type=metadata.detection_behavior_type,
        confidence=0.99,
        model_version="vit-dms-1.0.0",
        captured_at=timestamp,
        inference_started_at=timestamp,
        inference_completed_at=timestamp + timedelta(milliseconds=5),
        inference_latency_ms=5,
    )


def behavior_detection_result(action_type: ModelActionType, frame_number: int) -> DetectionResult:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    metadata = metadata_from_class_index(
        {
            ModelActionType.SAFE_DRIVING: 0,
            ModelActionType.WRITING_MSG_RIGHT: 4,
            ModelActionType.GPS_OPERATING: 3,
        }[action_type]
    )
    captured_at = timestamp + timedelta(milliseconds=frame_number)

    return DetectionResult(
        session_id="session-1",
        frame_id=f"frame-{frame_number}",
        model_action_type=action_type,
        model_class_code=metadata.class_code,
        model_class_label=metadata.class_label,
        behavior_type=metadata.detection_behavior_type,
        confidence=0.9,
        model_version="vit-dms-1.0.0",
        captured_at=captured_at,
        inference_started_at=captured_at,
        inference_completed_at=captured_at + timedelta(milliseconds=5),
        inference_latency_ms=5,
    )


@pytest.mark.asyncio
async def test_frame_queue_drops_oldest_and_keeps_latest_two() -> None:
    registry = SessionRuntimeRegistry()
    runtime = await registry.get_or_create("session-1", frame_queue_max_size=2)

    first = await registry.accept_frame("session-1", accepted_frame("frame-1"))
    second = await registry.accept_frame("session-1", accepted_frame("frame-2"))
    third = await registry.accept_frame("session-1", accepted_frame("frame-3"))
    frames = await registry.get_latest_frame_queue_snapshot("session-1")

    assert first.status == FrameAcceptStatus.ACCEPTED
    assert second.status == FrameAcceptStatus.ACCEPTED
    assert third.status == FrameAcceptStatus.ACCEPTED
    assert third.dropped_count == 1
    assert [frame.metadata.frame_id for frame in frames] == ["frame-2", "frame-3"]
    assert runtime.accepted_frame_count == 3
    assert runtime.dropped_frame_count == 1
    assert runtime.last_accepted_frame_id == "frame-3"


@pytest.mark.asyncio
async def test_wait_for_next_frame_awaits_signal_without_polling() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    waiter = asyncio.create_task(registry.wait_for_next_frame("session-1"))

    assert not waiter.done()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    frame = await asyncio.wait_for(waiter, timeout=1)

    assert frame is not None
    assert frame.metadata.frame_id == "frame-1"
    assert await registry.get_latest_frame_queue_snapshot("session-1") == ()


@pytest.mark.asyncio
async def test_wait_for_next_frame_returns_none_after_generation_changes() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    waiter = asyncio.create_task(
        registry.wait_for_next_frame("session-1", connection_generation=generation)
    )

    await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )

    assert await asyncio.wait_for(waiter, timeout=1) is None


@pytest.mark.asyncio
async def test_inference_result_and_failure_recording_are_generation_scoped() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation == 1

    stale_result = await registry.record_detection_result(
        "session-1",
        connection_generation=0,
        result=detection_result("old-frame"),
    )
    success = await registry.record_detection_result(
        "session-1",
        connection_generation=generation,
        result=detection_result("frame-1"),
    )
    failure = await registry.record_inference_failure(
        "session-1",
        connection_generation=generation,
    )
    stale_failure = await registry.record_inference_failure(
        "session-1",
        connection_generation=0,
    )
    snapshot = await registry.get_inference_snapshot("session-1")

    assert stale_result is False
    assert success is True
    assert failure is True
    assert stale_failure is False
    assert snapshot is not None
    assert snapshot.last_detection_result is not None
    assert snapshot.last_detection_result.frame_id == "frame-1"
    assert snapshot.processed_frame_count == 1
    assert snapshot.inference_failure_count == 1


@pytest.mark.asyncio
async def test_behavior_observation_records_started_and_cleared_state() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None

    for frame_number in [1, 2]:
        no_transition = await registry.observe_behavior_result(
            "session-1",
            connection_generation=generation,
            result=behavior_detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
        assert no_transition.status == BehaviorRuntimeObserveStatus.NO_TRANSITION

    started = await registry.observe_behavior_result(
        "session-1",
        connection_generation=generation,
        result=behavior_detection_result(ModelActionType.WRITING_MSG_RIGHT, 3),
    )
    started_snapshot = await registry.get_behavior_snapshot("session-1")

    assert started.status == BehaviorRuntimeObserveStatus.TRANSITION_RECORDED
    assert started.transition is not None
    assert started.transition.transition_type == BehaviorTransitionType.STARTED
    assert started_snapshot is not None
    assert started_snapshot.active_event_behavior_type is not None
    assert started_snapshot.dominant_model_action_type == ModelActionType.WRITING_MSG_RIGHT
    assert await registry.record_active_behavior_event(
        "session-1",
        connection_generation=generation,
        behavior_type=BehaviorType.PHONE_USE,
        event_id="event-1",
    )

    for frame_number in [4, 5]:
        await registry.observe_behavior_result(
            "session-1",
            connection_generation=generation,
            result=behavior_detection_result(ModelActionType.SAFE_DRIVING, frame_number),
        )
    cleared = await registry.observe_behavior_result(
        "session-1",
        connection_generation=generation,
        result=behavior_detection_result(ModelActionType.SAFE_DRIVING, 6),
    )
    cleared_snapshot = await registry.get_behavior_snapshot("session-1")

    assert cleared.status == BehaviorRuntimeObserveStatus.TRANSITION_RECORDED
    assert cleared.transition is not None
    assert cleared.transition.transition_type == BehaviorTransitionType.CLEARED
    assert cleared.previous_active_behavior_event_id == "event-1"
    assert cleared.previous_active_event_behavior_type == BehaviorType.PHONE_USE
    assert cleared_snapshot is not None
    assert cleared_snapshot.active_detection_behavior_type is None
    assert cleared_snapshot.active_event_behavior_type is None
    assert cleared_snapshot.active_behavior_event_id is None
    assert cleared_snapshot.dominant_model_action_type is None


@pytest.mark.asyncio
async def test_behavior_observation_is_generation_scoped() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    new_generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )

    stale = await registry.observe_behavior_result(
        "session-1",
        connection_generation=generation,
        result=behavior_detection_result(ModelActionType.WRITING_MSG_RIGHT, 1),
    )
    snapshot = await registry.get_behavior_snapshot("session-1")

    assert new_generation == generation + 1
    assert stale.status == BehaviorRuntimeObserveStatus.STALE_GENERATION
    assert snapshot is not None
    assert snapshot.policy_sample_count == 0
    assert snapshot.active_event_behavior_type is None


@pytest.mark.asyncio
async def test_behavior_event_id_updates_are_generation_scoped() -> None:
    registry = SessionRuntimeRegistry()
    runtime = await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    runtime.active_event_behavior_type = BehaviorType.PHONE_USE

    recorded = await registry.record_active_behavior_event(
        "session-1",
        connection_generation=generation,
        behavior_type=BehaviorType.PHONE_USE,
        event_id="event-1",
    )
    stale_generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    stale_record = await registry.record_active_behavior_event(
        "session-1",
        connection_generation=generation,
        behavior_type=BehaviorType.PHONE_USE,
        event_id="event-old",
    )
    stale_clear = await registry.clear_active_behavior_event(
        "session-1",
        connection_generation=generation,
        event_id="event-1",
    )
    snapshot = await registry.get_behavior_snapshot("session-1")

    assert recorded is True
    assert stale_generation == generation + 1
    assert stale_record is False
    assert stale_clear is False
    assert snapshot is not None
    assert snapshot.connection_generation == stale_generation
    assert snapshot.active_behavior_event_id is None


@pytest.mark.asyncio
async def test_frame_queue_max_size_one_keeps_only_latest() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", frame_queue_max_size=1)

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    result = await registry.accept_frame("session-1", accepted_frame("frame-2"))
    frames = await registry.get_latest_frame_queue_snapshot("session-1")

    assert result.dropped_count == 1
    assert [frame.metadata.frame_id for frame in frames] == ["frame-2"]


@pytest.mark.asyncio
async def test_frame_recent_id_cache_is_bounded_and_eviction_allows_reuse() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", frame_recent_id_cache_size=2)

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await registry.accept_frame("session-1", accepted_frame("frame-2"))
    duplicate = await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await registry.accept_frame("session-1", accepted_frame("frame-3"))
    evicted_reuse = await registry.accept_frame("session-1", accepted_frame("frame-1"))

    assert duplicate.status == FrameAcceptStatus.DUPLICATE
    assert evicted_reuse.status == FrameAcceptStatus.ACCEPTED


@pytest.mark.asyncio
async def test_reset_frame_state_preserves_location_state() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    occurred_at = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    await registry.apply_location_update(
        "session-1",
        LocationRuntimeUpdate(
            latitude=37.5501,
            longitude=127.0734,
            speed_kph=32.4,
            accuracy_meters=8.2,
            source=LocationSource.GPS,
            driving_state=DrivingState.MOVING,
            occurred_at=occurred_at,
            received_at=occurred_at,
        ),
    )
    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await registry.record_detection_result(
        "session-1",
        connection_generation=0,
        result=detection_result("frame-1"),
    )
    await registry.record_inference_failure("session-1", connection_generation=0)
    for frame_number in [1, 2, 3]:
        await registry.observe_behavior_result(
            "session-1",
            connection_generation=0,
            result=behavior_detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )

    reset = await registry.reset_frame_state(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    snapshot = await registry.get_location_snapshot("session-1")
    frames = await registry.get_latest_frame_queue_snapshot("session-1")
    runtime = await registry.get("session-1")

    assert reset is True
    assert snapshot is not None
    assert snapshot.current_latitude == 37.5501
    assert frames == ()
    assert runtime is not None
    assert runtime.accepted_frame_count == 0
    assert runtime.last_accepted_frame_id is None
    assert runtime.last_detection_result is None
    assert runtime.processed_frame_count == 0
    assert runtime.inference_failure_count == 0
    assert runtime.last_behavior_transition is None
    assert runtime.active_event_behavior_type is None
    assert runtime.behavior_policy.sample_count == 0
