from fastapi import WebSocket
from fastapi.testclient import TestClient

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType
from app.api.model_lab import run_model_lab_stream
from app.main import create_app

JPEG_BYTES = b"\xff\xd8\xff\xe0model-lab-jpeg\xff\xd9"


class FakeAdapter:
    model_version = "fake-vit"

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame):
        self.frames.append(frame.jpeg_bytes)

        class Result:
            session_id = frame.session_id
            frame_id = frame.frame_id
            behavior_type = DetectionBehaviorType.NORMAL
            model_action_type = ModelActionType.SAFE_DRIVING
            model_class_label = "safe_driving"
            model_class_code = "AC1"
            confidence = 0.92
            inference_latency_ms = 12

        return Result()


def registered_route_paths(app) -> set[str]:
    route_paths: set[str] = set()
    for route in app.routes:
        route_path = getattr(route, "path", None)
        if route_path is not None:
            route_paths.add(route_path)

        effective_route_contexts = getattr(route, "effective_route_contexts", None)
        if effective_route_contexts is None:
            continue

        for context in effective_route_contexts():
            starlette_route = getattr(context, "starlette_route", None)
            context_path = getattr(starlette_route, "path", None) or getattr(
                context,
                "path_format",
                None,
            )
            if context_path:
                route_paths.add(context_path)
    return route_paths


def test_model_lab_websocket_route_is_registered() -> None:
    paths = registered_route_paths(create_app())

    assert "/api/model/v7-fast/inference/stream" in paths


def test_model_lab_websocket_returns_lightweight_inference_result() -> None:
    app = create_app()
    adapter = FakeAdapter()

    @app.websocket("/test/model-lab")
    async def test_stream(websocket: WebSocket):
        await run_model_lab_stream(websocket, adapter, max_frame_bytes=1024 * 1024)

    client = TestClient(app)
    with client.websocket_connect("/test/model-lab") as websocket:
        websocket.send_json({
            "type": "session_start",
            "sessionId": "session-1",
            "targetTransmissionFps": 4,
            "transport": "websocket",
        })
        started = websocket.receive_json()
        assert started["type"] == "session_started"
        assert started["apiVersion"] == "v7-fast"
        assert started["queuePolicy"] == "latest_pending_only"

        websocket.send_json({
            "type": "frame_meta",
            "sessionId": "session-1",
            "frameId": "frame-1",
            "clientSentAt": "20",
            "contentType": "image/jpeg",
            "width": 224,
            "height": 224,
            "encodingMs": 3,
            "frameTimeSeconds": 1.25,
        })
        websocket.send_bytes(JPEG_BYTES)

        result = websocket.receive_json()
        assert result["type"] == "inference_result"
        assert result["frameId"] == "frame-1"
        assert result["detections"][0]["variableName"] == "safe_driving"
        assert result["queue"] == {"droppedFrames": 0}
        assert "model" not in result
        assert adapter.frames == [JPEG_BYTES]


def test_model_lab_websocket_rejects_frame_before_session_start() -> None:
    app = create_app()

    @app.websocket("/test/model-lab")
    async def test_stream(websocket: WebSocket):
        await run_model_lab_stream(websocket, FakeAdapter(), max_frame_bytes=1024 * 1024)

    client = TestClient(app)
    with client.websocket_connect("/test/model-lab") as websocket:
        websocket.send_json({
            "type": "frame_meta",
            "sessionId": "session-1",
            "frameId": "frame-1",
            "clientSentAt": "20",
            "contentType": "image/jpeg",
            "width": 224,
            "height": 224,
        })

        assert websocket.receive_json() == {
            "type": "error",
            "code": "session_not_started",
            "message": "Send session_start before frame_meta.",
        }
