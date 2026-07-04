from datetime import date, datetime

from app.schemas.report import (
    BehaviorEventReportResponse,
    BehaviorTypeStatisticResponse,
    DailySafetyScoreResponse,
    HourlyBehaviorCountResponse,
    ReportComparisonResponse,
    ReportOverviewResponse,
    ReportPeriodResponse,
    ReportSessionItemResponse,
    ReportSessionPageResponse,
    ReportSummaryResponse,
)


def test_report_summary_schema_serializes_camel_case_dates_and_string_risk_keys() -> None:
    response = ReportSummaryResponse(
        period=ReportPeriodResponse(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        overview=ReportOverviewResponse(
            total_sessions=1,
            total_driving_seconds=1200,
            total_distance_meters=10000,
            average_safety_score=None,
            behavior_event_count=0,
            intervention_count=0,
            corrected_behavior_count=0,
            behavior_correction_rate=0.0,
            average_response_latency_ms=None,
        ),
        behavior_counts={"PHONE_USE": 0},
        risk_level_counts={"0": 0, "1": 0, "2": 0, "3": 0},
        daily_safety_scores=[
            DailySafetyScoreResponse(date=date(2026, 6, 12), score=84.5)
        ],
        comparison=ReportComparisonResponse(
            previous_period_start=date(2026, 5, 1),
            previous_period_end=date(2026, 5, 31),
            previous_average_safety_score=None,
            score_change=None,
            phone_use_change_percent=0.0,
        ),
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload["period"] == {"start": "2026-06-01", "end": "2026-06-30"}
    assert payload["overview"]["averageSafetyScore"] is None
    assert payload["overview"]["averageResponseLatencyMs"] is None
    assert payload["riskLevelCounts"] == {"0": 0, "1": 0, "2": 0, "3": 0}
    assert payload["dailySafetyScores"][0] == {"date": "2026-06-12", "score": 84.5}
    assert payload["comparison"]["phoneUseChangePercent"] == 0.0
    assert "profileId" not in payload
    assert "accountId" not in payload


def test_behavior_report_schema_serializes_contract_fields_only() -> None:
    response = BehaviorEventReportResponse(
        period=ReportPeriodResponse(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        total_event_count=1,
        statistics=[
            BehaviorTypeStatisticResponse(
                behavior_type="SMOKING",
                event_count=1,
                total_duration_ms=6000,
                average_duration_ms=6000,
                average_confidence=0.8765,
                maximum_risk_level=3,
                corrected_count=1,
                correction_rate=100.0,
            )
        ],
        risk_level_counts={"0": 0, "1": 0, "2": 0, "3": 1},
        hourly_counts=[HourlyBehaviorCountResponse(hour=8, count=1)],
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload["totalEventCount"] == 1
    assert payload["statistics"][0]["behaviorType"] == "SMOKING"
    assert payload["statistics"][0]["averageConfidence"] == 0.8765
    assert payload["hourlyCounts"] == [{"hour": 8, "count": 1}]
    assert "eventId" not in payload["statistics"][0]


def test_report_sessions_schema_serializes_utc_z_and_hides_internal_ids() -> None:
    response = ReportSessionPageResponse.from_items(
        items=[
            ReportSessionItemResponse(
                session_id="67371b45-204c-4d87-b8f7-8a334229a41e",
                started_at=datetime(2026, 6, 28, 3, 10, 0, 123456),
                ended_at=None,
                destination_name=None,
                duration_seconds=2400,
                distance_meters=13800,
                average_speed_kph=None,
                safety_score=None,
                behavior_event_count=0,
                intervention_count=0,
                corrected_behavior_count=0,
                behavior_correction_rate=0.0,
            )
        ],
        page=1,
        size=20,
        total=1,
    )

    payload = response.model_dump(by_alias=True, mode="json")
    item = payload["items"][0]

    assert payload["totalPages"] == 1
    assert item["sessionId"] == "67371b45-204c-4d87-b8f7-8a334229a41e"
    assert item["startedAt"] == "2026-06-28T03:10:00.123456Z"
    assert item["endedAt"] is None
    assert item["averageSpeedKph"] is None
    assert item["safetyScore"] is None
    assert "id" not in item
    assert "profileId" not in item
