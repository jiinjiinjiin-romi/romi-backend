from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection

from app.ai.driver_monitoring import DetectionBehaviorType, DetectionResult, InferenceFrame
from app.ai.prediction_mapper import metadata_from_class_index
from app.api.dependencies import get_driver_monitoring_adapter
from app.core.exceptions import AppException
from app.main import create_app


class ClosingAdapter:
    model_version = "vit-lifecycle-test"

    def __init__(self) -> None:
        self.closed = 0

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
        metadata = metadata_from_class_index(0)
        return DetectionResult(
            session_id=frame.session_id,
            frame_id=frame.frame_id,
            model_action_type=metadata.action_type,
            model_class_code=metadata.class_code,
            model_class_label=metadata.class_label,
            behavior_type=DetectionBehaviorType.NORMAL,
            confidence=0.99,
            model_version=self.model_version,
            captured_at=frame.captured_at,
            inference_started_at=timestamp,
            inference_completed_at=timestamp,
            inference_latency_ms=0,
        )

    async def aclose(self) -> None:
        self.closed += 1


def test_lifespan_creates_one_app_scoped_adapter_and_closes_it(monkeypatch) -> None:
    adapter = ClosingAdapter()
    created_modes: list[str] = []

    def create_adapter(settings):
        created_modes.append(settings.driver_monitoring_adapter)
        return adapter

    monkeypatch.setattr("app.main.create_driver_monitoring_adapter", create_adapter)
    app = create_app()

    with TestClient(app):
        assert app.state.driver_monitoring_adapter is adapter
        assert len(created_modes) == 1

    assert adapter.closed == 1
    assert not hasattr(app.state, "driver_monitoring_adapter")


def test_get_driver_monitoring_adapter_returns_app_state_instance() -> None:
    app = FastAPI()
    adapter = ClosingAdapter()
    app.state.driver_monitoring_adapter = adapter
    connection = HTTPConnection({"type": "http", "app": app, "headers": []})

    assert get_driver_monitoring_adapter(connection) is adapter


def test_get_driver_monitoring_adapter_fails_when_state_is_missing() -> None:
    app = FastAPI()
    connection = HTTPConnection({"type": "http", "app": app, "headers": []})

    with pytest.raises(AppException) as exc_info:
        get_driver_monitoring_adapter(connection)

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "INTERNAL_SERVER_ERROR"
