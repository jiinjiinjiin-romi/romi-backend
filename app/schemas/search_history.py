from __future__ import annotations

from datetime import datetime

from pydantic import field_serializer, field_validator

from app.core.error_codes import ErrorCode
from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel, ApiRequestModel
from app.schemas.saved_place import (
    EMPTY_PLACE_ADDRESS_MESSAGE,
    INVALID_PLACE_SETTING_MESSAGE,
    _validate_latitude,
    _validate_longitude,
    _validate_provider_place_id,
    _validate_required_text,
)


class SearchHistoryCreateRequest(ApiRequestModel):
    query: str
    provider: str = "TMAP"
    provider_place_id: str | None = None
    place_name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, value: object) -> str:
        return _validate_required_text(
            value,
            max_length=200,
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
        ).upper()

    @field_validator("provider_place_id", mode="before")
    @classmethod
    def validate_provider_place_id(cls, value: object) -> str | None:
        return _validate_provider_place_id(value)

    @field_validator("place_name", mode="before")
    @classmethod
    def validate_place_name(cls, value: object) -> str | None:
        if value is None:
            return None
        return _validate_required_text(
            value,
            max_length=200,
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


class SearchHistoryItemResponse(ApiBaseModel):
    id: int
    query: str
    provider: str
    provider_place_id: str | None
    place_name: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    searched_at: datetime

    @field_serializer("searched_at")
    def serialize_searched_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class SearchHistoryListResponse(ApiBaseModel):
    items: list[SearchHistoryItemResponse]
    page: int
    size: int
    total: int
    total_pages: int

    @classmethod
    def from_items(
        cls,
        *,
        items: list[SearchHistoryItemResponse],
        page: int,
        size: int,
        total: int,
    ) -> SearchHistoryListResponse:
        total_pages = 0 if total == 0 else (total + size - 1) // size
        return cls(
            items=items,
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )


class SearchHistoryDeleteResponse(ApiBaseModel):
    deleted_count: int
    deleted_at: datetime

    @field_serializer("deleted_at")
    def serialize_deleted_at(self, value: datetime) -> str:
        return format_utc_datetime(value)
