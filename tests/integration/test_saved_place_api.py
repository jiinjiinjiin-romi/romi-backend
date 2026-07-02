import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.api.dependencies import get_current_account
from app.core.exceptions import AppException
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, DriverProfile, SavedPlace
from app.schemas.saved_place import SavedPlaceWriteRequest
from app.services.saved_place_service import SavedPlaceService

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


def place_payload(
    label: str = "Smoke Home",
    provider_place_id: str | None = "place-1",
    latitude: float = 37.5501,
    longitude: float = 127.0734,
) -> dict[str, object]:
    return {
        "label": label,
        "provider": "KAKAO",
        "providerPlaceId": provider_place_id,
        "address": f"{label} address",
        "latitude": latitude,
        "longitude": longitude,
    }


async def create_test_account(email_prefix: str = "saved-place-api") -> Account:
    account = Account(id=str(uuid4()), email=f"{email_prefix}-{uuid4().hex}@example.com")
    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.commit()
    return account


async def create_test_profile(account_id: str, display_name: str = "Place API") -> DriverProfile:
    async with AsyncSessionLocal() as session:
        profile = DriverProfile(
            account_id=account_id,
            display_name=display_name,
            agent_call_name=display_name,
        )
        session.add(profile)
        await session.commit()
        return profile


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_current_account(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override


async def test_saved_place_api_full_flow(app, client) -> None:
    account = await create_test_account()
    profile = await create_test_profile(account.id)
    override_current_account(app, account)

    try:
        empty_response = await client.get(f"/api/v1/profiles/{profile.id}/saved-places")
        assert empty_response.status_code == 200
        assert empty_response.json() == {
            "fixedPlaces": {"home": None, "work": None, "school": None},
            "favorites": [],
        }

        home_response = await client.put(
            f"/api/v1/profiles/{profile.id}/saved-places/HOME",
            json=place_payload("Smoke Home", "home-1"),
        )
        assert home_response.status_code == 200
        home = home_response.json()
        assert home["placeType"] == "HOME"

        updated_home_response = await client.put(
            f"/api/v1/profiles/{profile.id}/saved-places/HOME",
            json=place_payload("Updated Home", "home-1", 37.5510, 127.0740),
        )
        assert updated_home_response.status_code == 200
        assert updated_home_response.json()["id"] == home["id"]
        assert updated_home_response.json()["label"] == "Updated Home"

        work_response = await client.put(
            f"/api/v1/profiles/{profile.id}/saved-places/WORK",
            json=place_payload("Smoke Work", "work-1", 37.56, 127.08),
        )
        school_response = await client.put(
            f"/api/v1/profiles/{profile.id}/saved-places/SCHOOL",
            json=place_payload("Smoke School", "school-1", 37.57, 127.09),
        )
        assert work_response.status_code == 200
        assert school_response.status_code == 200

        favorite_response = await client.post(
            f"/api/v1/profiles/{profile.id}/favorites",
            json=place_payload("Smoke Favorite", "favorite-1", 37.5442, 127.0557),
        )
        assert favorite_response.status_code == 201
        favorite = favorite_response.json()
        assert favorite["placeType"] == "FAVORITE"

        duplicate_response = await client.post(
            f"/api/v1/profiles/{profile.id}/favorites",
            json=place_payload("Duplicate Favorite", "favorite-1", 37.5442, 127.0557),
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"] == "DUPLICATE_FAVORITE"

        custom_a_response = await client.post(
            f"/api/v1/profiles/{profile.id}/favorites",
            json=place_payload("Custom A", None, 37.6, 127.1),
        )
        custom_b_response = await client.post(
            f"/api/v1/profiles/{profile.id}/favorites",
            json=place_payload("Custom B", None, 37.7, 127.2),
        )
        assert custom_a_response.status_code == 201
        assert custom_b_response.status_code == 201

        custom_duplicate_response = await client.post(
            f"/api/v1/profiles/{profile.id}/favorites",
            json=place_payload("Custom Duplicate", None, 37.6, 127.1),
        )
        assert custom_duplicate_response.status_code == 409
        assert custom_duplicate_response.json()["error"] == "DUPLICATE_FAVORITE"

        list_response = await client.get(f"/api/v1/profiles/{profile.id}/saved-places")
        assert list_response.status_code == 200
        places = list_response.json()
        assert places["fixedPlaces"]["home"]["id"] == home["id"]
        assert places["fixedPlaces"]["work"]["id"] == work_response.json()["id"]
        assert places["fixedPlaces"]["school"]["id"] == school_response.json()["id"]
        assert {place["placeType"] for place in places["favorites"]} == {"FAVORITE"}

        patch_response = await client.patch(
            f"/api/v1/saved-places/{favorite['id']}",
            json={
                "label": "Updated Favorite",
                "address": "Updated address",
                "latitude": 37.5445,
                "longitude": 127.0561,
            },
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["label"] == "Updated Favorite"
        assert "createdAt" not in patch_response.json()

        patch_duplicate_response = await client.patch(
            f"/api/v1/saved-places/{custom_b_response.json()['id']}",
            json={"latitude": 37.6, "longitude": 127.1},
        )
        assert patch_duplicate_response.status_code == 409
        assert patch_duplicate_response.json()["error"] == "DUPLICATE_FAVORITE"

        fixed_patch_response = await client.patch(
            f"/api/v1/saved-places/{home['id']}",
            json={"label": "Should Fail"},
        )
        assert fixed_patch_response.status_code == 409
        assert fixed_patch_response.json()["error"] == "FIXED_PLACE_UPDATE_NOT_ALLOWED"

        favorite_delete_response = await client.delete(f"/api/v1/saved-places/{favorite['id']}")
        home_delete_response = await client.delete(f"/api/v1/saved-places/{home['id']}")
        assert favorite_delete_response.status_code == 204
        assert favorite_delete_response.content == b""
        assert home_delete_response.status_code == 204
        assert home_delete_response.content == b""
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_saved_place_api_validation_and_other_account_access(app, client) -> None:
    current_account = await create_test_account("current-place")
    other_account = await create_test_account("other-place")
    current_profile = await create_test_profile(current_account.id, "Current")
    other_profile = await create_test_profile(other_account.id, "Other")
    override_current_account(app, current_account)

    try:
        async with AsyncSessionLocal() as session:
            other_place = SavedPlace(
                profile_id=other_profile.id,
                place_type="FAVORITE",
                label="Other Favorite",
                provider_place_id="other-favorite",
                address="Other address",
                latitude=37.0,
                longitude=127.0,
            )
            session.add(other_place)
            await session.commit()
            other_place_id = other_place.id

        other_profile_response = await client.get(
            f"/api/v1/profiles/{other_profile.id}/saved-places"
        )
        assert other_profile_response.status_code == 404
        assert other_profile_response.json()["error"] == "PROFILE_NOT_FOUND"

        other_place_response = await client.patch(
            f"/api/v1/saved-places/{other_place_id}",
            json={"label": "Nope"},
        )
        assert other_place_response.status_code == 404
        assert other_place_response.json()["error"] == "SAVED_PLACE_NOT_FOUND"

        invalid_profile_response = await client.get("/api/v1/profiles/not-a-uuid/saved-places")
        assert invalid_profile_response.status_code == 422
        assert invalid_profile_response.json()["error"] == "INVALID_PROFILE_ID"
        assert "detail" not in invalid_profile_response.json()

        invalid_place_response = await client.patch(
            "/api/v1/saved-places/not-a-uuid",
            json={"label": "Valid"},
        )
        assert invalid_place_response.status_code == 422
        assert invalid_place_response.json()["error"] == "INVALID_SAVED_PLACE_ID"

        invalid_type_response = await client.put(
            f"/api/v1/profiles/{current_profile.id}/saved-places/FAVORITE",
            json=place_payload(),
        )
        assert invalid_type_response.status_code == 400
        assert invalid_type_response.json()["error"] == "INVALID_FIXED_PLACE_TYPE"

        invalid_body_response = await client.post(
            f"/api/v1/profiles/{current_profile.id}/favorites",
            json=place_payload(latitude=True),
        )
        assert invalid_body_response.status_code == 422
        assert invalid_body_response.json()["error"] == "INVALID_COORDINATES"
        assert "detail" not in invalid_body_response.json()
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()


async def test_saved_place_api_separates_places_by_profile_within_same_account(app, client) -> None:
    account = await create_test_account("profile-scoped-place")
    first_profile = await create_test_profile(account.id, "First")
    second_profile = await create_test_profile(account.id, "Second")
    override_current_account(app, account)

    try:
        first_favorite_response = await client.post(
            f"/api/v1/profiles/{first_profile.id}/favorites",
            json=place_payload("First Favorite", "first-favorite", 37.1, 127.1),
        )
        second_favorite_response = await client.post(
            f"/api/v1/profiles/{second_profile.id}/favorites",
            json=place_payload("Second Favorite", "second-favorite", 37.2, 127.2),
        )
        assert first_favorite_response.status_code == 201
        assert second_favorite_response.status_code == 201

        first_list_response = await client.get(
            f"/api/v1/profiles/{first_profile.id}/saved-places"
        )
        second_list_response = await client.get(
            f"/api/v1/profiles/{second_profile.id}/saved-places"
        )

        assert first_list_response.status_code == 200
        assert second_list_response.status_code == 200
        assert [place["label"] for place in first_list_response.json()["favorites"]] == [
            "First Favorite"
        ]
        assert [place["label"] for place in second_list_response.json()["favorites"]] == [
            "Second Favorite"
        ]
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_fixed_place_upsert_is_protected_by_profile_row_lock() -> None:
    account = await create_test_account("fixed-concurrent")
    profile = await create_test_profile(account.id, "Fixed Concurrent")

    try:
        async def upsert_home(label: str) -> tuple[str, str]:
            async with AsyncSessionLocal() as session:
                service = SavedPlaceService(session=session)
                response = await service.upsert_fixed_place(
                    account,
                    profile.id,
                    "HOME",
                    SavedPlaceWriteRequest(**place_payload(label, "concurrent-home")),
                )
                return "ok", response.id

        results = await asyncio.gather(upsert_home("Concurrent A"), upsert_home("Concurrent B"))

        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SavedPlace)
                .where(
                    SavedPlace.profile_id == profile.id,
                    SavedPlace.place_type == "HOME",
                )
            )

        assert [status for status, _ in results] == ["ok", "ok"]
        assert len({place_id for _, place_id in results}) == 1
        assert count == 1
    finally:
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_concurrent_duplicate_favorite_returns_single_success() -> None:
    account = await create_test_account("favorite-concurrent")
    profile = await create_test_profile(account.id, "Favorite Concurrent")

    try:
        async def create_favorite(label: str) -> str:
            async with AsyncSessionLocal() as session:
                service = SavedPlaceService(session=session)
                try:
                    response = await service.create_favorite(
                        account,
                        profile.id,
                        SavedPlaceWriteRequest(**place_payload(label, "concurrent-favorite")),
                    )
                    return response.id
                except AppException as exc:
                    return exc.error_code

        results = await asyncio.gather(
            create_favorite("Favorite A"),
            create_favorite("Favorite B"),
        )

        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SavedPlace)
                .where(
                    SavedPlace.profile_id == profile.id,
                    SavedPlace.place_type == "FAVORITE",
                )
            )

        assert results.count("DUPLICATE_FAVORITE") == 1
        assert count == 1
    finally:
        await delete_test_accounts(account.id)
        await dispose_engine()
