from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException
from app.schemas.agent import AgentConversationCreateRequest
from app.services.agent_conversation_service import AgentConversationService

SESSION_ID = "67371b45-204c-4d87-b8f7-8a334229a41e"
ACCOUNT_ID = "274d9648-e78a-4630-a8e8-e63070dc3c19"
CONVERSATION_ID = "9a6222e0-777f-414e-a0ba-9d756233468d"


class FakeSession:
    def __init__(self) -> None:
        self.flush = AsyncMock()
        self.refresh = AsyncMock(side_effect=self._refresh)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def _refresh(self, conversation) -> None:
        if conversation.id is None:
            conversation.id = CONVERSATION_ID


class FakeDrivingSessionRepository:
    def __init__(self, driving_session=None, error: Exception | None = None) -> None:
        self.driving_session = driving_session
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def get_owned_by_account_for_update(self, *, account_id: str, session_id: str):
        self.calls.append((account_id, session_id))
        if self.error is not None:
            raise self.error
        return self.driving_session


class FakeAgentConversationRepository:
    def __init__(self) -> None:
        self.added = None

    def add(self, conversation) -> None:
        self.added = conversation


def make_service(
    *,
    driving_session=None,
    repository_error: Exception | None = None,
) -> tuple[
    AgentConversationService,
    FakeSession,
    FakeDrivingSessionRepository,
    FakeAgentConversationRepository,
]:
    fake_session = FakeSession()
    service = AgentConversationService(session=fake_session)  # type: ignore[arg-type]
    driving_repository = FakeDrivingSessionRepository(
        driving_session=driving_session,
        error=repository_error,
    )
    conversation_repository = FakeAgentConversationRepository()
    service.driving_session_repository = driving_repository  # type: ignore[assignment]
    service.agent_conversation_repository = conversation_repository  # type: ignore[assignment]
    return service, fake_session, driving_repository, conversation_repository


async def test_start_general_conversation_creates_active_conversation() -> None:
    driving_session = SimpleNamespace(id=SESSION_ID, status="ACTIVE")
    service, fake_session, driving_repository, conversation_repository = make_service(
        driving_session=driving_session,
    )

    response = await service.start_general_conversation(
        SimpleNamespace(id=ACCOUNT_ID),
        SESSION_ID,
        AgentConversationCreateRequest(mode="GENERAL_ASSISTANT"),
    )

    assert UUID(response.id).version == 4
    assert response.session_id == SESSION_ID
    assert response.mode == "GENERAL_ASSISTANT"
    assert response.status == "ACTIVE"
    assert isinstance(response.started_at, datetime)
    assert driving_repository.calls == [(ACCOUNT_ID, SESSION_ID)]

    conversation = conversation_repository.added
    assert conversation is not None
    assert conversation.session_id == SESSION_ID
    assert conversation.trigger_behavior_event_id is None
    assert conversation.mode == "GENERAL_ASSISTANT"
    assert conversation.status == "ACTIVE"
    assert conversation.ended_at is None

    fake_session.flush.assert_awaited_once()
    fake_session.refresh.assert_awaited_once_with(conversation)
    fake_session.commit.assert_awaited_once()
    fake_session.rollback.assert_not_awaited()


async def test_start_general_conversation_missing_session_returns_not_found() -> None:
    service, fake_session, _, _ = make_service(driving_session=None)

    with pytest.raises(AppException) as exc_info:
        await service.start_general_conversation(
            SimpleNamespace(id=ACCOUNT_ID),
            SESSION_ID,
            AgentConversationCreateRequest(mode="GENERAL_ASSISTANT"),
        )

    assert exc_info.value.error_code == "SESSION_NOT_FOUND"
    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()


@pytest.mark.parametrize("session_status", ["COMPLETED", "ABORTED"])
async def test_start_general_conversation_requires_active_session(session_status: str) -> None:
    service, fake_session, _, _ = make_service(
        driving_session=SimpleNamespace(id=SESSION_ID, status=session_status),
    )

    with pytest.raises(AppException) as exc_info:
        await service.start_general_conversation(
            SimpleNamespace(id=ACCOUNT_ID),
            SESSION_ID,
            AgentConversationCreateRequest(mode="GENERAL_ASSISTANT"),
        )

    assert exc_info.value.error_code == "SESSION_NOT_ACTIVE"
    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()


async def test_start_general_conversation_rejects_safety_mode() -> None:
    service, fake_session, driving_repository, _ = make_service(
        driving_session=SimpleNamespace(id=SESSION_ID, status="ACTIVE"),
    )

    with pytest.raises(AppException) as exc_info:
        await service.start_general_conversation(
            SimpleNamespace(id=ACCOUNT_ID),
            SESSION_ID,
            AgentConversationCreateRequest(mode="SAFETY"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "SAFETY_CONVERSATION_NOT_ALLOWED"
    assert driving_repository.calls == []
    fake_session.rollback.assert_not_awaited()
    fake_session.commit.assert_not_awaited()


async def test_start_general_conversation_rejects_unknown_mode() -> None:
    service, fake_session, driving_repository, _ = make_service(
        driving_session=SimpleNamespace(id=SESSION_ID, status="ACTIVE"),
    )

    with pytest.raises(AppException) as exc_info:
        await service.start_general_conversation(
            SimpleNamespace(id=ACCOUNT_ID),
            SESSION_ID,
            AgentConversationCreateRequest.model_construct(mode="UNKNOWN"),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_CONVERSATION_MODE"
    assert driving_repository.calls == []
    fake_session.rollback.assert_not_awaited()
    fake_session.commit.assert_not_awaited()


async def test_start_general_conversation_rolls_back_on_repository_failure() -> None:
    service, fake_session, _, _ = make_service(
        repository_error=SQLAlchemyError("database unavailable"),
    )

    with pytest.raises(AppException) as exc_info:
        await service.start_general_conversation(
            SimpleNamespace(id=ACCOUNT_ID),
            SESSION_ID,
            AgentConversationCreateRequest(mode="GENERAL_ASSISTANT"),
        )

    assert exc_info.value.error_code == "INTERNAL_SERVER_ERROR"
    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()
