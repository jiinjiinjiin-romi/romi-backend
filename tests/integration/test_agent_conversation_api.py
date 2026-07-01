import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select

from app.api.dependencies import get_current_account
from app.db.session import AsyncSessionLocal, dispose_engine, engine
from app.models import (
    Account,
    AgentConversation,
    AgentMessage,
    DriverProfile,
    DrivingSession,
    ToolExecution,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)

BASE_TIME = datetime(2026, 6, 28, 3, 10, 0)


def make_account(prefix: str) -> Account:
    return Account(id=str(uuid4()), email=f"{prefix}-{uuid4().hex}@example.com")


def make_profile(account_id: str, display_name: str) -> DriverProfile:
    return DriverProfile(
        id=str(uuid4()),
        account_id=account_id,
        display_name=display_name[:50],
        agent_call_name=display_name[:50],
    )


def make_session(
    profile_id: str,
    *,
    session_status: str = "ACTIVE",
    started_at: datetime = BASE_TIME,
) -> DrivingSession:
    ended_at = None if session_status == "ACTIVE" else started_at + timedelta(minutes=10)
    end_reason = None
    if session_status == "COMPLETED":
        end_reason = "USER_REQUEST"
    elif session_status == "ABORTED":
        end_reason = "CAMERA_LOST"

    return DrivingSession(
        id=str(uuid4()),
        profile_id=profile_id,
        started_at=started_at,
        ended_at=ended_at,
        status=session_status,
        end_reason=end_reason,
        model_version="vit-test",
        policy_version="policy-test",
    )


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_current_account(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override


async def seed_account_profile_session(
    *,
    prefix: str,
    session_status: str = "ACTIVE",
) -> tuple[Account, DriverProfile, DrivingSession]:
    account = make_account(prefix)
    profile = make_profile(account.id, f"{prefix} Profile")
    driving_session = make_session(profile.id, session_status=session_status)

    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.flush()
        session.add(profile)
        await session.flush()
        session.add(driving_session)
        await session.commit()

    return account, profile, driving_session


def make_conversation(
    session_id: str,
    *,
    conversation_status: str = "ACTIVE",
    started_at: datetime = BASE_TIME,
) -> AgentConversation:
    ended_at = None
    if conversation_status != "ACTIVE":
        ended_at = started_at + timedelta(minutes=1, seconds=10)
    return AgentConversation(
        id=str(uuid4()),
        session_id=session_id,
        mode="GENERAL_ASSISTANT",
        status=conversation_status,
        started_at=started_at,
        ended_at=ended_at,
    )


def make_message(
    conversation_id: str,
    *,
    sequence_no: int,
    role: str = "USER",
    text: str | None = "Message",
    intent: str | None = None,
    input_type: str | None = "VOICE",
    created_at: datetime = BASE_TIME,
) -> AgentMessage:
    return AgentMessage(
        id=str(uuid4()),
        conversation_id=conversation_id,
        sequence_no=sequence_no,
        role=role,
        text=text,
        intent=intent,
        input_type=input_type,
        metadata_json={},
        created_at=created_at,
    )


async def count_messages_and_tools(conversation_ids: list[str]) -> tuple[int, int]:
    async with AsyncSessionLocal() as session:
        message_count = await session.scalar(
            select(func.count())
            .select_from(AgentMessage)
            .where(AgentMessage.conversation_id.in_(conversation_ids))
        )
        tool_count = await session.scalar(
            select(func.count())
            .select_from(ToolExecution)
            .join(AgentMessage, ToolExecution.message_id == AgentMessage.id)
            .where(AgentMessage.conversation_id.in_(conversation_ids))
        )
    return int(message_count or 0), int(tool_count or 0)


async def test_agent_conversation_detail_api_returns_sorted_messages_and_fixed_queries(
    app,
    client,
) -> None:
    account, _, driving_session = await seed_account_profile_session(prefix="agent-detail")
    conversation = make_conversation(
        driving_session.id,
        conversation_status="COMPLETED",
        started_at=BASE_TIME,
    )

    async with AsyncSessionLocal() as session:
        session.add(conversation)
        await session.flush()
        session.add_all(
            [
                make_message(
                    conversation.id,
                    sequence_no=3,
                    role="USER",
                    text="Third",
                    intent=None,
                    input_type="TEXT",
                    created_at=BASE_TIME + timedelta(seconds=4),
                ),
                make_message(
                    conversation.id,
                    sequence_no=1,
                    role="USER",
                    text="Turn down guidance volume.",
                    intent="SET_GUIDANCE_VOLUME",
                    input_type="VOICE",
                    created_at=BASE_TIME + timedelta(seconds=2),
                ),
                make_message(
                    conversation.id,
                    sequence_no=2,
                    role="AGENT",
                    text="Guidance volume is now 50.",
                    intent=None,
                    input_type="SYSTEM_EVENT",
                    created_at=BASE_TIME + timedelta(seconds=3),
                ),
            ]
        )
        await session.commit()

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
        table_names = (
            "agent_conversations",
            "agent_messages",
            "driving_sessions",
            "driver_profiles",
        )
        if lowered.lstrip().startswith("select") and any(name in lowered for name in table_names):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = await client.get(f"/api/v1/agent/conversations/{conversation.id}")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)

    try:
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == conversation.id
        assert payload["sessionId"] == driving_session.id
        assert payload["mode"] == "GENERAL_ASSISTANT"
        assert payload["status"] == "COMPLETED"
        assert payload["startedAt"] == "2026-06-28T03:10:00.000000Z"
        assert payload["endedAt"] == "2026-06-28T03:11:10.000000Z"
        assert [message["sequenceNo"] for message in payload["messages"]] == [1, 2, 3]
        assert payload["messages"][0]["role"] == "USER"
        assert payload["messages"][0]["text"] == "Turn down guidance volume."
        assert payload["messages"][0]["intent"] == "SET_GUIDANCE_VOLUME"
        assert payload["messages"][0]["inputType"] == "VOICE"
        assert payload["messages"][0]["createdAt"] == "2026-06-28T03:10:02.000000Z"
        assert payload["messages"][1]["intent"] is None

        assert "profileId" not in payload
        assert "accountId" not in payload
        assert "triggerBehaviorEventId" not in payload
        assert "toolExecutions" not in payload
        assert "conversationId" not in payload["messages"][0]
        assert "metadataJson" not in payload["messages"][0]
        assert "toolExecutionId" not in payload["messages"][0]
        assert len(statements) == 2
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_agent_conversation_detail_api_returns_statuses_and_empty_messages(
    app,
    client,
) -> None:
    account, _, driving_session = await seed_account_profile_session(
        prefix="agent-detail-status",
    )
    conversations = [
        make_conversation(
            driving_session.id,
            conversation_status="ACTIVE",
            started_at=BASE_TIME,
        ),
        make_conversation(
            driving_session.id,
            conversation_status="COMPLETED",
            started_at=BASE_TIME + timedelta(minutes=5),
        ),
        make_conversation(
            driving_session.id,
            conversation_status="ABORTED",
            started_at=BASE_TIME + timedelta(minutes=10),
        ),
    ]

    async with AsyncSessionLocal() as session:
        session.add_all(conversations)
        await session.commit()

    override_current_account(app, account)

    try:
        for conversation in conversations:
            response = await client.get(f"/api/v1/agent/conversations/{conversation.id}")
            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == conversation.id
            assert payload["status"] == conversation.status
            assert payload["messages"] == []
            if conversation.status == "ACTIVE":
                assert payload["endedAt"] is None
            else:
                assert payload["endedAt"].endswith("Z")
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_agent_conversation_detail_api_errors(app, client) -> None:
    current_account = make_account("agent-detail-current")
    other_account = make_account("agent-detail-other")
    current_profile = make_profile(current_account.id, "Current Agent Detail")
    other_profile = make_profile(other_account.id, "Other Agent Detail")
    current_session = make_session(current_profile.id, started_at=BASE_TIME)
    other_session = make_session(other_profile.id, started_at=BASE_TIME)
    other_conversation = make_conversation(other_session.id, started_at=BASE_TIME)

    async with AsyncSessionLocal() as session:
        session.add_all([current_account, other_account])
        await session.flush()
        session.add_all([current_profile, other_profile])
        await session.flush()
        session.add_all([current_session, other_session])
        await session.flush()
        session.add(other_conversation)
        await session.commit()

    override_current_account(app, current_account)

    try:
        other_response = await client.get(
            f"/api/v1/agent/conversations/{other_conversation.id}",
        )
        missing_response = await client.get(f"/api/v1/agent/conversations/{uuid4()}")
        invalid_response = await client.get("/api/v1/agent/conversations/not-a-uuid")

        assert other_response.status_code == 404
        assert other_response.json()["error"] == "CONVERSATION_NOT_FOUND"
        assert missing_response.status_code == 404
        assert missing_response.json()["error"] == "CONVERSATION_NOT_FOUND"
        assert invalid_response.status_code == 422
        assert invalid_response.json()["error"] == "INVALID_CONVERSATION_ID"

        for response in [other_response, missing_response, invalid_response]:
            assert "detail" not in response.json()
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()


async def test_agent_conversation_create_then_detail_returns_empty_messages(
    app,
    client,
) -> None:
    account, _, driving_session = await seed_account_profile_session(prefix="agent-create-get")
    override_current_account(app, account)

    try:
        create_response = await client.post(
            f"/api/v1/driving-sessions/{driving_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        assert create_response.status_code == 201
        created = create_response.json()

        detail_response = await client.get(
            f"/api/v1/agent/conversations/{created['id']}",
        )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["id"] == created["id"]
        assert payload["sessionId"] == driving_session.id
        assert payload["status"] == "ACTIVE"
        assert payload["endedAt"] is None
        assert payload["messages"] == []
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_agent_conversation_create_api_inserts_container_only(app, client) -> None:
    account, _, driving_session = await seed_account_profile_session(prefix="agent-create")
    override_current_account(app, account)

    try:
        first_response = await client.post(
            f"/api/v1/driving-sessions/{driving_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        second_response = await client.post(
            f"/api/v1/driving-sessions/{driving_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 201
        first_payload = first_response.json()
        second_payload = second_response.json()
        conversation_ids = [first_payload["id"], second_payload["id"]]

        assert UUID(first_payload["id"]).version == 4
        assert UUID(second_payload["id"]).version == 4
        assert first_payload["id"] != second_payload["id"]
        assert first_payload["sessionId"] == driving_session.id
        assert first_payload["mode"] == "GENERAL_ASSISTANT"
        assert first_payload["status"] == "ACTIVE"
        assert first_payload["startedAt"].endswith("Z")
        assert "accountId" not in first_payload
        assert "profileId" not in first_payload
        assert "triggerBehaviorEventId" not in first_payload
        assert "endedAt" not in first_payload
        assert "messages" not in first_payload
        assert "toolExecutions" not in first_payload

        async with AsyncSessionLocal() as session:
            conversations = list(
                (
                    await session.execute(
                        select(AgentConversation)
                        .where(AgentConversation.session_id == driving_session.id)
                        .order_by(AgentConversation.started_at, AgentConversation.id)
                    )
                )
                .scalars()
                .all()
            )

        assert len(conversations) == 2
        assert {conversation.id for conversation in conversations} == set(conversation_ids)
        assert {conversation.mode for conversation in conversations} == {"GENERAL_ASSISTANT"}
        assert {conversation.status for conversation in conversations} == {"ACTIVE"}
        assert {conversation.trigger_behavior_event_id for conversation in conversations} == {None}
        assert {conversation.ended_at for conversation in conversations} == {None}
        assert all(conversation.started_at is not None for conversation in conversations)

        message_count, tool_count = await count_messages_and_tools(conversation_ids)
        assert message_count == 0
        assert tool_count == 0
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_agent_conversation_create_api_errors(app, client) -> None:
    current_account = make_account("agent-errors-current")
    other_account = make_account("agent-errors-other")
    current_profile = make_profile(current_account.id, "Current Agent Errors")
    other_profile = make_profile(other_account.id, "Other Agent Errors")
    active_session = make_session(current_profile.id, started_at=BASE_TIME)
    completed_session = make_session(
        current_profile.id,
        session_status="COMPLETED",
        started_at=BASE_TIME + timedelta(hours=1),
    )
    aborted_session = make_session(
        current_profile.id,
        session_status="ABORTED",
        started_at=BASE_TIME + timedelta(hours=2),
    )
    other_session = make_session(other_profile.id, started_at=BASE_TIME)

    async with AsyncSessionLocal() as session:
        session.add_all([current_account, other_account])
        await session.flush()
        session.add_all([current_profile, other_profile])
        await session.flush()
        session.add_all([active_session, completed_session, aborted_session, other_session])
        await session.commit()

    override_current_account(app, current_account)

    try:
        completed_response = await client.post(
            f"/api/v1/driving-sessions/{completed_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        aborted_response = await client.post(
            f"/api/v1/driving-sessions/{aborted_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        other_response = await client.post(
            f"/api/v1/driving-sessions/{other_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        missing_response = await client.post(
            f"/api/v1/driving-sessions/{uuid4()}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        invalid_session_response = await client.post(
            "/api/v1/driving-sessions/not-a-uuid/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        safety_response = await client.post(
            f"/api/v1/driving-sessions/{active_session.id}/agent/conversations",
            json={"mode": "SAFETY"},
        )
        unknown_mode_response = await client.post(
            f"/api/v1/driving-sessions/{active_session.id}/agent/conversations",
            json={"mode": "UNKNOWN"},
        )
        missing_mode_response = await client.post(
            f"/api/v1/driving-sessions/{active_session.id}/agent/conversations",
            json={},
        )
        extra_field_response = await client.post(
            f"/api/v1/driving-sessions/{active_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT", "extra": "nope"},
        )

        assert completed_response.status_code == 409
        assert completed_response.json()["error"] == "SESSION_NOT_ACTIVE"
        assert aborted_response.status_code == 409
        assert aborted_response.json()["error"] == "SESSION_NOT_ACTIVE"
        assert other_response.status_code == 404
        assert other_response.json()["error"] == "SESSION_NOT_FOUND"
        assert missing_response.status_code == 404
        assert missing_response.json()["error"] == "SESSION_NOT_FOUND"
        assert invalid_session_response.status_code == 422
        assert invalid_session_response.json()["error"] == "INVALID_SESSION_ID"
        assert safety_response.status_code == 403
        assert safety_response.json()["error"] == "SAFETY_CONVERSATION_NOT_ALLOWED"
        assert unknown_mode_response.status_code == 422
        assert unknown_mode_response.json()["error"] == "INVALID_CONVERSATION_MODE"
        assert missing_mode_response.status_code == 422
        assert missing_mode_response.json()["error"] == "INVALID_CONVERSATION_MODE"
        assert extra_field_response.status_code == 422
        assert extra_field_response.json()["error"] == "INVALID_CONVERSATION_MODE"

        for response in [
            invalid_session_response,
            safety_response,
            unknown_mode_response,
            missing_mode_response,
            extra_field_response,
        ]:
            assert "detail" not in response.json()
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()


async def test_agent_conversation_is_aborted_when_session_ends(app, client) -> None:
    account, _, driving_session = await seed_account_profile_session(prefix="agent-end")
    override_current_account(app, account)

    try:
        create_response = await client.post(
            f"/api/v1/driving-sessions/{driving_session.id}/agent/conversations",
            json={"mode": "GENERAL_ASSISTANT"},
        )
        assert create_response.status_code == 201
        conversation_id = create_response.json()["id"]

        end_response = await client.post(
            f"/api/v1/driving-sessions/{driving_session.id}/end",
            json={"endReason": "USER_REQUEST"},
        )
        assert end_response.status_code == 200

        async with AsyncSessionLocal() as session:
            ended_session = await session.get(DrivingSession, driving_session.id)
            conversation = await session.get(AgentConversation, conversation_id)

        assert ended_session is not None
        assert conversation is not None
        assert ended_session.status == "COMPLETED"
        assert conversation.status == "ABORTED"
        assert conversation.ended_at == ended_session.ended_at
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()
