import logging

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_api_response
from app.models import Account
from app.repositories.profile_repository import ProfileRepository
from app.repositories.search_history_repository import SearchHistoryRepository
from app.schemas.search_history import (
    SearchHistoryDeleteResponse,
    SearchHistoryItemResponse,
    SearchHistoryListResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_HISTORY_PAGE = 1
DEFAULT_SEARCH_HISTORY_SIZE = 20
MAX_SEARCH_HISTORY_SIZE = 100


class SearchHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profile_repository = ProfileRepository(session)
        self.search_history_repository = SearchHistoryRepository(session)

    async def list_search_histories(
        self,
        account: Account,
        profile_id: str,
        *,
        page: int,
        size: int,
    ) -> SearchHistoryListResponse:
        self._validate_pagination(page, size)

        try:
            profile = await self.profile_repository.get_by_account(account.id, profile_id)
            if profile is None:
                raise self._profile_not_found()

            total = await self.search_history_repository.count_by_profile(profile_id)
            histories = await self.search_history_repository.list_by_profile(
                profile_id=profile_id,
                page=page,
                size=size,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Search history list database error profile_id=%s", profile_id)
            raise AppException(
                "검색 기록을 불러오지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

        return SearchHistoryListResponse.from_items(
            items=[SearchHistoryItemResponse.model_validate(history) for history in histories],
            page=page,
            size=size,
            total=total,
        )

    async def delete_search_histories(
        self,
        account: Account,
        profile_id: str,
    ) -> SearchHistoryDeleteResponse:
        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            deleted_count = await self.search_history_repository.delete_by_profile(profile.id)
            await self.session.commit()
            return SearchHistoryDeleteResponse(
                deleted_count=deleted_count,
                deleted_at=utc_now_for_api_response(),
            )
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Search history delete database error profile_id=%s", profile_id)
            raise AppException(
                "검색 기록을 삭제하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    @staticmethod
    def _validate_pagination(page: int, size: int) -> None:
        if page < 1:
            raise AppException(
                "페이지 번호는 1 이상이어야 합니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PAGE,
            )

        if size < 1 or size > MAX_SEARCH_HISTORY_SIZE:
            raise AppException(
                "페이지 크기는 1 이상 100 이하로 설정해야 합니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PAGE_SIZE,
            )

    @staticmethod
    def _profile_not_found() -> AppException:
        return AppException(
            "운전자 프로필을 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.PROFILE_NOT_FOUND,
        )
