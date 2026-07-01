from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.dependencies import CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.agent import AgentConversationDetailResponse
from app.services.agent_conversation_service import AgentConversationService
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["agent"])

ConversationPath = Annotated[str, Path(alias="conversationId")]


def get_agent_conversation_service(session: DbSession) -> AgentConversationService:
    return AgentConversationService(session=session)


AgentConversationServiceDep = Annotated[
    AgentConversationService,
    Depends(get_agent_conversation_service),
]


def parse_conversation_id(conversation_id: str) -> str:
    try:
        return normalize_uuid_string(conversation_id)
    except ValueError as exc:
        raise AppException(
            "Agent 대화 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_CONVERSATION_ID,
        ) from exc


@router.get(
    "/agent/conversations/{conversationId}",
    response_model=AgentConversationDetailResponse,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "CONVERSATION_NOT_FOUND",
        },
        422: {
            "model": ErrorResponse,
            "description": "INVALID_CONVERSATION_ID",
        },
    },
)
async def get_agent_conversation(
    conversation_id: ConversationPath,
    current_account: CurrentAccount,
    service: AgentConversationServiceDep,
) -> AgentConversationDetailResponse:
    return await service.get_conversation(
        current_account,
        parse_conversation_id(conversation_id),
    )
