import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.core.enums import BehaviorType
from app.core.exceptions import AppException
from app.integrations.gemini.behavior_sensitivity import (
    GeminiBehaviorSensitivityClient,
    GeminiNotConfiguredError,
    GeminiProviderError,
)
from app.schemas.behavior_sensitivity import DriveSummaryRequest
from app.schemas.profile import DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
from app.services.profile_service import ProfileService


def make_settings(**overrides: object) -> Settings:
    values = {
        "gemini_api_key": "test-api-key",
        "gemini_model": "gemini-2.5-flash",
        "gemini_behavior_sensitivity_prompt": (
            "운전 위험 데이터를 분석해 민감도를 JSON으로 반환하세요."
        ),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def telemetry_events() -> list[dict[str, object]]:
    return [
        {"behaviorType": "DROWSINESS", "clickCount": 2, "level": 3},
        {"behaviorType": "PHONE_USE", "clickCount": 1, "level": 2},
        {"behaviorType": "FOOD_OR_DRINK", "clickCount": 0, "level": 1},
        {"behaviorType": "SECONDARY_TASK", "clickCount": 4, "level": 3},
    ]


def test_gemini_prompt_example_uses_a_syntactically_valid_json_object() -> None:
    example_env = Path(__file__).parents[2] / ".env.example"
    prompt_line = next(
        line
        for line in example_env.read_text(encoding="utf-8").splitlines()
        if line.startswith("GEMINI_BEHAVIOR_SENSITIVITY_PROMPT=")
    )
    prompt = json.loads(prompt_line.split("=", 1)[1])
    example_json = prompt.rsplit(": ", 1)[1]

    assert json.loads(example_json) == {
        "behaviorWarningSensitivity": {
            behavior.value: 8 for behavior in BehaviorType
        }
    }


@pytest.mark.asyncio
async def test_recommendation_requires_key_model_and_env_prompt_without_fallback() -> None:
    client = GeminiBehaviorSensitivityClient(
        settings=make_settings(gemini_behavior_sensitivity_prompt="")
    )

    with pytest.raises(GeminiNotConfiguredError, match="GEMINI_BEHAVIOR_SENSITIVITY_PROMPT"):
        await client.recommend(telemetry_events())


@pytest.mark.asyncio
async def test_recommendation_sends_env_prompt_and_telemetry_as_separate_content() -> None:
    captured_payload: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.params) == ""
        assert request.headers["x-goog-api-key"] == "test-api-key"
        captured_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "behaviorWarningSensitivity": (
                                                DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
                                            )
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GeminiBehaviorSensitivityClient(
            settings=make_settings(), client=http_client
        ).recommend(telemetry_events())

    assert result == DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
    assert captured_payload["systemInstruction"] == {
        "parts": [{"text": "운전 위험 데이터를 분석해 민감도를 JSON으로 반환하세요."}]
    }
    request_text = captured_payload["contents"][0]["parts"][0]["text"]  # type: ignore[index]
    assert json.loads(request_text) == {"telemetryEvents": telemetry_events()}


@pytest.mark.asyncio
async def test_recommendation_enforces_the_exact_structured_json_response_schema() -> None:
    captured_payload: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "behaviorWarningSensitivity": (
                                                DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
                                            )
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await GeminiBehaviorSensitivityClient(
            settings=make_settings(), client=http_client
        ).recommend(telemetry_events())

    generation_config = captured_payload["generationConfig"]  # type: ignore[index]
    response_format = generation_config["responseFormat"]  # type: ignore[index]
    text_format = response_format["text"]  # type: ignore[index]
    schema = text_format["schema"]  # type: ignore[index]
    behavior_schema = schema["properties"]["behaviorWarningSensitivity"]  # type: ignore[index]

    expected_keys = [behavior.value for behavior in BehaviorType]
    assert text_format["mimeType"] == "APPLICATION_JSON"
    assert schema["type"] == "object"
    assert schema["required"] == ["behaviorWarningSensitivity"]
    assert schema["additionalProperties"] is False
    assert schema["propertyOrdering"] == ["behaviorWarningSensitivity"]
    assert behavior_schema["type"] == "object"
    assert behavior_schema["required"] == expected_keys
    assert behavior_schema["additionalProperties"] is False
    assert behavior_schema["propertyOrdering"] == expected_keys
    assert set(behavior_schema["properties"]) == set(expected_keys)
    assert all(
        property_schema == {"type": "integer", "minimum": 3, "maximum": 10}
        for property_schema in behavior_schema["properties"].values()
    )


@pytest.mark.asyncio
async def test_recommendation_accepts_a_single_complete_json_fence() -> None:
    response_text = "```json\n" + json.dumps(
        {"behaviorWarningSensitivity": DEFAULT_BEHAVIOR_WARNING_SENSITIVITY}
    ) + "\n```"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": response_text}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GeminiBehaviorSensitivityClient(
            settings=make_settings(), client=http_client
        ).recommend(telemetry_events())

    assert result == DEFAULT_BEHAVIOR_WARNING_SENSITIVITY


@pytest.mark.asyncio
async def test_recommendation_joins_multiple_text_parts_into_strict_json() -> None:
    response_text = json.dumps(
        {"behaviorWarningSensitivity": DEFAULT_BEHAVIOR_WARNING_SENSITIVITY}
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": response_text[:40]},
                                {"text": response_text[40:]},
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GeminiBehaviorSensitivityClient(
            settings=make_settings(), client=http_client
        ).recommend(telemetry_events())

    assert result == DEFAULT_BEHAVIOR_WARNING_SENSITIVITY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_text",
    [
        "```json\n{}\n```",
        "분석 결과입니다.\n"
        + json.dumps(
            {"behaviorWarningSensitivity": DEFAULT_BEHAVIOR_WARNING_SENSITIVITY}
        ),
        json.dumps({"behaviorWarningSensitivity": {"DROWSINESS": 8}}),
        json.dumps(
            {
                "behaviorWarningSensitivity": {
                    **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
                    "UNSUPPORTED": 7,
                }
            }
        ),
        json.dumps(
            {
                "behaviorWarningSensitivity": {
                    **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
                    "DROWSINESS": 11,
                }
            }
        ),
    ],
)
async def test_recommendation_rejects_non_strict_gemini_json(response_text: str) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": response_text}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = GeminiBehaviorSensitivityClient(settings=make_settings(), client=http_client)
        with pytest.raises(GeminiProviderError):
            await client.recommend(telemetry_events())


@pytest.mark.asyncio
async def test_recommendation_logs_only_safe_value_range_failure_classification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response_text = json.dumps(
        {
            "behaviorWarningSensitivity": {
                **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
                "DROWSINESS": 11,
            }
        }
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": response_text}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = GeminiBehaviorSensitivityClient(settings=make_settings(), client=http_client)
        with pytest.raises(GeminiProviderError):
            await client.recommend(telemetry_events())

    messages = [record.getMessage() for record in caplog.records]
    assert any("reason=value_type_or_range" in message for message in messages)
    assert response_text not in "\n".join(messages)
    assert "test-api-key" not in "\n".join(messages)


@pytest.mark.asyncio
async def test_recommendation_logs_timeout_with_configured_timeout_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = GeminiBehaviorSensitivityClient(
            settings=make_settings(gemini_request_timeout_seconds=45.0), client=http_client
        )
        with pytest.raises(GeminiProviderError, match="request failed") as exc_info:
            await client.recommend(telemetry_events())

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert exc_info.value.reason == "request_timeout"
    assert "reason=request_timeout timeout_seconds=45.0" in messages
    assert "test-api-key" not in messages
    assert "request timed out" not in messages


@pytest.mark.asyncio
async def test_recommendation_uses_configured_timeout_for_default_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_timeout: object | None = None

    class FakeAsyncClient:
        def __init__(self, *, timeout: object) -> None:
            nonlocal captured_timeout
            captured_timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "behaviorWarningSensitivity": (
                                                    DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
                                                )
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(
        "app.integrations.gemini.behavior_sensitivity.httpx.AsyncClient", FakeAsyncClient
    )

    result = await GeminiBehaviorSensitivityClient(
        settings=make_settings(gemini_request_timeout_seconds=42.5)
    ).recommend(telemetry_events())

    assert result == DEFAULT_BEHAVIOR_WARNING_SENSITIVITY
    assert captured_timeout == 42.5


@pytest.mark.asyncio
async def test_recommendation_logs_safe_http_status_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            request=request,
            json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "secret"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = GeminiBehaviorSensitivityClient(settings=make_settings(), client=http_client)
        with pytest.raises(GeminiProviderError) as exc_info:
            await client.recommend(telemetry_events())

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert exc_info.value.reason == "http_status"
    assert (
        "reason=http_status status_code=400 provider_code=400 "
        "provider_status=INVALID_ARGUMENT" in messages
    )
    assert "secret" not in messages


@pytest.mark.asyncio
async def test_drive_summary_recommendation_persists_the_valid_gemini_result() -> None:
    updated_sensitivity = {
        **DEFAULT_BEHAVIOR_WARNING_SENSITIVITY,
        "DROWSINESS": 6,
    }
    profile = SimpleNamespace(
        id="profile-id",
        account_id="account-id",
        display_name="운전자",
        agent_call_name="로디",
        profile_image_url=None,
        report_email=None,
        agent_personality="FRIENDLY",
        warning_sensitivity="MEDIUM",
        behavior_warning_sensitivity=DEFAULT_BEHAVIOR_WARNING_SENSITIVITY.copy(),
        tts_voice_id=None,
        tts_speed=Decimal("1.00"),
        guidance_volume=70,
        theme="SYSTEM",
        last_used_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class FakeProfileRepository:
        async def get_by_account(self, account_id: str, profile_id: str):
            assert (account_id, profile_id) == ("account-id", "profile-id")
            return profile

        async def get_by_account_for_update_current(self, account_id: str, profile_id: str):
            assert (account_id, profile_id) == ("account-id", "profile-id")
            return profile

    class FakeSession:
        commits = 0

        async def flush(self) -> None:
            return None

        async def refresh(self, _: object) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            return None

    class FakeGeminiClient:
        async def recommend(self, events: list[dict[str, object]]) -> dict[str, int]:
            assert events == telemetry_events()
            return updated_sensitivity

    service = ProfileService.__new__(ProfileService)
    service.session = FakeSession()
    service.profile_repository = FakeProfileRepository()
    service.gemini_client = FakeGeminiClient()
    response = await service.update_behavior_warning_sensitivity_from_drive_summary(
        SimpleNamespace(id="account-id"),
        "profile-id",
        DriveSummaryRequest(telemetryEvents=telemetry_events()),
    )

    assert profile.behavior_warning_sensitivity == updated_sensitivity
    assert response.behavior_warning_sensitivity == updated_sensitivity
    assert service.session.commits == 1


@pytest.mark.asyncio
async def test_drive_summary_does_not_persist_when_gemini_rejects_the_response() -> None:
    class FakeProfileRepository:
        async def get_by_account(self, _: str, __: str):
            return SimpleNamespace(
                behavior_warning_sensitivity=DEFAULT_BEHAVIOR_WARNING_SENSITIVITY.copy()
            )

        async def get_by_account_for_update(self, _: str, __: str):
            raise AssertionError("Gemini failure must not reach the persistence path.")

    class FakeGeminiClient:
        async def recommend(self, _: list[dict[str, object]]) -> dict[str, int]:
            raise GeminiProviderError("invalid response")

    service = ProfileService.__new__(ProfileService)
    service.profile_repository = FakeProfileRepository()
    service.gemini_client = FakeGeminiClient()

    with pytest.raises(AppException) as exc_info:
        await service.update_behavior_warning_sensitivity_from_drive_summary(
            SimpleNamespace(id="account-id"),
            "profile-id",
            DriveSummaryRequest(telemetryEvents=telemetry_events()),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "GEMINI_BEHAVIOR_SENSITIVITY_FAILED"


@pytest.mark.asyncio
async def test_drive_summary_does_not_overwrite_a_manual_update_during_gemini_inference() -> None:
    initial_sensitivity = DEFAULT_BEHAVIOR_WARNING_SENSITIVITY.copy()
    profile = SimpleNamespace(behavior_warning_sensitivity=initial_sensitivity)

    class FakeProfileRepository:
        async def get_by_account(self, _: str, __: str):
            return profile

        async def get_by_account_for_update_current(self, _: str, __: str):
            return profile

    class FakeSession:
        commits = 0

        async def flush(self) -> None:
            return None

        async def refresh(self, _: object) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            return None

    class FakeGeminiClient:
        async def recommend(self, _: list[dict[str, object]]) -> dict[str, int]:
            profile.behavior_warning_sensitivity = {
                **initial_sensitivity,
                "DROWSINESS": 5,
            }
            return {**initial_sensitivity, "DROWSINESS": 6}

    service = ProfileService.__new__(ProfileService)
    service.session = FakeSession()
    service.profile_repository = FakeProfileRepository()
    service.gemini_client = FakeGeminiClient()

    with pytest.raises(AppException) as exc_info:
        await service.update_behavior_warning_sensitivity_from_drive_summary(
            SimpleNamespace(id="account-id"),
            "profile-id",
            DriveSummaryRequest(telemetryEvents=telemetry_events()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "BEHAVIOR_SENSITIVITY_UPDATE_CONFLICT"
    assert profile.behavior_warning_sensitivity["DROWSINESS"] == 5
    assert service.session.commits == 0
