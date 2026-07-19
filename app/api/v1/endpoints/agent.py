from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.dependencies import AppSettings, CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.agent import (
    AgentConversationDetailResponse,
    AgentConversationMessageCreateRequest,
    AgentConversationMessageCreateResponse,
    AgentDriverResponseCreateRequest,
    AgentDriverResponseCreateResponse,
    AgentInterventionPlanRequest,
    AgentInterventionPlanResponse,
)
from app.services.agent_conversation_service import AgentConversationService
from app.services.agent_runtime_service import AgentRuntimeService
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["agent"])

ConversationPath = Annotated[str, Path(alias="conversationId")]
BehaviorEventPath = Annotated[str, Path(alias="behaviorEventId")]
InterventionPath = Annotated[str, Path(alias="interventionId")]


def get_agent_conversation_service(session: DbSession) -> AgentConversationService:
    return AgentConversationService(session=session)


AgentConversationServiceDep = Annotated[
    AgentConversationService,
    Depends(get_agent_conversation_service),
]


def get_agent_runtime_service(session: DbSession, settings: AppSettings) -> AgentRuntimeService:
    return AgentRuntimeService(session=session, settings=settings)


AgentRuntimeServiceDep = Annotated[
    AgentRuntimeService,
    Depends(get_agent_runtime_service),
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


def parse_behavior_event_id(behavior_event_id: str) -> str:
    try:
        return normalize_uuid_string(behavior_event_id)
    except ValueError as exc:
        raise AppException(
            "행동 이벤트 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.VALIDATION_ERROR,
        ) from exc


def parse_intervention_id(intervention_id: str) -> str:
    try:
        return normalize_uuid_string(intervention_id)
    except ValueError as exc:
        raise AppException(
            "개입 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.VALIDATION_ERROR,
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


@router.post(
    "/agent/behavior-events/{behaviorEventId}/interventions",
    response_model=AgentInterventionPlanResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def plan_agent_intervention(
    behavior_event_id: BehaviorEventPath,
    request: AgentInterventionPlanRequest,
    current_account: CurrentAccount,
    service: AgentRuntimeServiceDep,
) -> AgentInterventionPlanResponse:
    return await service.plan_intervention(
        account_id=current_account.id,
        behavior_event_id=parse_behavior_event_id(behavior_event_id),
        request=request,
    )


@router.post(
    "/agent/conversations/{conversationId}/messages",
    response_model=AgentConversationMessageCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def create_agent_conversation_message(
    conversation_id: ConversationPath,
    request: AgentConversationMessageCreateRequest,
    current_account: CurrentAccount,
    service: AgentRuntimeServiceDep,
) -> AgentConversationMessageCreateResponse:
    return await service.send_message(
        account_id=current_account.id,
        conversation_id=parse_conversation_id(conversation_id),
        request=request,
    )


@router.post(
    "/agent/interventions/{interventionId}/responses",
    response_model=AgentDriverResponseCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def record_agent_driver_response(
    intervention_id: InterventionPath,
    request: AgentDriverResponseCreateRequest,
    current_account: CurrentAccount,
    service: AgentRuntimeServiceDep,
) -> AgentDriverResponseCreateResponse:
    return await service.record_driver_response(
        account_id=current_account.id,
        intervention_id=parse_intervention_id(intervention_id),
        request=request,
    )
