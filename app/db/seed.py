import asyncio
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.enums import AgentPersonality, PlaceType, Theme, WarningSensitivity
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, DriverProfile, SavedPlace

logger = logging.getLogger(__name__)

SeedResult = Literal["created", "updated", "unchanged"]
DEFAULT_FAMILY_PROFILE_IMAGE_BASE_URL = "/storage/profile-images/default-family"
DEFAULT_FAMILY_PROFILES = (
    {
        "display_name": "아빠",
        "agent_call_name": "나비",
        "profile_image_url": f"{DEFAULT_FAMILY_PROFILE_IMAGE_BASE_URL}/father.svg",
    },
    {
        "display_name": "엄마",
        "agent_call_name": "나비",
        "profile_image_url": f"{DEFAULT_FAMILY_PROFILE_IMAGE_BASE_URL}/mother.svg",
    },
    {
        "display_name": "지우",
        "agent_call_name": "나비",
        "profile_image_url": f"{DEFAULT_FAMILY_PROFILE_IMAGE_BASE_URL}/child.svg",
    },
)
DEFAULT_NAVIGATION_LABELS = (
    {
        "place_type": PlaceType.FAVORITE.value,
        "label": "집",
        "provider": "TMAP",
        "provider_place_id": "origin:default-home",
        "address": "서울 중구 세종대로 110",
        "latitude": 37.5547,
        "longitude": 126.9706,
    },
    {
        "place_type": PlaceType.FAVORITE.value,
        "label": "회사",
        "provider": "TMAP",
        "provider_place_id": "destination:default-work",
        "address": "서울 강남구 테헤란로 152",
        "latitude": 37.4979,
        "longitude": 127.0276,
    },
)


class SeedError(RuntimeError):
    pass


async def seed_default_admin_account(session: AsyncSession, settings: Settings) -> SeedResult:
    admin_id = settings.default_admin_account_id
    admin_email = settings.default_admin_email

    if admin_email is not None:
        result = await session.execute(
            select(Account).where(Account.email == admin_email, Account.id != admin_id)
        )
        conflicting_account = result.scalar_one_or_none()
        if conflicting_account is not None:
            raise SeedError(
                "Default admin email is already used by another account: "
                f"{conflicting_account.id}"
            )

    account = await session.get(Account, admin_id)

    if account is None:
        session.add(Account(id=admin_id, email=admin_email))
        return "created"

    if account.email != admin_email:
        account.email = admin_email
        return "updated"

    return "unchanged"


async def seed_default_family_profiles(session: AsyncSession, account_id: str) -> int:
    profile_count = await session.scalar(
        select(func.count())
        .select_from(DriverProfile)
        .where(DriverProfile.account_id == account_id)
    )

    if int(profile_count or 0) > 0:
        return 0

    for profile_data in DEFAULT_FAMILY_PROFILES:
        session.add(
            DriverProfile(
                account_id=account_id,
                display_name=profile_data["display_name"],
                agent_call_name=profile_data["agent_call_name"],
                profile_image_url=profile_data["profile_image_url"],
                report_email=None,
                agent_personality=AgentPersonality.FRIENDLY.value,
                warning_sensitivity=WarningSensitivity.MEDIUM.value,
                tts_voice_id=None,
                tts_speed=Decimal("1.00"),
                guidance_volume=70,
                theme=Theme.LIGHT.value,
            )
        )

    return len(DEFAULT_FAMILY_PROFILES)


async def seed_default_navigation_labels(
    session: AsyncSession,
    profiles: list[DriverProfile],
) -> int:
    seeded_count = 0

    for profile in profiles:
        saved_places = getattr(session, "saved_places", None)
        if saved_places is None:
            place_count = await session.scalar(
                select(func.count())
                .select_from(SavedPlace)
                .where(SavedPlace.profile_id == profile.id)
            )
        else:
            place_count = sum(
                1 for saved_place in saved_places if saved_place.profile_id == profile.id
            )

        if int(place_count or 0) > 0:
            continue

        for label_data in DEFAULT_NAVIGATION_LABELS:
            session.add(
                SavedPlace(
                    profile_id=profile.id,
                    **label_data,
                )
            )
            seeded_count += 1

    return seeded_count


async def list_account_profiles(session: AsyncSession, account_id: str) -> list[DriverProfile]:
    if hasattr(session, "profiles"):
        return list(getattr(session, "profiles"))

    result = await session.execute(
        select(DriverProfile).where(DriverProfile.account_id == account_id)
    )
    return list(result.scalars().all())


async def run_seed(
    settings: Settings | None = None,
    session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
) -> SeedResult:
    active_settings = settings or get_settings()

    async with session_factory() as session:
        try:
            result = await seed_default_admin_account(session, active_settings)
            seeded_profiles = await seed_default_family_profiles(
                session,
                active_settings.default_admin_account_id,
            )
            await session.flush()
            account_profiles = await list_account_profiles(
                session,
                active_settings.default_admin_account_id,
            )
            seeded_labels = await seed_default_navigation_labels(session, account_profiles)
            await session.commit()
            logger.info(
                "Default seed completed: account=%s family_profiles=%s navigation_labels=%s",
                result,
                seeded_profiles,
                seeded_labels,
            )
            return result
        except Exception:
            await session.rollback()
            logger.exception("Default admin account seed failed")
            raise


async def run_seed_command() -> SeedResult:
    try:
        return await run_seed()
    finally:
        await dispose_engine()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    try:
        asyncio.run(run_seed_command())
    except Exception as exc:
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
