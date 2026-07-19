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
    assert settings.ws_frame_binary_timeout_ms == 1000
    assert settings.ws_max_frame_bytes == 307200
    assert settings.ws_frame_queue_max_size == 2
    assert settings.ws_frame_recent_id_cache_size == 256
    assert settings.ws_frame_max_width == 1920
    assert settings.ws_frame_max_height == 1080
    assert settings.driver_monitoring_adapter == "REAL"
    assert settings.mock_vit_inference_latency_ms == 0
    assert settings.driving_moving_speed_threshold_kph == 5.0
    assert settings.driving_location_max_accuracy_meters == 100.0


def test_settings_defaults_to_rgb2_model_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PATH", raising=False)

    settings = Settings(_env_file=None)

    assert settings.model_path == "/app/artifacts/models/best_ViT_kaggle_rgb2_4cls.pth"


def test_settings_exposes_default_tmap_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMAP_APP_KEY", raising=False)
    monkeypatch.delenv("TMAP_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TMAP_PROXY_CACHE_TTL_MS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.tmap_app_key == ""
    assert settings.tmap_request_timeout_seconds == 10.0
    assert settings.tmap_proxy_cache_ttl_ms == 30_000


def test_settings_exposes_default_clova_voice_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOVA_VOICE_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLOVA_VOICE_CLIENT_SECRET", raising=False)

    settings = Settings(_env_file=None)

    assert settings.clova_voice_client_id == ""
    assert settings.clova_voice_client_secret == ""
    assert settings.clova_voice_tts_url == "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"
    assert settings.clova_voice_request_timeout_seconds == 10.0
    assert settings.clova_voice_assistant_speaker == "nara"
    assert settings.clova_voice_user_male_speaker == "nminsang"
    assert settings.clova_voice_user_female_speaker == "nminseo"


def test_settings_exposes_and_validates_gemini_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_REQUEST_TIMEOUT_SECONDS", raising=False)

    assert Settings(_env_file=None).gemini_request_timeout_seconds == 180.0

    with pytest.raises(ValidationError):
        Settings(gemini_request_timeout_seconds=0, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(gemini_request_timeout_seconds=float("inf"), _env_file=None)


def test_settings_rejects_non_positive_websocket_runtime_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(ws_recommended_frame_fps=0)

    with pytest.raises(ValidationError):
        Settings(ws_location_interval_ms=0)

    with pytest.raises(ValidationError):
        Settings(ws_location_persist_interval_ms=0)

    with pytest.raises(ValidationError):
        Settings(ws_frame_binary_timeout_ms=0)


def test_settings_rejects_invalid_tmap_proxy_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(tmap_request_timeout_seconds=0, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(tmap_proxy_cache_ttl_ms=-1, _env_file=None)


def test_settings_rejects_invalid_clova_voice_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(clova_voice_request_timeout_seconds=0, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(clova_voice_assistant_speaker="", _env_file=None)


def test_settings_normalizes_and_validates_driver_monitoring_adapter() -> None:
    assert Settings(driver_monitoring_adapter="mock").driver_monitoring_adapter == "MOCK"
    assert Settings(driver_monitoring_adapter="REAL").driver_monitoring_adapter == "REAL"

    with pytest.raises(ValidationError):
        Settings(driver_monitoring_adapter="unsupported")


def test_settings_rejects_invalid_mock_vit_latency() -> None:
    with pytest.raises(ValidationError):
        Settings(mock_vit_inference_latency_ms=-1)

    with pytest.raises(ValidationError):
        Settings(mock_vit_inference_latency_ms=10001)


def test_settings_rejects_invalid_websocket_frame_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(ws_max_frame_bytes=0)

    with pytest.raises(ValidationError):
        Settings(ws_frame_queue_max_size=3)

    with pytest.raises(ValidationError):
        Settings(ws_frame_recent_id_cache_size=0)

    with pytest.raises(ValidationError):
        Settings(ws_frame_max_width=0)

    with pytest.raises(ValidationError):
        Settings(ws_frame_max_height=0)


def test_settings_rejects_invalid_driving_context_thresholds() -> None:
    with pytest.raises(ValidationError):
        Settings(driving_moving_speed_threshold_kph=-0.1)

    with pytest.raises(ValidationError):
        Settings(driving_location_max_accuracy_meters=0)


def test_settings_rejects_heartbeat_timeout_not_greater_than_interval() -> None:
    with pytest.raises(ValidationError):
        Settings(ws_heartbeat_interval_ms=10000, ws_heartbeat_timeout_ms=10000)
