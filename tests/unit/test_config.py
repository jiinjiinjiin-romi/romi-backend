import pytest
from pydantic import ValidationError

from app.core.config import Settings, parse_cors_origins


def test_parse_cors_origins_from_comma_separated_string() -> None:
    assert parse_cors_origins("http://localhost:5173, https://example.com") == [
        "http://localhost:5173",
        "https://example.com",
    ]


def test_parse_cors_origins_from_json_array_string() -> None:
    assert parse_cors_origins('["http://localhost:5173", "https://example.com"]') == [
        "http://localhost:5173",
        "https://example.com",
    ]


def test_settings_exposes_parsed_cors_origins() -> None:
    settings = Settings(cors_origins="http://localhost:5173,https://example.com")

    assert settings.cors_origin_list == ["http://localhost:5173", "https://example.com"]


def test_parse_cors_origins_trims_empty_and_duplicate_values() -> None:
    assert parse_cors_origins(" http://localhost:5173, ,http://localhost:5173 ") == [
        "http://localhost:5173",
    ]


def test_settings_uses_database_url_override_when_configured() -> None:
    database_url = "mysql+asyncmy://custom:secret@mysql:3306/custom"
    settings = Settings(database_url_override=database_url)

    assert settings.database_url == database_url


def test_settings_validates_default_admin_account_id() -> None:
    settings = Settings(
        default_admin_account_id="00000000-0000-0000-0000-000000000001",
    )

    assert settings.default_admin_account_id == "00000000-0000-0000-0000-000000000001"


def test_settings_rejects_invalid_default_admin_account_id() -> None:
    with pytest.raises(ValidationError):
        Settings(default_admin_account_id="not-a-uuid")


def test_settings_normalizes_empty_default_admin_email_to_none() -> None:
    settings = Settings(default_admin_email=" ")

    assert settings.default_admin_email is None


def test_settings_exposes_default_websocket_runtime_settings() -> None:
    settings = Settings()

    assert settings.ws_recommended_frame_fps == 5
    assert settings.ws_location_interval_ms == 1000
    assert settings.ws_location_persist_interval_ms == 5000
    assert settings.ws_heartbeat_interval_ms == 10000
    assert settings.ws_heartbeat_timeout_ms == 30000
    assert settings.driving_moving_speed_threshold_kph == 5.0
    assert settings.driving_location_max_accuracy_meters == 100.0


def test_settings_rejects_non_positive_websocket_runtime_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(ws_recommended_frame_fps=0)

    with pytest.raises(ValidationError):
        Settings(ws_location_interval_ms=0)

    with pytest.raises(ValidationError):
        Settings(ws_location_persist_interval_ms=0)


def test_settings_rejects_invalid_driving_context_thresholds() -> None:
    with pytest.raises(ValidationError):
        Settings(driving_moving_speed_threshold_kph=-0.1)

    with pytest.raises(ValidationError):
        Settings(driving_location_max_accuracy_meters=0)


def test_settings_rejects_heartbeat_timeout_not_greater_than_interval() -> None:
    with pytest.raises(ValidationError):
        Settings(ws_heartbeat_interval_ms=10000, ws_heartbeat_timeout_ms=10000)
