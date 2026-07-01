from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.dependencies import AppSettings, CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.integrations.driver_monitoring import (
    DriverMonitoringReadiness,
    HealthDriverMonitoringReadiness,
)
from app.schemas.agent import AgentConversationCreateRequest, AgentConversationCreateResponse
from app.schemas.driving_session import (
    ActiveDrivingSessionResponse,
    DrivingSessionDetailResponse,
    DrivingSessionEndRequest,
    DrivingSessionEndResponse,
    DrivingSessionHistoryResponse,
    DrivingSessionLocationsResponse,
    DrivingSessionStartRequest,
    DrivingSessionStartResponse,
    DrivingSessionTimelineResponse,
)
from app.services.agent_conversation_service import AgentConversationService
from app.services.driving_session_service import DrivingSessionService
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["driving-sessions"])

ProfilePath = Annotated[str, Path(alias="profileId")]
SessionPath = Annotated[str, Path(alias="sessionId")]
ProfileQuery = Annotated[str, Query(alias="profileId")]


def get_driver_monitoring_readiness(settings: AppSettings) -> DriverMonitoringReadiness:
    return HealthDriverMonitoringReadiness(settings)


DriverMonitoringReadinessDep = Annotated[
    DriverMonitoringReadiness,
    Depends(get_driver_monitoring_readiness),
]


def get_driving_session_service(
    session: DbSession,
    settings: AppSettings,
    readiness: DriverMonitoringReadinessDep,
) -> DrivingSessionService:
    return DrivingSessionService(session=session, settings=settings, readiness=readiness)


DrivingSessionServiceDep = Annotated[
    DrivingSessionService,
    Depends(get_driving_session_service),
]


def get_agent_conversation_service(session: DbSession) -> AgentConversationService:
    return AgentConversationService(session=session)


AgentConversationServiceDep = Annotated[
    AgentConversationService,
    Depends(get_agent_conversation_service),
]


def parse_profile_id(profile_id: str) -> str:
    try:
        return normalize_uuid_string(profile_id)
    except ValueError as exc:
        raise AppException(
            "Profile ID format is invalid.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_PROFILE_ID,
        ) from exc


def parse_session_id(session_id: str) -> str:
    try:
        return normalize_uuid_string(session_id)
    except ValueError as exc:
        raise AppException(
            "Driving session ID format is invalid.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_SESSION_ID,
        ) from exc


@router.post(
    "/driving-sessions",
    response_model=DrivingSessionStartResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def start_driving_session(
    request: DrivingSessionStartRequest,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
) -> DrivingSessionStartResponse:
    return await service.start_session(current_account, request)


@router.get(
    "/driving-sessions/active",
    response_model=ActiveDrivingSessionResponse,
    responses={
        200: {"model": ActiveDrivingSessionResponse},
        204: {"description": "No active driving session."},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_active_driving_session(
    profile_id: ProfileQuery,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
) -> ActiveDrivingSessionResponse | Response:
    active_session = await service.get_active_session(
        current_account,
        parse_profile_id(profile_id),
    )
    if active_session is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return active_session


@router.get(
    "/driving-sessions/{sessionId}",
    response_model=DrivingSessionDetailResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_driving_session(
    session_id: SessionPath,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
) -> DrivingSessionDetailResponse:
    return await service.get_session_detail(current_account, parse_session_id(session_id))


@router.get(
    "/driving-sessions/{sessionId}/timeline",
    response_model=DrivingSessionTimelineResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_driving_session_timeline(
    session_id: SessionPath,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
) -> DrivingSessionTimelineResponse:
    return await service.get_session_timeline(current_account, parse_session_id(session_id))


@router.get(
    "/driving-sessions/{sessionId}/locations",
    response_model=DrivingSessionLocationsResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_driving_session_locations(
    session_id: SessionPath,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
    from_value: str | None = Query(default=None, alias="from"),
    to_value: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> DrivingSessionLocationsResponse:
    return await service.get_session_locations(
        current_account,
        parse_session_id(session_id),
        from_value=from_value,
        to_value=to_value,
        limit=limit,
    )


@router.post(
    "/driving-sessions/{sessionId}/agent/conversations",
    response_model=AgentConversationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {
            "model": ErrorResponse,
            "description": "SAFETY_CONVERSATION_NOT_ALLOWED",
        },
        404: {
            "model": ErrorResponse,
            "description": "SESSION_NOT_FOUND",
        },
        409: {
            "model": ErrorResponse,
            "description": "SESSION_NOT_ACTIVE",
        },
        422: {
            "model": ErrorResponse,
            "description": "INVALID_SESSION_ID or INVALID_CONVERSATION_MODE",
        },
    },
)
async def start_agent_conversation(
    session_id: SessionPath,
    request: AgentConversationCreateRequest,
    current_account: CurrentAccount,
    service: AgentConversationServiceDep,
) -> AgentConversationCreateResponse:
    return await service.start_general_conversation(
        current_account,
        parse_session_id(session_id),
        request,
    )


@router.post(
    "/driving-sessions/{sessionId}/end",
    response_model=DrivingSessionEndResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def end_driving_session(
    session_id: SessionPath,
    request: DrivingSessionEndRequest,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
) -> DrivingSessionEndResponse:
    return await service.end_session(
        current_account,
        parse_session_id(session_id),
        request,
    )


@router.get(
    "/profiles/{profileId}/driving-sessions",
    response_model=DrivingSessionHistoryResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def list_driving_sessions(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: DrivingSessionServiceDep,
    page: int = Query(default=1),
    size: int = Query(default=20),
    status_filter: str | None = Query(default=None, alias="status"),
    started_from: str | None = Query(default=None, alias="startedFrom"),
    started_to: str | None = Query(default=None, alias="startedTo"),
) -> DrivingSessionHistoryResponse:
    return await service.list_history(
        current_account,
        parse_profile_id(profile_id),
        page=page,
        size=size,
        status_filter=status_filter,
        started_from=started_from,
        started_to=started_to,
    )
