import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.api.dependencies import get_current_account, get_settings_dependency
from app.core.config import Settings
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
    ToolExecution,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)

BASE_TIME = datetime(2026, 7, 20, 4, 0, 0)


def make_account(prefix: str) -> Account:
    return Account(id=str(uuid4()), email=f"{prefix}-{uuid4().hex}@example.com")


def make_profile(account_id: str, prefix: str) -> DriverProfile:
    return DriverProfile(
        id=str(uuid4()),
        account_id=account_id,
        display_name=f"{prefix} Driver",
        agent_call_name="로디",
        warning_sensitivity="HIGH",
        behavior_warning_sensitivity={
            "DROWSINESS": 9,
            "PHONE_USE": 9,
            "FOOD_OR_DRINK": 7,
            "GAZE_AWAY": 9,
            "SECONDARY_TASK": 7,
            "REACHING_BEHIND": 7,
            "SMOKING": 7,
        },
    )


def make_session(profile_id: str) -> DrivingSession:
    return DrivingSession(
        id=str(uuid4()),
        profile_id=profile_id,
        started_at=BASE_TIME,
        status="ACTIVE",
        model_version="vit-test",
        policy_version="policy-test",
    )


def make_behavior_event(session_id: str) -> BehaviorEvent:
    return BehaviorEvent(
        id=str(uuid4()),
        session_id=session_id,
        behavior_type="PHONE_USE",
        started_at=BASE_TIME,
        average_confidence=Decimal("0.9000"),
        maximum_confidence=Decimal("0.9500"),
        driving_state="MOVING",
        speed_kph=Decimal("42.00"),
        risk_level=2,
        recurrence_count=2,
    )


def make_conversation(session_id: str) -> AgentConversation:
    return AgentConversation(
        id=str(uuid4()),
        session_id=session_id,
        mode="GENERAL_ASSISTANT",
        status="ACTIVE",
        started_at=BASE_TIME,
    )


def make_intervention(behavior_event_id: str) -> Intervention:
    return Intervention(
        id=str(uuid4()),
        behavior_event_id=behavior_event_id,
        level=2,
        intervention_type="WARNING",
        speech_text="전방을 확인해 주세요.",
        ui_text="휴대폰 사용 위험이 감지되었습니다.",
        channels_json=["VOICE", "VISUAL"],
        status="WAITING_RESPONSE",
    )


async def seed_runtime_graph(prefix: str):
    account = make_account(prefix)
    profile = make_profile(account.id, prefix)
    driving_session = make_session(profile.id)
    behavior_event = make_behavior_event(driving_session.id)

    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.flush()
        session.add(profile)
        await session.flush()
        session.add(driving_session)
        await session.flush()
        session.add(behavior_event)
        await session.commit()

    return account, driving_session, behavior_event


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_current_account(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override
    app.dependency_overrides[get_settings_dependency] = lambda: Settings(
        gemini_api_key="",
        gemini_model="",
    )


async def test_plan_intervention_creates_safety_conversation_and_messages(app, client) -> None:
    account, _, behavior_event = await seed_runtime_graph("agent-plan")
    override_current_account(app, account)

    try:
        response = await client.post(
            f"/api/v1/agent/behavior-events/{behavior_event.id}/interventions",
            json={"channels": ["VOICE"]},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["behaviorEventId"] == behavior_event.id
        assert payload["level"] == 3
        assert payload["interventionType"] == "TOOL_OFFER"
        assert payload["generatedBy"] == "TEMPLATE"
        assert payload["channelsJson"] == ["VOICE"]
        assert payload["status"] == "WAITING_RESPONSE"

        async with AsyncSessionLocal() as session:
            conversation = await session.get(AgentConversation, payload["conversationId"])
            assert conversation is not None
            assert conversation.mode == "SAFETY"
            assert conversation.trigger_behavior_event_id == behavior_event.id
            message_count = await session.scalar(
                select(func.count())
                .select_from(AgentMessage)
                .where(AgentMessage.conversation_id == conversation.id)
            )
        assert message_count == 2
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_conversation_message_uses_backend_fallback_and_records_tool(app, client) -> None:
    account, driving_session, _ = await seed_runtime_graph("agent-message")
    conversation = make_conversation(driving_session.id)

    async with AsyncSessionLocal() as session:
        session.add(conversation)
        await session.commit()

    override_current_account(app, account)

    try:
        response = await client.post(
            f"/api/v1/agent/conversations/{conversation.id}/messages",
            json={"text": "신나는 노래 틀어줘", "inputType": "VOICE"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["conversationId"] == conversation.id
        assert payload["userMessage"]["sequenceNo"] == 1
        assert payload["userMessage"]["intent"] == "PLAY_MUSIC"
        assert payload["agentMessage"]["sequenceNo"] == 2
        assert payload["agentMessage"]["intent"] == "PLAY_MUSIC"
        assert payload["toolExecution"]["toolName"] == "music.play"
        assert payload["toolExecution"]["executionStatus"] == "SUCCEEDED"
        assert payload["toolExecution"]["isSimulated"] is True

        async with AsyncSessionLocal() as session:
            tool = await session.scalar(select(ToolExecution))
            assert tool is not None
            assert tool.arguments_json["mood"] == "drive"
            assert tool.result_json == {"status": "READY", "executionMode": "SIMULATED"}
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_driver_response_records_result_and_resolves_intervention(app, client) -> None:
    account, _, behavior_event = await seed_runtime_graph("agent-response")
    intervention = make_intervention(behavior_event.id)

    async with AsyncSessionLocal() as session:
        session.add(intervention)
        await session.commit()

    override_current_account(app, account)

    try:
        response = await client.post(
            f"/api/v1/agent/interventions/{intervention.id}/responses",
            json={
                "responseType": "VOICE_ACCEPTED",
                "transcript": "알겠어",
                "behaviorCorrected": True,
                "responseLatencyMs": 1800,
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["interventionId"] == intervention.id
        assert payload["responseType"] == "VOICE_ACCEPTED"
        assert payload["behaviorCorrected"] is True

        async with AsyncSessionLocal() as session:
            stored_response = await session.get(DriverResponse, payload["id"])
            stored_intervention = await session.get(Intervention, intervention.id)
            assert stored_response is not None
            assert stored_response.response_latency_ms == 1800
            assert stored_intervention is not None
            assert stored_intervention.status == "RESOLVED"
            assert stored_intervention.ended_at is not None
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()
