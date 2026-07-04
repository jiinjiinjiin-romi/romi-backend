import pytest

from app.core.config import Settings
from app.db.seed import (
    DEFAULT_FAMILY_PROFILES,
    DEFAULT_NAVIGATION_LABELS,
    SeedError,
    run_seed,
    seed_default_admin_account,
    seed_default_family_profiles,
    seed_default_navigation_labels,
)
from app.models import Account, DriverProfile, SavedPlace


class FakeScalarResult:
    def __init__(self, account: Account | None) -> None:
        self.account = account

    def scalar_one_or_none(self) -> Account | None:
        return self.account


class FakeSession:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.profiles: list[DriverProfile] = []
        self.saved_places: list[SavedPlace] = []
        self.conflicting_account: Account | None = None
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, model: type[Account], key: str) -> Account | None:
        assert model is Account
        return self.accounts.get(key)

    async def execute(self, statement: object) -> FakeScalarResult:
        assert statement is not None
        return FakeScalarResult(self.conflicting_account)

    async def scalar(self, statement: object) -> int:
        assert statement is not None
        return len(self.profiles)

    def add(self, model: Account | DriverProfile | SavedPlace) -> None:
        if isinstance(model, Account):
            self.accounts[model.id] = model
            return
        if isinstance(model, DriverProfile):
            if model.id is None:
                model.id = f"profile-{len(self.profiles) + 1}"
            self.profiles.append(model)
            return
        if isinstance(model, SavedPlace):
            self.saved_places.append(model)
            return
        raise AssertionError(f"Unexpected model: {model!r}")

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        return None


def make_settings(**overrides: object) -> Settings:
    values = {
        "mysql_password": "test-password",
        "default_admin_account_id": "00000000-0000-0000-0000-000000000001",
        "default_admin_email": "admin@example.com",
    }
    values.update(overrides)
    return Settings(**values)


async def test_seed_creates_default_admin_account() -> None:
    session = FakeSession()

    result = await seed_default_admin_account(session, make_settings())

    assert result == "created"
    account = session.accounts["00000000-0000-0000-0000-000000000001"]
    assert account.display_name == "안정현"
    assert account.email == "admin@example.com"


async def test_seed_is_idempotent_for_existing_matching_account() -> None:
    session = FakeSession()
    session.accounts["00000000-0000-0000-0000-000000000001"] = Account(
        id="00000000-0000-0000-0000-000000000001",
        display_name="안정현",
        email="admin@example.com",
    )

    result = await seed_default_admin_account(session, make_settings())

    assert result == "unchanged"
    assert len(session.accounts) == 1


async def test_seed_updates_email_for_existing_admin_id() -> None:
    session = FakeSession()
    session.accounts["00000000-0000-0000-0000-000000000001"] = Account(
        id="00000000-0000-0000-0000-000000000001",
        display_name="안정현",
        email="old@example.com",
    )

    result = await seed_default_admin_account(
        session,
        make_settings(default_admin_email="new@example.com"),
    )

    assert result == "updated"
    assert session.accounts["00000000-0000-0000-0000-000000000001"].display_name == "안정현"
    assert session.accounts["00000000-0000-0000-0000-000000000001"].email == "new@example.com"


async def test_seed_fails_when_email_belongs_to_another_account() -> None:
    session = FakeSession()
    session.conflicting_account = Account(
        id="00000000-0000-0000-0000-000000000099",
        display_name="안정현",
        email="admin@example.com",
    )

    with pytest.raises(SeedError):
        await seed_default_admin_account(session, make_settings())

    assert "00000000-0000-0000-0000-000000000001" not in session.accounts


async def test_seed_creates_default_family_profiles_for_empty_account() -> None:
    session = FakeSession()

    result = await seed_default_family_profiles(
        session,
        "00000000-0000-0000-0000-000000000001",
    )

    assert result == 3
    assert [profile.display_name for profile in session.profiles] == ["아빠", "엄마", "지우"]
    assert [profile.agent_call_name for profile in session.profiles] == ["나비", "나비", "나비"]
    assert [profile.profile_image_url for profile in session.profiles] == [
        profile["profile_image_url"] for profile in DEFAULT_FAMILY_PROFILES
    ]
    assert {profile.theme for profile in session.profiles} == {"LIGHT"}


async def test_seed_creates_default_navigation_labels_for_profiles() -> None:
    session = FakeSession()
    profile = DriverProfile(
        id="profile-1",
        account_id="00000000-0000-0000-0000-000000000001",
        display_name="아빠",
        agent_call_name="나비",
    )

    result = await seed_default_navigation_labels(session, [profile])

    assert result == len(DEFAULT_NAVIGATION_LABELS)
    assert [place.label for place in session.saved_places] == ["집", "회사"]
    assert [place.provider_place_id for place in session.saved_places] == [
        "origin:default-home",
        "destination:default-work",
    ]


async def test_seed_skips_default_navigation_labels_when_profile_has_places() -> None:
    session = FakeSession()
    profile = DriverProfile(
        id="profile-1",
        account_id="00000000-0000-0000-0000-000000000001",
        display_name="아빠",
        agent_call_name="나비",
    )
    session.saved_places.append(
        SavedPlace(
            profile_id="profile-1",
            place_type="FAVORITE",
            label="기존 장소",
            provider="TMAP",
            provider_place_id="origin:existing",
            address="서울",
            latitude=37.0,
            longitude=127.0,
        )
    )

    result = await seed_default_navigation_labels(session, [profile])

    assert result == 0
    assert len(session.saved_places) == 1


async def test_seed_skips_default_family_profiles_when_account_already_has_profiles() -> None:
    session = FakeSession()
    session.profiles.append(
        DriverProfile(
            account_id="00000000-0000-0000-0000-000000000001",
            display_name="기존 운전자",
            agent_call_name="나비",
        )
    )

    result = await seed_default_family_profiles(
        session,
        "00000000-0000-0000-0000-000000000001",
    )

    assert result == 0
    assert len(session.profiles) == 1
    assert session.profiles[0].display_name == "기존 운전자"


async def test_run_seed_commits_on_success() -> None:
    session = FakeSession()

    result = await run_seed(make_settings(), session_factory=lambda: session)

    assert result == "created"
    assert len(session.profiles) == 3
    assert len(session.saved_places) == len(DEFAULT_NAVIGATION_LABELS) * 3
    assert session.committed is True
    assert session.rolled_back is False


async def test_run_seed_rolls_back_on_failure() -> None:
    session = FakeSession()
    session.conflicting_account = Account(
        id="00000000-0000-0000-0000-000000000099",
        display_name="안정현",
        email="admin@example.com",
    )

    with pytest.raises(SeedError):
        await run_seed(make_settings(), session_factory=lambda: session)

    assert session.committed is False
    assert session.rolled_back is True
