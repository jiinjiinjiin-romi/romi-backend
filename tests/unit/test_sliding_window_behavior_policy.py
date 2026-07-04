from datetime import UTC, datetime, timedelta

import pytest

from app.ai.driver_monitoring import (
    DetectionBehaviorType,
    DetectionResult,
    ModelActionType,
)
from app.ai.prediction_mapper import metadata_from_action_type
from app.core.enums import BehaviorType
from app.policies.sliding_window_behavior_policy import (
    BehaviorTransitionType,
    SlidingWindowBehaviorConfig,
    SlidingWindowBehaviorPolicy,
    detection_behavior_to_event_behavior_type,
)

BASE_TIME = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)


def detection_result(
    action_type: ModelActionType,
    frame_number: int,
    *,
    confidence: float = 0.9,
) -> DetectionResult:
    metadata = metadata_from_action_type(action_type)
    captured_at = BASE_TIME + timedelta(milliseconds=frame_number)
    completed_at = captured_at + timedelta(milliseconds=1)

    return DetectionResult(
        session_id="session-1",
        frame_id=f"frame-{frame_number}",
        model_action_type=action_type,
        model_class_code=metadata.class_code,
        model_class_label=metadata.class_label,
        behavior_type=metadata.detection_behavior_type,
        confidence=confidence,
        model_version="vit-dms-test",
        captured_at=captured_at,
        inference_started_at=captured_at,
        inference_completed_at=completed_at,
        inference_latency_ms=1,
    )


def observe_many(
    policy: SlidingWindowBehaviorPolicy,
    action_type: ModelActionType,
    frame_numbers: list[int],
    *,
    confidence: float = 0.9,
) -> list[BehaviorTransitionType]:
    return [
        policy.observe(
            detection_result(action_type, frame_number, confidence=confidence),
        ).transition_type
        for frame_number in frame_numbers
    ]


def test_phone_use_starts_when_window_threshold_is_met() -> None:
    policy = SlidingWindowBehaviorPolicy()

    assert observe_many(policy, ModelActionType.WRITING_MSG_RIGHT, [1, 2]) == [
        BehaviorTransitionType.NONE,
        BehaviorTransitionType.NONE,
    ]
    transition = policy.observe(detection_result(ModelActionType.WRITING_MSG_RIGHT, 3))

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.detection_behavior_type == DetectionBehaviorType.PHONE_USE
    assert transition.event_behavior_type == BehaviorType.PHONE_USE
    assert transition.dominant_model_action_type == ModelActionType.WRITING_MSG_RIGHT
    assert transition.hit_count == 3
    assert transition.hit_ratio == 1.0
    assert transition.sample_count == 3


def test_active_phone_use_does_not_emit_duplicate_started() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.WRITING_MSG_RIGHT, [1, 2, 3])
    transition = policy.observe(detection_result(ModelActionType.WRITING_MSG_RIGHT, 4))

    assert transition.transition_type == BehaviorTransitionType.NONE
    assert policy.active_behavior_type == DetectionBehaviorType.PHONE_USE


def test_normal_clears_active_behavior_after_clear_threshold() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.WRITING_MSG_RIGHT, [1, 2, 3])
    assert observe_many(policy, ModelActionType.SAFE_DRIVING, [4, 5]) == [
        BehaviorTransitionType.NONE,
        BehaviorTransitionType.NONE,
    ]
    transition = policy.observe(detection_result(ModelActionType.SAFE_DRIVING, 6))

    assert transition.transition_type == BehaviorTransitionType.CLEARED
    assert transition.detection_behavior_type == DetectionBehaviorType.NORMAL
    assert transition.event_behavior_type is None
    assert transition.dominant_model_action_type == ModelActionType.SAFE_DRIVING
    assert transition.hit_count == 3
    assert transition.hit_ratio == 0.6
    assert policy.active_behavior_type is None


def test_normal_without_active_behavior_does_not_clear() -> None:
    policy = SlidingWindowBehaviorPolicy()

    transitions = observe_many(policy, ModelActionType.SAFE_DRIVING, [1, 2, 3, 4, 5])

    assert transitions == [BehaviorTransitionType.NONE] * 5
    assert policy.active_behavior_type is None


def test_single_abnormal_frame_is_suppressed() -> None:
    policy = SlidingWindowBehaviorPolicy()

    transition = policy.observe(detection_result(ModelActionType.TALKING_PHONE_LEFT, 1))

    assert transition.transition_type == BehaviorTransitionType.NONE
    assert policy.active_behavior_type is None


def test_low_confidence_detection_is_not_counted_as_hit() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.WRITING_MSG_RIGHT, [1, 2])
    transition = policy.observe(
        detection_result(ModelActionType.WRITING_MSG_RIGHT, 3, confidence=0.749),
    )

    assert transition.transition_type == BehaviorTransitionType.NONE
    assert transition.sample_count == 2
    assert policy.active_behavior_type is None


def test_confidence_threshold_boundary_is_inclusive() -> None:
    policy = SlidingWindowBehaviorPolicy(
        SlidingWindowBehaviorConfig(
            window_size=2,
            min_hit_count=2,
            min_hit_ratio=1.0,
            clear_hit_count=2,
            clear_hit_ratio=1.0,
        ),
    )

    assert (
        policy.observe(
            detection_result(ModelActionType.TALKING_PHONE_RIGHT, 1, confidence=0.75),
        ).transition_type
        == BehaviorTransitionType.NONE
    )
    transition = policy.observe(
        detection_result(ModelActionType.TALKING_PHONE_RIGHT, 2, confidence=0.75),
    )

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.hit_count == 2


def test_secondary_task_starts_and_preserves_dominant_model_action() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.GPS_OPERATING, [1, 2])
    transition = policy.observe(detection_result(ModelActionType.GPS_OPERATING, 3))

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.detection_behavior_type == DetectionBehaviorType.SECONDARY_TASK
    assert transition.event_behavior_type == BehaviorType.SECONDARY_TASK
    assert transition.dominant_model_action_type == ModelActionType.GPS_OPERATING
    assert transition.dominant_model_class_code == "AC4"
    assert transition.dominant_model_class_label == "gps_operating"


def test_secondary_task_dominant_action_tie_break_is_deterministic() -> None:
    policy = SlidingWindowBehaviorPolicy(
        SlidingWindowBehaviorConfig(
            window_size=4,
            min_hit_count=4,
            min_hit_ratio=1.0,
            clear_hit_count=3,
            clear_hit_ratio=0.75,
        ),
    )

    policy.observe(detection_result(ModelActionType.GPS_OPERATING, 1))
    policy.observe(detection_result(ModelActionType.TALKING_PASSENGER, 2))
    policy.observe(detection_result(ModelActionType.TALKING_PASSENGER, 3))
    transition = policy.observe(detection_result(ModelActionType.GPS_OPERATING, 4))

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.dominant_model_action_type == ModelActionType.GPS_OPERATING
    assert transition.event_behavior_type == BehaviorType.SECONDARY_TASK


@pytest.mark.parametrize(
    ("action_type", "expected_behavior_type"),
    [
        (ModelActionType.REACHING_BEHIND, BehaviorType.REACHING_BEHIND),
        (ModelActionType.SMOKING, BehaviorType.SMOKING),
        (ModelActionType.FATIGUE_SOMNOLENCE, BehaviorType.DROWSINESS),
        (ModelActionType.DRINKING_RIGHT, BehaviorType.FOOD_OR_DRINK),
    ],
)
def test_supported_abnormal_behaviors_can_start(
    action_type: ModelActionType,
    expected_behavior_type: BehaviorType,
) -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, action_type, [1, 2])
    transition = policy.observe(detection_result(action_type, 3))

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.event_behavior_type == expected_behavior_type


def test_detection_behavior_to_event_behavior_type_never_maps_normal() -> None:
    assert detection_behavior_to_event_behavior_type(DetectionBehaviorType.NORMAL) is None
    assert (
        detection_behavior_to_event_behavior_type(DetectionBehaviorType.PHONE_USE)
        == BehaviorType.PHONE_USE
    )
    assert "NORMAL" not in {behavior_type.value for behavior_type in BehaviorType}


def test_model_action_type_is_not_treated_as_event_behavior_type() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.GPS_OPERATING, [1, 2])
    transition = policy.observe(detection_result(ModelActionType.GPS_OPERATING, 3))

    assert transition.event_behavior_type == BehaviorType.SECONDARY_TASK
    assert transition.dominant_model_action_type == ModelActionType.GPS_OPERATING
    assert ModelActionType.GPS_OPERATING.value not in {
        behavior_type.value for behavior_type in BehaviorType
    }


def test_reset_clears_samples_and_active_behavior() -> None:
    policy = SlidingWindowBehaviorPolicy()

    observe_many(policy, ModelActionType.WRITING_MSG_RIGHT, [1, 2, 3])
    assert policy.active_behavior_type == DetectionBehaviorType.PHONE_USE

    policy.reset()
    normal_transition = policy.observe(detection_result(ModelActionType.SAFE_DRIVING, 4))
    abnormal_transition = policy.observe(detection_result(ModelActionType.WRITING_MSG_RIGHT, 5))

    assert normal_transition.transition_type == BehaviorTransitionType.NONE
    assert abnormal_transition.transition_type == BehaviorTransitionType.NONE
    assert policy.active_behavior_type is None
    assert policy.sample_count == 2


def test_old_samples_are_removed_when_window_size_is_exceeded() -> None:
    policy = SlidingWindowBehaviorPolicy(
        SlidingWindowBehaviorConfig(
            window_size=3,
            min_hit_count=2,
            min_hit_ratio=0.5,
            clear_hit_count=2,
            clear_hit_ratio=0.5,
        ),
    )

    policy.observe(detection_result(ModelActionType.WRITING_MSG_RIGHT, 1))
    policy.observe(detection_result(ModelActionType.SAFE_DRIVING, 2))
    policy.observe(detection_result(ModelActionType.SAFE_DRIVING, 3))
    transition = policy.observe(detection_result(ModelActionType.WRITING_MSG_RIGHT, 4))

    assert transition.transition_type == BehaviorTransitionType.NONE
    assert transition.sample_count == 3
    assert policy.sample_count == 3


def test_transition_preserves_frame_and_captured_at_metadata() -> None:
    policy = SlidingWindowBehaviorPolicy()

    first_frame = detection_result(ModelActionType.TALKING_PHONE_RIGHT, 1)
    second_frame = detection_result(ModelActionType.TALKING_PHONE_RIGHT, 2)
    third_frame = detection_result(ModelActionType.TALKING_PHONE_RIGHT, 3)

    policy.observe(first_frame)
    policy.observe(second_frame)
    transition = policy.observe(third_frame)

    assert transition.transition_type == BehaviorTransitionType.STARTED
    assert transition.started_at == first_frame.captured_at
    assert transition.last_seen_at == third_frame.captured_at
    assert transition.frame_id == third_frame.frame_id
    assert transition.captured_at == third_frame.captured_at
