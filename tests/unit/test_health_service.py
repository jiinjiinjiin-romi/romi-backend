from collections.abc import Awaitable, Callable

import pytest

from app.core.config import Settings
from app.services.health_service import DatabaseUnavailableError, HealthService


async def db_ok() -> None:
    return None


async def db_down() -> None:
    raise RuntimeError("database unavailable")


def make_settings(**overrides: object) -> Settings:
    values = {
        "mysql_password": "test-password",
        "model_path": "missing-model-file.pth",
        "gemini_api_key": "",
        "gemini_model": "",
        "email_provider": "",
        "email_host": "",
        "email_port": "",
        "email_username": "",
        "email_password": "",
        "email_from": "",
    }
    values.update(overrides)
    return Settings(**values)


def make_service(
    settings: Settings,
    db_checker: Callable[[], Awaitable[None]] = db_ok,
) -> HealthService:
    return HealthService(settings=settings, db_checker=db_checker)


async def test_health_is_up_when_all_services_are_up(tmp_path) -> None:
    model_file = tmp_path / "best_vit.pth"
    model_file.write_bytes(b"model-placeholder")
    settings = make_settings(
        model_path=str(model_file),
        gemini_api_key="key",
        gemini_model="gemini-test",
        email_provider="smtp",
        email_host="smtp.example.com",
        email_port="587",
        email_username="user",
        email_password="password",
        email_from="noreply@example.com",
    )

    response = await make_service(settings).get_health()

    assert response.status == "UP"
    assert response.services.database == "UP"
    assert response.services.vit_model == "UP"
    assert response.services.gemini == "UP"
    assert response.services.email == "UP"


async def test_health_is_degraded_when_optional_services_are_down() -> None:
    response = await make_service(make_settings()).get_health()

    assert response.status == "DEGRADED"
    assert response.services.database == "UP"
    assert response.services.vit_model == "DOWN"
    assert response.services.gemini == "DOWN"
    assert response.services.email == "DOWN"


async def test_health_response_serializes_as_camel_case() -> None:
    response = await make_service(make_settings()).get_health()

    payload = response.model_dump(mode="json", by_alias=True)

    assert "modelVersion" in payload
    assert "policyVersion" in payload
    assert "checkedAt" in payload
    assert "vitModel" in payload["services"]


def test_model_file_availability_uses_file_existence(tmp_path) -> None:
    missing_settings = make_settings(model_path=str(tmp_path / "missing.pth"))
    existing_model = tmp_path / "best_vit.pth"
    existing_model.write_bytes(b"model-placeholder")
    existing_settings = make_settings(model_path=str(existing_model))

    assert make_service(missing_settings).is_vit_model_available() is False
    assert make_service(existing_settings).is_vit_model_available() is True


def test_gemini_requires_api_key_and_model() -> None:
    assert make_service(
        make_settings(gemini_api_key="key", gemini_model="model")
    ).is_gemini_configured()
    assert not make_service(
        make_settings(gemini_api_key="key", gemini_model="")
    ).is_gemini_configured()
    assert not make_service(
        make_settings(gemini_api_key="", gemini_model="model")
    ).is_gemini_configured()


def test_email_requires_provider_and_required_settings() -> None:
    configured = make_settings(
        email_provider="smtp",
        email_host="smtp.example.com",
        email_port="587",
        email_username="user",
        email_password="password",
        email_from="noreply@example.com",
    )
    missing_password = make_settings(
        email_provider="smtp",
        email_host="smtp.example.com",
        email_port="587",
        email_username="user",
        email_password="",
        email_from="noreply@example.com",
    )

    assert make_service(configured).is_email_configured()
    assert not make_service(missing_password).is_email_configured()


async def test_database_failure_is_converted_to_domain_exception() -> None:
    service = make_service(make_settings(), db_checker=db_down)

    with pytest.raises(DatabaseUnavailableError):
        await service.get_health()
