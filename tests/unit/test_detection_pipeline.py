from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from starlette.websockets import WebSocketState

from app.ai.driver_monitoring import DetectionResult, ModelActionType
from app.ai.prediction_mapper import metadata_from_action_type
from app.core.enums import BehaviorType
from app.policies.sliding_window_behavior_policy import BehaviorTransitionType
from app.realtime.connection_manager import ConnectionManager
from app.realtime.detection_pipeline import DetectionPipeline, DetectionPipelineStatus
from app.realtime.detection_publisher import (
    DetectionPublishResult,
    DetectionPublishStatus,
    DetectionUpdatePublisher,
)
from app.realtime.session_runtime import (
    BehaviorRuntimeObserveStatus,
    SessionRuntimeRegistry,
)
from app.services.behavior_event_service import (
    BehaviorEventWriteResult,
    BehaviorEventWriteStatus,
)

BASE_TIME = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)


class FakeWebSocket:
    def __init__(self) -> None:
        self.application_state = WebSocketState.CONNECTED
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, DetectionResult]] = []

    async def publish(
        self,
        *,
        session_id: str,
        websocket: object,
        result: DetectionResult,
    ) -> DetectionPublishResult:
        self.calls.append((session_id, websocket, result))
        return DetectionPublishResult(status=DetectionPublishStatus.PUBLISHED)


class RecordingBehaviorEventService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def handle_transition(self, **kwargs) -> BehaviorEventWriteResult:
        if self.fail:
            raise RuntimeError("behavior event write failed")

        self.calls.append(kwargs)
        transition = kwargs["transition"]
        if transition.transition_type == BehaviorTransitionType.CLEARED:
            return BehaviorEventWriteResult(
                status=BehaviorEventWriteStatus.CLEARED,
                behavior_event_id="event-1",
                behavior_type=BehaviorType.PHONE_USE,
            )
        return BehaviorEventWriteResult(
            status=BehaviorEventWriteStatus.STARTED_CREATED,
            behavior_event_id="event-1",
            behavior_type=transition.event_behavior_type,
        )


def detection_result(action_type: ModelActionType, frame_number: int) -> DetectionResult:
    metadata = metadata_from_action_type(action_type)
    captured_at = BASE_TIME + timedelta(milliseconds=frame_number)

    return DetectionResult(
        session_id="session-1",
        frame_id=f"frame-{frame_number}",
        model_action_type=action_type,
        model_class_code=metadata.class_code,
        model_class_label=metadata.class_label,
        behavior_type=metadata.detection_behavior_type,
        confidence=0.9,
        model_version="vit-test",
        captured_at=captured_at,
        inference_started_at=captured_at,
        inference_completed_at=captured_at + timedelta(milliseconds=7),
        inference_latency_ms=7,
    )


async def prepare_pipeline(
    *,
    publisher: RecordingPublisher | DetectionUpdatePublisher | None = None,
    behavior_event_service: RecordingBehaviorEventService | None = None,
) -> tuple[DetectionPipeline, SessionRuntimeRegistry, ConnectionManager, FakeWebSocket]:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", connected_at=BASE_TIME)
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None

    manager = ConnectionManager()
    websocket = FakeWebSocket()
    await manager.register("session-1", websocket)
    pipeline = DetectionPipeline(
        session_id="session-1",
        websocket=websocket,
        connection_generation=generation,
        connection_manager=manager,
        runtime_registry=registry,
        detection_publisher=publisher,
        behavior_event_service=behavior_event_service,
    )
    return pipeline, registry, manager, websocket


@pytest.mark.asyncio
async def test_pipeline_records_publishes_and_observes_started_transition() -> None:
    publisher = RecordingPublisher()
    pipeline, registry, _, _ = await prepare_pipeline(publisher=publisher)

    results = [
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
        for frame_number in [1, 2, 3]
    ]
    inference = await registry.get_inference_snapshot("session-1")
    behavior = await registry.get_behavior_snapshot("session-1")

    assert [result.status for result in results] == [DetectionPipelineStatus.PROCESSED] * 3
    assert inference is not None
    assert inference.processed_frame_count == 3
    assert inference.last_detection_result is not None
    assert inference.last_detection_result.frame_id == "frame-3"
    assert [call[2].frame_id for call in publisher.calls] == ["frame-1", "frame-2", "frame-3"]
    assert behavior is not None
    assert behavior.last_behavior_transition is not None
    assert behavior.last_behavior_transition.transition_type == BehaviorTransitionType.STARTED
    assert behavior.active_event_behavior_type == BehaviorType.PHONE_USE
    assert behavior.dominant_model_action_type == ModelActionType.WRITING_MSG_RIGHT


@pytest.mark.asyncio
async def test_pipeline_records_cleared_transition_without_normal_event_candidate() -> None:
    pipeline, registry, _, _ = await prepare_pipeline(publisher=RecordingPublisher())

    for frame_number in [1, 2, 3]:
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
    for frame_number in [4, 5, 6]:
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.SAFE_DRIVING, frame_number),
        )
    behavior = await registry.get_behavior_snapshot("session-1")

    assert behavior is not None
    assert behavior.last_behavior_transition is not None
    assert behavior.last_behavior_transition.transition_type == BehaviorTransitionType.CLEARED
    assert behavior.last_behavior_transition.event_behavior_type is None
    assert (
        behavior.last_behavior_transition.dominant_model_action_type
        == ModelActionType.SAFE_DRIVING
    )
    assert behavior.active_detection_behavior_type is None
    assert behavior.active_event_behavior_type is None
    assert behavior.dominant_model_action_type is None


@pytest.mark.asyncio
async def test_pipeline_calls_behavior_event_service_for_started_and_cleared() -> None:
    service = RecordingBehaviorEventService()
    pipeline, _, _, _ = await prepare_pipeline(
        publisher=RecordingPublisher(),
        behavior_event_service=service,
    )

    started_results = [
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
        for frame_number in [1, 2, 3]
    ]
    for frame_number in [4, 5, 6]:
        cleared_result = await pipeline.handle_detection_result(
            detection_result(ModelActionType.SAFE_DRIVING, frame_number),
        )

    assert started_results[-1].behavior_event_write_result is not None
    assert (
        started_results[-1].behavior_event_write_result.status
        == BehaviorEventWriteStatus.STARTED_CREATED
    )
    assert cleared_result.behavior_event_write_result is not None
    assert cleared_result.behavior_event_write_result.status == BehaviorEventWriteStatus.CLEARED
    assert [call["transition"].transition_type for call in service.calls] == [
        BehaviorTransitionType.STARTED,
        BehaviorTransitionType.CLEARED,
    ]
    assert service.calls[1]["previous_active_event_behavior_type"] == BehaviorType.PHONE_USE


@pytest.mark.asyncio
async def test_pipeline_does_not_call_behavior_event_service_for_none_or_updated() -> None:
    service = RecordingBehaviorEventService()
    pipeline, _, _, _ = await prepare_pipeline(
        publisher=RecordingPublisher(),
        behavior_event_service=service,
    )

    no_transition = await pipeline.handle_detection_result(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 1),
    )
    for frame_number in [2, 3]:
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
    for frame_number in [4, 5, 6]:
        updated = await pipeline.handle_detection_result(
            detection_result(ModelActionType.GPS_OPERATING, frame_number),
        )

    assert no_transition.behavior_event_write_result is None
    assert updated.behavior_observe_result is not None
    assert updated.behavior_observe_result.transition is not None
    assert (
        updated.behavior_observe_result.transition.transition_type
        == BehaviorTransitionType.UPDATED
    )
    assert [call["transition"].transition_type for call in service.calls] == [
        BehaviorTransitionType.STARTED
    ]


@pytest.mark.asyncio
async def test_secondary_task_transition_preserves_dominant_model_action() -> None:
    pipeline, registry, _, _ = await prepare_pipeline(publisher=RecordingPublisher())

    for frame_number in [1, 2, 3]:
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.GPS_OPERATING, frame_number),
        )
    behavior = await registry.get_behavior_snapshot("session-1")

    assert behavior is not None
    assert behavior.active_event_behavior_type == BehaviorType.SECONDARY_TASK
    assert behavior.dominant_model_action_type == ModelActionType.GPS_OPERATING


@pytest.mark.asyncio
async def test_old_generation_result_does_not_publish_or_update_behavior_state() -> None:
    publisher = RecordingPublisher()
    service = RecordingBehaviorEventService()
    pipeline, registry, _, _ = await prepare_pipeline(
        publisher=publisher,
        behavior_event_service=service,
    )
    await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )

    result = await pipeline.handle_detection_result(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 1),
    )
    inference = await registry.get_inference_snapshot("session-1")
    behavior = await registry.get_behavior_snapshot("session-1")

    assert result.status == DetectionPipelineStatus.STALE_GENERATION
    assert result.detection_recorded is False
    assert publisher.calls == []
    assert inference is not None
    assert inference.processed_frame_count == 0
    assert behavior is not None
    assert behavior.active_event_behavior_type is None
    assert behavior.policy_sample_count == 0
    assert service.calls == []


@pytest.mark.asyncio
async def test_non_current_connection_result_does_not_publish_or_update_runtime() -> None:
    publisher = RecordingPublisher()
    pipeline, registry, manager, websocket = await prepare_pipeline(publisher=publisher)
    replacement = FakeWebSocket()
    await manager.register("session-1", replacement)

    result = await pipeline.handle_detection_result(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 1),
    )
    inference = await registry.get_inference_snapshot("session-1")
    behavior = await registry.get_behavior_snapshot("session-1")

    assert websocket.sent == []
    assert result.status == DetectionPipelineStatus.NOT_CURRENT_CONNECTION
    assert result.detection_recorded is False
    assert publisher.calls == []
    assert inference is not None
    assert inference.processed_frame_count == 0
    assert behavior is not None
    assert behavior.policy_sample_count == 0


@pytest.mark.asyncio
async def test_pipeline_returns_failure_when_behavior_event_service_fails_after_publish() -> None:
    publisher = RecordingPublisher()
    service = RecordingBehaviorEventService(fail=True)
    pipeline, _, _, _ = await prepare_pipeline(
        publisher=publisher,
        behavior_event_service=service,
    )

    for frame_number in [1, 2]:
        await pipeline.handle_detection_result(
            detection_result(ModelActionType.WRITING_MSG_RIGHT, frame_number),
        )
    result = await pipeline.handle_detection_result(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 3),
    )

    assert result.status == DetectionPipelineStatus.BEHAVIOR_EVALUATION_FAILED
    assert result.behavior_event_write_result is not None
    assert result.behavior_event_write_result.status == BehaviorEventWriteStatus.WRITE_FAILED
    assert [call[2].frame_id for call in publisher.calls] == ["frame-1", "frame-2", "frame-3"]


@pytest.mark.asyncio
async def test_detection_update_payload_shape_is_unchanged() -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1", connected_at=BASE_TIME)
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    manager = ConnectionManager()
    websocket = FakeWebSocket()
    await manager.register("session-1", websocket)
    pipeline = DetectionPipeline(
        session_id="session-1",
        websocket=websocket,
        connection_generation=generation,
        connection_manager=manager,
        runtime_registry=registry,
        detection_publisher=DetectionUpdatePublisher(connection_manager=manager),
    )

    result = await pipeline.handle_detection_result(
        detection_result(ModelActionType.SAFE_DRIVING, 1),
    )

    assert result.status == DetectionPipelineStatus.PROCESSED
    assert websocket.sent == [
        {
            "type": "DETECTION_UPDATE",
            "occurredAt": websocket.sent[0]["occurredAt"],
            "payload": {
                "sessionId": "session-1",
                "frameId": "frame-1",
                "behaviorType": "NORMAL",
                "modelActionType": "SAFE_DRIVING",
                "modelClassCode": "AC1",
                "modelClassLabel": "safe_driving",
                "confidence": 0.9,
                "modelVersion": "vit-test",
                "capturedAt": "2026-07-03T09:00:00.001000Z",
                "inferenceLatencyMs": 7,
            },
        }
    ]
    assert {
        "riskLevel",
        "behaviorEventId",
        "interventionId",
        "speechText",
        "uiText",
        "toolCall",
        "transitionType",
        "hitRatio",
        "dominantModelActionType",
    }.isdisjoint(websocket.sent[0]["payload"])


@pytest.mark.asyncio
async def test_no_transition_result_is_returned_for_suppressed_single_frame() -> None:
    pipeline, _, _, _ = await prepare_pipeline(publisher=RecordingPublisher())

    result = await pipeline.handle_detection_result(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 1),
    )

    assert result.status == DetectionPipelineStatus.PROCESSED
    assert result.behavior_observe_result is not None
    assert result.behavior_observe_result.status == BehaviorRuntimeObserveStatus.NO_TRANSITION
    assert result.behavior_observe_result.transition is not None
    assert result.behavior_observe_result.transition.transition_type == BehaviorTransitionType.NONE
