import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.api.dependencies import get_current_account
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.db.session import AsyncSessionLocal, dispose_engine
from app.models import Account, DriverProfile, DrivingSession
from app.schemas.profile import DEFAULT_BEHAVIOR_WARNING_SENSITIVITY, ProfileCreateRequest
from app.services.profile_service import ProfileService

pytestmark = pytest.mark.skipif(
    not (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_PASSWORD")),
    reason="MySQL integration tests require Docker Compose database environment.",
)


def profile_payload(name: str = "Demo Driver") -> dict[str, object]:
    return {
        "displayName": name,
        "agentCallName": "Roady",
        "reportEmail": "demo-driver@example.com",
        "agentPersonality": "FRIENDLY",
        "behaviorWarningSensitivity": DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
        "ttsVoiceId": None,
        "ttsSpeed": 1.0,
        "guidanceVolume": 70,
    }


async def create_test_account() -> Account:
    account = Account(
        id=str(uuid4()),
        display_name="Demo Tester",
        email=f"profile-api-{uuid4().hex}@example.com",
    )
    async with AsyncSessionLocal() as session:
        session.add(account)
        await session.commit()
    return account


async def delete_test_accounts(*account_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await session.commit()


def override_current_account(app, account: Account) -> None:
    async def current_account_override() -> Account:
        return account

    app.dependency_overrides[get_current_account] = current_account_override


async def test_bootstrap_uses_seeded_current_account(client) -> None:
    response = await client.get("/api/v1/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "account",
        "profiles",
        "selectedProfileId",
        "profileLimit",
        "capabilities",
    }
    assert payload["account"]["displayName"] == "안정현"
    assert payload["account"]["email"] == "admin@example.com"
    assert payload["profileLimit"] == 5
    assert set(payload["capabilities"]) == {
        "vitModelAvailable",
        "geminiAvailable",
        "emailAvailable",
        "demoMode",
    }


async def test_profile_api_crud_select_and_validation(app, client) -> None:
    account = await create_test_account()
    override_current_account(app, account)

    try:
        bootstrap_response = await client.get("/api/v1/bootstrap")
        assert bootstrap_response.status_code == 200
        assert bootstrap_response.json()["profiles"] == []
        assert bootstrap_response.json()["selectedProfileId"] is None

        create_response = await client.post("/api/v1/profiles", json=profile_payload())
        assert create_response.status_code == 201
        created = create_response.json()
        profile_id = created["id"]
        assert "accountId" not in created
        assert created["displayName"] == "Demo Driver"
        assert created["behaviorWarningSensitivity"]["DROWSINESS"] == 9
        assert created["ttsSpeed"] == 1.0

        list_response = await client.get("/api/v1/profiles")
        assert list_response.status_code == 200
        assert list_response.json()["count"] == 1
        assert list_response.json()["profiles"][0]["id"] == profile_id

        detail_response = await client.get(f"/api/v1/profiles/{profile_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == profile_id

        empty_patch_response = await client.patch(f"/api/v1/profiles/{profile_id}", json={})
        assert empty_patch_response.status_code == 400
        assert empty_patch_response.json()["error"] == "EMPTY_UPDATE_REQUEST"

        invalid_uuid_response = await client.get("/api/v1/profiles/not-a-uuid")
        assert invalid_uuid_response.status_code == 422
        assert invalid_uuid_response.json()["error"] == "INVALID_PROFILE_ID"
        assert "detail" not in invalid_uuid_response.json()

        update_response = await client.patch(
            f"/api/v1/profiles/{profile_id}",
            json={
                "agentCallName": "Roady Updated",
                "reportEmail": None,
                "behaviorWarningSensitivity": {
                    **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
                    "FOOD_OR_DRINK": 4,
                },
                "ttsVoiceId": "nes_c_hyeri",
                "ttsSpeed": 0.9,
                "guidanceVolume": 80,
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["agentCallName"] == "Roady Updated"
        assert updated["reportEmail"] is None
        assert updated["behaviorWarningSensitivity"]["FOOD_OR_DRINK"] == 4
        assert updated["ttsVoiceId"] == "nes_c_hyeri"

        select_response = await client.post(f"/api/v1/profiles/{profile_id}/select")
        assert select_response.status_code == 200
        assert select_response.json()["selectedProfileId"] == profile_id
        assert select_response.json()["selectedAt"].endswith("Z")

        selected_bootstrap_response = await client.get("/api/v1/bootstrap")
        assert selected_bootstrap_response.status_code == 200
        assert selected_bootstrap_response.json()["selectedProfileId"] == profile_id
        assert selected_bootstrap_response.json()["profiles"][0]["ttsVoiceId"] == "nes_c_hyeri"

        for index in range(2, 6):
            response = await client.post(
                "/api/v1/profiles",
                json=profile_payload(f"Demo Driver {index}"),
            )
            assert response.status_code == 201

        limit_response = await client.post("/api/v1/profiles", json=profile_payload("Too Many"))
        assert limit_response.status_code == 409
        assert limit_response.json()["error"] == "PROFILE_LIMIT_EXCEEDED"

        delete_response = await client.delete(f"/api/v1/profiles/{profile_id}")
        assert delete_response.status_code == 204
        assert delete_response.content == b""

        deleted_get_response = await client.get(f"/api/v1/profiles/{profile_id}")
        assert deleted_get_response.status_code == 404
        assert deleted_get_response.json()["error"] == "PROFILE_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_profile_api_blocks_other_account_profile_access(app, client) -> None:
    current_account = await create_test_account()
    other_account = await create_test_account()
    override_current_account(app, current_account)

    try:
        async with AsyncSessionLocal() as session:
            profile = DriverProfile(
                account_id=other_account.id,
                display_name="Other",
                agent_call_name="Other",
            )
            session.add(profile)
            await session.commit()
            profile_id = profile.id

        response = await client.get(f"/api/v1/profiles/{profile_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "PROFILE_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(current_account.id, other_account.id)
        await dispose_engine()


async def test_profile_delete_rejects_active_driving_session(app, client) -> None:
    account = await create_test_account()
    override_current_account(app, account)

    try:
        async with AsyncSessionLocal() as session:
            profile = DriverProfile(
                account_id=account.id,
                display_name="Active Session",
                agent_call_name="Active",
            )
            session.add(profile)
            await session.flush()
            session.add(
                DrivingSession(
                    profile_id=profile.id,
                    model_version="test-model",
                    policy_version="test-policy",
                )
            )
            await session.commit()
            profile_id = profile.id

        response = await client.delete(f"/api/v1/profiles/{profile_id}")

        assert response.status_code == 409
        assert response.json()["error"] == "ACTIVE_SESSION_EXISTS"
    finally:
        app.dependency_overrides.clear()
        await delete_test_accounts(account.id)
        await dispose_engine()


async def test_profile_limit_is_protected_by_account_row_lock() -> None:
    account = await create_test_account()

    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    DriverProfile(
                        account_id=account.id,
                        display_name=f"Existing {index}",
                        agent_call_name=f"Existing {index}",
                    )
                    for index in range(4)
                ]
            )
            await session.commit()

        async def create_one(name: str) -> str:
            async with AsyncSessionLocal() as session:
                service = ProfileService(session=session, settings=get_settings())
                try:
                    response = await service.create_profile(
                        account,
                        ProfileCreateRequest(**profile_payload(name)),
                    )
                    return response.id
                except AppException as exc:
                    return exc.error_code

        results = await asyncio.gather(
            create_one("Concurrent A"),
            create_one("Concurrent B"),
        )

        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(DriverProfile)
                .where(DriverProfile.account_id == account.id)
            )

        assert results.count("PROFILE_LIMIT_EXCEEDED") == 1
        assert count == 5
    finally:
        await delete_test_accounts(account.id)
        await dispose_engine()
