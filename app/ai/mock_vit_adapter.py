from __future__ import annotations

import asyncio

from app.ai.driver_monitoring import (
    DetectionResult,
    InferenceFrame,
    ModelActionType,
)
from app.ai.prediction_mapper import metadata_from_action_type
from app.core.time import utc_now_for_api_response


class MockViTAdapter:
    def __init__(self, *, model_version: str, latency_ms: int = 0) -> None:
        if latency_ms < 0 or latency_ms > 10000:
            raise ValueError("Mock ViT latency must be between 0 and 10000 ms.")
        self._model_version = model_version
        self._latency_ms = latency_ms

    @property
    def model_version(self) -> str:
        return self._model_version

    async def is_ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        started_at = utc_now_for_api_response()
        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000)
        completed_at = utc_now_for_api_response()
        latency_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        metadata = metadata_from_action_type(ModelActionType.SAFE_DRIVING)

        return DetectionResult(
            session_id=frame.session_id,
            frame_id=frame.frame_id,
            model_action_type=metadata.action_type,
            model_class_code=metadata.class_code,
            model_class_label=metadata.class_label,
            behavior_type=metadata.detection_behavior_type,
            confidence=0.99,
            model_version=self.model_version,
            captured_at=frame.captured_at,
            inference_started_at=started_at,
            inference_completed_at=completed_at,
            inference_latency_ms=latency_ms,
        )
