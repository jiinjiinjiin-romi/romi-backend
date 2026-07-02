from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class DetectionBehaviorType(StrEnum):
    NORMAL = "NORMAL"
    DROWSINESS = "DROWSINESS"
    PHONE_USE = "PHONE_USE"
    FOOD_OR_DRINK = "FOOD_OR_DRINK"
    GAZE_AWAY = "GAZE_AWAY"


@dataclass(frozen=True, slots=True)
class InferenceFrame:
    session_id: str
    request_id: str
    frame_id: str
    captured_at: datetime
    occurred_at: datetime
    format: str
    width: int
    height: int
    jpeg_bytes: bytes
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DetectionResult:
    session_id: str
    frame_id: str
    behavior_type: DetectionBehaviorType
    confidence: float
    model_version: str
    captured_at: datetime
    inference_started_at: datetime
    inference_completed_at: datetime
    inference_latency_ms: int

    def __post_init__(self) -> None:
        if not self.frame_id:
            raise ValueError("DetectionResult frame_id must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("DetectionResult confidence must be between 0 and 1.")
        if not self.model_version.strip():
            raise ValueError("DetectionResult model_version must not be empty.")
        if self.inference_latency_ms < 0:
            raise ValueError("DetectionResult latency must be non-negative.")

        for field_name in (
            "captured_at",
            "inference_started_at",
            "inference_completed_at",
        ):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"DetectionResult {field_name} must be timezone-aware.")
        if self.inference_completed_at < self.inference_started_at:
            raise ValueError("DetectionResult completion time must not precede start time.")


class DriverMonitoringAdapter(Protocol):
    @property
    def model_version(self) -> str:
        pass

    async def is_ready(self) -> bool:
        pass

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        pass

    async def aclose(self) -> None:
        pass
