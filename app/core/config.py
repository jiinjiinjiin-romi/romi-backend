import json
import math
from collections.abc import Iterable
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote_plus
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_origins(values: Iterable[object]) -> list[str]:
    origins: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not isinstance(value, str):
            raise ValueError("CORS origins must be strings.")

        origin = value.strip()
        if not origin or origin in seen:
            continue

        origins.append(origin)
        seen.add(origin)

    return origins


def parse_cors_origins(raw_value: str | Iterable[str] | None) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        value = raw_value.strip()
        if not value:
            return []

        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS JSON value must be an array.")
            return _normalize_origins(parsed)

        return _normalize_origins(value.split(","))

    return _normalize_origins(raw_value)


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "roadie-api"
    api_v1_prefix: str = "/api/v1"
    ws_v1_prefix: str = "/ws/v1"
    log_level: str = "INFO"
    sql_echo: bool = False
    demo_mode: bool = True
    cors_origins: str = "http://localhost:5173"
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "roadie"
    mysql_user: str = "driving_user"
    mysql_password: str = Field(default="", repr=False)
    mysql_root_password: str = Field(default="", repr=False)
    mysql_exposed_port: int = 3306
    database_url_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "database_url_override"),
        repr=False,
    )
    db_pool_recycle_seconds: int = 1800
    default_admin_account_id: str = "00000000-0000-0000-0000-000000000001"
    default_admin_display_name: str = "안정현"
    default_admin_email: str | None = "admin@example.com"
    backend_exposed_port: int = 8000
    tmap_app_key: str = Field(default="", repr=False)
    tmap_request_timeout_seconds: float = 10.0
    tmap_proxy_cache_ttl_ms: int = 30_000
    clova_voice_client_id: str = Field(default="", repr=False)
    clova_voice_client_secret: str = Field(default="", repr=False)
    clova_voice_tts_url: str = "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"
    clova_voice_request_timeout_seconds: float = 10.0
    clova_voice_assistant_speaker: str = "nara"
    clova_voice_user_male_speaker: str = "nminsang"
    clova_voice_user_female_speaker: str = "nminseo"
    model_path: str = "/app/artifacts/models/best_ViT_kaggle_rgb2_4cls.pth"
    model_device: Literal["cpu", "cuda", "mps"] = "cpu"
    model_input_size: int = 224
    model_version: str = "vit-dms-1.0.0"
    driver_monitoring_adapter: Literal["MOCK", "REAL"] = "MOCK"
    mock_vit_inference_latency_ms: int = 0
    torch_num_threads: int = 4
    policy_version: str = "risk-policy-1.0.0"
    ws_recommended_frame_fps: int = 5
    ws_location_interval_ms: int = 1000
    ws_location_persist_interval_ms: int = 5000
    ws_heartbeat_interval_ms: int = 10000
    ws_heartbeat_timeout_ms: int = 30000
    ws_frame_binary_timeout_ms: int = 1000
    ws_max_frame_bytes: int = 300 * 1024
    ws_frame_queue_max_size: int = 2
    ws_frame_recent_id_cache_size: int = 256
    ws_frame_max_width: int = 1920
    ws_frame_max_height: int = 1080
    driving_moving_speed_threshold_kph: float = 5.0
    driving_location_max_accuracy_meters: float = 100.0
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = ""
    gemini_behavior_sensitivity_prompt: str = Field(default="", repr=False)
    gemini_request_timeout_seconds: float = 180.0
    email_provider: str = ""
    email_host: str = ""
    email_port: str = ""
    email_username: str = Field(default="", repr=False)
    email_password: str = Field(default="", repr=False)
    email_from: str = ""
    report_storage_path: str = "/app/storage/reports"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return parse_cors_origins(self.cors_origins)

    @field_validator("default_admin_account_id", mode="before")
    @classmethod
    def validate_default_admin_account_id(cls, value: object) -> str:
        return str(UUID(str(value)))

    @field_validator("default_admin_display_name", mode="before")
    @classmethod
    def normalize_default_admin_display_name(cls, value: object) -> str:
        display_name = str(value).strip()
        if not display_name or len(display_name) > 50:
            raise ValueError("Default admin display name must be between 1 and 50 characters.")
        return display_name

    @field_validator("default_admin_email", mode="before")
    @classmethod
    def normalize_default_admin_email(cls, value: object) -> str | None:
        if value is None:
            return None
        email = str(value).strip()
        return email or None

    @field_validator("driver_monitoring_adapter", mode="before")
    @classmethod
    def normalize_driver_monitoring_adapter(cls, value: object) -> str:
        return str(value).strip().upper()

    @field_validator(
        "ws_recommended_frame_fps",
        "ws_location_interval_ms",
        "ws_location_persist_interval_ms",
        "ws_heartbeat_interval_ms",
        "ws_heartbeat_timeout_ms",
        "ws_frame_binary_timeout_ms",
    )
    @classmethod
    def validate_positive_websocket_setting(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("WebSocket timing settings must be positive.")
        return value

    @field_validator(
        "ws_max_frame_bytes",
        "ws_frame_recent_id_cache_size",
        "ws_frame_max_width",
        "ws_frame_max_height",
        "model_input_size",
        "torch_num_threads",
    )
    @classmethod
    def validate_positive_frame_setting(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("WebSocket frame settings must be positive.")
        return value

    @field_validator("mock_vit_inference_latency_ms")
    @classmethod
    def validate_mock_vit_inference_latency_ms(cls, value: int) -> int:
        if value < 0 or value > 10000:
            raise ValueError("MOCK_VIT_INFERENCE_LATENCY_MS must be between 0 and 10000.")
        return value

    @field_validator("ws_frame_queue_max_size")
    @classmethod
    def validate_frame_queue_max_size(cls, value: int) -> int:
        if value not in {1, 2}:
            raise ValueError("WS_FRAME_QUEUE_MAX_SIZE must be 1 or 2.")
        return value

    @field_validator("tmap_request_timeout_seconds")
    @classmethod
    def validate_positive_tmap_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("TMAP request timeout must be positive.")
        return value

    @field_validator("tmap_proxy_cache_ttl_ms")
    @classmethod
    def validate_non_negative_tmap_cache_ttl(cls, value: int) -> int:
        if value < 0:
            raise ValueError("TMAP proxy cache TTL must be non-negative.")
        return value

    @field_validator("clova_voice_request_timeout_seconds")
    @classmethod
    def validate_positive_clova_voice_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("CLOVA Voice request timeout must be positive.")
        return value

    @field_validator("gemini_request_timeout_seconds")
    @classmethod
    def validate_positive_finite_gemini_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Gemini request timeout must be a positive finite number.")
        return value

    @field_validator(
        "clova_voice_assistant_speaker",
        "clova_voice_user_male_speaker",
        "clova_voice_user_female_speaker",
    )
    @classmethod
    def normalize_clova_voice_speaker(cls, value: object) -> str:
        speaker = str(value).strip()
        if not speaker:
            raise ValueError("CLOVA Voice speaker must not be empty.")
        return speaker

    @field_validator("driving_moving_speed_threshold_kph")
    @classmethod
    def validate_non_negative_driving_speed_threshold(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Driving speed threshold must be non-negative.")
        return value

    @field_validator("driving_location_max_accuracy_meters")
    @classmethod
    def validate_positive_location_accuracy_threshold(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Driving location max accuracy must be positive.")
        return value

    @model_validator(mode="after")
    def validate_websocket_heartbeat_timeout(self) -> Self:
        if self.ws_heartbeat_timeout_ms <= self.ws_heartbeat_interval_ms:
            raise ValueError("WS_HEARTBEAT_TIMEOUT_MS must be greater than interval.")
        return self

    @property
    def database_url(self) -> str:
        if self.database_url_override and self.database_url_override.strip():
            return self.database_url_override.strip()

        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        database = quote_plus(self.mysql_database)
        return (
            f"mysql+asyncmy://{user}:{password}@"
            f"{self.mysql_host}:{self.mysql_port}/{database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
