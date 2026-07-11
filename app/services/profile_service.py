import logging

from fastapi import status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_mysql_datetime
from app.integrations.gemini.behavior_sensitivity import (
    GeminiBehaviorSensitivityClient,
    GeminiNotConfiguredError,
    GeminiProviderError,
)
from app.integrations.storage.local import LocalStorageAdapter, StorageDeleteError
from app.models import Account, DriverProfile
from app.repositories.account_repository import AccountRepository
from app.repositories.driving_session_repository import DrivingSessionRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.report_export_repository import ReportExportRepository
from app.schemas.behavior_sensitivity import DriveSummaryRequest
from app.schemas.profile import (
    PROFILE_LIMIT,
    ProfileCreateRequest,
    ProfileListResponse,
    ProfileResponse,
    ProfileSelectResponse,
    ProfileUpdateRequest,
)

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        storage_adapter: LocalStorageAdapter | None = None,
        gemini_client: GeminiBehaviorSensitivityClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.account_repository = AccountRepository(session)
        self.profile_repository = ProfileRepository(session)
        self.driving_session_repository = DrivingSessionRepository(session)
        self.report_export_repository = ReportExportRepository(session)
        self.storage_adapter = storage_adapter or LocalStorageAdapter(settings.report_storage_path)
        self.gemini_client = gemini_client or GeminiBehaviorSensitivityClient(settings=settings)

    async def list_profiles(self, account: Account) -> ProfileListResponse:
        try:
            profiles = await self.profile_repository.list_by_account(account.id)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Profile list query failed account_id=%s", account.id)
            raise AppException(
                "운전자 프로필 목록을 불러오지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.PROFILE_LIST_FAILED,
            ) from exc

        return ProfileListResponse(
            profiles=[ProfileResponse.model_validate(profile) for profile in profiles],
            count=len(profiles),
            limit=PROFILE_LIMIT,
        )

    async def create_profile(
        self,
        account: Account,
        request: ProfileCreateRequest,
    ) -> ProfileResponse:
        try:
            locked_account = await self.account_repository.get_by_id_for_update(account.id)
            if locked_account is None:
                logger.error("Current account disappeared account_id=%s", account.id)
                raise AppException(
                    "기본 관리자 계정을 찾을 수 없습니다.",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                )

            profile_count = await self.profile_repository.count_by_account(account.id)
            if profile_count >= PROFILE_LIMIT:
                raise AppException(
                    "운전자 프로필은 최대 5개까지 생성할 수 있습니다.",
                    status_code=status.HTTP_409_CONFLICT,
                    error_code=ErrorCode.PROFILE_LIMIT_EXCEEDED,
                )

            profile = DriverProfile(account_id=account.id, **request.to_model_data())
            self.profile_repository.add(profile)
            await self.session.flush()
            await self.session.refresh(profile)
            await self.session.commit()
            return ProfileResponse.model_validate(profile)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Profile create integrity error account_id=%s", account.id)
            raise AppException(
                "프로필 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PROFILE_SETTING,
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Profile create database error account_id=%s", account.id)
            raise AppException(
                "프로필 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def get_profile(self, account: Account, profile_id: str) -> ProfileResponse:
        profile = await self.profile_repository.get_by_account(account.id, profile_id)
        if profile is None:
            raise self._profile_not_found()
        return ProfileResponse.model_validate(profile)

    async def update_profile(
        self,
        account: Account,
        profile_id: str,
        request: ProfileUpdateRequest,
    ) -> ProfileResponse:
        update_data = request.to_update_data()
        if not update_data:
            raise AppException(
                "수정할 프로필 정보를 하나 이상 입력해 주세요.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.EMPTY_UPDATE_REQUEST,
            )

        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            for field_name, value in update_data.items():
                setattr(profile, field_name, value)

            await self.session.flush()
            await self.session.refresh(profile)
            await self.session.commit()
            return ProfileResponse.model_validate(profile)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("Profile update integrity error profile_id=%s", profile_id)
            raise AppException(
                "프로필 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PROFILE_SETTING,
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Profile update database error profile_id=%s", profile_id)
            raise AppException(
                "프로필 설정값이 올바르지 않습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def update_behavior_warning_sensitivity_from_drive_summary(
        self,
        account: Account,
        profile_id: str,
        request: DriveSummaryRequest,
    ) -> ProfileResponse:
        profile = await self.profile_repository.get_by_account(account.id, profile_id)
        if profile is None:
            raise self._profile_not_found()
        original_sensitivity = dict(profile.behavior_warning_sensitivity)

        telemetry_events = [
            event.model_dump(mode="json", by_alias=True) for event in request.telemetry_events
        ]
        try:
            sensitivity = await self.gemini_client.recommend(telemetry_events)
        except GeminiNotConfiguredError as exc:
            raise AppException(
                "Gemini 민감도 분석 설정이 완료되지 않았습니다.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code=ErrorCode.GEMINI_BEHAVIOR_SENSITIVITY_NOT_CONFIGURED,
            ) from exc
        except GeminiProviderError as exc:
            raise AppException(
                "Gemini 민감도 분석에 실패했습니다.",
                status_code=status.HTTP_502_BAD_GATEWAY,
                error_code=ErrorCode.GEMINI_BEHAVIOR_SENSITIVITY_FAILED,
            ) from exc

        try:
            locked_profile = await self.profile_repository.get_by_account_for_update_current(
                account.id,
                profile_id,
            )
            if locked_profile is None:
                raise self._profile_not_found()
            if dict(locked_profile.behavior_warning_sensitivity) != original_sensitivity:
                raise AppException(
                    "민감도가 수동으로 변경되어 자동 반영을 중단했습니다.",
                    status_code=status.HTTP_409_CONFLICT,
                    error_code=ErrorCode.BEHAVIOR_SENSITIVITY_UPDATE_CONFLICT,
                )

            locked_profile.behavior_warning_sensitivity = sensitivity
            await self.session.flush()
            await self.session.refresh(locked_profile)
            await self.session.commit()
            return ProfileResponse.model_validate(locked_profile)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Behavior sensitivity update failed profile_id=%s", profile_id)
            raise AppException(
                "프로필 민감도를 저장하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def delete_profile(self, account: Account, profile_id: str) -> None:
        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            has_active_session = (
                await self.driving_session_repository.has_active_session_for_profile(profile_id)
            )
            if has_active_session:
                raise AppException(
                    "진행 중인 운전 세션을 종료한 뒤 프로필을 삭제해 주세요.",
                    status_code=status.HTTP_409_CONFLICT,
                    error_code=ErrorCode.ACTIVE_SESSION_EXISTS,
                )

            storage_keys = await self.report_export_repository.list_storage_keys_by_profile(
                profile_id,
            )
            self._delete_profile_files(profile.profile_image_url, storage_keys)
            await self.profile_repository.delete(profile)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Profile delete database error profile_id=%s", profile_id)
            raise AppException(
                "프로필을 삭제하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    async def select_profile(self, account: Account, profile_id: str) -> ProfileSelectResponse:
        selected_at = utc_now_for_mysql_datetime()

        try:
            profile = await self.profile_repository.get_by_account_for_update(
                account.id,
                profile_id,
            )
            if profile is None:
                raise self._profile_not_found()

            profile.last_used_at = selected_at
            await self.session.flush()
            await self.session.commit()
            return ProfileSelectResponse(
                selected_profile_id=profile.id,
                selected_at=selected_at,
            )
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Profile select database error profile_id=%s", profile_id)
            raise AppException(
                "프로필을 선택하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

    def _delete_profile_files(self, profile_image_url: str | None, storage_keys: list[str]) -> None:
        try:
            self.storage_adapter.delete_report_keys(storage_keys)
            self.storage_adapter.delete_profile_image(profile_image_url)
        except StorageDeleteError as exc:
            logger.exception("Profile file delete failed")
            raise AppException(
                "프로필 관련 파일을 삭제하지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.PROFILE_FILE_DELETE_FAILED,
            ) from exc

    @staticmethod
    def _profile_not_found() -> AppException:
        return AppException(
            "운전자 프로필을 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.PROFILE_NOT_FOUND,
        )
