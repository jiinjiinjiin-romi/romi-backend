from decimal import Decimal

import pytest

from app.core.exceptions import AppException
from app.repositories.report_repository import BehaviorTypeAggregate
from app.services.report_service import CANONICAL_BEHAVIOR_TYPES, ReportService

EXPECTED_CANONICAL_BEHAVIOR_TYPES = [
    "DROWSINESS",
    "PHONE_USE",
    "FOOD_OR_DRINK",
    "GAZE_AWAY",
    "SECONDARY_TASK",
    "REACHING_BEHIND",
    "SMOKING",
]


def test_behavior_filter_defaults_to_all_canonical_types() -> None:
    assert CANONICAL_BEHAVIOR_TYPES == EXPECTED_CANONICAL_BEHAVIOR_TYPES
    assert ReportService.parse_behavior_types(None) == EXPECTED_CANONICAL_BEHAVIOR_TYPES


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PHONE_USE", ["PHONE_USE"]),
        (" DROWSINESS , PHONE_USE ", ["DROWSINESS", "PHONE_USE"]),
        ("PHONE_USE,DROWSINESS,PHONE_USE", ["DROWSINESS", "PHONE_USE"]),
        ("SMOKING,PHONE_USE,SECONDARY_TASK", ["PHONE_USE", "SECONDARY_TASK", "SMOKING"]),
    ],
)
def test_behavior_filter_trims_deduplicates_and_preserves_canonical_order(
    value: str,
    expected: list[str],
) -> None:
    assert ReportService.parse_behavior_types(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "PHONE_USE,", "PHONE_USE,UNKNOWN", "NORMAL", "SAFE_DRIVING"],
)
def test_behavior_filter_rejects_empty_or_unknown_values(value: str) -> None:
    with pytest.raises(AppException) as exc_info:
        ReportService.parse_behavior_types(value)

    assert exc_info.value.error_code == "INVALID_BEHAVIOR_TYPE"


@pytest.mark.parametrize(
    ("page", "size", "error_code"),
    [
        (0, 20, "INVALID_PAGE"),
        (1, 0, "INVALID_PAGE_SIZE"),
        (1, 101, "INVALID_PAGE_SIZE"),
    ],
)
def test_report_session_pagination_validation(page: int, size: int, error_code: str) -> None:
    with pytest.raises(AppException) as exc_info:
        ReportService.validate_pagination(page, size)

    assert exc_info.value.error_code == error_code


def test_numeric_policy_for_rates_changes_and_averages() -> None:
    assert ReportService._rate(0, 0) == 0.0
    assert ReportService._rate(2, 3) == 66.7
    assert ReportService._change_percent(current=0, previous=0) == 0.0
    assert ReportService._change_percent(current=2, previous=0) is None
    assert ReportService._change_percent(current=2, previous=4) == -50.0
    assert ReportService._score_change(None, 80.0) is None
    assert ReportService._score_change(84.5, 78.0) == 6.5
    assert ReportService._round_int_or_none(None) is None
    assert ReportService._round_int_or_none(Decimal("2409.5")) == 2410


def test_behavior_statistic_response_zero_and_decimal_policy() -> None:
    empty = ReportService._behavior_statistic_response("PHONE_USE", None).model_dump(
        by_alias=True
    )

    assert empty == {
        "behaviorType": "PHONE_USE",
        "eventCount": 0,
        "totalDurationMs": 0,
        "averageDurationMs": None,
        "averageConfidence": None,
        "maximumRiskLevel": None,
        "correctedCount": 0,
        "correctionRate": 0.0,
    }

    aggregate = BehaviorTypeAggregate(
        behavior_type="PHONE_USE",
        event_count=2,
        total_duration_ms=6001,
        average_confidence=Decimal("0.87654"),
        maximum_risk_level=3,
        corrected_event_count=1,
    )
    payload = ReportService._behavior_statistic_response("PHONE_USE", aggregate).model_dump(
        by_alias=True
    )

    assert payload["averageDurationMs"] == 3001
    assert payload["averageConfidence"] == 0.8765
    assert payload["correctionRate"] == 50.0
