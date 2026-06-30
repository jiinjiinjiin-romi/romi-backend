from datetime import datetime

import pytest

from app.core.exceptions import AppException
from app.models import SearchHistory
from app.schemas.search_history import SearchHistoryItemResponse, SearchHistoryListResponse
from app.services.search_history_service import SearchHistoryService


def test_search_history_item_serializes_camel_case_datetime() -> None:
    history = SearchHistory(
        id=301,
        profile_id="274d9648-e78a-4630-a8e8-e63070dc3c19",
        query="편의점",
        provider="KAKAO",
        provider_place_id="111111",
        place_name="CU 세종대점",
        address="서울특별시 광진구 능동로",
        latitude=37.5505,
        longitude=127.0738,
        searched_at=datetime(2026, 6, 30, 1, 2, 3, 123456),
    )

    payload = SearchHistoryItemResponse.model_validate(history).model_dump(
        by_alias=True,
        mode="json",
    )

    assert payload == {
        "id": 301,
        "query": "편의점",
        "provider": "KAKAO",
        "providerPlaceId": "111111",
        "placeName": "CU 세종대점",
        "address": "서울특별시 광진구 능동로",
        "latitude": 37.5505,
        "longitude": 127.0738,
        "searchedAt": "2026-06-30T01:02:03.123456Z",
    }


@pytest.mark.parametrize(
    ("total", "size", "expected_pages"),
    [
        (0, 20, 0),
        (1, 20, 1),
        (20, 20, 1),
        (21, 20, 2),
    ],
)
def test_search_history_list_total_pages(
    total: int,
    size: int,
    expected_pages: int,
) -> None:
    response = SearchHistoryListResponse.from_items(
        items=[],
        page=1,
        size=size,
        total=total,
    )

    assert response.total_pages == expected_pages


@pytest.mark.parametrize(
    ("page", "size", "error_code"),
    [
        (0, 20, "INVALID_PAGE"),
        (1, 0, "INVALID_PAGE_SIZE"),
        (1, 101, "INVALID_PAGE_SIZE"),
    ],
)
def test_search_history_pagination_validation(
    page: int,
    size: int,
    error_code: str,
) -> None:
    with pytest.raises(AppException) as exc_info:
        SearchHistoryService._validate_pagination(page, size)

    assert exc_info.value.error_code == error_code
