from collections.abc import Awaitable, Callable

from app.ai.driver_monitoring import DriverMonitoringAdapter
from app.core.config import Settings
from app.core.time import utc_now_for_api_response
from app.db.init_db import check_database_connection
from app.schemas.health import HealthResponse, HealthServices, ServiceState


class DatabaseUnavailableError(Exception):
    pass


class HealthService:
    def __init__(
        self,
        settings: Settings,
        db_checker: Callable[[], Awaitable[None]] = check_database_connection,
        driver_monitoring_adapter: DriverMonitoringAdapter | None = None,
        vit_model_checker: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.settings = settings
        self.db_checker = db_checker
        self.driver_monitoring_adapter = driver_monitoring_adapter
        self.vit_model_checker = vit_model_checker

    async def get_health(self) -> HealthResponse:
        try:
            await self.db_checker()
        except Exception as exc:
            raise DatabaseUnavailableError("Database connection check failed.") from exc

        vit_model_available = await self.is_vit_model_available()
        services = HealthServices(
            database="UP",
            vit_model=self._service_state(vit_model_available),
            gemini=self._service_state(self.is_gemini_configured()),
            email=self._service_state(self.is_email_configured()),
        )
        status = (
            "UP"
            if all(
                state == "UP"
                for state in (services.vit_model, services.gemini, services.email)
            )
            else "DEGRADED"
        )

        return HealthResponse(
            status=status,
            services=services,
            model_version=self.settings.model_version,
            policy_version=self.settings.policy_version,
            checked_at=utc_now_for_api_response(),
        )

    async def is_vit_model_available(self) -> bool:
        if self.vit_model_checker is not None:
            return await self.vit_model_checker()
        if self.driver_monitoring_adapter is None:
            raise RuntimeError("Driver monitoring adapter is not configured.")
        return await self.driver_monitoring_adapter.is_ready()

    def is_gemini_configured(self) -> bool:
        return bool(
            self.settings.gemini_api_key
            and self.settings.gemini_model
            and self.settings.gemini_behavior_sensitivity_prompt
        )

    def is_email_configured(self) -> bool:
        return all(
            (
                self.settings.email_provider,
                self.settings.email_host,
                self.settings.email_port,
                self.settings.email_username,
                self.settings.email_password,
                self.settings.email_from,
            )
        )

    @staticmethod
    def _service_state(is_available: bool) -> ServiceState:
        return "UP" if is_available else "DOWN"
