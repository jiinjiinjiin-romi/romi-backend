import os
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.ai.driver_monitoring import InferenceFrame
from app.api.dependencies import get_current_account
from app.core.time import utc_now_for_mysql_datetime
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import (
    Account,
    AgentConversation,
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
    LocationSample,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


class FakeDriverMonitoringAdapter:
    model_version = "vit-dms-1.0.0"

    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.ready_calls = 0

    async def is_ready(self) -> bool:
        self.ready_calls += 1
        return self.ready

    async def predict(self, frame: InferenceFrame):
        raise AssertionError("predict should not be called by REST session start")


def start_payload(profile_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profileId": profile_id,
        "startLocation": {"latitude": 0.0, "longitude": 0.0},
        "destination": {
            "providerPlaceId": "destination-1",
            "name": "Session Destination",
            "latitude": 0.0,
            "longitude": 2.0,
        },
    }
    payload.update(overrides)
    return payload


def end_payload(reason: str = "USER_REQUEST") -> dict[str, object]:
    return {
        "endReason": reason,
        "endLocation": {"latitude": 0.0, "longitude": 2.0},
    }


async def create_test_account(email_prefix: str = "driving-session-api") -> Account:
    account = Account(id=str(uuid4()), email=f"{email_prefix}-{uuid4().hex}@example.com")
    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.commit()
    return account


async def create_test_profile(account_id: str, display_name: str = "Session API") -> DriverProfile:
    async with AsyncSessionLocal() as session:
        profile = DriverProfile(
            account_id=account_id,
            display_name=display_name,
            agent_call_name=display_name,
        )
        session.add(profile)
        await session.commit()
        return profile


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_dependencies(app, account: Account, *, model_available: bool = True) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override
    app.state.driver_monitoring_adapter = FakeDriverMonitoringAdapter(model_available)


async def seed_session_activity(session_id: str) -> None:
    started_at = utc_now_for_mysql_datetime() - timedelta(minutes=10)
    async with AsyncSessionLocal() as session:
        driving_session = await session.get(DrivingSession, session_id)
        assert driving_session is not None
        driving_session.started_at = started_at

        session.add(
            LocationSample(
                session_id=session_id,
                latitude=0.0,
                longitude=1.0,
                driving_state="MOVING",
                recorded_at=started_at + timedelta(minutes=5),
            )
        )

        first_event = BehaviorEvent(
            session_id=session_id,
            behavior_type="PHONE_USE",
            started_at=started_at + timedelta(minutes=1),
            average_confidence=Decimal("0.8000"),
            maximum_confidence=Decimal("0.9000"),
            driving_state="MOVING",
            risk_level=2,
        )
        second_event = BehaviorEvent(
            session_id=session_id,
            behavior_type="DROWSINESS",
            started_at=started_at + timedelta(minutes=2),
            average_confidence=Decimal("0.8500"),
            maximum_confidence=Decimal("0.9500"),
            driving_state="MOVING",
            risk_level=3,
        )
        session.add_all([first_event, second_event])
        await session.flush()

        first_intervention = Intervention(
            behavior_event_id=first_event.id,
            level=1,
            intervention_type="WARNING",
            ui_text="Watch the road.",
            channels_json=["VISUAL"],
            status="WAITING_RESPONSE",
            started_at=started_at + timedelta(minutes=1, seconds=10),
        )
        second_intervention = Intervention(
            behavior_event_id=second_event.id,
            level=2,
            intervention_type="WARNING",
            ui_text="Take a break.",
            channels_json=["VISUAL"],
            status="RESOLVED",
            started_at=started_at + timedelta(minutes=2, seconds=10),
            ended_at=started_at + timedelta(minutes=2, seconds=30),
        )
        conversation = AgentConversation(
            session_id=session_id,
            mode="SAFETY",
            started_at=started_at + timedelta(minutes=3),
        )
        session.add_all([first_intervention, second_intervention, conversation])
        await session.flush()

        session.add_all(
            [
                DriverResponse(
                    intervention_id=first_intervention.id,
                    response_type="BEHAVIOR_CORRECTED",
                    behavior_corrected=True,
                    response_latency_ms=2000,
                ),
                DriverResponse(
                    intervention_id=first_intervention.id,
                    response_type="BEHAVIOR_CORRECTED",
                    behavior_corrected=True,
                    response_latency_ms=3000,
                ),
            ]
        )
        await session.commit()


async def test_driving_session_api_full_lifecycle_summary_and_history(app, client) -> None:
    account = await create_test_account()
    profile = await create_test_profile(account.id)
    override_dependencies(app, account)

    try:
        start_response = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(profile.id),
        )
        assert start_response.status_code == 201
        started = start_response.json()
        session_id = started["id"]
        assert started["profileId"] == profile.id
        assert started["status"] == "ACTIVE"
        assert started["webSocketUrl"] == f"/ws/v1/driving-sessions/{session_id}"
        assert "accountId" not in started
        assert "activeProfileId" not in started

        duplicate_response = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(profile.id),
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"] == "ACTIVE_SESSION_EXISTS"

        await seed_session_activity(session_id)

        active_response = await client.get(
            f"/api/v1/driving-sessions/active?profileId={profile.id}"
        )
        assert active_response.status_code == 200
        assert active_response.json()["id"] == session_id

        detail_response = await client.get(f"/api/v1/driving-sessions/{session_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["status"] == "ACTIVE"
        assert detail["summary"]["behaviorEventCount"] == 2
        assert detail["summary"]["interventionCount"] == 2

        end_response = await client.post(
            f"/api/v1/driving-sessions/{session_id}/end",
            json=end_payload(),
        )
        assert end_response.status_code == 200
        ended = end_response.json()
        assert ended["status"] == "COMPLETED"
        assert ended["endReason"] == "USER_REQUEST"
        assert ended["distanceMeters"] == 222390
        assert ended["durationSeconds"] >= 599
        assert ended["averageSpeedKph"] is not None
        assert ended["safetyScore"] is None
        assert ended["summary"]["behaviorEventCount"] == 2
        assert ended["summary"]["interventionCount"] == 2
        assert ended["summary"]["correctedBehaviorCount"] == 1
        assert ended["summary"]["behaviorCorrectionRate"] == 50.0
        assert ended["summary"]["averageResponseLatencyMs"] == 2500.0

        active_after_end = await client.get(
            f"/api/v1/driving-sessions/active?profileId={profile.id}"
        )
        assert active_after_end.status_code == 204
        assert active_after_end.content == b""

        repeated_end_response = await client.post(
            f"/api/v1/driving-sessions/{session_id}/end",
            json=end_payload(),
        )
        assert repeated_end_response.status_code == 409
        assert repeated_end_response.json()["error"] == "SESSION_NOT_ACTIVE"

        today = utc_now_for_mysql_datetime().date().isoformat()
        history_response = await client.get(
            f"/api/v1/profiles/{profile.id}/driving-sessions"
            f"?page=1&size=20&status=COMPLETED&startedFrom={today}&startedTo={today}"
        )
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 1
        assert history["items"][0]["id"] == session_id
        assert history["items"][0]["behaviorEventCount"] == 2

        async with AsyncSessionLocal() as session:
            events = list(
                (
                    await session.execute(
                        select(BehaviorEvent).where(BehaviorEvent.session_id == session_id)
                    )
                )
                .scalars()
                .all()
            )
            interventions = list(
                (
                    await session.execute(
                        select(Intervention)
                        .join(BehaviorEvent, Intervention.behavior_event_id == BehaviorEvent.id)
                        .where(BehaviorEvent.session_id == session_id)
                    )
                )
                .scalars()
                .all()
            )
            conversation = await session.scalar(
                select(AgentConversation).where(AgentConversation.session_id == session_id)
            )

        assert {event.status for event in events} == {"RESOLVED"}
        assert {event.resolution_reason for event in events} == {"SESSION_ENDED"}
        assert "CANCELLED" in {intervention.status for intervention in interventions}
        assert "RESOLVED" in {intervention.status for intervention in interventions}
        assert conversation is not None
        assert conversation.status == "ABORTED"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_non_user_end_reason_aborts_and_allows_new_active_session(app, client) -> None:
    account = await create_test_account("abort-session")
    profile = await create_test_profile(account.id, "Abort Session")
    override_dependencies(app, account)

    try:
        first = await client.post("/api/v1/driving-sessions", json=start_payload(profile.id))
        assert first.status_code == 201
        first_session_id = first.json()["id"]

        abort_response = await client.post(
            f"/api/v1/driving-sessions/{first_session_id}/end",
            json=end_payload("CAMERA_LOST"),
        )
        assert abort_response.status_code == 200
        assert abort_response.json()["status"] == "ABORTED"

        second = await client.post("/api/v1/driving-sessions", json=start_payload(profile.id))
        assert second.status_code == 201
        assert second.json()["id"] != first_session_id
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_different_profiles_can_have_active_sessions(app, client) -> None:
    account = await create_test_account("different-profile-session")
    first_profile = await create_test_profile(account.id, "First Profile")
    second_profile = await create_test_profile(account.id, "Second Profile")
    override_dependencies(app, account)

    try:
        first = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(first_profile.id),
        )
        second = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(second_profile.id),
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_driving_session_api_errors_and_other_account_access(app, client) -> None:
    current_account = await create_test_account("current-session")
    other_account = await create_test_account("other-session")
    current_profile = await create_test_profile(current_account.id, "Current Session")
    other_profile = await create_test_profile(other_account.id, "Other Session")
    override_dependencies(app, current_account)

    try:
        async with AsyncSessionLocal() as session:
            other_session = DrivingSession(
                profile_id=other_profile.id,
                model_version="test-model",
                policy_version="test-policy",
            )
            session.add(other_session)
            await session.commit()
            other_session_id = other_session.id

        other_session_response = await client.get(
            f"/api/v1/driving-sessions/{other_session_id}"
        )
        assert other_session_response.status_code == 404
        assert other_session_response.json()["error"] == "SESSION_NOT_FOUND"

        other_profile_history = await client.get(
            f"/api/v1/profiles/{other_profile.id}/driving-sessions"
        )
        assert other_profile_history.status_code == 404
        assert other_profile_history.json()["error"] == "PROFILE_NOT_FOUND"

        missing_profile_query = await client.get("/api/v1/driving-sessions/active")
        assert missing_profile_query.status_code == 422
        assert missing_profile_query.json()["error"] == "MISSING_PROFILE_ID"
        assert "detail" not in missing_profile_query.json()

        invalid_profile_response = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload("not-a-uuid"),
        )
        assert invalid_profile_response.status_code == 422
        assert invalid_profile_response.json()["error"] == "INVALID_PROFILE_ID"

        missing_body_profile_response = await client.post(
            "/api/v1/driving-sessions",
            json={
                "startLocation": {"latitude": 37.0, "longitude": 127.0},
            },
        )
        assert missing_body_profile_response.status_code == 422
        assert missing_body_profile_response.json()["error"] == "INVALID_PROFILE_ID"

        invalid_session_response = await client.get("/api/v1/driving-sessions/not-a-uuid")
        assert invalid_session_response.status_code == 422
        assert invalid_session_response.json()["error"] == "INVALID_SESSION_ID"

        invalid_body_response = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(
                current_profile.id,
                startLocation={"latitude": True, "longitude": 127.0},
            ),
        )
        assert invalid_body_response.status_code == 422
        assert invalid_body_response.json()["error"] == "INVALID_START_LOCATION"
        assert "detail" not in invalid_body_response.json()

        invalid_end_location_response = await client.post(
            f"/api/v1/driving-sessions/{uuid4()}/end",
            json={
                "endReason": "USER_REQUEST",
                "endLocation": {"latitude": False, "longitude": 127.0},
            },
        )
        assert invalid_end_location_response.status_code == 422
        assert invalid_end_location_response.json()["error"] == "INVALID_END_LOCATION"

        invalid_status_response = await client.get(
            f"/api/v1/profiles/{current_profile.id}/driving-sessions?status=PAUSED"
        )
        assert invalid_status_response.status_code == 422
        assert invalid_status_response.json()["error"] == "INVALID_SESSION_STATUS"

        invalid_date_response = await client.get(
            f"/api/v1/profiles/{current_profile.id}/driving-sessions"
            "?startedFrom=2026-06-30&startedTo=2026-06-29"
        )
        assert invalid_date_response.status_code == 422
        assert invalid_date_response.json()["error"] == "INVALID_DATE_RANGE"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()


async def test_model_unavailable_returns_503(app, client) -> None:
    account = await create_test_account("model-unavailable")
    profile = await create_test_profile(account.id, "Model Unavailable")
    override_dependencies(app, account, model_available=False)

    try:
        adapter = app.state.driver_monitoring_adapter
        response = await client.post("/api/v1/driving-sessions", json=start_payload(profile.id))

        assert response.status_code == 503
        assert response.json()["error"] == "MODEL_NOT_AVAILABLE"
        assert adapter.ready_calls == 1
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()
