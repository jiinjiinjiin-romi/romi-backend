from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlaceType
from app.models import DriverProfile, SavedPlace


class SavedPlaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_profile(self, profile_id: str) -> list[SavedPlace]:
        result = await self.session.execute(
            select(SavedPlace)
            .where(SavedPlace.profile_id == profile_id)
            .order_by(desc(SavedPlace.created_at), desc(SavedPlace.id))
        )
        return list(result.scalars().all())

    async def get_fixed_by_profile_and_type(
        self,
        profile_id: str,
        place_type: str,
    ) -> SavedPlace | None:
        result = await self.session.execute(
            select(SavedPlace).where(
                SavedPlace.profile_id == profile_id,
                SavedPlace.place_type == place_type,
            )
        )
        return result.scalar_one_or_none()

    async def get_owned_by_account_for_update(
        self,
        account_id: str,
        place_id: str,
    ) -> SavedPlace | None:
        result = await self.session.execute(
            select(SavedPlace)
            .join(DriverProfile, SavedPlace.profile_id == DriverProfile.id)
            .where(
                SavedPlace.id == place_id,
                DriverProfile.account_id == account_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def find_duplicate_favorite(
        self,
        *,
        profile_id: str,
        provider: str,
        provider_place_id: str | None,
        latitude: float,
        longitude: float,
        exclude_place_id: str | None = None,
    ) -> SavedPlace | None:
        conditions = [
            SavedPlace.profile_id == profile_id,
            SavedPlace.place_type == PlaceType.FAVORITE.value,
            SavedPlace.provider == provider,
        ]

        if provider_place_id is not None:
            conditions.append(SavedPlace.provider_place_id == provider_place_id)
        else:
            conditions.extend(
                [
                    SavedPlace.provider_place_id.is_(None),
                    SavedPlace.latitude == latitude,
                    SavedPlace.longitude == longitude,
                ]
            )

        if exclude_place_id is not None:
            conditions.append(SavedPlace.id != exclude_place_id)

        result = await self.session.execute(select(SavedPlace).where(*conditions).limit(1))
        return result.scalar_one_or_none()

    def add(self, place: SavedPlace) -> None:
        self.session.add(place)

    async def delete(self, place: SavedPlace) -> None:
        await self.session.delete(place)
