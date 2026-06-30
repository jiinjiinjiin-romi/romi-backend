from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.dependencies import CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.saved_place import (
    SavedPlaceListResponse,
    SavedPlaceResponse,
    SavedPlaceUpdateRequest,
    SavedPlaceUpdateResponse,
    SavedPlaceWriteRequest,
)
from app.services.saved_place_service import SavedPlaceService
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["saved-places"])

ProfilePath = Annotated[str, Path(alias="profileId")]
PlacePath = Annotated[str, Path(alias="placeId")]
PlaceTypePath = Annotated[str, Path(alias="placeType")]


def get_saved_place_service(session: DbSession) -> SavedPlaceService:
    return SavedPlaceService(session=session)


SavedPlaceServiceDep = Annotated[SavedPlaceService, Depends(get_saved_place_service)]


def parse_profile_id(profile_id: str) -> str:
    try:
        return normalize_uuid_string(profile_id)
    except ValueError as exc:
        raise AppException(
            "프로필 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_PROFILE_ID,
        ) from exc


def parse_place_id(place_id: str) -> str:
    try:
        return normalize_uuid_string(place_id)
    except ValueError as exc:
        raise AppException(
            "저장 장소 ID 형식이 올바르지 않습니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_SAVED_PLACE_ID,
        ) from exc


@router.get(
    "/profiles/{profileId}/saved-places",
    response_model=SavedPlaceListResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def list_saved_places(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: SavedPlaceServiceDep,
) -> SavedPlaceListResponse:
    return await service.list_saved_places(current_account, parse_profile_id(profile_id))


@router.put(
    "/profiles/{profileId}/saved-places/{placeType}",
    response_model=SavedPlaceResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upsert_fixed_place(
    profile_id: ProfilePath,
    place_type: PlaceTypePath,
    request: SavedPlaceWriteRequest,
    current_account: CurrentAccount,
    service: SavedPlaceServiceDep,
) -> SavedPlaceResponse:
    return await service.upsert_fixed_place(
        current_account,
        parse_profile_id(profile_id),
        place_type,
        request,
    )


@router.post(
    "/profiles/{profileId}/favorites",
    response_model=SavedPlaceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_favorite(
    profile_id: ProfilePath,
    request: SavedPlaceWriteRequest,
    current_account: CurrentAccount,
    service: SavedPlaceServiceDep,
) -> SavedPlaceResponse:
    return await service.create_favorite(
        current_account,
        parse_profile_id(profile_id),
        request,
    )


@router.patch(
    "/saved-places/{placeId}",
    response_model=SavedPlaceUpdateResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_favorite(
    place_id: PlacePath,
    request: SavedPlaceUpdateRequest,
    current_account: CurrentAccount,
    service: SavedPlaceServiceDep,
) -> SavedPlaceUpdateResponse:
    return await service.update_favorite(current_account, parse_place_id(place_id), request)


@router.delete(
    "/saved-places/{placeId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def delete_saved_place(
    place_id: PlacePath,
    current_account: CurrentAccount,
    service: SavedPlaceServiceDep,
) -> Response:
    await service.delete_saved_place(current_account, parse_place_id(place_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
