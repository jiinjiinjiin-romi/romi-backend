import json
from collections.abc import Iterable
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
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
    db_pool_recycle_seconds: int = 1800
    backend_exposed_port: int = 8000
    model_path: str = "/app/artifacts/models/best_vit.pth"
    model_version: str = "vit-dms-1.0.0"
    policy_version: str = "risk-policy-1.0.0"
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

    @property
    def database_url(self) -> str:
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
