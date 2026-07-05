from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import DriverProfile
from app.schemas.profile import (
    DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)


def make_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "displayName": " Codex Driver ",
        "agentCallName": " Codex ",
        "reportEmail": "codex@example.com",
        "agentPersonality": "FRIENDLY",
        "behaviorWarningSensitivity": DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
        "ttsVoiceId": None,
        "ttsSpeed": 1.0,
        "guidanceVolume": 70,
    }
    payload.update(overrides)
    return payload


def test_profile_response_serializes_camel_case_without_account_id() -> None:
    profile = DriverProfile(
        id="274d9648-e78a-4630-a8e8-e63070dc3c19",
        account_id="00000000-0000-0000-0000-000000000001",
        display_name="Codex Driver",
        agent_call_name="Codex",
        profile_image_url=None,
        report_email="codex@example.com",
        agent_personality="FRIENDLY",
        warning_sensitivity="MEDIUM",
        behavior_warning_sensitivity=DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
        tts_voice_id=None,
        tts_speed=Decimal("1.20"),
        guidance_volume=70,
        theme="SYSTEM",
        last_used_at=datetime(2026, 6, 30, 1, 2, 3, 123456),
        created_at=datetime(2026, 6, 29, 1, 2, 3, 123456),
        updated_at=datetime(2026, 6, 30, 1, 2, 3, 123456),
    )

    payload = ProfileResponse.model_validate(profile).model_dump(
        by_alias=True,
        mode="json",
    )

    assert "accountId" not in payload
    assert payload["displayName"] == "Codex Driver"
    assert payload["behaviorWarningSensitivity"]["DROWSINESS"] == 9
    assert payload["ttsSpeed"] == 1.2
    assert payload["lastUsedAt"] == "2026-06-30T01:02:03.123456Z"
    assert payload["createdAt"] == "2026-06-29T01:02:03.123456Z"


def test_profile_create_request_trims_supported_text_fields() -> None:
    request = ProfileCreateRequest(**make_create_payload(ttsVoiceId=" voice-1 "))

    assert request.display_name == "Codex Driver"
    assert request.agent_call_name == "Codex"
    assert request.tts_voice_id == "voice-1"


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("displayName", "", "INVALID_DISPLAY_NAME"),
        ("displayName", "x" * 51, "INVALID_DISPLAY_NAME"),
        ("agentCallName", "", "INVALID_PROFILE_SETTING"),
        ("agentCallName", "x" * 51, "INVALID_PROFILE_SETTING"),
        ("reportEmail", "", "INVALID_EMAIL_FORMAT"),
        ("reportEmail", "not-an-email", "INVALID_EMAIL_FORMAT"),
        ("agentPersonality", "LOUD", "INVALID_AGENT_PERSONALITY"),
        ("warningSensitivity", "EXTREME", "INVALID_WARNING_SENSITIVITY"),
        (
            "behaviorWarningSensitivity",
            {**DEFAULT_BEHAVIOR_WARNING_SENSITIVITY, "PHONE_USE": 11},
            "INVALID_WARNING_SENSITIVITY",
        ),
        (
            "behaviorWarningSensitivity",
            {"DROWSINESS": "HIGH"},
            "INVALID_WARNING_SENSITIVITY",
        ),
        ("ttsSpeed", 0.49, "INVALID_TTS_SPEED"),
        ("ttsSpeed", 2.01, "INVALID_TTS_SPEED"),
        ("guidanceVolume", -1, "INVALID_PROFILE_SETTING"),
        ("guidanceVolume", 101, "INVALID_PROFILE_SETTING"),
        ("guidanceVolume", True, "INVALID_PROFILE_SETTING"),
        ("theme", "BLUE", "INVALID_PROFILE_SETTING"),
    ],
)
def test_profile_create_validation_errors_are_structured(
    field: str,
    value: object,
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProfileCreateRequest(**make_create_payload(**{field: value}))

    assert exc_info.value.errors()[0]["type"] == error_type


def test_profile_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProfileCreateRequest(**make_create_payload(accountId="not-allowed"))

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_profile_create_accepts_legacy_behavior_warning_sensitivity_values() -> None:
    request = ProfileCreateRequest(
        **make_create_payload(
            behaviorWarningSensitivity={
                "DROWSINESS": "HIGH",
                "PHONE_USE": "HIGH",
                "FOOD_OR_DRINK": "MEDIUM",
                "GAZE_AWAY": "HIGH",
                "SECONDARY_TASK": "MEDIUM",
                "REACHING_BEHIND": "MEDIUM",
                "SMOKING": "LOW",
            },
        )
    )

    assert request.behavior_warning_sensitivity == {
        **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
        "SMOKING": 4,
    }


def test_profile_update_distinguishes_omitted_and_explicit_null_fields() -> None:
    request = ProfileUpdateRequest(reportEmail=None, ttsVoiceId="")

    assert request.model_fields_set == {"report_email", "tts_voice_id"}
    assert request.to_update_data() == {"report_email": None, "tts_voice_id": None}

    with pytest.raises(ValidationError) as exc_info:
        ProfileUpdateRequest(displayName=None)

    assert exc_info.value.errors()[0]["type"] == "INVALID_PROFILE_SETTING"

    with pytest.raises(ValidationError) as exc_info:
        ProfileUpdateRequest(behaviorWarningSensitivity=None)

    assert exc_info.value.errors()[0]["type"] == "INVALID_PROFILE_SETTING"
