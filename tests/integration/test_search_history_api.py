import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.api.dependencies import get_current_account
from app.core.time import utc_now_for_mysql_datetime
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, DriverProfile, SearchHistory

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


async def create_test_account(email_prefix: str = "search-history-api") -> Account:
    account = Account(id=str(uuid4()), email=f"{email_prefix}-{uuid4().hex}@example.com")
    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.commit()
    return account


async def create_test_profile(account_id: str, display_name: str = "Search API") -> DriverProfile:
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


async def create_search_histories(profile_id: str, count: int) -> None:
    base_time = utc_now_for_mysql_datetime()
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                SearchHistory(
                    profile_id=profile_id,
                    query=f"query-{index:02d}",
                    provider="KAKAO",
                    provider_place_id=f"place-{index:02d}",
                    place_name=f"Place {index:02d}",
                    address=f"Address {index:02d}",
                    latitude=37.0 + (index / 1000),
                    longitude=127.0 + (index / 1000),
                    searched_at=base_time + timedelta(seconds=index),
                )
                for index in range(count)
            ]
        )
        await session.commit()


async def test_search_history_api_pagination_and_delete(app, client) -> None:
    account = await create_test_account()
    profile = await create_test_profile(account.id)
    other_profile = await create_test_profile(account.id, "Other Profile")
    override_current_account(app, account)

    try:
        await create_search_histories(profile.id, 25)
        await create_search_histories(other_profile.id, 3)

        first_page_response = await client.get(
            f"/api/v1/profiles/{profile.id}/search-histories?page=1&size=20"
        )
        assert first_page_response.status_code == 200
        first_page = first_page_response.json()
        assert first_page["page"] == 1
        assert first_page["size"] == 20
        assert first_page["total"] == 25
        assert first_page["totalPages"] == 2
        assert len(first_page["items"]) == 20
        assert first_page["items"][0]["query"] == "query-24"
        assert first_page["items"][-1]["query"] == "query-05"

        second_page_response = await client.get(
            f"/api/v1/profiles/{profile.id}/search-histories?page=2&size=20"
        )
        assert second_page_response.status_code == 200
        second_page = second_page_response.json()
        assert len(second_page["items"]) == 5
        assert second_page["items"][0]["query"] == "query-04"
        assert second_page["items"][-1]["query"] == "query-00"

        invalid_page_response = await client.get(
            f"/api/v1/profiles/{profile.id}/search-histories?page=0&size=20"
        )
        assert invalid_page_response.status_code == 422
        assert invalid_page_response.json()["error"] == "INVALID_PAGE"
        assert "detail" not in invalid_page_response.json()

        invalid_size_response = await client.get(
            f"/api/v1/profiles/{profile.id}/search-histories?page=1&size=101"
        )
        assert invalid_size_response.status_code == 422
        assert invalid_size_response.json()["error"] == "INVALID_PAGE_SIZE"
        assert "detail" not in invalid_size_response.json()

        delete_response = await client.delete(f"/api/v1/profiles/{profile.id}/search-histories")
        assert delete_response.status_code == 200
        assert delete_response.json()["deletedCount"] == 25
        assert delete_response.json()["deletedAt"].endswith("Z")

        empty_list_response = await client.get(f"/api/v1/profiles/{profile.id}/search-histories")
        assert empty_list_response.status_code == 200
        assert empty_list_response.json()["total"] == 0
        assert empty_list_response.json()["totalPages"] == 0
        assert empty_list_response.json()["items"] == []

        empty_delete_response = await client.delete(
            f"/api/v1/profiles/{profile.id}/search-histories"
        )
        assert empty_delete_response.status_code == 200
        assert empty_delete_response.json()["deletedCount"] == 0

        other_profile_response = await client.get(
            f"/api/v1/profiles/{other_profile.id}/search-histories"
        )
        assert other_profile_response.status_code == 200
        assert other_profile_response.json()["total"] == 3
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_search_history_api_creates_history_from_selected_place(app, client) -> None:
    account = await create_test_account("create-search-history")
    profile = await create_test_profile(account.id)
    override_current_account(app, account)

    try:
        create_response = await client.post(
            f"/api/v1/profiles/{profile.id}/search-histories",
            json={
                "query": "서울역",
                "provider": "TMAP",
                "providerPlaceId": "poi-1",
                "placeName": "서울역",
                "address": "서울 중구 봉래동2가",
                "latitude": 37.5547,
                "longitude": 126.9706,
            },
        )

        assert create_response.status_code == 201
        created = create_response.json()
        assert created["query"] == "서울역"
        assert created["provider"] == "TMAP"
        assert created["providerPlaceId"] == "poi-1"
        assert created["placeName"] == "서울역"
        assert created["address"] == "서울 중구 봉래동2가"
        assert created["latitude"] == 37.5547
        assert created["longitude"] == 126.9706
        assert created["searchedAt"].endswith("Z")

        list_response = await client.get(f"/api/v1/profiles/{profile.id}/search-histories")
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["query"] == "서울역"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_search_history_api_blocks_other_account_and_invalid_uuid(app, client) -> None:
    current_account = await create_test_account("current-search")
    other_account = await create_test_account("other-search")
    other_profile = await create_test_profile(other_account.id, "Other Search")
    override_current_account(app, current_account)

    try:
        other_profile_response = await client.get(
            f"/api/v1/profiles/{other_profile.id}/search-histories"
        )
        assert other_profile_response.status_code == 404
        assert other_profile_response.json()["error"] == "PROFILE_NOT_FOUND"

        invalid_uuid_response = await client.get(
            "/api/v1/profiles/not-a-uuid/search-histories"
        )
        assert invalid_uuid_response.status_code == 422
        assert invalid_uuid_response.json()["error"] == "INVALID_PROFILE_ID"
        assert "detail" not in invalid_uuid_response.json()
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()
