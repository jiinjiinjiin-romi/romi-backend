from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchHistory


class SearchHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_profile(
        self,
        *,
        profile_id: str,
        page: int,
        size: int,
    ) -> list[SearchHistory]:
        offset = (page - 1) * size
        result = await self.session.execute(
            select(SearchHistory)
            .where(SearchHistory.profile_id == profile_id)
            .order_by(desc(SearchHistory.searched_at), desc(SearchHistory.id))
            .offset(offset)
            .limit(size)
        )
        return list(result.scalars().all())

    async def count_by_profile(self, profile_id: str) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(SearchHistory)
            .where(SearchHistory.profile_id == profile_id)
        )
        return int(count or 0)

    async def delete_by_profile(self, profile_id: str) -> int:
        result = await self.session.execute(
            delete(SearchHistory).where(SearchHistory.profile_id == profile_id)
        )
        return int(result.rowcount or 0)

    def add(self, history: SearchHistory) -> None:
        self.session.add(history)
