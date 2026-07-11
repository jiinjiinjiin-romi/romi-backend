import pytest
from pydantic import ValidationError

from app.schemas.behavior_sensitivity import DriveSummaryRequest


def valid_events() -> list[dict[str, object]]:
    return [
        {"behaviorType": "DROWSINESS", "clickCount": 0, "level": 1},
        {"behaviorType": "PHONE_USE", "clickCount": 1, "level": 2},
        {"behaviorType": "FOOD_OR_DRINK", "clickCount": 2, "level": 3},
        {"behaviorType": "SECONDARY_TASK", "clickCount": 3, "level": 3},
    ]


def test_drive_summary_requires_exactly_the_four_manual_risk_behavior_types() -> None:
    request = DriveSummaryRequest(telemetryEvents=valid_events())

    assert len(request.telemetry_events) == 4

    with pytest.raises(ValidationError):
        DriveSummaryRequest(telemetryEvents=valid_events()[:3])

    with pytest.raises(ValidationError):
        DriveSummaryRequest(
            telemetryEvents=[
                *valid_events()[:3],
                {"behaviorType": "DROWSINESS", "clickCount": 3, "level": 3},
            ]
        )

    with pytest.raises(ValidationError):
        DriveSummaryRequest(
            telemetryEvents=[
                *valid_events()[:3],
                {"behaviorType": "GAZE_AWAY", "clickCount": 3, "level": 3},
            ]
        )

    with pytest.raises(ValidationError):
        DriveSummaryRequest(
            telemetryEvents=[{**event, "clickCount": True} for event in valid_events()]
        )

    zero_level = DriveSummaryRequest(
        telemetryEvents=[
            {**event, "level": 0} if event["clickCount"] == 0 else event
            for event in valid_events()
        ]
    )
    assert zero_level.telemetry_events[0].level == 0

    with pytest.raises(ValidationError):
        DriveSummaryRequest(
            telemetryEvents=[{**event, "level": -1} for event in valid_events()]
        )

    with pytest.raises(ValidationError):
        DriveSummaryRequest(
            telemetryEvents=[{**event, "level": 4} for event in valid_events()]
        )
