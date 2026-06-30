from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.core.error_codes import ErrorCode
from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel, ApiRequestModel

INVALID_PLACE_SETTING_MESSAGE = "장소 설정값이 올바르지 않습니다."
INVALID_COORDINATES_MESSAGE = "위도 또는 경도 값이 올바르지 않습니다."
EMPTY_PLACE_ADDRESS_MESSAGE = "장소 주소를 입력해 주세요."


def _raise_validation_error(error_code: ErrorCode, message: str) -> None:
    raise PydanticCustomError(error_code.value, message)


def _validate_required_text(
    value: object,
    *,
    max_length: int | None,
    error_code: ErrorCode,
    message: str,
) -> str:
    if not isinstance(value, str):
        _raise_validation_error(error_code, message)

    normalized = value.strip()
    if not normalized:
        _raise_validation_error(error_code, message)

    if max_length is not None and len(normalized) > max_length:
        _raise_validation_error(error_code, message)

    return normalized


def _validate_provider_place_id(value: object) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        _raise_validation_error(ErrorCode.INVALID_PLACE_SETTING, INVALID_PLACE_SETTING_MESSAGE)

    normalized = value.strip()
    if not normalized:
        return None

    if len(normalized) > 255:
        _raise_validation_error(ErrorCode.INVALID_PLACE_SETTING, INVALID_PLACE_SETTING_MESSAGE)

    return normalized


def _validate_coordinate(value: object) -> float:
    if isinstance(value, bool):
        _raise_validation_error(ErrorCode.INVALID_COORDINATES, INVALID_COORDINATES_MESSAGE)

    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        _raise_validation_error(ErrorCode.INVALID_COORDINATES, INVALID_COORDINATES_MESSAGE)

    if not math.isfinite(coordinate):
        _raise_validation_error(ErrorCode.INVALID_COORDINATES, INVALID_COORDINATES_MESSAGE)

    return coordinate


def _validate_latitude(value: object) -> float:
    latitude = _validate_coordinate(value)
    if latitude < -90 or latitude > 90:
        _raise_validation_error(ErrorCode.INVALID_COORDINATES, INVALID_COORDINATES_MESSAGE)
    return latitude


def _validate_longitude(value: object) -> float:
    longitude = _validate_coordinate(value)
    if longitude < -180 or longitude > 180:
        _raise_validation_error(ErrorCode.INVALID_COORDINATES, INVALID_COORDINATES_MESSAGE)
    return longitude


def normalize_saved_place_values(
    *,
    label: object,
    provider: object,
    provider_place_id: object,
    address: object,
    latitude: object,
    longitude: object,
) -> dict[str, Any]:
    return {
        "label": _validate_required_text(
            label,
            max_length=100,
            error_code=ErrorCode.INVALID_PLACE_SETTING,
            message=INVALID_PLACE_SETTING_MESSAGE,
        ),
        "provider": _validate_required_text(
            provider,
            max_length=20,
            error_code=ErrorCode.INVALID_PLACE_SETTING,
            message=INVALID_PLACE_SETTING_MESSAGE,
        ),
        "provider_place_id": _validate_provider_place_id(provider_place_id),
        "address": _validate_required_text(
            address,
            max_length=None,
            error_code=ErrorCode.EMPTY_PLACE_ADDRESS,
            message=EMPTY_PLACE_ADDRESS_MESSAGE,
        ),
        "latitude": _validate_latitude(latitude),
        "longitude": _validate_longitude(longitude),
    }


class SavedPlaceWriteRequest(ApiRequestModel):
    label: str
    provider: str
    provider_place_id: str | None = None
    address: str
    latitude: float
    longitude: float

    @field_validator("label", mode="before")
    @classmethod
    def validate_label(cls, value: object) -> str:
        return _validate_required_text(
            value,
            max_length=100,
            error_code=ErrorCode.INVALID_PLACE_SETTING,
            message=INVALID_PLACE_SETTING_MESSAGE,
        )

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, value: object) -> str:
        return _validate_required_text(
            value,
            max_length=20,
            error_code=ErrorCode.INVALID_PLACE_SETTING,
            message=INVALID_PLACE_SETTING_MESSAGE,
        )

    @field_validator("provider_place_id", mode="before")
    @classmethod
    def validate_provider_place_id(cls, value: object) -> str | None:
        return _validate_provider_place_id(value)

    @field_validator("address", mode="before")
    @classmethod
    def validate_address(cls, value: object) -> str:
        return _validate_required_text(
            value,
            max_length=None,
            error_code=ErrorCode.EMPTY_PLACE_ADDRESS,
            message=EMPTY_PLACE_ADDRESS_MESSAGE,
        )

    @field_validator("latitude", mode="before")
    @classmethod
    def validate_latitude(cls, value: object) -> float:
        return _validate_latitude(value)

    @field_validator("longitude", mode="before")
    @classmethod
    def validate_longitude(cls, value: object) -> float:
        return _validate_longitude(value)

    def to_place_data(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "provider": self.provider,
            "provider_place_id": self.provider_place_id,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


class SavedPlaceUpdateRequest(ApiRequestModel):
    label: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("label", mode="before")
    @classmethod
    def validate_label(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_required_text(
            value,
            max_length=100,
            error_code=ErrorCode.INVALID_PLACE_SETTING,
            message=INVALID_PLACE_SETTING_MESSAGE,
        )

    @field_validator("address", mode="before")
    @classmethod
    def validate_address(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_required_text(
            value,
            max_length=None,
            error_code=ErrorCode.EMPTY_PLACE_ADDRESS,
            message=EMPTY_PLACE_ADDRESS_MESSAGE,
        )

    @field_validator("latitude", mode="before")
    @classmethod
    def validate_latitude(cls, value: object) -> float | None:
        if value is None:
            return None
        return _validate_latitude(value)

    @field_validator("longitude", mode="before")
    @classmethod
    def validate_longitude(cls, value: object) -> float | None:
        if value is None:
            return None
        return _validate_longitude(value)

    def to_update_data(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in self.model_fields_set}


class SavedPlaceSummaryResponse(ApiBaseModel):
    id: str
    place_type: str
    label: str
    provider: str
    provider_place_id: str | None
    address: str
    latitude: float
    longitude: float


class SavedPlaceResponse(SavedPlaceSummaryResponse):
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return format_utc_datetime(value)


class SavedPlaceUpdateResponse(SavedPlaceSummaryResponse):
    updated_at: datetime

    @field_serializer("updated_at")
    def serialize_updated_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class FixedPlacesResponse(ApiBaseModel):
    home: SavedPlaceSummaryResponse | None = None
    work: SavedPlaceSummaryResponse | None = None
    school: SavedPlaceSummaryResponse | None = None


class SavedPlaceListResponse(ApiBaseModel):
    fixed_places: FixedPlacesResponse
    favorites: list[SavedPlaceSummaryResponse]
