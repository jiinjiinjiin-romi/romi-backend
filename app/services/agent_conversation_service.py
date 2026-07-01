import logging

from fastapi import status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ConversationMode, ConversationStatus, DrivingSessionStatus
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_mysql_datetime
from app.models import Account, AgentConversation
from app.repositories.agent_conversation_repository import AgentConversationRepository
from app.repositories.driving_session_repository import DrivingSessionRepository
from app.schemas.agent import AgentConversationCreateRequest, AgentConversationCreateResponse

logger = logging.getLogger(__name__)


class AgentConversationService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.driving_session_repository = DrivingSessionRepository(session)
        self.agent_conversation_repository = AgentConversationRepository(session)

    async def start_general_conversation(
        self,
        account: Account,
        session_id: str,
        request: AgentConversationCreateRequest,
    ) -> AgentConversationCreateResponse:
        self._validate_create_mode(request.mode)

        try:
            driving_session = await self.driving_session_repository.get_owned_by_account_for_update(
                account_id=account.id,
                session_id=session_id,
            )
            if driving_session is None:
                raise self._session_not_found()

            if driving_session.status != DrivingSessionStatus.ACTIVE.value:
                raise self._session_not_active()

            started_at = utc_now_for_mysql_datetime()
            conversation = AgentConversation(
                session_id=driving_session.id,
                trigger_behavior_event_id=None,
                mode=ConversationMode.GENERAL_ASSISTANT.value,
                status=ConversationStatus.ACTIVE.value,
                started_at=started_at,
                ended_at=None,
            )
            self.agent_conversation_repository.add(conversation)
            await self.session.flush()
            await self.session.refresh(conversation)
            await self.session.commit()
            return self._to_create_response(conversation)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Agent conversation integrity error session_id=%s", session_id)
            raise self._internal_error("Failed to start agent conversation.") from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Agent conversation database error session_id=%s", session_id)
            raise self._internal_error("Failed to start agent conversation.") from exc

    @classmethod
    def _validate_create_mode(cls, mode: str) -> None:
        if mode == ConversationMode.SAFETY.value:
            raise cls._safety_conversation_not_allowed()

        if mode != ConversationMode.GENERAL_ASSISTANT.value:
            raise cls._invalid_conversation_mode()

    @staticmethod
    def _to_create_response(
        conversation: AgentConversation,
    ) -> AgentConversationCreateResponse:
        return AgentConversationCreateResponse(
            id=conversation.id,
            session_id=conversation.session_id,
            mode=conversation.mode,
            status=conversation.status,
            started_at=conversation.started_at,
        )

    @staticmethod
    def _session_not_found() -> AppException:
        return AppException(
            "운전 세션을 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.SESSION_NOT_FOUND,
        )

    @staticmethod
    def _session_not_active() -> AppException:
        return AppException(
            "진행 중인 운전 세션에서만 Agent를 호출할 수 있습니다.",
            status_code=status.HTTP_409_CONFLICT,
            error_code=ErrorCode.SESSION_NOT_ACTIVE,
        )

    @staticmethod
    def _safety_conversation_not_allowed() -> AppException:
        return AppException(
            "안전 개입 대화는 시스템에서만 생성할 수 있습니다.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code=ErrorCode.SAFETY_CONVERSATION_NOT_ALLOWED,
        )

    @staticmethod
    def _invalid_conversation_mode() -> AppException:
        return AppException(
            "지원하지 않는 Agent 대화 모드입니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_CONVERSATION_MODE,
        )

    @staticmethod
    def _internal_error(message: str) -> AppException:
        return AppException(
            message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        )
