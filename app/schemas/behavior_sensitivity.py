from pydantic import Field, model_validator

from app.core.enums import BehaviorType
from app.schemas.base import ApiRequestModel

MANUAL_RISK_BEHAVIOR_TYPES = frozenset(
    {
        BehaviorType.PHONE_USE,
        BehaviorType.DROWSINESS,
        BehaviorType.SECONDARY_TASK,
        BehaviorType.FOOD_OR_DRINK,
    }
)


class BehaviorTelemetryEvent(ApiRequestModel):
    behavior_type: BehaviorType
    click_count: int = Field(ge=0, strict=True)
    level: int = Field(ge=0, le=3, strict=True)


class DriveSummaryRequest(ApiRequestModel):
    telemetry_events: list[BehaviorTelemetryEvent] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def require_exact_manual_risk_behavior_types(self) -> "DriveSummaryRequest":
        behavior_types = {event.behavior_type for event in self.telemetry_events}
        if behavior_types != MANUAL_RISK_BEHAVIOR_TYPES:
            raise ValueError("telemetryEvents must contain each manual risk behavior exactly once.")
        return self
