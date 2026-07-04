import asyncio
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.ai.driver_monitoring import DetectionResult, InferenceFrame
from app.ai.prediction_mapper import metadata_from_class_index
from app.api.dependencies import get_current_account, get_settings_dependency
from app.core.config import Settings
from app.core.time import format_utc_datetime, utc_now_for_api_response, utc_now_for_mysql_datetime
from app.db.session import AsyncSessionLocal
from app.models import Account, DriverProfile, DrivingSession, LocationSample
from app.policies.driving_context_policy import DrivingContextPolicy
from app.services.location_update_service import (
    LocationUpdateResultStatus,
    LocationUpdateService,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


class AppStateDriverMonitoringAdapter:
    model_version = "vit-dms-1.0.0"

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.frames: list[InferenceFrame] = []
        self.ready_calls = 0

    async def is_ready(self) -> bool:
        self.ready_calls += 1
        return self.ready

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.frames.append(frame)
        return _detection_result(frame)


class BlockingDriverMonitoringAdapter:
    model_version = "vit-dms-1.0.0"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.started.set()
        await self.release.wait()
        return _detection_result(frame)


class FailingThenSuccessDriverMonitoringAdapter:
    model_version = "vit-dms-1.0.0"

    def __init__(self) -> None:
        self.calls = 0

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("inference failed")
        return _detection_result(frame)


def _detection_result(frame: InferenceFrame) -> DetectionResult:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    metadata = metadata_from_class_index(0)
    return DetectionResult(
        session_id=frame.session_id,
        frame_id=frame.frame_id,
        model_action_type=metadata.action_type,
        model_class_code=metadata.class_code,
        model_class_label=metadata.class_label,
        behavior_type=metadata.detection_behavior_type,
        confidence=0.99,
        model_version="vit-dms-1.0.0",
        captured_at=frame.captured_at,
        inference_started_at=timestamp,
        inference_completed_at=timestamp + timedelta(milliseconds=5),
        inference_latency_ms=5,
    )


@dataclass(slots=True)
class WebSocketTestData:
    current_account: Account
    other_account: Account
    active_session_id: str
    completed_session_id: str
    aborted_session_id: str
    other_active_session_id: str


class FakeMonotonicClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def create_test_data() -> WebSocketTestData:
    now = utc_now_for_mysql_datetime()
    current_account = Account(
        id=str(uuid4()),
        email=f"ws-current-{uuid4().hex}@example.com",
    )
    other_account = Account(
        id=str(uuid4()),
        email=f"ws-other-{uuid4().hex}@example.com",
    )
    current_profile = DriverProfile(
        account_id=current_account.id,
        display_name="WebSocket Current",
        agent_call_name="WebSocket Current",
    )
    other_profile = DriverProfile(
        account_id=other_account.id,
        display_name="WebSocket Other",
        agent_call_name="WebSocket Other",
    )

    async with AsyncSessionLocal() as session:
        session.add_all([current_account, other_account])
        await session.flush()
        session.add_all([current_profile, other_profile])
        await session.flush()

        active_session = DrivingSession(
            profile_id=current_profile.id,
            model_version="vit-dms-1.0.0",
            policy_version="risk-policy-1.0.0",
        )
        completed_session = DrivingSession(
            profile_id=current_profile.id,
            status="COMPLETED",
            ended_at=now + timedelta(minutes=10),
            end_reason="USER_REQUEST",
            model_version="vit-dms-1.0.0",
            policy_version="risk-policy-1.0.0",
        )
        aborted_session = DrivingSession(
            profile_id=current_profile.id,
            status="ABORTED",
            ended_at=now + timedelta(minutes=11),
            end_reason="CAMERA_LOST",
            model_version="vit-dms-1.0.0",
            policy_version="risk-policy-1.0.0",
        )
        other_active_session = DrivingSession(
            profile_id=other_profile.id,
            model_version="vit-dms-1.0.0",
            policy_version="risk-policy-1.0.0",
        )
        session.add_all(
            [
                active_session,
                completed_session,
                aborted_session,
                other_active_session,
            ]
        )
        await session.commit()

    return WebSocketTestData(
        current_account=current_account,
        other_account=other_account,
        active_session_id=active_session.id,
        completed_session_id=completed_session.id,
        aborted_session_id=aborted_session.id,
        other_active_session_id=other_active_session.id,
    )


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


async def get_driving_session_status(session_id: str) -> str:
    async with AsyncSessionLocal() as session:
        driving_session = await session.get(DrivingSession, session_id)
        assert driving_session is not None
        return driving_session.status


async def list_location_samples(session_id: str) -> list[LocationSample]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LocationSample)
            .where(LocationSample.session_id == session_id)
            .order_by(LocationSample.recorded_at, LocationSample.id)
        )
        return list(result.scalars().all())


async def list_runtime_frame_ids(app, session_id: str) -> list[str]:
    frames = await app.state.session_runtime_registry.get_latest_frame_queue_snapshot(session_id)
    return [frame.metadata.frame_id for frame in frames]


async def get_runtime_frame_bytes(app, session_id: str) -> list[bytes]:
    frames = await app.state.session_runtime_registry.get_latest_frame_queue_snapshot(session_id)
    return [frame.jpeg_bytes for frame in frames]


async def get_runtime_inference_state(app, session_id: str) -> dict[str, object | None]:
    snapshot = await app.state.session_runtime_registry.get_inference_snapshot(session_id)
    if snapshot is None:
        return {
            "lastFrameId": None,
            "lastBehaviorType": None,
            "confidence": None,
            "processedFrameCount": 0,
            "inferenceFailureCount": 0,
        }

    result = snapshot.last_detection_result
    return {
        "lastFrameId": None if result is None else result.frame_id,
        "lastBehaviorType": None if result is None else result.behavior_type.value,
        "confidence": None if result is None else result.confidence,
        "processedFrameCount": snapshot.processed_frame_count,
        "inferenceFailureCount": snapshot.inference_failure_count,
    }


async def complete_driving_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        driving_session = await session.get(DrivingSession, session_id)
        assert driving_session is not None
        driving_session.status = "COMPLETED"
        driving_session.ended_at = utc_now_for_mysql_datetime()
        driving_session.end_reason = "USER_REQUEST"
        await session.commit()


def override_dependencies(app, account: Account, *, model_available: bool = True) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override
    app.state.driver_monitoring_adapter = AppStateDriverMonitoringAdapter(
        ready=model_available,
    )


def override_settings(app, settings: Settings) -> None:
    def settings_override() -> Settings:
        return settings

    app.dependency_overrides[get_settings_dependency] = settings_override


def override_driver_monitoring_adapter(app, adapter) -> None:
    app.state.driver_monitoring_adapter = adapter


def override_location_update_service(app, clock: FakeMonotonicClock) -> None:
    def location_update_service_factory(*, settings, runtime_registry) -> LocationUpdateService:
        return LocationUpdateService(
            runtime_registry=runtime_registry,
            policy=DrivingContextPolicy(
                moving_speed_threshold_kph=settings.driving_moving_speed_threshold_kph,
                max_accuracy_meters=settings.driving_location_max_accuracy_meters,
            ),
            persist_interval_ms=settings.ws_location_persist_interval_ms,
            monotonic_clock=clock,
        )

    app.state.location_update_service_factory = location_update_service_factory


def override_failing_location_persist_service(app, clock: FakeMonotonicClock) -> None:
    def location_update_service_factory(*, settings, runtime_registry) -> LocationUpdateService:
        service = LocationUpdateService(
            runtime_registry=runtime_registry,
            policy=DrivingContextPolicy(
                moving_speed_threshold_kph=settings.driving_moving_speed_threshold_kph,
                max_accuracy_meters=settings.driving_location_max_accuracy_meters,
            ),
            persist_interval_ms=settings.ws_location_persist_interval_ms,
            monotonic_clock=clock,
        )

        async def fail_persist(**kwargs) -> LocationUpdateResultStatus:
            return LocationUpdateResultStatus.PERSIST_FAILED

        service._persist_location_sample = fail_persist
        return service

    app.state.location_update_service_factory = location_update_service_factory


def location_update_message(
    occurred_at: datetime,
    *,
    latitude: float = 37.5501,
    longitude: float = 127.0734,
    speed_kph: float | None = 32.4,
    accuracy_meters: float | None = 8.2,
) -> dict[str, object]:
    return {
        "type": "LOCATION_UPDATE",
        "requestId": str(uuid4()),
        "occurredAt": format_utc_datetime(occurred_at),
        "payload": {
            "latitude": latitude,
            "longitude": longitude,
            "speedKph": speed_kph,
            "accuracyMeters": accuracy_meters,
            "source": "GPS",
        },
    }


def frame_meta_message(
    occurred_at: datetime,
    *,
    frame_id: str = "frame-1",
    width: int = 640,
    height: int = 360,
) -> dict[str, object]:
    return {
        "type": "FRAME_META",
        "requestId": str(uuid4()),
        "occurredAt": format_utc_datetime(occurred_at),
        "payload": {
            "frameId": frame_id,
            "format": "JPEG",
            "width": width,
            "height": height,
            "capturedAt": format_utc_datetime(occurred_at),
        },
    }


def minimal_jpeg() -> bytes:
    return b"\xff\xd8\xff\xd9"


def assert_denial(
    client: TestClient,
    path: str,
    *,
    status_code: int,
    error_code: str,
) -> None:
    with pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect(path):
            raise AssertionError("WebSocket connection unexpectedly succeeded")

    response = exc_info.value
    assert response.status_code == status_code
    payload = response.json()
    assert payload["status"] == status_code
    assert payload["error"] == error_code
    assert "detail" not in payload


def wait_for_condition(predicate, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition was not met before timeout.")


def receive_message_by_type(websocket, message_type: str) -> dict[str, object]:
    for _ in range(5):
        message = websocket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"{message_type} was not received.")


def receive_detection_update(
    websocket,
    *,
    session_id: str,
    frame_id: str,
    captured_at: datetime,
    model_version: str = "vit-dms-1.0.0",
) -> dict[str, object]:
    message = receive_message_by_type(websocket, "DETECTION_UPDATE")
    payload = message["payload"]

    assert set(payload) == {
        "sessionId",
        "frameId",
        "behaviorType",
        "modelActionType",
        "modelClassCode",
        "modelClassLabel",
        "confidence",
        "modelVersion",
        "capturedAt",
        "inferenceLatencyMs",
    }
    assert payload["sessionId"] == session_id
    assert payload["frameId"] == frame_id
    assert payload["behaviorType"] == "NORMAL"
    assert payload["modelActionType"] == "SAFE_DRIVING"
    assert payload["modelClassCode"] == "AC1"
    assert payload["modelClassLabel"] == "safe_driving"
    assert payload["confidence"] == 0.99
    assert payload["modelVersion"] == model_version
    assert payload["capturedAt"] == format_utc_datetime(captured_at)
    assert payload["inferenceLatencyMs"] >= 0
    return message


def test_websocket_handshake_denial_responses(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)

        try:
            assert_denial(
                client,
                "/ws/v1/driving-sessions/not-a-uuid",
                status_code=422,
                error_code="INVALID_SESSION_ID",
            )
            assert_denial(
                client,
                f"/ws/v1/driving-sessions/{uuid4()}",
                status_code=404,
                error_code="SESSION_NOT_FOUND",
            )
            assert_denial(
                client,
                f"/ws/v1/driving-sessions/{data.other_active_session_id}",
                status_code=404,
                error_code="SESSION_NOT_FOUND",
            )
            assert_denial(
                client,
                f"/ws/v1/driving-sessions/{data.completed_session_id}",
                status_code=409,
                error_code="SESSION_NOT_ACTIVE",
            )
            assert_denial(
                client,
                f"/ws/v1/driving-sessions/{data.aborted_session_id}",
                status_code=409,
                error_code="SESSION_NOT_ACTIVE",
            )

            app.dependency_overrides.clear()
            override_dependencies(app, data.current_account, model_available=False)
            assert_denial(
                client,
                f"/ws/v1/driving-sessions/{data.active_session_id}",
                status_code=503,
                error_code="MODEL_NOT_AVAILABLE",
            )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_success_session_ready_pong_and_cleanup(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                ready = websocket.receive_json()

                assert ready["type"] == "SESSION_READY"
                assert ready["payload"] == {
                    "sessionId": data.active_session_id,
                    "modelVersion": "vit-dms-1.0.0",
                    "policyVersion": "risk-policy-1.0.0",
                    "recommendedFrameFps": 5,
                    "locationIntervalMs": 1000,
                    "heartbeatIntervalMs": 10000,
                }
                assert app.state.websocket_connection_manager.active_count == 1
                assert app.state.session_runtime_registry.count == 1

                runtime = app.state.session_runtime_registry._runtimes[data.active_session_id]
                previous_heartbeat_at = runtime.last_heartbeat_at
                websocket.send_json(
                    {
                        "type": "PONG",
                        "occurredAt": format_utc_datetime(utc_now_for_api_response()),
                        "payload": {},
                    }
                )

                wait_for_condition(
                    lambda: runtime.last_heartbeat_at > previous_heartbeat_at,
                )

            wait_for_condition(lambda: app.state.websocket_connection_manager.active_count == 0)
            wait_for_condition(lambda: app.state.session_runtime_registry.count == 0)

            session_status = client.portal.call(get_driving_session_status, data.active_session_id)
            assert session_status == "ACTIVE"
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_uses_app_state_adapter_for_handshake_and_worker(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        adapter = AppStateDriverMonitoringAdapter()
        override_driver_monitoring_adapter(app, adapter)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"
                assert adapter.ready_calls == 1

                websocket.send_json(
                    frame_meta_message(base_time, frame_id="app-state-frame")
                )
                websocket.send_bytes(minimal_jpeg())
                receive_detection_update(
                    websocket,
                    session_id=data.active_session_id,
                    frame_id="app-state-frame",
                    captured_at=base_time,
                )

                assert [frame.frame_id for frame in adapter.frames] == ["app-state-frame"]
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


@pytest.mark.parametrize(
    ("send_invalid_message", "expected_error"),
    [
        (lambda websocket: websocket.send_text("not-json"), "WEBSOCKET_PROTOCOL_ERROR"),
        (lambda websocket: websocket.send_json({"type": "UNKNOWN"}), "WEBSOCKET_PROTOCOL_ERROR"),
    ],
)
def test_websocket_protocol_errors_close_with_policy_violation(
    app,
    send_invalid_message,
    expected_error: str,
) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                send_invalid_message(websocket)
                error_message = websocket.receive_json()

                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == expected_error
                assert error_message["payload"]["recoverable"] is False

                with pytest.raises(WebSocketDisconnect) as exc_info:
                    websocket.receive_json()
                assert exc_info.value.code == 1008
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_orphan_binary_is_recoverable(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_bytes(minimal_jpeg())
                error_message = websocket.receive_json()

                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "ORPHAN_FRAME_BINARY"
                assert error_message["payload"]["recoverable"] is True

                websocket.send_json(frame_meta_message(base_time))
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-1"
                )
                receive_detection_update(
                    websocket,
                    session_id=data.active_session_id,
                    frame_id="frame-1",
                    captured_at=base_time,
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_frame_meta_binary_pair_runs_internal_inference_without_db_write(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                websocket.send_bytes(minimal_jpeg())

                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )
                    == {
                        "lastFrameId": "frame-1",
                        "lastBehaviorType": "NORMAL",
                        "confidence": 0.99,
                        "processedFrameCount": 1,
                        "inferenceFailureCount": 0,
                    }
                )
                assert client.portal.call(list_runtime_frame_ids, app, data.active_session_id) == []
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 0
                receive_detection_update(
                    websocket,
                    session_id=data.active_session_id,
                    frame_id="frame-1",
                    captured_at=base_time,
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_multiple_frames_publish_detection_updates(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                for index in range(1, 3):
                    captured_at = base_time + timedelta(milliseconds=index)
                    frame_id = f"frame-{index}"
                    websocket.send_json(frame_meta_message(captured_at, frame_id=frame_id))
                    websocket.send_bytes(minimal_jpeg())
                    wait_for_condition(
                        lambda expected_frame_id=frame_id: client.portal.call(
                            get_runtime_inference_state,
                            app,
                            data.active_session_id,
                        )["lastFrameId"]
                        == expected_frame_id
                    )
                    receive_detection_update(
                        websocket,
                        session_id=data.active_session_id,
                        frame_id=frame_id,
                        captured_at=captured_at,
                    )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_inference_failure_recovers_on_next_frame(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        adapter = FailingThenSuccessDriverMonitoringAdapter()
        override_driver_monitoring_adapter(app, adapter)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["inferenceFailureCount"]
                    == 1
                )

                websocket.send_json(
                    frame_meta_message(base_time + timedelta(seconds=1), frame_id="frame-2")
                )
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-2"
                )
                state = client.portal.call(
                    get_runtime_inference_state,
                    app,
                    data.active_session_id,
                )
                assert state["processedFrameCount"] == 1
                assert state["inferenceFailureCount"] == 1
                assert adapter.calls == 2
                receive_detection_update(
                    websocket,
                    session_id=data.active_session_id,
                    frame_id="frame-2",
                    captured_at=base_time + timedelta(seconds=1),
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_frame_queue_backpressure_drops_oldest(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        adapter = BlockingDriverMonitoringAdapter()
        override_driver_monitoring_adapter(app, adapter)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(
                    frame_meta_message(
                        base_time + timedelta(milliseconds=1),
                        frame_id="frame-1",
                    )
                )
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(lambda: adapter.started.is_set())
                )

                for index in range(2, 5):
                    websocket.send_json(
                        frame_meta_message(
                            base_time + timedelta(milliseconds=index),
                            frame_id=f"frame-{index}",
                        )
                    )
                    websocket.send_bytes(minimal_jpeg())

                wait_for_condition(
                    lambda: client.portal.call(list_runtime_frame_ids, app, data.active_session_id)
                    == ["frame-3", "frame-4"]
                )
                runtime = app.state.session_runtime_registry._runtimes[data.active_session_id]
                assert runtime.accepted_frame_count == 4
                assert runtime.dropped_frame_count == 1
                client.portal.call(adapter.release.set)
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["processedFrameCount"]
                    == 3
                )
                received_frame_ids = [
                    receive_detection_update(
                        websocket,
                        session_id=data.active_session_id,
                        frame_id=frame_id,
                        captured_at=base_time + timedelta(milliseconds=offset),
                    )["payload"]["frameId"]
                    for frame_id, offset in (
                        ("frame-1", 1),
                        ("frame-3", 3),
                        ("frame-4", 4),
                    )
                ]
                assert received_frame_ids == ["frame-1", "frame-3", "frame-4"]
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_invalid_frame_meta_is_recoverable(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, width=0))
                error_message = websocket.receive_json()
                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "INVALID_FRAME_META"
                assert error_message["payload"]["recoverable"] is True

                websocket.send_json(frame_meta_message(base_time + timedelta(seconds=1)))
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-1"
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_invalid_jpeg_and_too_large_are_recoverable(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_settings(app, Settings(ws_max_frame_bytes=4))
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                websocket.send_bytes(b"\xff\xd8\x00\x00")
                invalid = websocket.receive_json()
                assert invalid["payload"]["code"] == "INVALID_JPEG_FRAME"
                assert invalid["payload"]["recoverable"] is True

                websocket.send_json(
                    frame_meta_message(base_time + timedelta(seconds=1), frame_id="frame-1")
                )
                websocket.send_bytes(b"\xff\xd8\x00\x00\xff\xd9")
                too_large = websocket.receive_json()
                assert too_large["payload"]["code"] == "FRAME_TOO_LARGE"
                assert too_large["payload"]["recoverable"] is True

                websocket.send_json(
                    frame_meta_message(base_time + timedelta(seconds=2), frame_id="frame-1")
                )
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-1"
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_duplicate_frame_id_is_recoverable(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-1"
                )
                receive_detection_update(
                    websocket,
                    session_id=data.active_session_id,
                    frame_id="frame-1",
                    captured_at=base_time,
                )

                websocket.send_json(
                    frame_meta_message(base_time + timedelta(seconds=1), frame_id="frame-1")
                )
                websocket.send_bytes(minimal_jpeg())
                duplicate = websocket.receive_json()
                assert duplicate["payload"]["code"] == "DUPLICATE_FRAME_ID"
                assert duplicate["payload"]["recoverable"] is True
                assert client.portal.call(list_runtime_frame_ids, app, data.active_session_id) == []
                assert client.portal.call(
                    get_runtime_inference_state,
                    app,
                    data.active_session_id,
                )["processedFrameCount"] == 1
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_frame_binary_timeout_is_recoverable(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_settings(app, Settings(ws_frame_binary_timeout_ms=1))
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                timeout = websocket.receive_json()
                assert timeout["payload"]["code"] == "FRAME_BINARY_TIMEOUT"
                assert timeout["payload"]["recoverable"] is True

                websocket.send_json(
                    frame_meta_message(base_time + timedelta(seconds=1), frame_id="frame-2")
                )
                websocket.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-2"
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_pending_frame_then_location_update_sends_expected_and_processes_location(
    app,
) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_location_update_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                websocket.send_json(location_update_message(base_time + timedelta(seconds=1)))
                error_message = websocket.receive_json()
                assert error_message["payload"]["code"] == "FRAME_BINARY_EXPECTED"
                assert error_message["payload"]["recoverable"] is True
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 1
                )
                assert client.portal.call(list_runtime_frame_ids, app, data.active_session_id) == []
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_location_update_updates_runtime_persists_with_throttle_and_rest_lookup(
    app,
) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_location_update_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(location_update_message(base_time))
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 1
                )

                runtime = app.state.session_runtime_registry._runtimes[data.active_session_id]
                assert runtime.current_latitude == 37.5501
                assert runtime.current_speed_kph == 32.4
                assert runtime.driving_state == "MOVING"

                clock.advance(1)
                websocket.send_json(
                    location_update_message(
                        base_time + timedelta(seconds=1),
                        latitude=37.5502,
                        speed_kph=0.0,
                    )
                )
                wait_for_condition(lambda: runtime.current_latitude == 37.5502)
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 1
                assert runtime.driving_state == "TEMPORARY_STOP"

                clock.advance(4)
                websocket.send_json(
                    location_update_message(
                        base_time + timedelta(seconds=2),
                        latitude=37.5503,
                        speed_kph=None,
                    )
                )
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 2
                )
                assert runtime.current_latitude == 37.5503
                assert runtime.driving_state == "UNKNOWN"

            locations = client.get(f"/api/v1/driving-sessions/{data.active_session_id}/locations")
            assert locations.status_code == 200
            payload = locations.json()
            assert payload["count"] == 2
            assert [item["recordedAt"] for item in payload["samples"]] == [
                "2026-06-28T03:10:10.000000Z",
                "2026-06-28T03:10:12.000000Z",
            ]
            assert payload["samples"][0]["speedKph"] == 32.4
            assert payload["samples"][0]["drivingState"] == "MOVING"
            assert payload["samples"][1]["speedKph"] is None
            assert payload["samples"][1]["drivingState"] == "UNKNOWN"
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_invalid_location_update_is_recoverable(app) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_location_update_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(
                    location_update_message(base_time, latitude=91.0),
                )
                error_message = websocket.receive_json()
                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "INVALID_LOCATION_UPDATE"
                assert error_message["payload"]["recoverable"] is True
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 0

                websocket.send_json(location_update_message(base_time + timedelta(seconds=1)))
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 1
                )
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_stale_and_duplicate_location_updates_do_not_persist(app) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_location_update_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(location_update_message(base_time))
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 1
                )

                clock.advance(5)
                websocket.send_json(location_update_message(base_time, latitude=37.5510))
                time.sleep(0.05)
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 1

                websocket.send_json(
                    location_update_message(base_time - timedelta(seconds=1), latitude=37.5520)
                )
                error_message = websocket.receive_json()
                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "STALE_LOCATION_UPDATE"
                assert error_message["payload"]["recoverable"] is True
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 1

                runtime = app.state.session_runtime_registry._runtimes[data.active_session_id]
                assert runtime.current_latitude == 37.5501
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_session_not_active_location_update_closes_with_policy_violation(app) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_location_update_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"
                websocket.send_json(location_update_message(base_time))
                wait_for_condition(
                    lambda: len(client.portal.call(list_location_samples, data.active_session_id))
                    == 1
                )

                client.portal.call(complete_driving_session, data.active_session_id)
                clock.advance(5)
                websocket.send_json(location_update_message(base_time + timedelta(seconds=5)))

                error_message = websocket.receive_json()
                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "SESSION_NOT_ACTIVE"
                assert error_message["payload"]["recoverable"] is False

                with pytest.raises(WebSocketDisconnect) as exc_info:
                    websocket.receive_json()
                assert exc_info.value.code == 1008
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 1
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_location_persist_failure_is_recoverable_and_keeps_runtime(app) -> None:
    clock = FakeMonotonicClock()
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        override_failing_location_persist_service(app, clock)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as websocket:
                assert websocket.receive_json()["type"] == "SESSION_READY"

                websocket.send_json(location_update_message(base_time))
                error_message = websocket.receive_json()
                assert error_message["type"] == "ERROR"
                assert error_message["payload"]["code"] == "LOCATION_PERSIST_FAILED"
                assert error_message["payload"]["recoverable"] is True
                assert len(client.portal.call(list_location_samples, data.active_session_id)) == 0

                runtime = app.state.session_runtime_registry._runtimes[data.active_session_id]
                assert runtime.current_latitude == 37.5501
                assert runtime.last_location_persisted_at is None
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)


def test_websocket_duplicate_connection_replaces_previous_connection(app) -> None:
    with TestClient(app) as client:
        data = client.portal.call(create_test_data)
        override_dependencies(app, data.current_account)
        base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)

        try:
            with client.websocket_connect(
                f"/ws/v1/driving-sessions/{data.active_session_id}"
            ) as first:
                assert first.receive_json()["type"] == "SESSION_READY"
                first.send_json(frame_meta_message(base_time, frame_id="frame-1"))
                first.send_bytes(minimal_jpeg())
                wait_for_condition(
                    lambda: client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["lastFrameId"]
                    == "frame-1"
                )
                receive_detection_update(
                    first,
                    session_id=data.active_session_id,
                    frame_id="frame-1",
                    captured_at=base_time,
                )

                with client.websocket_connect(
                    f"/ws/v1/driving-sessions/{data.active_session_id}"
                ) as second:
                    second_ready = second.receive_json()
                    assert second_ready["type"] == "SESSION_READY"
                    assert app.state.websocket_connection_manager.active_count == 1
                    assert app.state.session_runtime_registry.count == 1

                    with pytest.raises(WebSocketDisconnect) as exc_info:
                        first.receive_json()
                    assert exc_info.value.code == 4001
                    assert app.state.websocket_connection_manager.active_count == 1
                    assert app.state.session_runtime_registry.count == 1
                    assert client.portal.call(
                        list_runtime_frame_ids,
                        app,
                        data.active_session_id,
                    ) == []
                    assert client.portal.call(
                        get_runtime_inference_state,
                        app,
                        data.active_session_id,
                    )["processedFrameCount"] == 0

                    second.send_json(
                        frame_meta_message(base_time + timedelta(seconds=1), frame_id="frame-1")
                    )
                    second.send_bytes(minimal_jpeg())
                    wait_for_condition(
                        lambda: client.portal.call(
                            get_runtime_inference_state,
                            app,
                            data.active_session_id,
                        )["lastFrameId"]
                        == "frame-1"
                    )
                    receive_detection_update(
                        second,
                        session_id=data.active_session_id,
                        frame_id="frame-1",
                        captured_at=base_time + timedelta(seconds=1),
                    )

                wait_for_condition(lambda: app.state.websocket_connection_manager.active_count == 0)
                wait_for_condition(lambda: app.state.session_runtime_registry.count == 0)
        finally:
            app.dependency_overrides.clear()
            client.portal.call(delete_test_accounts, data.current_account.id, data.other_account.id)
