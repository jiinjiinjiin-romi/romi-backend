from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session


def get_request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def get_settings_dependency() -> Settings:
    return get_settings()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session
