import json
from collections.abc import Iterable
from functools import lru_cache
from typing import Self
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
    app_name: str = "driving-agent-api"
    api_v1_prefix: str = "/api/v1"
    ws_v1_prefix: str = "/ws/v1"
    log_level: str = "INFO"
    sql_echo: bool = False
    demo_mode: bool = True
    cors_origins: str = "http://localhost:5173"
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "driving_agent"
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
    default_admin_email: str | None = "admin@example.com"
    backend_exposed_port: int = 8000
    model_path: str = "/app/artifacts/models/best_vit.pth"
    model_version: str = "vit-dms-1.0.0"
    policy_version: str = "risk-policy-1.0.0"
    ws_recommended_frame_fps: int = 5
    ws_location_interval_ms: int = 1000
    ws_location_persist_interval_ms: int = 5000
    ws_heartbeat_interval_ms: int = 10000
    ws_heartbeat_timeout_ms: int = 30000
    driving_moving_speed_threshold_kph: float = 5.0
    driving_location_max_accuracy_meters: float = 100.0
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = ""
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

    @field_validator("default_admin_email", mode="before")
    @classmethod
    def normalize_default_admin_email(cls, value: object) -> str | None:
        if value is None:
            return None
        email = str(value).strip()
        return email or None

    @field_validator(
        "ws_recommended_frame_fps",
        "ws_location_interval_ms",
        "ws_location_persist_interval_ms",
        "ws_heartbeat_interval_ms",
        "ws_heartbeat_timeout_ms",
    )
    @classmethod
    def validate_positive_websocket_setting(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("WebSocket timing settings must be positive.")
        return value

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
