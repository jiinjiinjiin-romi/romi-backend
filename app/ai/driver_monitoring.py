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
    SECONDARY_TASK = "SECONDARY_TASK"
    REACHING_BEHIND = "REACHING_BEHIND"
    SMOKING = "SMOKING"


class ModelActionType(StrEnum):
    SAFE_DRIVING = "SAFE_DRIVING"
    HAIR_MAKEUP = "HAIR_MAKEUP"
    ADJUSTING_RADIO = "ADJUSTING_RADIO"
    GPS_OPERATING = "GPS_OPERATING"
    WRITING_MSG_RIGHT = "WRITING_MSG_RIGHT"
    WRITING_MSG_LEFT = "WRITING_MSG_LEFT"
    TALKING_PHONE_RIGHT = "TALKING_PHONE_RIGHT"
    TALKING_PHONE_LEFT = "TALKING_PHONE_LEFT"
    TAKING_PICTURE = "TAKING_PICTURE"
    TALKING_PASSENGER = "TALKING_PASSENGER"
    SINGING_DANCING = "SINGING_DANCING"
    FATIGUE_SOMNOLENCE = "FATIGUE_SOMNOLENCE"
    DRINKING_RIGHT = "DRINKING_RIGHT"
    DRINKING_LEFT = "DRINKING_LEFT"
    REACHING_BEHIND = "REACHING_BEHIND"
    SMOKING = "SMOKING"


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
    model_action_type: ModelActionType
    model_class_code: str
    model_class_label: str
    behavior_type: DetectionBehaviorType
    confidence: float
    model_version: str
    captured_at: datetime
    inference_started_at: datetime
    inference_completed_at: datetime
    inference_latency_ms: int

    def __post_init__(self) -> None:
        from app.ai.prediction_mapper import metadata_from_action_type

        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("DetectionResult session_id must not be empty.")
        if not isinstance(self.frame_id, str) or not self.frame_id:
            raise ValueError("DetectionResult frame_id must not be empty.")
        if not isinstance(self.model_class_code, str) or not self.model_class_code.strip():
            raise ValueError("DetectionResult model_class_code must not be empty.")
        if not isinstance(self.model_class_label, str) or not self.model_class_label.strip():
            raise ValueError("DetectionResult model_class_label must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("DetectionResult confidence must be between 0 and 1.")
        if not isinstance(self.model_version, str) or not self.model_version.strip():
            raise ValueError("DetectionResult model_version must not be empty.")
        if self.inference_latency_ms < 0:
            raise ValueError("DetectionResult latency must be non-negative.")

        metadata = metadata_from_action_type(self.model_action_type)
        if self.model_class_code != metadata.class_code:
            raise ValueError("DetectionResult model_class_code does not match model_action_type.")
        if self.model_class_label != metadata.class_label:
            raise ValueError("DetectionResult model_class_label does not match model_action_type.")
        if self.behavior_type != metadata.detection_behavior_type:
            raise ValueError("DetectionResult behavior_type does not match model_action_type.")

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
