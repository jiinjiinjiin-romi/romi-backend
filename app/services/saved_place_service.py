import logging

from fastapi import status
from pydantic_core import PydanticCustomError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlaceType
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.models import Account, SavedPlace
from app.repositories.profile_repository import ProfileRepository
from app.repositories.saved_place_repository import SavedPlaceRepository
from app.schemas.saved_place import (
    FixedPlacesResponse,
    SavedPlaceListResponse,
    SavedPlaceResponse,
    SavedPlaceSummaryResponse,
    SavedPlaceUpdateRequest,
    SavedPlaceUpdateResponse,
    SavedPlaceWriteRequest,
    normalize_saved_place_values,
)

logger = logging.getLogger(__name__)

FIXED_PLACE_TYPES = {
    PlaceType.HOME.value,
    PlaceType.WORK.value,
    PlaceType.SCHOOL.value,
}


class SavedPlaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profile_repository = ProfileRepository(session)
        self.saved_place_repository = SavedPlaceRepository(session)

    async def list_saved_places(
        self,
        account: Account,
        profile_id: str,
    ) -> SavedPlaceListResponse:
        try:
            profile = await self.profile_repository.get_by_account(account.id, profile_id)
            if profile is None:
                raise self._profile_not_found()

            places = await self.saved_place_repository.list_by_profile(profile_id)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Saved place list database error profile_id=%s", profile_id)
            raise AppException(
                "저장 장소 목록을 불러오지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

        fixed_places = FixedPlacesResponse()
        favorites: list[SavedPlaceSummaryResponse] = []

        for place in places:
            summary = SavedPlaceSummaryResponse.model_validate(place)
            if place.place_type == PlaceType.HOME.value:
                fixed_places.home = summary
            elif place.place_type == PlaceType.WORK.value:
                fixed_places.work = summary
            elif place.place_type == PlaceType.SCHOOL.value:
                fixed_places.school = summary
            elif place.place_type == PlaceType.FAVORITE.value:
                favorites.append(summary)

        return SavedPlaceListResponse(fixed_places=fixed_places, favorites=favorites)

    async def upsert_fixed_place(
        self,
        account: Account,
        profile_id: str,
        place_type: str,
        request: SavedPlaceWriteRequest,
    ) -> SavedPlaceResponse:
        if place_type not in FIXED_PLACE_TYPES:
            raise AppException(
                "집, 회사, 학교만 이 API를 통해 저장할 수 있습니다.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.INVALID_FIXED_PLACE_TYPE,
            )

        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            place = await self.saved_place_repository.get_fixed_by_profile_and_type(
                profile.id,
                place_type,
            )
            place_data = request.to_place_data()

            if place is None:
                place = SavedPlace(
                    profile_id=profile.id,
                    place_type=place_type,
                    **place_data,
                )
                self.saved_place_repository.add(place)
            else:
                self._apply_place_data(place, place_data)

            await self.session.flush()
            await self.session.refresh(place)
            await self.session.commit()
            return SavedPlaceResponse.model_validate(place)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Fixed place upsert integrity error profile_id=%s", profile_id)
            raise AppException(
                "장소 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PLACE_SETTING,
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Fixed place upsert database error profile_id=%s", profile_id)
            raise AppException(
                "저장 장소를 저장하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def create_favorite(
        self,
        account: Account,
        profile_id: str,
        request: SavedPlaceWriteRequest,
    ) -> SavedPlaceResponse:
        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            place_data = request.to_place_data()
            duplicate = await self.saved_place_repository.find_duplicate_favorite(
                profile_id=profile.id,
                provider=place_data["provider"],
                provider_place_id=place_data["provider_place_id"],
                latitude=place_data["latitude"],
                longitude=place_data["longitude"],
            )
            if duplicate is not None:
                raise self._duplicate_favorite()

            place = SavedPlace(
                profile_id=profile.id,
                place_type=PlaceType.FAVORITE.value,
                **place_data,
            )
            self.saved_place_repository.add(place)

            await self.session.flush()
            await self.session.refresh(place)
            await self.session.commit()
            return SavedPlaceResponse.model_validate(place)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Favorite create integrity error profile_id=%s", profile_id)
            raise self._duplicate_favorite() from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Favorite create database error profile_id=%s", profile_id)
            raise AppException(
                "즐겨찾기를 저장하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def update_favorite(
        self,
        account: Account,
        place_id: str,
        request: SavedPlaceUpdateRequest,
    ) -> SavedPlaceUpdateResponse:
        update_data = request.to_update_data()
        if not update_data:
            raise AppException(
                "수정할 장소 정보를 하나 이상 입력해 주세요.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.EMPTY_UPDATE_REQUEST,
            )

        try:
            place = await self.saved_place_repository.get_owned_by_account_for_update(
                account.id,
                place_id,
            )
            if place is None:
                raise self._saved_place_not_found()

            if place.place_type != PlaceType.FAVORITE.value:
                raise AppException(
                    "집, 회사, 학교는 전용 저장 API를 사용해 수정해야 합니다.",
                    status_code=status.HTTP_409_CONFLICT,
                    error_code=ErrorCode.FIXED_PLACE_UPDATE_NOT_ALLOWED,
                )

            final_data = self._final_favorite_data(place, update_data)
            duplicate = await self.saved_place_repository.find_duplicate_favorite(
                profile_id=place.profile_id,
                provider=final_data["provider"],
                provider_place_id=final_data["provider_place_id"],
                latitude=final_data["latitude"],
                longitude=final_data["longitude"],
                exclude_place_id=place.id,
            )
            if duplicate is not None:
                raise self._duplicate_favorite()

            self._apply_place_data(place, update_data)
            await self.session.flush()
            await self.session.refresh(place)
            await self.session.commit()
            return SavedPlaceUpdateResponse.model_validate(place)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Favorite update integrity error place_id=%s", place_id)
            raise self._duplicate_favorite() from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Favorite update database error place_id=%s", place_id)
            raise AppException(
                "저장 장소를 수정하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def delete_saved_place(self, account: Account, place_id: str) -> None:
        try:
            place = await self.saved_place_repository.get_owned_by_account_for_update(
                account.id,
                place_id,
            )
            if place is None:
                raise self._saved_place_not_found()

            await self.saved_place_repository.delete(place)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Saved place delete database error place_id=%s", place_id)
            raise AppException(
                "저장 장소를 삭제하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    @staticmethod
    def _apply_place_data(place: SavedPlace, place_data: dict[str, object]) -> None:
        for field_name, value in place_data.items():
            setattr(place, field_name, value)

    @staticmethod
    def _final_favorite_data(
        place: SavedPlace,
        update_data: dict[str, object],
    ) -> dict[str, object]:
        try:
            return normalize_saved_place_values(
                label=update_data.get("label", place.label),
                provider=place.provider,
                provider_place_id=place.provider_place_id,
                address=update_data.get("address", place.address),
                latitude=update_data.get("latitude", place.latitude),
                longitude=update_data.get("longitude", place.longitude),
            )
        except PydanticCustomError as exc:
            error_type = str(getattr(exc, "type", ""))
            if error_type == ErrorCode.EMPTY_PLACE_ADDRESS.value:
                raise AppException(
                    "장소 주소를 입력해 주세요.",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    error_code=ErrorCode.EMPTY_PLACE_ADDRESS,
                ) from exc
            if error_type == ErrorCode.INVALID_COORDINATES.value:
                raise AppException(
                    "위도 또는 경도 값이 올바르지 않습니다.",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    error_code=ErrorCode.INVALID_COORDINATES,
                ) from exc
            raise AppException(
                "장소 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PLACE_SETTING,
            ) from exc

    @staticmethod
    def _profile_not_found() -> AppException:
        return AppException(
            "운전자 프로필을 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.PROFILE_NOT_FOUND,
        )

    @staticmethod
    def _saved_place_not_found() -> AppException:
        return AppException(
            "저장된 장소를 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.SAVED_PLACE_NOT_FOUND,
        )

    @staticmethod
    def _duplicate_favorite() -> AppException:
        return AppException(
            "이미 즐겨찾기에 등록된 장소입니다.",
            status_code=status.HTTP_409_CONFLICT,
            error_code=ErrorCode.DUPLICATE_FAVORITE,
        )
