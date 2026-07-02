from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    AppSettings,
    CurrentAccount,
    DbSession,
    DriverMonitoringAdapterDep,
)
from app.schemas.bootstrap import BootstrapResponse
from app.services.bootstrap_service import BootstrapService

router = APIRouter(tags=["bootstrap"])


def get_bootstrap_service(
    session: DbSession,
    settings: AppSettings,
    driver_monitoring_adapter: DriverMonitoringAdapterDep,
) -> BootstrapService:
    return BootstrapService(
        session=session,
        settings=settings,
        driver_monitoring_adapter=driver_monitoring_adapter,
    )


BootstrapServiceDep = Annotated[BootstrapService, Depends(get_bootstrap_service)]


@router.get("/bootstrap", response_model=BootstrapResponse)
async def get_bootstrap(
    current_account: CurrentAccount,
    service: BootstrapServiceDep,
) -> BootstrapResponse:
    return await service.get_bootstrap(current_account)
