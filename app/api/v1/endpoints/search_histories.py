from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.dependencies import CurrentAccount, DbSession
from app.api.error_handlers import ErrorResponse
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.search_history import SearchHistoryDeleteResponse, SearchHistoryListResponse
from app.services.search_history_service import (
    DEFAULT_SEARCH_HISTORY_PAGE,
    DEFAULT_SEARCH_HISTORY_SIZE,
    MAX_SEARCH_HISTORY_SIZE,
    SearchHistoryService,
)
from app.utils.uuid import normalize_uuid_string

router = APIRouter(tags=["search-histories"])

ProfilePath = Annotated[str, Path(alias="profileId")]
PageQuery = Annotated[int, Query(ge=1)]
SizeQuery = Annotated[int, Query(ge=1, le=MAX_SEARCH_HISTORY_SIZE)]


def get_search_history_service(session: DbSession) -> SearchHistoryService:
    return SearchHistoryService(session=session)


SearchHistoryServiceDep = Annotated[SearchHistoryService, Depends(get_search_history_service)]


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
    "/profiles/{profileId}/search-histories",
    response_model=SearchHistoryListResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def list_search_histories(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: SearchHistoryServiceDep,
    page: PageQuery = DEFAULT_SEARCH_HISTORY_PAGE,
    size: SizeQuery = DEFAULT_SEARCH_HISTORY_SIZE,
) -> SearchHistoryListResponse:
    return await service.list_search_histories(
        current_account,
        parse_profile_id(profile_id),
        page=page,
        size=size,
    )


@router.delete(
    "/profiles/{profileId}/search-histories",
    response_model=SearchHistoryDeleteResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def delete_search_histories(
    profile_id: ProfilePath,
    current_account: CurrentAccount,
    service: SearchHistoryServiceDep,
) -> SearchHistoryDeleteResponse:
    return await service.delete_search_histories(current_account, parse_profile_id(profile_id))
