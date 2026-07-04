import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, event

from app.api.dependencies import get_current_account
from app.db.session import AsyncSessionLocal, dispose_engine, engine
from app.models import (
    Account,
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)

UTC_PERIOD_START = datetime(2026, 5, 31, 15, 0, 0)
UTC_PERIOD_END_EXCLUSIVE = datetime(2026, 6, 30, 15, 0, 0)


def make_account(prefix: str) -> Account:
    return Account(id=str(uuid4()), email=f"{prefix}-{uuid4().hex}@example.com")


def make_profile(account_id: str, display_name: str) -> DriverProfile:
    return DriverProfile(
        account_id=account_id,
        display_name=display_name,
        agent_call_name=display_name,
    )


def make_session(
    profile_id: str,
    *,
    started_at: datetime,
    status: str = "COMPLETED",
    duration_seconds: int = 0,
    distance_meters: int = 0,
    safety_score: int | None = None,
    average_speed_kph: Decimal | None = None,
    destination_name: str | None = None,
) -> DrivingSession:
    ended_at = None if status == "ACTIVE" else started_at + timedelta(seconds=duration_seconds)
    end_reason = None if status == "ACTIVE" else "USER_REQUEST"
    return DrivingSession(
        profile_id=profile_id,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        end_reason=end_reason,
        destination_name=destination_name,
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        safety_score=safety_score,
        average_speed_kph=average_speed_kph,
        model_version="vit-report-test",
        policy_version="policy-report-test",
    )


def make_event(
    session_id: str,
    *,
    behavior_type: str,
    started_at: datetime,
    risk_level: int,
    duration_ms: int | None,
    average_confidence: Decimal,
) -> BehaviorEvent:
    return BehaviorEvent(
        session_id=session_id,
        behavior_type=behavior_type,
        status="RESOLVED",
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=5),
        duration_ms=duration_ms,
        average_confidence=average_confidence,
        maximum_confidence=min(Decimal("1.0000"), average_confidence + Decimal("0.0500")),
        driving_state="MOVING",
        risk_level=risk_level,
        resolution_reason="BEHAVIOR_CORRECTED",
    )


def make_intervention(event_id: str, *, level: int = 1) -> Intervention:
    return Intervention(
        behavior_event_id=event_id,
        level=level,
        intervention_type="WARNING",
        ui_text="Watch the road.",
        channels_json=["VISUAL"],
        status="RESOLVED",
        started_at=datetime(2026, 6, 1, 0, 0, level),
    )


def override_current_account(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


async def seed_report_data(prefix: str = "report-api") -> dict[str, object]:
    current_account = make_account(prefix)
    other_account = make_account(f"{prefix}-other")
    current_profile = make_profile(current_account.id, "Report Current")
    other_profile = make_profile(other_account.id, "Report Other")

    async with AsyncSessionLocal() as session:
        session.add_all([current_account, other_account])
        await session.flush()
        session.add_all([current_profile, other_profile])
        await session.flush()

        boundary_session = make_session(
            current_profile.id,
            started_at=UTC_PERIOD_START,
            duration_seconds=1000,
            distance_meters=10000,
            safety_score=80,
            average_speed_kph=Decimal("36.50"),
            destination_name="Boundary Start",
        )
        middle_session = make_session(
            current_profile.id,
            started_at=datetime(2026, 6, 14, 3, 0, 0),
            status="ABORTED",
            duration_seconds=2000,
            distance_meters=20000,
            safety_score=None,
            average_speed_kph=None,
            destination_name=None,
        )
        end_boundary_session = make_session(
            current_profile.id,
            started_at=UTC_PERIOD_END_EXCLUSIVE - timedelta(minutes=1),
            duration_seconds=500,
            distance_meters=5000,
            safety_score=90,
            average_speed_kph=Decimal("36.00"),
            destination_name="End Boundary",
        )
        active_session = make_session(
            current_profile.id,
            started_at=datetime(2026, 6, 14, 4, 0, 0),
            status="ACTIVE",
        )
        excluded_session = make_session(
            current_profile.id,
            started_at=UTC_PERIOD_END_EXCLUSIVE,
            duration_seconds=600,
            distance_meters=6000,
            safety_score=100,
        )
        previous_session = make_session(
            current_profile.id,
            started_at=datetime(2026, 5, 10, 3, 0, 0),
            duration_seconds=800,
            distance_meters=8000,
            safety_score=70,
        )
        other_session = make_session(
            other_profile.id,
            started_at=datetime(2026, 6, 14, 3, 0, 0),
            duration_seconds=999,
            distance_meters=9999,
            safety_score=100,
        )
        session.add_all(
            [
                boundary_session,
                middle_session,
                end_boundary_session,
                active_session,
                excluded_session,
                previous_session,
                other_session,
            ]
        )
        await session.flush()

        phone_one = make_event(
            boundary_session.id,
            behavior_type="PHONE_USE",
            started_at=datetime(2026, 5, 31, 23, 30, 0),
            risk_level=2,
            duration_ms=6000,
            average_confidence=Decimal("0.8000"),
        )
        phone_two = make_event(
            boundary_session.id,
            behavior_type="PHONE_USE",
            started_at=datetime(2026, 6, 1, 0, 5, 0),
            risk_level=3,
            duration_ms=None,
            average_confidence=Decimal("0.9000"),
        )
        drowsiness = make_event(
            boundary_session.id,
            behavior_type="DROWSINESS",
            started_at=datetime(2026, 6, 1, 1, 0, 0),
            risk_level=1,
            duration_ms=4000,
            average_confidence=Decimal("0.7000"),
        )
        gaze_away = make_event(
            middle_session.id,
            behavior_type="GAZE_AWAY",
            started_at=datetime(2026, 6, 14, 3, 15, 0),
            risk_level=0,
            duration_ms=3000,
            average_confidence=Decimal("0.6000"),
        )
        food_or_drink = make_event(
            middle_session.id,
            behavior_type="FOOD_OR_DRINK",
            started_at=datetime(2026, 6, 14, 4, 0, 0),
            risk_level=1,
            duration_ms=1000,
            average_confidence=Decimal("0.5000"),
        )
        secondary_task = make_event(
            middle_session.id,
            behavior_type="SECONDARY_TASK",
            started_at=datetime(2026, 6, 14, 5, 0, 0),
            risk_level=2,
            duration_ms=2000,
            average_confidence=Decimal("0.6500"),
        )
        reaching_behind = make_event(
            end_boundary_session.id,
            behavior_type="REACHING_BEHIND",
            started_at=datetime(2026, 6, 30, 14, 50, 0),
            risk_level=3,
            duration_ms=2500,
            average_confidence=Decimal("0.7500"),
        )
        smoking = make_event(
            boundary_session.id,
            behavior_type="SMOKING",
            started_at=datetime(2026, 6, 1, 2, 0, 0),
            risk_level=2,
            duration_ms=3500,
            average_confidence=Decimal("0.8800"),
        )
        active_event = make_event(
            active_session.id,
            behavior_type="PHONE_USE",
            started_at=datetime(2026, 6, 14, 4, 1, 0),
            risk_level=3,
            duration_ms=1000,
            average_confidence=Decimal("0.9900"),
        )
        excluded_event = make_event(
            excluded_session.id,
            behavior_type="PHONE_USE",
            started_at=UTC_PERIOD_END_EXCLUSIVE,
            risk_level=3,
            duration_ms=1000,
            average_confidence=Decimal("0.9900"),
        )
        other_event = make_event(
            other_session.id,
            behavior_type="PHONE_USE",
            started_at=datetime(2026, 6, 14, 3, 30, 0),
            risk_level=3,
            duration_ms=9999,
            average_confidence=Decimal("0.9900"),
        )
        previous_phone_events = [
            make_event(
                previous_session.id,
                behavior_type="PHONE_USE",
                started_at=datetime(2026, 5, 10, 3, minute, 0),
                risk_level=2,
                duration_ms=1000,
                average_confidence=Decimal("0.8000"),
            )
            for minute in range(4)
        ]
        session.add_all(
            [
                phone_one,
                phone_two,
                drowsiness,
                gaze_away,
                food_or_drink,
                secondary_task,
                reaching_behind,
                smoking,
                active_event,
                excluded_event,
                other_event,
                *previous_phone_events,
            ]
        )
        await session.flush()

        phone_one_first = make_intervention(phone_one.id, level=1)
        phone_one_second = make_intervention(phone_one.id, level=2)
        phone_two_intervention = make_intervention(phone_two.id, level=3)
        drowsiness_intervention = make_intervention(drowsiness.id, level=1)
        session.add_all(
            [
                phone_one_first,
                phone_one_second,
                phone_two_intervention,
                drowsiness_intervention,
            ]
        )
        await session.flush()

        session.add_all(
            [
                DriverResponse(
                    intervention_id=phone_one_first.id,
                    response_type="BEHAVIOR_CORRECTED",
                    behavior_corrected=True,
                    response_latency_ms=1000,
                    responded_at=datetime(2026, 6, 1, 0, 0, 1),
                ),
                DriverResponse(
                    intervention_id=phone_one_first.id,
                    response_type="BEHAVIOR_CORRECTED",
                    behavior_corrected=True,
                    response_latency_ms=3000,
                    responded_at=datetime(2026, 6, 1, 0, 0, 2),
                ),
                DriverResponse(
                    intervention_id=phone_one_second.id,
                    response_type="BEHAVIOR_REPEATED",
                    behavior_corrected=False,
                    response_latency_ms=None,
                    responded_at=datetime(2026, 6, 1, 0, 0, 3),
                ),
                DriverResponse(
                    intervention_id=phone_two_intervention.id,
                    response_type="BEHAVIOR_CORRECTED",
                    behavior_corrected=True,
                    response_latency_ms=5000,
                    responded_at=datetime(2026, 6, 1, 0, 0, 4),
                ),
                DriverResponse(
                    intervention_id=drowsiness_intervention.id,
                    response_type="VOICE_ACCEPTED",
                    behavior_corrected=None,
                    response_latency_ms=None,
                    responded_at=datetime(2026, 6, 1, 0, 0, 5),
                ),
            ]
        )
        await session.commit()

    return {
        "account": current_account,
        "other_account": other_account,
        "profile": current_profile,
        "other_profile": other_profile,
        "boundary_session_id": boundary_session.id,
        "middle_session_id": middle_session.id,
        "end_boundary_session_id": end_boundary_session.id,
    }


async def test_report_summary_api_aggregates_filtered_behavior_and_comparison(
    app,
    client,
) -> None:
    data = await seed_report_data("summary-report")
    account = data["account"]
    other_account = data["other_account"]
    profile = data["profile"]
    assert isinstance(account, Account)
    assert isinstance(other_account, Account)
    assert isinstance(profile, DriverProfile)
    override_current_account(app, account)

    try:
        response = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/summary",
            params={
                "periodStart": "2026-06-01",
                "periodEnd": "2026-06-30",
                "behaviorTypes": "PHONE_USE,DROWSINESS",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["period"] == {"start": "2026-06-01", "end": "2026-06-30"}
        assert payload["overview"] == {
            "totalSessions": 3,
            "totalDrivingSeconds": 3500,
            "totalDistanceMeters": 35000,
            "averageSafetyScore": 85.0,
            "behaviorEventCount": 3,
            "interventionCount": 4,
            "correctedBehaviorCount": 2,
            "behaviorCorrectionRate": 50.0,
            "averageResponseLatencyMs": 3000,
        }
        assert list(payload["behaviorCounts"]) == ["DROWSINESS", "PHONE_USE"]
        assert payload["behaviorCounts"] == {"DROWSINESS": 1, "PHONE_USE": 2}
        assert payload["riskLevelCounts"] == {"0": 0, "1": 1, "2": 1, "3": 1}
        assert payload["dailySafetyScores"] == [
            {"date": "2026-06-01", "score": 80.0},
            {"date": "2026-06-30", "score": 90.0},
        ]
        assert payload["comparison"] == {
            "previousPeriodStart": "2026-05-01",
            "previousPeriodEnd": "2026-05-31",
            "previousAverageSafetyScore": 70.0,
            "scoreChange": 15.0,
            "phoneUseChangePercent": -50.0,
        }

        empty = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/summary",
            params={"periodStart": "2026-04-01", "periodEnd": "2026-04-30"},
        )
        assert empty.status_code == 200
        empty_payload = empty.json()
        assert empty_payload["overview"]["totalSessions"] == 0
        assert empty_payload["overview"]["averageSafetyScore"] is None
        assert empty_payload["behaviorCounts"] == {
            "DROWSINESS": 0,
            "PHONE_USE": 0,
            "FOOD_OR_DRINK": 0,
            "GAZE_AWAY": 0,
            "SECONDARY_TASK": 0,
            "REACHING_BEHIND": 0,
            "SMOKING": 0,
        }
        assert empty_payload["dailySafetyScores"] == []
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id, other_account.id)
        await dispose_engine()


async def test_behavior_event_report_api_aggregates_by_type_risk_and_seoul_hour(
    app,
    client,
) -> None:
    data = await seed_report_data("behavior-report")
    account = data["account"]
    other_account = data["other_account"]
    profile = data["profile"]
    assert isinstance(account, Account)
    assert isinstance(other_account, Account)
    assert isinstance(profile, DriverProfile)
    override_current_account(app, account)

    try:
        response = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/behavior-events",
            params={"periodStart": "2026-06-01", "periodEnd": "2026-06-30"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["totalEventCount"] == 8
        assert [item["behaviorType"] for item in payload["statistics"]] == [
            "DROWSINESS",
            "PHONE_USE",
            "FOOD_OR_DRINK",
            "GAZE_AWAY",
            "SECONDARY_TASK",
            "REACHING_BEHIND",
            "SMOKING",
        ]

        by_type = {item["behaviorType"]: item for item in payload["statistics"]}
        assert by_type["PHONE_USE"] == {
            "behaviorType": "PHONE_USE",
            "eventCount": 2,
            "totalDurationMs": 6000,
            "averageDurationMs": 3000,
            "averageConfidence": 0.85,
            "maximumRiskLevel": 3,
            "correctedCount": 2,
            "correctionRate": 100.0,
        }
        assert by_type["DROWSINESS"]["eventCount"] == 1
        assert by_type["DROWSINESS"]["correctedCount"] == 0
        assert by_type["FOOD_OR_DRINK"]["eventCount"] == 1
        assert by_type["GAZE_AWAY"]["eventCount"] == 1
        assert by_type["SECONDARY_TASK"]["eventCount"] == 1
        assert by_type["REACHING_BEHIND"]["eventCount"] == 1
        assert by_type["SMOKING"]["eventCount"] == 1
        assert payload["riskLevelCounts"] == {"0": 1, "1": 2, "2": 3, "3": 2}
        assert payload["hourlyCounts"] == [
            {"hour": 8, "count": 1},
            {"hour": 9, "count": 1},
            {"hour": 10, "count": 1},
            {"hour": 11, "count": 1},
            {"hour": 12, "count": 1},
            {"hour": 13, "count": 1},
            {"hour": 14, "count": 1},
            {"hour": 23, "count": 1},
        ]

        filtered = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/behavior-events",
            params={
                "periodStart": "2026-06-01",
                "periodEnd": "2026-06-30",
                "behaviorTypes": "PHONE_USE",
            },
        )
        assert filtered.status_code == 200
        assert filtered.json()["totalEventCount"] == 2
        assert [item["behaviorType"] for item in filtered.json()["statistics"]] == [
            "PHONE_USE"
        ]
        filtered_new = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/behavior-events",
            params={
                "periodStart": "2026-06-01",
                "periodEnd": "2026-06-30",
                "behaviorTypes": "SMOKING",
            },
        )
        assert filtered_new.status_code == 200
        assert filtered_new.json()["totalEventCount"] == 1
        assert [item["behaviorType"] for item in filtered_new.json()["statistics"]] == [
            "SMOKING"
        ]
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id, other_account.id)
        await dispose_engine()


async def test_report_sessions_api_paginates_sorts_and_uses_fixed_query_count(
    app,
    client,
) -> None:
    data = await seed_report_data("sessions-report")
    account = data["account"]
    other_account = data["other_account"]
    profile = data["profile"]
    assert isinstance(account, Account)
    assert isinstance(other_account, Account)
    assert isinstance(profile, DriverProfile)
    override_current_account(app, account)
    statements: list[str] = []

    def before_cursor_execute(
        conn,
        cursor,
        statement: str,
        parameters,
        context,
        executemany,
    ) -> None:
        lowered = statement.lower()
        table_names = ("driving_sessions", "behavior_events", "interventions", "driver_responses")
        if lowered.lstrip().startswith("select") and any(name in lowered for name in table_names):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/sessions",
            params={
                "periodStart": "2026-06-01",
                "periodEnd": "2026-06-30",
                "page": 1,
                "size": 2,
            },
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)

    try:
        assert response.status_code == 200
        payload = response.json()
        assert payload["page"] == 1
        assert payload["size"] == 2
        assert payload["total"] == 3
        assert payload["totalPages"] == 2
        assert len(payload["items"]) == 2
        assert [item["sessionId"] for item in payload["items"]] == [
            data["end_boundary_session_id"],
            data["middle_session_id"],
        ]

        middle = payload["items"][1]
        assert middle["startedAt"] == "2026-06-14T03:00:00.000000Z"
        assert middle["endedAt"] == "2026-06-14T03:33:20.000000Z"
        assert middle["destinationName"] is None
        assert middle["durationSeconds"] == 2000
        assert middle["distanceMeters"] == 20000
        assert middle["averageSpeedKph"] is None
        assert middle["safetyScore"] is None
        assert middle["behaviorEventCount"] == 3
        assert middle["interventionCount"] == 0
        assert middle["correctedBehaviorCount"] == 0
        assert middle["behaviorCorrectionRate"] == 0.0
        assert "profileId" not in middle

        second_page = await client.get(
            f"/api/v1/profiles/{profile.id}/reports/sessions",
            params={
                "periodStart": "2026-06-01",
                "periodEnd": "2026-06-30",
                "page": 2,
                "size": 2,
            },
        )
        assert second_page.status_code == 200
        assert second_page.json()["items"][0]["sessionId"] == data["boundary_session_id"]
        assert second_page.json()["items"][0]["behaviorEventCount"] == 4
        assert second_page.json()["items"][0]["interventionCount"] == 4
        assert second_page.json()["items"][0]["correctedBehaviorCount"] == 2
        assert second_page.json()["items"][0]["behaviorCorrectionRate"] == 50.0
        assert len(statements) == 2
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id, other_account.id)
        await dispose_engine()


async def test_report_api_errors_use_common_response_shape(app, client) -> None:
    data = await seed_report_data("report-errors")
    account = data["account"]
    other_account = data["other_account"]
    profile = data["profile"]
    other_profile = data["other_profile"]
    assert isinstance(account, Account)
    assert isinstance(other_account, Account)
    assert isinstance(profile, DriverProfile)
    assert isinstance(other_profile, DriverProfile)
    override_current_account(app, account)

    try:
        cases = [
            (
                "summary invalid profile id",
                "/api/v1/profiles/not-a-uuid/reports/summary",
                {"periodStart": "2026-06-01", "periodEnd": "2026-06-30"},
                422,
                "INVALID_PROFILE_ID",
            ),
            (
                "summary other profile",
                f"/api/v1/profiles/{other_profile.id}/reports/summary",
                {"periodStart": "2026-06-01", "periodEnd": "2026-06-30"},
                404,
                "PROFILE_NOT_FOUND",
            ),
            (
                "summary reversed period",
                f"/api/v1/profiles/{profile.id}/reports/summary",
                {"periodStart": "2026-06-30", "periodEnd": "2026-06-01"},
                422,
                "INVALID_REPORT_PERIOD",
            ),
            (
                "summary too long",
                f"/api/v1/profiles/{profile.id}/reports/summary",
                {"periodStart": "2026-01-01", "periodEnd": "2027-01-01"},
                422,
                "REPORT_PERIOD_TOO_LONG",
            ),
            (
                "behavior invalid type",
                f"/api/v1/profiles/{profile.id}/reports/behavior-events",
                {
                    "periodStart": "2026-06-01",
                    "periodEnd": "2026-06-30",
                    "behaviorTypes": "INVALID",
                },
                422,
                "INVALID_BEHAVIOR_TYPE",
            ),
            (
                "sessions invalid page",
                f"/api/v1/profiles/{profile.id}/reports/sessions",
                {"periodStart": "2026-06-01", "periodEnd": "2026-06-30", "page": 0},
                422,
                "INVALID_PAGE",
            ),
            (
                "sessions invalid size",
                f"/api/v1/profiles/{profile.id}/reports/sessions",
                {"periodStart": "2026-06-01", "periodEnd": "2026-06-30", "size": 101},
                422,
                "INVALID_PAGE_SIZE",
            ),
            (
                "summary missing period",
                f"/api/v1/profiles/{profile.id}/reports/summary",
                {"periodStart": "2026-06-01"},
                422,
                "INVALID_REPORT_PERIOD",
            ),
        ]

        for label, url, params, expected_status, expected_error in cases:
            response = await client.get(url, params=params)
            assert response.status_code == expected_status, label
            payload = response.json()
            assert payload["error"] == expected_error, label
            assert "detail" not in payload
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id, other_account.id)
        await dispose_engine()
