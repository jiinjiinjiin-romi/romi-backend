from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.dependencies import AppSettings, CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.report import (
    BehaviorEventReportResponse,
    ReportNarrativeResponse,
    ReportSessionPageResponse,
    ReportSummaryResponse,
)
from app.services.report_service import (
    DEFAULT_REPORT_SESSION_PAGE,
    DEFAULT_REPORT_SESSION_SIZE,
    MAX_REPORT_SESSION_SIZE,
    ReportService,
)
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["reports"])

ProfilePath = Annotated[str, Path(alias="profileId")]
ReportPeriodStart = Annotated[str, Query(alias="periodStart")]
ReportPeriodEnd = Annotated[str, Query(alias="periodEnd")]

COMMON_REPORT_RESPONSES = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def get_report_service(session: DbSession, settings: AppSettings) -> ReportService:
    return ReportService(session=session, settings=settings)


ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]


def parse_profile_id(profile_id: str) -> str:
    try:
        return normalize_uuid_string(profile_id)
    except ValueError as exc:
        raise AppException(
            "프로필 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_PROFILE_ID,
        ) from exc


@router.get(
    "/profiles/{profileId}/reports/summary",
    response_model=ReportSummaryResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_report_summary(
    profile_id: ProfilePath,
    period_start: ReportPeriodStart,
    period_end: ReportPeriodEnd,
    current_account: CurrentAccount,
    service: ReportServiceDep,
    behavior_types: str | None = Query(default=None, alias="behaviorTypes"),
) -> ReportSummaryResponse:
    return await service.get_summary(
        current_account,
        parse_profile_id(profile_id),
        period_start=period_start,
        period_end=period_end,
        behavior_types=behavior_types,
    )


@router.get(
    "/profiles/{profileId}/reports/narrative",
    response_model=ReportNarrativeResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_report_narrative(
    profile_id: ProfilePath,
    period_start: ReportPeriodStart,
    period_end: ReportPeriodEnd,
    current_account: CurrentAccount,
    service: ReportServiceDep,
    behavior_types: str | None = Query(default=None, alias="behaviorTypes"),
) -> ReportNarrativeResponse:
    return await service.get_narrative(
        current_account,
        parse_profile_id(profile_id),
        period_start=period_start,
        period_end=period_end,
        behavior_types=behavior_types,
    )


@router.get(
    "/profiles/{profileId}/reports/behavior-events",
    response_model=BehaviorEventReportResponse,
    responses=COMMON_REPORT_RESPONSES,
)
async def get_behavior_event_report(
    profile_id: ProfilePath,
    period_start: ReportPeriodStart,
    period_end: ReportPeriodEnd,
    current_account: CurrentAccount,
    service: ReportServiceDep,
    behavior_types: str | None = Query(default=None, alias="behaviorTypes"),
) -> BehaviorEventReportResponse:
    return await service.get_behavior_events(
        current_account,
        parse_profile_id(profile_id),
        period_start=period_start,
        period_end=period_end,
        behavior_types=behavior_types,
    )


@router.get(
    "/profiles/{profileId}/reports/sessions",
    response_model=ReportSessionPageResponse,
    responses=COMMON_REPORT_RESPONSES,
)
async def get_report_sessions(
    profile_id: ProfilePath,
    period_start: ReportPeriodStart,
    period_end: ReportPeriodEnd,
    current_account: CurrentAccount,
    service: ReportServiceDep,
    page: int = Query(default=DEFAULT_REPORT_SESSION_PAGE, ge=1),
    size: int = Query(default=DEFAULT_REPORT_SESSION_SIZE, ge=1, le=MAX_REPORT_SESSION_SIZE),
) -> ReportSessionPageResponse:
    return await service.get_sessions(
        current_account,
        parse_profile_id(profile_id),
        period_start=period_start,
        period_end=period_end,
        page=page,
        size=size,
    )
