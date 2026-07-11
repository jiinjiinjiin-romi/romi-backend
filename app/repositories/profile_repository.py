from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DriverProfile


def profile_ordering() -> tuple[object, object, object, object]:
    return (
        DriverProfile.last_used_at.is_(None),
        desc(DriverProfile.last_used_at),
        desc(DriverProfile.created_at),
        DriverProfile.id,
    )


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_account(self, account_id: str) -> list[DriverProfile]:
        result = await self.session.execute(
            select(DriverProfile)
            .where(DriverProfile.account_id == account_id)
            .order_by(*profile_ordering())
        )
        return list(result.scalars().all())

    async def get_by_account(self, account_id: str, profile_id: str) -> DriverProfile | None:
        result = await self.session.execute(
            select(DriverProfile).where(
                DriverProfile.id == profile_id,
                DriverProfile.account_id == account_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_account_for_update(
        self,
        account_id: str,
        profile_id: str,
    ) -> DriverProfile | None:
        result = await self.session.execute(
            select(DriverProfile)
            .where(
                DriverProfile.id == profile_id,
                DriverProfile.account_id == account_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_account_for_update_current(
        self,
        account_id: str,
        profile_id: str,
    ) -> DriverProfile | None:
        result = await self.session.execute(
            select(DriverProfile)
            .where(
                DriverProfile.id == profile_id,
                DriverProfile.account_id == account_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def count_by_account(self, account_id: str) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(DriverProfile)
            .where(DriverProfile.account_id == account_id)
        )
        return int(count or 0)

    def add(self, profile: DriverProfile) -> None:
        self.session.add(profile)

    async def delete(self, profile: DriverProfile) -> None:
        await self.session.delete(profile)
