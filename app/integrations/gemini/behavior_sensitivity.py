import json
import logging
from collections.abc import Mapping, Sequence

import httpx

from app.core.config import Settings
from app.core.enums import BehaviorType

GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
logger = logging.getLogger(__name__)

BEHAVIOR_SENSITIVITY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "behaviorWarningSensitivity": {
            "type": "object",
            "properties": {
                behavior.value: {"type": "integer", "minimum": 3, "maximum": 10}
                for behavior in BehaviorType
            },
            "required": [behavior.value for behavior in BehaviorType],
            "additionalProperties": False,
            "propertyOrdering": [behavior.value for behavior in BehaviorType],
        }
    },
    "required": ["behaviorWarningSensitivity"],
    "additionalProperties": False,
    "propertyOrdering": ["behaviorWarningSensitivity"],
}


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiProviderError(RuntimeError):
    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class GeminiBehaviorSensitivityClient:
    def __init__(
        self,
        *,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def recommend(self, telemetry_events: Sequence[Mapping[str, object]]) -> dict[str, int]:
        api_key, model, prompt = self._required_settings()
        payload = {
            "systemInstruction": {"parts": [{"text": prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {"telemetryEvents": list(telemetry_events)},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "responseFormat": {
                    "text": {
                        "mimeType": "APPLICATION_JSON",
                        "schema": BEHAVIOR_SENSITIVITY_RESPONSE_SCHEMA,
                    }
                }
            },
        }

        try:
            response = await self._generate_content(
                model=model,
                api_key=api_key,
                payload=payload,
            )
            response.raise_for_status()
            response_data = response.json()
        except httpx.TimeoutException as exc:
            logger.warning(
                "Gemini behavior sensitivity request failed reason=request_timeout "
                "timeout_seconds=%s",
                self._settings.gemini_request_timeout_seconds,
            )
            raise GeminiProviderError(
                "Gemini behavior sensitivity request failed.", reason="request_timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            provider_code, provider_status = _safe_provider_error_details(exc.response)
            logger.warning(
                "Gemini behavior sensitivity request failed reason=http_status "
                "status_code=%s provider_code=%s provider_status=%s",
                exc.response.status_code,
                provider_code,
                provider_status,
            )
            raise GeminiProviderError(
                "Gemini behavior sensitivity request failed.", reason="http_status"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Gemini behavior sensitivity request failed reason=transport_error "
                "exception_type=%s",
                type(exc).__name__,
            )
            raise GeminiProviderError(
                "Gemini behavior sensitivity request failed.", reason="transport_error"
            ) from exc
        except ValueError as exc:
            logger.warning(
                "Gemini behavior sensitivity request failed reason=response_json_decode "
                "exception_type=%s",
                type(exc).__name__,
            )
            raise GeminiProviderError(
                "Gemini behavior sensitivity request failed.", reason="response_json_decode"
            ) from exc

        try:
            return parse_behavior_warning_sensitivity_response(response_data)
        except GeminiProviderError as exc:
            logger.warning(
                "Gemini behavior sensitivity response rejected reason=%s",
                exc.reason or "unknown",
            )
            raise

    def _required_settings(self) -> tuple[str, str, str]:
        api_key = self._settings.gemini_api_key.strip()
        model = self._settings.gemini_model.strip()
        prompt = self._settings.gemini_behavior_sensitivity_prompt.strip()
        missing = [
            name
            for name, value in (
                ("GEMINI_API_KEY", api_key),
                ("GEMINI_MODEL", model),
                ("GEMINI_BEHAVIOR_SENSITIVITY_PROMPT", prompt),
            )
            if not value
        ]
        if missing:
            raise GeminiNotConfiguredError(
                f"Required Gemini configuration is missing: {', '.join(missing)}."
            )
        return api_key, model, prompt

    async def _generate_content(
        self,
        *,
        model: str,
        api_key: str,
        payload: dict[str, object],
    ) -> httpx.Response:
        url = GEMINI_GENERATE_CONTENT_URL.format(model=model)
        headers = {"x-goog-api-key": api_key}
        if self._client is not None:
            return await self._client.post(url, headers=headers, json=payload)

        async with httpx.AsyncClient(
            timeout=self._settings.gemini_request_timeout_seconds
        ) as client:
            return await client.post(url, headers=headers, json=payload)


def _safe_provider_error_details(response: httpx.Response) -> tuple[int | str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return None, None

    if not isinstance(payload, Mapping):
        return None, None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None, None

    code = error.get("code")
    status = error.get("status")
    safe_code = code if isinstance(code, (int, str)) and not isinstance(code, bool) else None
    safe_status = status if isinstance(status, str) else None
    return safe_code, safe_status


def parse_behavior_warning_sensitivity_response(value: object) -> dict[str, int]:
    try:
        text = _extract_response_text(value)
        payload = json.loads(text)
    except GeminiProviderError:
        raise
    except (TypeError, ValueError) as exc:
        raise _invalid_response("json_decode") from exc

    if not isinstance(payload, dict) or set(payload) != {"behaviorWarningSensitivity"}:
        raise _invalid_response("top_level_shape")

    sensitivity = payload["behaviorWarningSensitivity"]
    if not isinstance(sensitivity, dict):
        raise _invalid_response("top_level_shape")

    expected_keys = {behavior.value for behavior in BehaviorType}
    if set(sensitivity) != expected_keys:
        raise _invalid_response("behavior_key_set")

    normalized: dict[str, int] = {}
    for behavior in BehaviorType:
        value = sensitivity[behavior.value]
        if isinstance(value, bool) or not isinstance(value, int) or not 3 <= value <= 10:
            raise _invalid_response("value_type_or_range")
        normalized[behavior.value] = value
    return normalized


def _extract_response_text(value: object) -> str:
    if not isinstance(value, Mapping):
        raise _invalid_response("candidate_missing")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise _invalid_response("candidate_missing")
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        raise _invalid_response("candidate_missing")
    content = candidate.get("content")
    if not isinstance(content, Mapping):
        raise _invalid_response("parts_missing")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise _invalid_response("parts_missing")

    texts: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise _invalid_response("parts_missing")
        text = part.get("text")
        if not isinstance(text, str):
            raise _invalid_response("parts_missing")
        texts.append(text)
    return _strip_complete_json_fence("".join(texts))


def _invalid_response(reason: str) -> GeminiProviderError:
    return GeminiProviderError(
        "Gemini returned an invalid behavior sensitivity response.",
        reason=reason,
    )


def _strip_complete_json_fence(text: str) -> str:
    prefix = "```json\n"
    suffix = "\n```"
    if text.startswith(prefix) and text.endswith(suffix):
        return text[len(prefix) : -len(suffix)]
    return text
