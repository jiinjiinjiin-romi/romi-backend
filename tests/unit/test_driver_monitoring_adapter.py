from datetime import UTC, datetime

import pytest

from app.ai.driver_monitoring import (
    DetectionBehaviorType,
    DetectionResult,
    InferenceFrame,
)
from app.ai.mock_vit_adapter import MockViTAdapter
from app.core.config import Settings
from app.integrations.driver_monitoring import (
    close_driver_monitoring_adapter,
    create_driver_monitoring_adapter,
)


def inference_frame(frame_id: str = "frame-1") -> InferenceFrame:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    return InferenceFrame(
        session_id="session-1",
        request_id="6a972e7b-2151-4997-acbd-19b01facb6b0",
        frame_id=frame_id,
        captured_at=timestamp,
        occurred_at=timestamp,
        format="JPEG",
        width=640,
        height=360,
        jpeg_bytes=b"\xff\xd8\xff\xd9",
        received_at=timestamp,
    )


@pytest.mark.asyncio
async def test_mock_vit_adapter_returns_deterministic_normal_result() -> None:
    adapter = MockViTAdapter(model_version="vit-test", latency_ms=0)

    result = await adapter.predict(inference_frame("frame-123"))

    assert await adapter.is_ready() is True
    assert adapter.model_version == "vit-test"
    assert result.session_id == "session-1"
    assert result.frame_id == "frame-123"
    assert result.behavior_type == DetectionBehaviorType.NORMAL
    assert result.confidence == 0.99
    assert result.model_version == "vit-test"
    assert result.inference_latency_ms >= 0


@pytest.mark.asyncio
async def test_mock_vit_adapter_uses_async_latency(monkeypatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.ai.mock_vit_adapter.asyncio.sleep", fake_sleep)
    adapter = MockViTAdapter(model_version="vit-test", latency_ms=25)

    await adapter.predict(inference_frame())

    assert sleeps == [0.025]


def test_detection_result_validates_internal_contract() -> None:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)

    with pytest.raises(ValueError):
        DetectionResult(
            session_id="session-1",
            frame_id="frame-1",
            behavior_type=DetectionBehaviorType.NORMAL,
            confidence=1.01,
            model_version="vit-test",
            captured_at=timestamp,
            inference_started_at=timestamp,
            inference_completed_at=timestamp,
            inference_latency_ms=0,
        )


@pytest.mark.asyncio
async def test_adapter_provider_selects_mock_and_unavailable_real_modes() -> None:
    mock = create_driver_monitoring_adapter(Settings(driver_monitoring_adapter="MOCK"))
    real = create_driver_monitoring_adapter(Settings(driver_monitoring_adapter="REAL"))

    assert await mock.is_ready() is True
    assert await real.is_ready() is False
    with pytest.raises(RuntimeError):
        await real.predict(inference_frame())


@pytest.mark.asyncio
async def test_close_driver_monitoring_adapter_uses_optional_async_close_hook() -> None:
    class ClosingAdapter:
        model_version = "vit-test"

        def __init__(self) -> None:
            self.closed = False

        async def is_ready(self) -> bool:
            return True

        async def predict(self, frame: InferenceFrame) -> DetectionResult:
            return DetectionResult(
                session_id=frame.session_id,
                frame_id=frame.frame_id,
                behavior_type=DetectionBehaviorType.NORMAL,
                confidence=0.99,
                model_version=self.model_version,
                captured_at=frame.captured_at,
                inference_started_at=frame.received_at,
                inference_completed_at=frame.received_at,
                inference_latency_ms=0,
            )

        async def aclose(self) -> None:
            self.closed = True

    adapter = ClosingAdapter()

    await close_driver_monitoring_adapter(adapter)

    assert adapter.closed is True


@pytest.mark.asyncio
async def test_close_driver_monitoring_adapter_is_noop_without_close_hook() -> None:
    class AdapterWithoutClose:
        model_version = "vit-test"

        async def is_ready(self) -> bool:
            return True

        async def predict(self, frame: InferenceFrame) -> DetectionResult:
            raise AssertionError("predict should not be called")

    await close_driver_monitoring_adapter(AdapterWithoutClose())
