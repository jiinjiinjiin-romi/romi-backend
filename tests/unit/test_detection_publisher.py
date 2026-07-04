import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from starlette.websockets import WebSocketState

from app.ai.driver_monitoring import DetectionResult
from app.ai.prediction_mapper import metadata_from_class_index
from app.realtime.connection_manager import ConnectionManager
from app.realtime.detection_publisher import DetectionPublishStatus, DetectionUpdatePublisher


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.application_state = WebSocketState.CONNECTED
        self.fail_send = fail_send
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(message)


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
        model_version="vit-test",
        captured_at=timestamp,
        inference_started_at=timestamp,
        inference_completed_at=timestamp + timedelta(milliseconds=7),
        inference_latency_ms=7,
    )


@pytest.mark.asyncio
async def test_publish_sends_detection_update_to_current_connection() -> None:
    manager = ConnectionManager()
    websocket = FakeWebSocket()
    await manager.register("session-1", websocket)
    publisher = DetectionUpdatePublisher(connection_manager=manager)

    result = await publisher.publish(
        session_id="session-1",
        websocket=websocket,
        result=detection_result("frame-1"),
    )

    assert result.status == DetectionPublishStatus.PUBLISHED
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
                "confidence": 0.99,
                "modelVersion": "vit-test",
                "capturedAt": "2026-06-28T03:10:00.000000Z",
                "inferenceLatencyMs": 7,
            },
        }
    ]
    assert "riskLevel" not in websocket.sent[0]["payload"]
    assert "behaviorEventId" not in websocket.sent[0]["payload"]
    assert "interventionId" not in websocket.sent[0]["payload"]
    assert "speechText" not in websocket.sent[0]["payload"]
    assert "uiText" not in websocket.sent[0]["payload"]
    assert "toolCall" not in websocket.sent[0]["payload"]


@pytest.mark.asyncio
async def test_publish_skips_non_current_connection() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    await manager.register("session-1", second)
    publisher = DetectionUpdatePublisher(connection_manager=manager)

    result = await publisher.publish(
        session_id="session-1",
        websocket=first,
        result=detection_result("frame-1"),
    )

    assert result.status == DetectionPublishStatus.NOT_CURRENT_CONNECTION
    assert first.sent == []
    assert second.sent == []


@pytest.mark.asyncio
async def test_publish_handles_send_failure_without_raising() -> None:
    manager = ConnectionManager()
    websocket = FakeWebSocket(fail_send=True)
    await manager.register("session-1", websocket)
    publisher = DetectionUpdatePublisher(connection_manager=manager)

    result = await publisher.publish(
        session_id="session-1",
        websocket=websocket,
        result=detection_result("frame-1"),
    )

    assert result.status == DetectionPublishStatus.SEND_FAILED
    assert websocket.sent == []
