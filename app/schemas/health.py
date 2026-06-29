from datetime import datetime
from typing import Literal

from pydantic import field_serializer

from app.schemas.base import ApiBaseModel

ServiceState = Literal["UP", "DOWN"]
OverallHealthStatus = Literal["UP", "DEGRADED"]


class HealthServices(ApiBaseModel):
    database: ServiceState
    vit_model: ServiceState
    gemini: ServiceState
    email: ServiceState


class HealthResponse(ApiBaseModel):
    status: OverallHealthStatus
    services: HealthServices
    model_version: str
    policy_version: str
    checked_at: datetime

    @field_serializer("checked_at")
    def serialize_checked_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
