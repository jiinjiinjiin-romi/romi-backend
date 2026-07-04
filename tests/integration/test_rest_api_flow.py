import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.ai.driver_monitoring import InferenceFrame
from app.api.dependencies import get_current_account
from app.core.time import utc_now_for_mysql_datetime
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import (
    Account,
    AgentConversation,
    AgentMessage,
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
    LocationSample,
    SavedPlace,
    SearchHistory,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


class FakeDriverMonitoringAdapter:
    model_version = "vit-dms-1.0.0"

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame: InferenceFrame):
        raise AssertionError("predict should not be called by REST flow")


def profile_payload() -> dict[str, object]:
    return {
        "displayName": "REST Flow",
        "agentCallName": "Flow",
        "reportEmail": "rest-flow@example.com",
        "agentPersonality": "FRIENDLY",
        "warningSensitivity": "MEDIUM",
        "ttsVoiceId": None,
        "ttsSpeed": 1.0,
        "guidanceVolume": 70,
        "theme": "SYSTEM",
    }


def place_payload(label: str, provider_place_id: str, latitude: float) -> dict[str, object]:
    return {
        "label": label,
        "provider": "KAKAO",
        "providerPlaceId": provider_place_id,
        "address": f"{label} address",
        "latitude": latitude,
        "longitude": 127.0734,
    }


def start_payload(profile_id: str) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "startLocation": {"latitude": 37.5501, "longitude": 127.0734},
        "destination": {
            "providerPlaceId": "rest-flow-destination",
            "name": "REST Flow Destination",
            "latitude": 37.5601,
            "longitude": 127.0834,
        },
    }


async def create_test_account() -> Account:
    account = Account(id=str(uuid4()), email=f"rest-flow-{uuid4().hex}@example.com")
    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.commit()
    return account


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_dependencies(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override
    app.state.driver_monitoring_adapter = FakeDriverMonitoringAdapter()


async def seed_search_histories(profile_id: str) -> None:
    base_time = utc_now_for_mysql_datetime() - timedelta(minutes=5)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                SearchHistory(
                    profile_id=profile_id,
                    query=f"flow-query-{index}",
                    provider="KAKAO",
                    provider_place_id=f"flow-place-{index}",
                    place_name=f"Flow Place {index}",
                    address=f"Flow Address {index}",
                    latitude=37.55 + index / 1000,
                    longitude=127.07 + index / 1000,
                    searched_at=base_time + timedelta(seconds=index),
                )
                for index in range(3)
            ]
        )
        await session.commit()


async def seed_session_activity(
    *,
    session_id: str,
    conversation_id: str,
) -> dict[str, str | datetime]:
    base_time = utc_now_for_mysql_datetime() - timedelta(minutes=15)
    async with AsyncSessionLocal() as session:
        driving_session = await session.get(DrivingSession, session_id)
        assert driving_session is not None
        driving_session.started_at = base_time

        session.add_all(
            [
                LocationSample(
                    session_id=session_id,
                    latitude=37.5520,
                    longitude=127.0750,
                    speed_kph=Decimal("24.50"),
                    driving_state="MOVING",
                    accuracy_meters=Decimal("6.00"),
                    source="GPS",
                    recorded_at=base_time + timedelta(minutes=5),
                ),
                LocationSample(
                    session_id=session_id,
                    latitude=37.5540,
                    longitude=127.0770,
                    speed_kph=Decimal("30.00"),
                    driving_state="MOVING",
                    accuracy_meters=Decimal("5.50"),
                    source="GPS",
                    recorded_at=base_time + timedelta(minutes=10),
                ),
            ]
        )

        event = BehaviorEvent(
            session_id=session_id,
            behavior_type="PHONE_USE",
            status="RESOLVED",
            started_at=base_time + timedelta(minutes=2),
            ended_at=base_time + timedelta(minutes=3),
            duration_ms=60_000,
            average_confidence=Decimal("0.8000"),
            maximum_confidence=Decimal("0.9200"),
            driving_state="MOVING",
            speed_kph=Decimal("25.00"),
            risk_level=2,
            resolution_reason="BEHAVIOR_CORRECTED",
        )
        session.add(event)
        await session.flush()

        intervention = Intervention(
            behavior_event_id=event.id,
            level=1,
            intervention_type="WARNING",
            ui_text="Please keep your eyes on the road.",
            speech_text="Please keep your eyes on the road.",
            channels_json=["VOICE", "VISUAL"],
            status="RESOLVED",
            started_at=base_time + timedelta(minutes=2, seconds=10),
            ended_at=base_time + timedelta(minutes=2, seconds=30),
        )
        session.add(intervention)
        await session.flush()

        response = DriverResponse(
            intervention_id=intervention.id,
            response_type="BEHAVIOR_CORRECTED",
            behavior_corrected=True,
            response_latency_ms=2500,
            responded_at=base_time + timedelta(minutes=2, seconds=20),
        )
        first_message = AgentMessage(
            conversation_id=conversation_id,
            sequence_no=1,
            role="USER",
            text="Turn down the guidance volume.",
            intent="SET_GUIDANCE_VOLUME",
            input_type="VOICE",
            metadata_json={"source": "test"},
            created_at=base_time + timedelta(minutes=6),
        )
        second_message = AgentMessage(
            conversation_id=conversation_id,
            sequence_no=2,
            role="AGENT",
            text="Guidance volume is now lower.",
            intent=None,
            input_type="SYSTEM_EVENT",
            metadata_json={},
            created_at=base_time + timedelta(minutes=6, seconds=1),
        )
        session.add_all([response, second_message, first_message])
        await session.commit()

    return {
        "base_time": base_time,
        "event_id": event.id,
        "intervention_id": intervention.id,
        "response_id": response.id,
        "first_message_id": first_message.id,
    }


async def count_rows(model, criterion) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            await session.scalar(select(func.count()).select_from(model).where(criterion))
            or 0
        )


def assert_no_snake_case_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not key.isupper():
                assert "_" not in key
            assert_no_snake_case_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_snake_case_keys(nested)


async def test_rest_api_full_flow_and_cascade_cleanup(app, client) -> None:
    account = await create_test_account()
    override_dependencies(app, account)

    try:
        bootstrap = await client.get("/api/v1/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["profiles"] == []

        created_profile = await client.post("/api/v1/profiles", json=profile_payload())
        assert created_profile.status_code == 201
        profile = created_profile.json()
        profile_id = profile["id"]
        assert_no_snake_case_keys(profile)
        assert "accountId" not in profile

        profile_list = await client.get("/api/v1/profiles")
        profile_detail = await client.get(f"/api/v1/profiles/{profile_id}")
        assert profile_list.status_code == 200
        assert profile_list.json()["count"] == 1
        assert profile_detail.status_code == 200
        assert profile_detail.json()["id"] == profile_id

        select_response = await client.post(f"/api/v1/profiles/{profile_id}/select")
        assert select_response.status_code == 200
        assert select_response.json()["selectedAt"].endswith("Z")

        home_response = await client.put(
            f"/api/v1/profiles/{profile_id}/saved-places/HOME",
            json=place_payload("REST Home", "rest-home", 37.5501),
        )
        favorite_response = await client.post(
            f"/api/v1/profiles/{profile_id}/favorites",
            json=place_payload("REST Favorite", "rest-favorite", 37.5601),
        )
        assert home_response.status_code == 200
        assert favorite_response.status_code == 201
        home_id = home_response.json()["id"]
        favorite_id = favorite_response.json()["id"]

        saved_places = await client.get(f"/api/v1/profiles/{profile_id}/saved-places")
        assert saved_places.status_code == 200
        assert saved_places.json()["fixedPlaces"]["home"]["id"] == home_id
        assert [place["id"] for place in saved_places.json()["favorites"]] == [favorite_id]
        assert_no_snake_case_keys(saved_places.json())

        await seed_search_histories(profile_id)
        search_history = await client.get(
            f"/api/v1/profiles/{profile_id}/search-histories?page=1&size=20"
        )
        assert search_history.status_code == 200
        assert search_history.json()["total"] == 3
        assert search_history.json()["items"][0]["query"] == "flow-query-2"
        assert search_history.json()["items"][0]["searchedAt"].endswith("Z")
        assert_no_snake_case_keys(search_history.json())

        started_session = await client.post(
            "/api/v1/driving-sessions",
            json=start_payload(profile_id),
        )
        assert started_session.status_code == 201
        session_payload = started_session.json()
        session_id = session_payload["id"]
        assert session_payload["profileId"] == profile_id
        assert session_payload["webSocketUrl"] == f"/ws/v1/driving-sessions/{session_id}"
        assert session_payload["startedAt"].endswith("Z")
        assert_no_snake_case_keys(session_payload)

        active_session = await client.get(
            f"/api/v1/driving-sessions/active?profileId={profile_id}"
        )
        assert active_session.status_code == 200
        assert active_session.json()["id"] == session_id

        created_conversation = await client.post(
            f"/api/v1/driving-sessions/{session_id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        assert created_conversation.status_code == 201
        conversation_id = created_conversation.json()["id"]

        empty_conversation = await client.get(f"/api/v1/agent/conversations/{conversation_id}")
        assert empty_conversation.status_code == 200
        assert empty_conversation.json()["messages"] == []

        seeded = await seed_session_activity(
            session_id=session_id,
            conversation_id=conversation_id,
        )
        base_time = seeded["base_time"]
        assert isinstance(base_time, datetime)

        timeline = await client.get(f"/api/v1/driving-sessions/{session_id}/timeline")
        assert timeline.status_code == 200
        assert timeline.json()["events"][0]["behaviorType"] == "PHONE_USE"
        assert timeline.json()["events"][0]["interventions"][0]["responses"][0][
            "behaviorCorrected"
        ] is True
        assert_no_snake_case_keys(timeline.json())

        locations = await client.get(f"/api/v1/driving-sessions/{session_id}/locations")
        assert locations.status_code == 200
        assert locations.json()["count"] == 2
        assert [sample["recordedAt"] for sample in locations.json()["samples"]] == sorted(
            sample["recordedAt"] for sample in locations.json()["samples"]
        )
        assert_no_snake_case_keys(locations.json())

        conversation_with_messages = await client.get(
            f"/api/v1/agent/conversations/{conversation_id}"
        )
        assert conversation_with_messages.status_code == 200
        message_payloads = conversation_with_messages.json()["messages"]
        assert [message["sequenceNo"] for message in message_payloads] == [1, 2]
        assert message_payloads[0]["id"] == seeded["first_message_id"]
        assert "conversationId" not in message_payloads[0]
        assert "metadataJson" not in message_payloads[0]
        assert_no_snake_case_keys(conversation_with_messages.json())

        ended_session = await client.post(
            f"/api/v1/driving-sessions/{session_id}/end",
            json={
                "endReason": "USER_REQUEST",
                "endLocation": {"latitude": 37.5651, "longitude": 127.0901},
            },
        )
        assert ended_session.status_code == 200
        ended_payload = ended_session.json()
        assert ended_payload["status"] == "COMPLETED"
        assert ended_payload["endedAt"].endswith("Z")
        assert ended_payload["summary"]["behaviorEventCount"] == 1
        assert ended_payload["summary"]["interventionCount"] == 1
        assert ended_payload["summary"]["correctedBehaviorCount"] == 1

        active_after_end = await client.get(
            f"/api/v1/driving-sessions/active?profileId={profile_id}"
        )
        assert active_after_end.status_code == 204
        assert active_after_end.content == b""

        session_detail = await client.get(f"/api/v1/driving-sessions/{session_id}")
        assert session_detail.status_code == 200
        assert session_detail.json()["status"] == "COMPLETED"

        session_history = await client.get(
            f"/api/v1/profiles/{profile_id}/driving-sessions?page=1&size=20"
        )
        assert session_history.status_code == 200
        assert session_history.json()["total"] == 1
        assert session_history.json()["items"][0]["id"] == session_id

        report_day = (base_time + timedelta(hours=9)).date().isoformat()
        report_params = {"periodStart": report_day, "periodEnd": report_day}
        report_summary = await client.get(
            f"/api/v1/profiles/{profile_id}/reports/summary",
            params=report_params,
        )
        report_behavior = await client.get(
            f"/api/v1/profiles/{profile_id}/reports/behavior-events",
            params=report_params,
        )
        report_sessions = await client.get(
            f"/api/v1/profiles/{profile_id}/reports/sessions",
            params=report_params,
        )
        assert report_summary.status_code == 200
        assert report_summary.json()["overview"]["totalSessions"] == 1
        assert report_summary.json()["behaviorCounts"]["PHONE_USE"] == 1
        assert report_behavior.status_code == 200
        assert report_behavior.json()["totalEventCount"] == 1
        assert report_sessions.status_code == 200
        assert report_sessions.json()["total"] == 1
        assert report_sessions.json()["items"][0]["sessionId"] == session_id
        assert_no_snake_case_keys(report_summary.json())
        assert_no_snake_case_keys(report_behavior.json())
        assert_no_snake_case_keys(report_sessions.json())

        deleted_search = await client.delete(
            f"/api/v1/profiles/{profile_id}/search-histories"
        )
        assert deleted_search.status_code == 200
        assert deleted_search.json()["deletedCount"] == 3

        deleted_favorite = await client.delete(f"/api/v1/saved-places/{favorite_id}")
        assert deleted_favorite.status_code == 204
        assert deleted_favorite.content == b""

        deleted_profile = await client.delete(f"/api/v1/profiles/{profile_id}")
        assert deleted_profile.status_code == 204
        assert deleted_profile.content == b""

        assert await count_rows(DriverProfile, DriverProfile.id == profile_id) == 0
        assert await count_rows(SavedPlace, SavedPlace.id == home_id) == 0
        assert await count_rows(SearchHistory, SearchHistory.profile_id == profile_id) == 0
        assert await count_rows(DrivingSession, DrivingSession.id == session_id) == 0
        assert await count_rows(LocationSample, LocationSample.session_id == session_id) == 0
        assert await count_rows(BehaviorEvent, BehaviorEvent.id == seeded["event_id"]) == 0
        assert await count_rows(Intervention, Intervention.id == seeded["intervention_id"]) == 0
        assert await count_rows(DriverResponse, DriverResponse.id == seeded["response_id"]) == 0
        assert await count_rows(AgentConversation, AgentConversation.id == conversation_id) == 0
        assert await count_rows(AgentMessage, AgentMessage.id == seeded["first_message_id"]) == 0
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()
