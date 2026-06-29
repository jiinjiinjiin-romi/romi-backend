import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def check_database_connection() -> None:
    async with asyncio.timeout(5):
        async with AsyncSessionLocal() as session:
            await check_database_connection_with_session(session)


async def check_database_connection_with_session(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))
