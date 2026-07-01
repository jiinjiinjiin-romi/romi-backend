from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.agent import (
    AgentConversationCreateRequest,
    AgentConversationCreateResponse,
    AgentConversationDetailResponse,
    AgentMessageResponse,
)


def test_create_request_accepts_general_assistant() -> None:
    request = AgentConversationCreateRequest(mode="GENERAL_ASSISTANT")

    assert request.mode == "GENERAL_ASSISTANT"


def test_create_request_accepts_safety_for_service_level_403_mapping() -> None:
    request = AgentConversationCreateRequest(mode="SAFETY")

    assert request.mode == "SAFETY"


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"mode": "UNKNOWN"}, "INVALID_CONVERSATION_MODE"),
        ({"mode": ""}, "INVALID_CONVERSATION_MODE"),
        ({"mode": 123}, "INVALID_CONVERSATION_MODE"),
        ({}, "missing"),
        ({"mode": "GENERAL_ASSISTANT", "extra": "nope"}, "extra_forbidden"),
    ],
)
def test_create_request_validation_errors(
    payload: dict[str, object],
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentConversationCreateRequest(**payload)

    assert exc_info.value.errors()[0]["type"] == error_type


def test_create_response_serializes_contract_fields_only() -> None:
    response = AgentConversationCreateResponse(
        id="9a6222e0-777f-414e-a0ba-9d756233468d",
        session_id="67371b45-204c-4d87-b8f7-8a334229a41e",
        mode="GENERAL_ASSISTANT",
        status="ACTIVE",
        started_at=datetime(2026, 6, 28, 3, 30, 0, 123456),
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload == {
        "id": "9a6222e0-777f-414e-a0ba-9d756233468d",
        "sessionId": "67371b45-204c-4d87-b8f7-8a334229a41e",
        "mode": "GENERAL_ASSISTANT",
        "status": "ACTIVE",
        "startedAt": "2026-06-28T03:30:00.123456Z",
    }
    assert "accountId" not in payload
    assert "profileId" not in payload
    assert "triggerBehaviorEventId" not in payload
    assert "endedAt" not in payload
    assert "createdAt" not in payload


def test_message_response_serializes_contract_fields_only() -> None:
    response = AgentMessageResponse(
        id="fa28500f-6c8e-4c02-a0cb-c5e6f7f268d1",
        sequence_no=1,
        role="USER",
        text="Turn down guidance volume.",
        intent="SET_GUIDANCE_VOLUME",
        input_type="VOICE",
        created_at=datetime(2026, 6, 28, 3, 30, 2, 123456),
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload == {
        "id": "fa28500f-6c8e-4c02-a0cb-c5e6f7f268d1",
        "sequenceNo": 1,
        "role": "USER",
        "text": "Turn down guidance volume.",
        "intent": "SET_GUIDANCE_VOLUME",
        "inputType": "VOICE",
        "createdAt": "2026-06-28T03:30:02.123456Z",
    }
    assert "conversationId" not in payload
    assert "metadataJson" not in payload
    assert "toolExecutionId" not in payload
    assert "updatedAt" not in payload


def test_detail_response_serializes_empty_messages_and_nullable_fields() -> None:
    response = AgentConversationDetailResponse(
        id="9a6222e0-777f-414e-a0ba-9d756233468d",
        session_id="67371b45-204c-4d87-b8f7-8a334229a41e",
        mode="GENERAL_ASSISTANT",
        status="ACTIVE",
        started_at=datetime(2026, 6, 28, 3, 30, 0),
        ended_at=None,
        messages=[],
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload == {
        "id": "9a6222e0-777f-414e-a0ba-9d756233468d",
        "sessionId": "67371b45-204c-4d87-b8f7-8a334229a41e",
        "mode": "GENERAL_ASSISTANT",
        "status": "ACTIVE",
        "startedAt": "2026-06-28T03:30:00.000000Z",
        "endedAt": None,
        "messages": [],
    }
    assert "profileId" not in payload
    assert "accountId" not in payload
    assert "triggerBehaviorEventId" not in payload
    assert "toolExecutions" not in payload


def test_detail_response_serializes_messages_and_intent_null() -> None:
    response = AgentConversationDetailResponse(
        id="9a6222e0-777f-414e-a0ba-9d756233468d",
        session_id="67371b45-204c-4d87-b8f7-8a334229a41e",
        mode="GENERAL_ASSISTANT",
        status="COMPLETED",
        started_at=datetime(2026, 6, 28, 3, 30, 0),
        ended_at=datetime(2026, 6, 28, 3, 31, 10),
        messages=[
            AgentMessageResponse(
                id="16a7087e-27e3-4ea1-bbeb-83bb817eeec9",
                sequence_no=2,
                role="AGENT",
                text="Guidance volume is now 50.",
                intent=None,
                input_type="SYSTEM_EVENT",
                created_at=datetime(2026, 6, 28, 3, 30, 3),
            )
        ],
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload["endedAt"] == "2026-06-28T03:31:10.000000Z"
    assert payload["messages"] == [
        {
            "id": "16a7087e-27e3-4ea1-bbeb-83bb817eeec9",
            "sequenceNo": 2,
            "role": "AGENT",
            "text": "Guidance volume is now 50.",
            "intent": None,
            "inputType": "SYSTEM_EVENT",
            "createdAt": "2026-06-28T03:30:03.000000Z",
        }
    ]
