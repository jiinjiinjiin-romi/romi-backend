from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from app.ai.driver_monitoring import (
    DetectionBehaviorType,
    DetectionResult,
    ModelActionType,
)
from app.core.enums import BehaviorType

_EVENT_BEHAVIOR_BY_DETECTION = {
    DetectionBehaviorType.DROWSINESS: BehaviorType.DROWSINESS,
    DetectionBehaviorType.PHONE_USE: BehaviorType.PHONE_USE,
    DetectionBehaviorType.FOOD_OR_DRINK: BehaviorType.FOOD_OR_DRINK,
    DetectionBehaviorType.GAZE_AWAY: BehaviorType.GAZE_AWAY,
    DetectionBehaviorType.SECONDARY_TASK: BehaviorType.SECONDARY_TASK,
    DetectionBehaviorType.REACHING_BEHIND: BehaviorType.REACHING_BEHIND,
    DetectionBehaviorType.SMOKING: BehaviorType.SMOKING,
}
_DETECTION_BEHAVIOR_TIE_ORDER = {
    behavior_type: index for index, behavior_type in enumerate(DetectionBehaviorType)
}
_MODEL_ACTION_TIE_ORDER = {
    action_type: index for index, action_type in enumerate(ModelActionType)
}


class BehaviorTransitionType(StrEnum):
    NONE = "NONE"
    STARTED = "STARTED"
    UPDATED = "UPDATED"
    CLEARED = "CLEARED"


@dataclass(frozen=True, slots=True)
class SlidingWindowBehaviorConfig:
    window_size: int = 5
    min_confidence: float = 0.75
    min_hit_count: int = 3
    min_hit_ratio: float = 0.6
    clear_hit_count: int = 3
    clear_hit_ratio: float = 0.6
    allow_update_transition: bool = True

    def __post_init__(self) -> None:
        if self.window_size <= 0:
            raise ValueError("Sliding window size must be positive.")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("Sliding window min_confidence must be between 0 and 1.")
        if self.min_hit_count <= 0:
            raise ValueError("Sliding window min_hit_count must be positive.")
        if self.clear_hit_count <= 0:
            raise ValueError("Sliding window clear_hit_count must be positive.")
        if self.min_hit_count > self.window_size:
            raise ValueError("Sliding window min_hit_count must not exceed window_size.")
        if self.clear_hit_count > self.window_size:
            raise ValueError("Sliding window clear_hit_count must not exceed window_size.")
        if not 0.0 <= self.min_hit_ratio <= 1.0:
            raise ValueError("Sliding window min_hit_ratio must be between 0 and 1.")
        if not 0.0 <= self.clear_hit_ratio <= 1.0:
            raise ValueError("Sliding window clear_hit_ratio must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class BehaviorTransition:
    transition_type: BehaviorTransitionType
    detection_behavior_type: DetectionBehaviorType | None
    event_behavior_type: BehaviorType | None
    dominant_model_action_type: ModelActionType | None
    dominant_model_class_code: str | None
    dominant_model_class_label: str | None
    confidence: float | None
    average_confidence: float | None
    maximum_confidence: float | None
    hit_ratio: float
    hit_count: int
    sample_count: int
    started_at: datetime | None
    last_seen_at: datetime | None
    frame_id: str | None
    captured_at: datetime | None

    @classmethod
    def none(cls, *, sample_count: int = 0) -> Self:
        return cls(
            transition_type=BehaviorTransitionType.NONE,
            detection_behavior_type=None,
            event_behavior_type=None,
            dominant_model_action_type=None,
            dominant_model_class_code=None,
            dominant_model_class_label=None,
            confidence=None,
            average_confidence=None,
            maximum_confidence=None,
            hit_ratio=0.0,
            hit_count=0,
            sample_count=sample_count,
            started_at=None,
            last_seen_at=None,
            frame_id=None,
            captured_at=None,
        )


@dataclass(frozen=True, slots=True)
class _BehaviorWindowSummary:
    behavior_type: DetectionBehaviorType
    event_behavior_type: BehaviorType | None
    dominant_model_action_type: ModelActionType
    dominant_model_class_code: str
    dominant_model_class_label: str
    average_confidence: float
    maximum_confidence: float
    hit_ratio: float
    hit_count: int
    sample_count: int
    started_at: datetime
    last_seen_at: datetime
    frame_id: str
    captured_at: datetime


class SlidingWindowBehaviorPolicy:
    def __init__(self, config: SlidingWindowBehaviorConfig | None = None) -> None:
        self.config = config or SlidingWindowBehaviorConfig()
        self._samples: deque[DetectionResult] = deque()
        self._frame_ids: set[str] = set()
        self._active_behavior_type: DetectionBehaviorType | None = None
        self._active_model_action_type: ModelActionType | None = None
        self._active_started_at: datetime | None = None

    @property
    def active_behavior_type(self) -> DetectionBehaviorType | None:
        return self._active_behavior_type

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def reset(self) -> None:
        self._samples.clear()
        self._frame_ids.clear()
        self._clear_active()

    def observe(self, result: DetectionResult) -> BehaviorTransition:
        if result.frame_id in self._frame_ids:
            return BehaviorTransition.none(sample_count=len(self._eligible_samples()))

        self._append_sample(result)
        eligible_samples = self._eligible_samples()
        if not eligible_samples:
            return BehaviorTransition.none()

        if self._active_behavior_type is not None:
            clear_summary = self._summarize_behavior(
                DetectionBehaviorType.NORMAL,
                eligible_samples,
            )
            if clear_summary is not None and self._meets_clear_threshold(clear_summary):
                transition = self._transition_from_summary(
                    BehaviorTransitionType.CLEARED,
                    clear_summary,
                    started_at=self._active_started_at,
                )
                self._clear_active()
                return transition

        abnormal_summary = self._dominant_abnormal_summary(eligible_samples)
        if abnormal_summary is None or not self._meets_start_threshold(abnormal_summary):
            return BehaviorTransition.none(sample_count=len(eligible_samples))

        if self._active_behavior_type is None:
            self._set_active(abnormal_summary)
            return self._transition_from_summary(
                BehaviorTransitionType.STARTED,
                abnormal_summary,
            )

        if abnormal_summary.behavior_type != self._active_behavior_type:
            self._set_active(abnormal_summary)
            if self.config.allow_update_transition:
                return self._transition_from_summary(
                    BehaviorTransitionType.UPDATED,
                    abnormal_summary,
                )
            return BehaviorTransition.none(sample_count=len(eligible_samples))

        if abnormal_summary.dominant_model_action_type != self._active_model_action_type:
            self._active_model_action_type = abnormal_summary.dominant_model_action_type
            if self.config.allow_update_transition:
                return self._transition_from_summary(
                    BehaviorTransitionType.UPDATED,
                    abnormal_summary,
                    started_at=self._active_started_at,
                )

        return BehaviorTransition.none(sample_count=len(eligible_samples))

    def _append_sample(self, result: DetectionResult) -> None:
        if len(self._samples) >= self.config.window_size:
            dropped = self._samples.popleft()
            self._frame_ids.discard(dropped.frame_id)
        self._samples.append(result)
        self._frame_ids.add(result.frame_id)

    def _eligible_samples(self) -> tuple[DetectionResult, ...]:
        return tuple(
            sample
            for sample in self._samples
            if sample.confidence >= self.config.min_confidence
        )

    def _dominant_abnormal_summary(
        self,
        samples: tuple[DetectionResult, ...],
    ) -> _BehaviorWindowSummary | None:
        summaries = [
            summary
            for behavior_type in _EVENT_BEHAVIOR_BY_DETECTION
            if (
                summary := self._summarize_behavior(
                    behavior_type,
                    samples,
                )
            )
            is not None
        ]
        if not summaries:
            return None

        return max(
            summaries,
            key=lambda summary: (
                summary.hit_count,
                summary.average_confidence,
                summary.maximum_confidence,
                -_DETECTION_BEHAVIOR_TIE_ORDER[summary.behavior_type],
            ),
        )

    def _summarize_behavior(
        self,
        behavior_type: DetectionBehaviorType,
        samples: tuple[DetectionResult, ...],
    ) -> _BehaviorWindowSummary | None:
        matching_samples = tuple(
            sample for sample in samples if sample.behavior_type == behavior_type
        )
        if not matching_samples:
            return None

        dominant_action = self._dominant_model_action_type(matching_samples)
        dominant_action_samples = tuple(
            sample
            for sample in matching_samples
            if sample.model_action_type == dominant_action
        )
        latest_sample = max(
            dominant_action_samples,
            key=lambda sample: (sample.captured_at, sample.frame_id),
        )
        first_sample = min(
            matching_samples,
            key=lambda sample: (sample.captured_at, sample.frame_id),
        )
        last_sample = max(
            matching_samples,
            key=lambda sample: (sample.captured_at, sample.frame_id),
        )
        confidence_sum = sum(sample.confidence for sample in matching_samples)
        average_confidence = confidence_sum / len(matching_samples)

        return _BehaviorWindowSummary(
            behavior_type=behavior_type,
            event_behavior_type=detection_behavior_to_event_behavior_type(behavior_type),
            dominant_model_action_type=dominant_action,
            dominant_model_class_code=latest_sample.model_class_code,
            dominant_model_class_label=latest_sample.model_class_label,
            average_confidence=average_confidence,
            maximum_confidence=max(sample.confidence for sample in matching_samples),
            hit_ratio=len(matching_samples) / len(samples),
            hit_count=len(matching_samples),
            sample_count=len(samples),
            started_at=first_sample.captured_at,
            last_seen_at=last_sample.captured_at,
            frame_id=last_sample.frame_id,
            captured_at=last_sample.captured_at,
        )

    def _dominant_model_action_type(
        self,
        samples: tuple[DetectionResult, ...],
    ) -> ModelActionType:
        action_types = {sample.model_action_type for sample in samples}

        return max(
            action_types,
            key=lambda action_type: (
                self._action_hit_count(action_type, samples),
                self._action_average_confidence(action_type, samples),
                self._action_maximum_confidence(action_type, samples),
                -_MODEL_ACTION_TIE_ORDER[action_type],
            ),
        )

    @staticmethod
    def _action_hit_count(
        action_type: ModelActionType,
        samples: tuple[DetectionResult, ...],
    ) -> int:
        return sum(1 for sample in samples if sample.model_action_type == action_type)

    @staticmethod
    def _action_average_confidence(
        action_type: ModelActionType,
        samples: tuple[DetectionResult, ...],
    ) -> float:
        action_samples = tuple(
            sample for sample in samples if sample.model_action_type == action_type
        )
        return sum(sample.confidence for sample in action_samples) / len(action_samples)

    @staticmethod
    def _action_maximum_confidence(
        action_type: ModelActionType,
        samples: tuple[DetectionResult, ...],
    ) -> float:
        return max(
            sample.confidence
            for sample in samples
            if sample.model_action_type == action_type
        )

    def _meets_start_threshold(self, summary: _BehaviorWindowSummary) -> bool:
        return (
            summary.event_behavior_type is not None
            and summary.hit_count >= self.config.min_hit_count
            and summary.hit_ratio >= self.config.min_hit_ratio
        )

    def _meets_clear_threshold(self, summary: _BehaviorWindowSummary) -> bool:
        return (
            summary.behavior_type == DetectionBehaviorType.NORMAL
            and summary.hit_count >= self.config.clear_hit_count
            and summary.hit_ratio >= self.config.clear_hit_ratio
        )

    def _transition_from_summary(
        self,
        transition_type: BehaviorTransitionType,
        summary: _BehaviorWindowSummary,
        *,
        started_at: datetime | None = None,
    ) -> BehaviorTransition:
        return BehaviorTransition(
            transition_type=transition_type,
            detection_behavior_type=summary.behavior_type,
            event_behavior_type=summary.event_behavior_type,
            dominant_model_action_type=summary.dominant_model_action_type,
            dominant_model_class_code=summary.dominant_model_class_code,
            dominant_model_class_label=summary.dominant_model_class_label,
            confidence=summary.average_confidence,
            average_confidence=summary.average_confidence,
            maximum_confidence=summary.maximum_confidence,
            hit_ratio=summary.hit_ratio,
            hit_count=summary.hit_count,
            sample_count=summary.sample_count,
            started_at=started_at or summary.started_at,
            last_seen_at=summary.last_seen_at,
            frame_id=summary.frame_id,
            captured_at=summary.captured_at,
        )

    def _set_active(self, summary: _BehaviorWindowSummary) -> None:
        self._active_behavior_type = summary.behavior_type
        self._active_model_action_type = summary.dominant_model_action_type
        self._active_started_at = summary.started_at

    def _clear_active(self) -> None:
        self._active_behavior_type = None
        self._active_model_action_type = None
        self._active_started_at = None


def detection_behavior_to_event_behavior_type(
    behavior_type: DetectionBehaviorType,
) -> BehaviorType | None:
    return _EVENT_BEHAVIOR_BY_DETECTION.get(behavior_type)
