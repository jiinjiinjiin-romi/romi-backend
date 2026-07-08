from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_serializer, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.core.enums import AgentPersonality, BehaviorType, Theme, WarningSensitivity
from app.core.error_codes import ErrorCode
from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel, ApiRequestModel

PROFILE_LIMIT = 5
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

INVALID_PROFILE_SETTING_MESSAGE = "프로필 설정값이 올바르지 않습니다."
DEFAULT_BEHAVIOR_WARNING_SENSITIVITY = {
    BehaviorType.DROWSINESS.value: 9,
    BehaviorType.PHONE_USE.value: 9,
    BehaviorType.FOOD_OR_DRINK.value: 7,
    BehaviorType.GAZE_AWAY.value: 9,
    BehaviorType.SECONDARY_TASK.value: 7,
    BehaviorType.REACHING_BEHIND.value: 7,
    BehaviorType.SMOKING.value: 7,
}
LEGACY_BEHAVIOR_WARNING_SENSITIVITY_MAP = {
    WarningSensitivity.LOW.value: 4,
    WarningSensitivity.MEDIUM.value: 7,
    WarningSensitivity.HIGH.value: 9,
}


def _raise_validation_error(error_code: ErrorCode, message: str) -> None:
    raise PydanticCustomError(error_code.value, message)


def _validate_required_text(
    value: object,
    *,
    error_code: ErrorCode,
    message: str,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        _raise_validation_error(error_code, message)

    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        _raise_validation_error(error_code, message)

    return normalized


def _validate_optional_text(
    value: object,
    *,
    max_length: int,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        _raise_validation_error(ErrorCode.INVALID_PROFILE_SETTING, INVALID_PROFILE_SETTING_MESSAGE)

    normalized = value.strip()
    if not normalized:
        return None

    if len(normalized) > max_length:
        _raise_validation_error(ErrorCode.INVALID_PROFILE_SETTING, INVALID_PROFILE_SETTING_MESSAGE)

    return normalized


def _validate_enum_value(
    value: object,
    *,
    allowed_values: set[str],
    error_code: ErrorCode,
    message: str,
) -> str:
    if not isinstance(value, str) or value not in allowed_values:
        _raise_validation_error(error_code, message)
    return value


def _validate_agent_personality(value: object) -> str:
    if not isinstance(value, str):
        _raise_validation_error(
            ErrorCode.INVALID_AGENT_PERSONALITY,
            "지원하지 않는 안내 음성 스타일입니다.",
        )

    normalized = value.strip().upper()
    if normalized not in {item.value for item in AgentPersonality}:
        _raise_validation_error(
            ErrorCode.INVALID_AGENT_PERSONALITY,
            "지원하지 않는 안내 음성 스타일입니다.",
        )
    return normalized


def _validate_behavior_warning_sensitivity(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        _raise_validation_error(
            ErrorCode.INVALID_WARNING_SENSITIVITY,
            "지원하지 않는 경고 민감도입니다.",
        )

    expected_keys = {item.value for item in BehaviorType}
    if set(value.keys()) != expected_keys:
        _raise_validation_error(
            ErrorCode.INVALID_WARNING_SENSITIVITY,
            "지원하지 않는 경고 민감도입니다.",
        )

    normalized: dict[str, int] = {}
    for behavior_type in BehaviorType:
        sensitivity = value[behavior_type.value]
        if isinstance(sensitivity, str) and sensitivity in LEGACY_BEHAVIOR_WARNING_SENSITIVITY_MAP:
            normalized[behavior_type.value] = LEGACY_BEHAVIOR_WARNING_SENSITIVITY_MAP[sensitivity]
            continue

        invalid_numeric_sensitivity = (
            isinstance(sensitivity, bool)
            or not isinstance(sensitivity, int)
            or sensitivity < 3
            or sensitivity > 10
        )
        if invalid_numeric_sensitivity:
            _raise_validation_error(
                ErrorCode.INVALID_WARNING_SENSITIVITY,
                "지원하지 않는 경고 민감도입니다.",
            )
        normalized[behavior_type.value] = sensitivity

    return normalized


def _validate_report_email(value: object) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        _raise_validation_error(
            ErrorCode.INVALID_EMAIL_FORMAT,
            "올바른 이메일 주소를 입력해 주세요.",
        )

    normalized = value.strip()
    if not normalized or len(normalized) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        _raise_validation_error(
            ErrorCode.INVALID_EMAIL_FORMAT,
            "올바른 이메일 주소를 입력해 주세요.",
        )

    return normalized


def _validate_tts_speed(value: object) -> float:
    if isinstance(value, bool):
        _raise_validation_error(
            ErrorCode.INVALID_TTS_SPEED,
            "TTS 속도는 0.5 이상 2.0 이하로 설정해야 합니다.",
        )

    try:
        speed = float(value)
    except (TypeError, ValueError):
        _raise_validation_error(
            ErrorCode.INVALID_TTS_SPEED,
            "TTS 속도는 0.5 이상 2.0 이하로 설정해야 합니다.",
        )

    if speed < 0.5 or speed > 2.0:
        _raise_validation_error(
            ErrorCode.INVALID_TTS_SPEED,
            "TTS 속도는 0.5 이상 2.0 이하로 설정해야 합니다.",
        )

    return speed


def _validate_guidance_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _raise_validation_error(ErrorCode.INVALID_PROFILE_SETTING, INVALID_PROFILE_SETTING_MESSAGE)

    if value < 0 or value > 100:
        _raise_validation_error(ErrorCode.INVALID_PROFILE_SETTING, INVALID_PROFILE_SETTING_MESSAGE)

    return value


class ProfileCreateRequest(ApiRequestModel):
    display_name: str
    agent_call_name: str
    report_email: str | None = None
    agent_personality: str
    warning_sensitivity: str = WarningSensitivity.MEDIUM.value
    behavior_warning_sensitivity: dict[str, int] = Field(
        default_factory=lambda: DEFAULT_BEHAVIOR_WARNING_SENSITIVITY.copy()
    )
    tts_voice_id: str | None = None
    tts_speed: float
    guidance_volume: int
    theme: str = Theme.SYSTEM.value

    @field_validator("display_name", mode="before")
    @classmethod
    def validate_display_name(cls, value: object) -> str:
        return _validate_required_text(
            value,
            error_code=ErrorCode.INVALID_DISPLAY_NAME,
            message="프로필 이름을 입력해 주세요.",
            max_length=50,
        )

    @field_validator("agent_call_name", mode="before")
    @classmethod
    def validate_agent_call_name(cls, value: object) -> str:
        return _validate_required_text(
            value,
            error_code=ErrorCode.INVALID_PROFILE_SETTING,
            message=INVALID_PROFILE_SETTING_MESSAGE,
            max_length=50,
        )

    @field_validator("report_email", mode="before")
    @classmethod
    def validate_report_email(cls, value: object) -> str | None:
        return _validate_report_email(value)

    @field_validator("agent_personality", mode="before")
    @classmethod
    def validate_agent_personality(cls, value: object) -> str:
        return _validate_agent_personality(value)

    @field_validator("warning_sensitivity", mode="before")
    @classmethod
    def validate_warning_sensitivity(cls, value: object) -> str:
        return _validate_enum_value(
            value,
            allowed_values={item.value for item in WarningSensitivity},
            error_code=ErrorCode.INVALID_WARNING_SENSITIVITY,
            message="지원하지 않는 경고 민감도입니다.",
        )

    @field_validator("behavior_warning_sensitivity", mode="before")
    @classmethod
    def validate_behavior_warning_sensitivity(cls, value: object) -> dict[str, int]:
        return _validate_behavior_warning_sensitivity(value)

    @field_validator("tts_voice_id", mode="before")
    @classmethod
    def validate_tts_voice_id(cls, value: object) -> str | None:
        return _validate_optional_text(value, max_length=100)

    @field_validator("tts_speed", mode="before")
    @classmethod
    def validate_tts_speed(cls, value: object) -> float:
        return _validate_tts_speed(value)

    @field_validator("guidance_volume", mode="before")
    @classmethod
    def validate_guidance_volume(cls, value: object) -> int:
        return _validate_guidance_volume(value)

    @field_validator("theme", mode="before")
    @classmethod
    def validate_theme(cls, value: object) -> str:
        return _validate_enum_value(
            value,
            allowed_values={item.value for item in Theme},
            error_code=ErrorCode.INVALID_PROFILE_SETTING,
            message=INVALID_PROFILE_SETTING_MESSAGE,
        )

    def to_model_data(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "agent_call_name": self.agent_call_name,
            "report_email": self.report_email,
            "agent_personality": self.agent_personality,
            "warning_sensitivity": self.warning_sensitivity,
            "behavior_warning_sensitivity": self.behavior_warning_sensitivity,
            "tts_voice_id": self.tts_voice_id,
            "tts_speed": Decimal(str(self.tts_speed)),
            "guidance_volume": self.guidance_volume,
            "theme": self.theme,
        }


class ProfileUpdateRequest(ApiRequestModel):
    display_name: str | None = None
    agent_call_name: str | None = None
    report_email: str | None = None
    agent_personality: str | None = None
    warning_sensitivity: str | None = None
    behavior_warning_sensitivity: dict[str, int] | None = None
    tts_voice_id: str | None = None
    tts_speed: float | None = None
    guidance_volume: int | None = None
    theme: str | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def validate_display_name(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_required_text(
            value,
            error_code=ErrorCode.INVALID_DISPLAY_NAME,
            message="프로필 이름을 입력해 주세요.",
            max_length=50,
        )

    @field_validator("agent_call_name", mode="before")
    @classmethod
    def validate_agent_call_name(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_required_text(
            value,
            error_code=ErrorCode.INVALID_PROFILE_SETTING,
            message=INVALID_PROFILE_SETTING_MESSAGE,
            max_length=50,
        )

    @field_validator("report_email", mode="before")
    @classmethod
    def validate_report_email(cls, value: object) -> str | None:
        return _validate_report_email(value)

    @field_validator("agent_personality", mode="before")
    @classmethod
    def validate_agent_personality(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_agent_personality(value)

    @field_validator("warning_sensitivity", mode="before")
    @classmethod
    def validate_warning_sensitivity(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_enum_value(
            value,
            allowed_values={item.value for item in WarningSensitivity},
            error_code=ErrorCode.INVALID_WARNING_SENSITIVITY,
            message="지원하지 않는 경고 민감도입니다.",
        )

    @field_validator("behavior_warning_sensitivity", mode="before")
    @classmethod
    def validate_behavior_warning_sensitivity(cls, value: object) -> dict[str, int] | None:
        if value is None:
            return None
        return _validate_behavior_warning_sensitivity(value)

    @field_validator("tts_voice_id", mode="before")
    @classmethod
    def validate_tts_voice_id(cls, value: object) -> str | None:
        return _validate_optional_text(value, max_length=100)

    @field_validator("tts_speed", mode="before")
    @classmethod
    def validate_tts_speed(cls, value: object) -> float | None:
        if value is None:
            return None
        return _validate_tts_speed(value)

    @field_validator("guidance_volume", mode="before")
    @classmethod
    def validate_guidance_volume(cls, value: object) -> int | None:
        if value is None:
            return None
        return _validate_guidance_volume(value)

    @field_validator("theme", mode="before")
    @classmethod
    def validate_theme(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_enum_value(
            value,
            allowed_values={item.value for item in Theme},
            error_code=ErrorCode.INVALID_PROFILE_SETTING,
            message=INVALID_PROFILE_SETTING_MESSAGE,
        )

    @model_validator(mode="after")
    def reject_null_for_required_settings(self) -> ProfileUpdateRequest:
        nullable_fields = {"report_email", "tts_voice_id"}
        for field_name in self.model_fields_set:
            if field_name not in nullable_fields and getattr(self, field_name) is None:
                _raise_validation_error(
                    ErrorCode.INVALID_PROFILE_SETTING,
                    INVALID_PROFILE_SETTING_MESSAGE,
                )
        return self

    def to_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field_name in self.model_fields_set:
            value = getattr(self, field_name)
            data[field_name] = Decimal(str(value)) if field_name == "tts_speed" else value
        return data


class ProfileResponse(ApiBaseModel):
    id: str
    display_name: str
    agent_call_name: str
    profile_image_url: str | None
    report_email: str | None
    agent_personality: str
    warning_sensitivity: str
    behavior_warning_sensitivity: dict[str, int]
    tts_voice_id: str | None
    tts_speed: float
    guidance_volume: int
    theme: str
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("behavior_warning_sensitivity", mode="before")
    @classmethod
    def validate_behavior_warning_sensitivity(cls, value: object) -> dict[str, int]:
        return _validate_behavior_warning_sensitivity(value)

    @field_serializer("last_used_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc_datetime(value)


class ProfileSummaryResponse(ApiBaseModel):
    id: str
    display_name: str
    agent_call_name: str
    profile_image_url: str | None
    agent_personality: str
    warning_sensitivity: str
    behavior_warning_sensitivity: dict[str, int]
    last_used_at: datetime | None

    @field_validator("behavior_warning_sensitivity", mode="before")
    @classmethod
    def validate_behavior_warning_sensitivity(cls, value: object) -> dict[str, int]:
        return _validate_behavior_warning_sensitivity(value)

    @field_serializer("last_used_at")
    def serialize_last_used_at(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc_datetime(value)


class ProfileListResponse(ApiBaseModel):
    profiles: list[ProfileResponse]
    count: int
    limit: int = PROFILE_LIMIT


class ProfileSelectResponse(ApiBaseModel):
    selected_profile_id: str
    selected_at: datetime

    @field_serializer("selected_at")
    def serialize_selected_at(self, value: datetime) -> str:
        return format_utc_datetime(value)
