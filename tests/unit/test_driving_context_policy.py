from app.core.enums import DrivingSessionStatus, DrivingState
from app.policies.driving_context_policy import DrivingContextPolicy


def test_driving_context_policy_uses_configured_thresholds() -> None:
    policy = DrivingContextPolicy(
        moving_speed_threshold_kph=10.0,
        max_accuracy_meters=50.0,
    )

    assert (
        policy.determine_state(
            speed_kph=9.99,
            accuracy_meters=20.0,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        == DrivingState.TEMPORARY_STOP
    )
    assert (
        policy.determine_state(
            speed_kph=10.0,
            accuracy_meters=20.0,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        == DrivingState.MOVING
    )


def test_driving_context_policy_returns_unknown_for_missing_or_poor_location_data() -> None:
    policy = DrivingContextPolicy(
        moving_speed_threshold_kph=5.0,
        max_accuracy_meters=100.0,
    )

    assert (
        policy.determine_state(
            speed_kph=None,
            accuracy_meters=None,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        == DrivingState.UNKNOWN
    )
    assert (
        policy.determine_state(
            speed_kph=70.0,
            accuracy_meters=100.01,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        == DrivingState.UNKNOWN
    )
    assert (
        policy.determine_state(
            speed_kph=70.0,
            accuracy_meters=10.0,
            session_status=DrivingSessionStatus.COMPLETED.value,
        )
        == DrivingState.UNKNOWN
    )


def test_driving_context_policy_never_generates_parked_from_location_update() -> None:
    policy = DrivingContextPolicy(
        moving_speed_threshold_kph=5.0,
        max_accuracy_meters=100.0,
    )

    states = {
        policy.determine_state(
            speed_kph=speed,
            accuracy_meters=accuracy,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        for speed, accuracy in [
            (None, None),
            (0.0, None),
            (4.99, 10.0),
            (5.0, 10.0),
            (80.0, 120.0),
        ]
    }

    assert DrivingState.PARKED not in states
