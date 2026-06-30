from __future__ import annotations

from datetime import datetime

from pydantic import field_serializer

from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel


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
