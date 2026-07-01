from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentConversationCreateRequest, AgentConversationCreateResponse


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
