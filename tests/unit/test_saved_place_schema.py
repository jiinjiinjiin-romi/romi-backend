from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import SavedPlace
from app.schemas.saved_place import (
    SavedPlaceResponse,
    SavedPlaceUpdateRequest,
    SavedPlaceWriteRequest,
)


def place_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": " Smoke Home ",
        "provider": " KAKAO ",
        "providerPlaceId": " place-1 ",
        "address": " 서울특별시 광진구 능동로 209 ",
        "latitude": 37.5501,
        "longitude": 127.0734,
    }
    payload.update(overrides)
    return payload


def test_saved_place_write_request_normalizes_camel_case_payload() -> None:
    request = SavedPlaceWriteRequest(**place_payload(providerPlaceId=" "))

    assert request.label == "Smoke Home"
    assert request.provider == "KAKAO"
    assert request.provider_place_id is None
    assert request.address == "서울특별시 광진구 능동로 209"
    assert request.to_place_data()["latitude"] == 37.5501


def test_saved_place_response_serializes_camel_case_without_profile_id() -> None:
    place = SavedPlace(
        id="50d6e127-cc8f-46dd-958f-a2cc12a0aa66",
        profile_id="274d9648-e78a-4630-a8e8-e63070dc3c19",
        place_type="HOME",
        label="Smoke Home",
        provider="KAKAO",
        provider_place_id="place-1",
        address="서울특별시 광진구 능동로 209",
        latitude=37.5501,
        longitude=127.0734,
        created_at=datetime(2026, 6, 30, 1, 2, 3, 123456),
        updated_at=datetime(2026, 6, 30, 2, 3, 4, 123456),
    )

    payload = SavedPlaceResponse.model_validate(place).model_dump(
        by_alias=True,
        mode="json",
    )

    assert "profileId" not in payload
    assert payload["placeType"] == "HOME"
    assert payload["providerPlaceId"] == "place-1"
    assert payload["createdAt"] == "2026-06-30T01:02:03.123456Z"
    assert payload["updatedAt"] == "2026-06-30T02:03:04.123456Z"


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("label", "", "INVALID_PLACE_SETTING"),
        ("label", "x" * 101, "INVALID_PLACE_SETTING"),
        ("provider", "", "INVALID_PLACE_SETTING"),
        ("provider", "x" * 21, "INVALID_PLACE_SETTING"),
        ("providerPlaceId", "x" * 256, "INVALID_PLACE_SETTING"),
        ("address", "", "EMPTY_PLACE_ADDRESS"),
        ("latitude", 91.0, "INVALID_COORDINATES"),
        ("longitude", 181.0, "INVALID_COORDINATES"),
        ("latitude", True, "INVALID_COORDINATES"),
        ("longitude", False, "INVALID_COORDINATES"),
    ],
)
def test_saved_place_write_validation_errors_are_structured(
    field: str,
    value: object,
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SavedPlaceWriteRequest(**place_payload(**{field: value}))

    assert exc_info.value.errors()[0]["type"] == error_type


def test_saved_place_write_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SavedPlaceWriteRequest(**place_payload(accountId="not-allowed"))

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_saved_place_update_tracks_omitted_and_explicit_null_fields() -> None:
    request = SavedPlaceUpdateRequest(label=" Updated ", latitude=37.0)

    assert request.model_fields_set == {"label", "latitude"}
    assert request.to_update_data() == {"label": "Updated", "latitude": 37.0}

    explicit_null = SavedPlaceUpdateRequest(address=None)
    assert explicit_null.model_fields_set == {"address"}
    assert explicit_null.to_update_data() == {"address": None}


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"label": ""}, "INVALID_PLACE_SETTING"),
        ({"address": ""}, "EMPTY_PLACE_ADDRESS"),
        ({"latitude": 90.1}, "INVALID_COORDINATES"),
        ({"longitude": -180.1}, "INVALID_COORDINATES"),
        ({"provider": "KAKAO"}, "extra_forbidden"),
    ],
)
def test_saved_place_update_validation(payload: dict[str, object], error_type: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SavedPlaceUpdateRequest(**payload)

    assert exc_info.value.errors()[0]["type"] == error_type
