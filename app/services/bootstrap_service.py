import logging

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.driver_monitoring import DriverMonitoringAdapter
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.models import Account
from app.repositories.profile_repository import ProfileRepository
from app.schemas.bootstrap import (
    BootstrapAccountResponse,
    BootstrapCapabilitiesResponse,
    BootstrapResponse,
)
from app.schemas.profile import PROFILE_LIMIT, ProfileSummaryResponse
from app.services.health_service import HealthService

logger = logging.getLogger(__name__)


class BootstrapService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        driver_monitoring_adapter: DriverMonitoringAdapter,
    ) -> None:
        self.session = session
        self.settings = settings
        self.driver_monitoring_adapter = driver_monitoring_adapter
        self.profile_repository = ProfileRepository(session)

    async def get_bootstrap(self, account: Account) -> BootstrapResponse:
        try:
            profiles = await self.profile_repository.list_by_account(account.id)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Bootstrap database query failed")
            raise AppException(
                "데이터베이스에 연결할 수 없습니다.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code=ErrorCode.DATABASE_UNAVAILABLE,
            ) from exc
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Bootstrap load failed")
            raise AppException(
                "앱 초기화 정보를 불러오지 못했습니다.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code=ErrorCode.BOOTSTRAP_FAILED,
            ) from exc

        selected_profile = next(
            (profile for profile in profiles if profile.last_used_at is not None),
            None,
        )

        return BootstrapResponse(
            account=BootstrapAccountResponse(
                id=account.id,
                display_name=account.display_name,
                email=account.email,
            ),
            profiles=[ProfileSummaryResponse.model_validate(profile) for profile in profiles],
            selected_profile_id=selected_profile.id if selected_profile is not None else None,
            profile_limit=PROFILE_LIMIT,
            capabilities=await self._capabilities(),
        )

    async def _capabilities(self) -> BootstrapCapabilitiesResponse:
        health_service = HealthService(
            settings=self.settings,
            driver_monitoring_adapter=self.driver_monitoring_adapter,
        )
        return BootstrapCapabilitiesResponse(
            vit_model_available=await health_service.is_vit_model_available(),
            gemini_available=health_service.is_gemini_configured(),
            email_available=health_service.is_email_configured(),
            demo_mode=self.settings.demo_mode,
        )
