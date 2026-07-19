from __future__ import annotations

import json
import logging
from collections.abc import Mapping

import httpx

from app.core.config import Settings

GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
logger = logging.getLogger(__name__)

REPORT_NARRATIVE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "recommendations"],
    "additionalProperties": False,
    "propertyOrdering": ["title", "summary", "recommendations"],
}


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiProviderError(RuntimeError):
    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class GeminiReportNarrativeClient:
    def __init__(
        self,
        *,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def generate(self, summary: Mapping[str, object]) -> dict[str, object]:
        api_key, model = self._required_settings()
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "주행 리포트 요약 데이터를 바탕으로 개인화된 안전 요약과 "
                            "실행 가능한 개선 제안을 JSON으로 작성하세요."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {"reportSummary": summary},
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
                        "schema": REPORT_NARRATIVE_RESPONSE_SCHEMA,
                    }
                }
            },
        }
        response_data = await self._request(model=model, api_key=api_key, payload=payload)
        return parse_report_narrative_response(response_data)

    def _required_settings(self) -> tuple[str, str]:
        api_key = self._settings.gemini_api_key.strip()
        model = self._settings.gemini_model.strip()
        missing = [
            name
            for name, value in (("GEMINI_API_KEY", api_key), ("GEMINI_MODEL", model))
            if not value
        ]
        if missing:
            raise GeminiNotConfiguredError(
                f"Required Gemini configuration is missing: {', '.join(missing)}."
            )
        return api_key, model

    async def _request(
        self,
        *,
        model: str,
        api_key: str,
        payload: dict[str, object],
    ) -> object:
        try:
            response = await self._generate_content(model=model, api_key=api_key, payload=payload)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise GeminiProviderError(
                "Gemini report narrative request failed.",
                reason="request_timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Gemini report narrative request failed reason=http_status status_code=%s",
                exc.response.status_code,
            )
            raise GeminiProviderError(
                "Gemini report narrative request failed.",
                reason="http_status",
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiProviderError(
                "Gemini report narrative request failed.",
                reason="transport_error",
            ) from exc
        except ValueError as exc:
            raise GeminiProviderError(
                "Gemini report narrative request failed.",
                reason="response_json_decode",
            ) from exc

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


def parse_report_narrative_response(value: object) -> dict[str, object]:
    try:
        payload = json.loads(_strip_complete_json_fence(_extract_response_text(value)))
    except (TypeError, ValueError, GeminiProviderError) as exc:
        raise _invalid_response("json_decode") from exc

    if not isinstance(payload, dict):
        raise _invalid_response("top_level_shape")
    title = payload.get("title")
    summary = payload.get("summary")
    recommendations = payload.get("recommendations")
    if not isinstance(title, str) or not title.strip():
        raise _invalid_response("title")
    if not isinstance(summary, str) or not summary.strip():
        raise _invalid_response("summary")
    if not isinstance(recommendations, list) or not recommendations:
        raise _invalid_response("recommendations")
    if not all(isinstance(item, str) and item.strip() for item in recommendations):
        raise _invalid_response("recommendations")
    return {
        "title": title.strip(),
        "summary": summary.strip(),
        "recommendations": [item.strip() for item in recommendations],
        "provider": "GEMINI",
        "fallback": False,
    }


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
    texts = [part.get("text") for part in parts if isinstance(part, Mapping)]
    if len(texts) != len(parts) or not all(isinstance(text, str) for text in texts):
        raise _invalid_response("parts_missing")
    return "".join(texts)


def _invalid_response(reason: str) -> GeminiProviderError:
    return GeminiProviderError(
        "Gemini returned an invalid report narrative response.",
        reason=reason,
    )


def _strip_complete_json_fence(text: str) -> str:
    prefix = "```json\n"
    suffix = "\n```"
    if text.startswith(prefix) and text.endswith(suffix):
        return text[len(prefix) : -len(suffix)]
    return text
