from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.dependencies import AppSettings, CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.behavior_sensitivity import DriveSummaryRequest
from app.schemas.profile import (
    ProfileCreateRequest,
    ProfileListResponse,
    ProfileResponse,
    ProfileSelectResponse,
    ProfileUpdateRequest,
)
from app.services.profile_service import ProfileService
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["profiles"])

COMMON_PROFILE_RESPONSES = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def get_profile_service(
    session: DbSession,
    settings: AppSettings,
) -> ProfileService:
    return ProfileService(session=session, settings=settings)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]
ProfilePath = Annotated[str, Path(alias="profileId")]


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
    "/profiles",
    response_model=ProfileListResponse,
    responses={500: {"model": ErrorResponse}},
)
async def list_profiles(
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileListResponse:
    return await service.list_profiles(current_account)


@router.post(
    "/profiles",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_profile(
    request: ProfileCreateRequest,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileResponse:
    return await service.create_profile(current_account, request)


@router.get(
    "/profiles/{profileId}",
    response_model=ProfileResponse,
    responses=COMMON_PROFILE_RESPONSES,
)
async def get_profile(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileResponse:
    return await service.get_profile(current_account, parse_profile_id(profile_id))


@router.patch(
    "/profiles/{profileId}",
    response_model=ProfileResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_profile(
    profile_id: ProfilePath,
    request: ProfileUpdateRequest,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileResponse:
    return await service.update_profile(current_account, parse_profile_id(profile_id), request)


@router.post(
    "/profiles/{profileId}/behavior-warning-sensitivity/drive-summary",
    response_model=ProfileResponse,
    responses={
        409: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def update_behavior_warning_sensitivity_from_drive_summary(
    profile_id: ProfilePath,
    request: DriveSummaryRequest,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileResponse:
    return await service.update_behavior_warning_sensitivity_from_drive_summary(
        current_account,
        parse_profile_id(profile_id),
        request,
    )


@router.delete(
    "/profiles/{profileId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def delete_profile(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> Response:
    await service.delete_profile(current_account, parse_profile_id(profile_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/profiles/{profileId}/select",
    response_model=ProfileSelectResponse,
    responses=COMMON_PROFILE_RESPONSES,
)
async def select_profile(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: ProfileServiceDep,
) -> ProfileSelectResponse:
    return await service.select_profile(current_account, parse_profile_id(profile_id))
