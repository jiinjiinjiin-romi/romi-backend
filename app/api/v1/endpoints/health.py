from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_settings_dependency
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.health import HealthResponse
from app.services.health_service import DatabaseUnavailableError, HealthService

router = APIRouter(tags=["health"])


def get_health_service(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> HealthService:
    return HealthService(settings=settings)


@router.get("/health", response_model=HealthResponse)
async def get_health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    try:
        return await service.get_health()
    except DatabaseUnavailableError as exc:
        raise AppException(
            "데이터베이스에 연결할 수 없습니다.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=ErrorCode.DATABASE_UNAVAILABLE,
        ) from exc
