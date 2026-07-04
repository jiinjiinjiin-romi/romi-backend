import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.ai.driver_monitoring import DriverMonitoringAdapter
from app.core.config import Settings, get_settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.db.session import get_session
from app.models import Account
from app.repositories.account_repository import AccountRepository

logger = logging.getLogger(__name__)


def get_request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def get_settings_dependency() -> Settings:
    return get_settings()


def get_driver_monitoring_adapter(
    connection: HTTPConnection,
) -> DriverMonitoringAdapter:
    adapter = getattr(connection.app.state, "driver_monitoring_adapter", None)
    if adapter is None:
        raise AppException(
            "Driver monitoring adapter is not initialized.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        )
    return adapter


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings_dependency)]
DriverMonitoringAdapterDep = Annotated[
    DriverMonitoringAdapter,
    Depends(get_driver_monitoring_adapter),
]


async def load_current_account(session: AsyncSession, settings: Settings) -> Account:
    repository = AccountRepository(session)

    try:
        account = await repository.get_default_admin(settings.default_admin_account_id)
    except SQLAlchemyError as exc:
        logger.exception("Failed to load current account")
        raise AppException(
            "데이터베이스에 연결할 수 없습니다.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=ErrorCode.DATABASE_UNAVAILABLE,
        ) from exc

    if account is None:
        logger.error(
            "Default admin account does not exist account_id=%s",
            settings.default_admin_account_id,
        )
        raise AppException(
            "기본 관리자 계정을 찾을 수 없습니다.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        )

    return account


async def get_current_account(
    session: DbSession,
    settings: AppSettings,
) -> Account:
    return await load_current_account(session, settings)


CurrentAccount = Annotated[Account, Depends(get_current_account)]
