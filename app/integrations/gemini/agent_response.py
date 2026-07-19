from __future__ import annotations

import json
import logging
from collections.abc import Mapping

import httpx

from app.core.config import Settings
from app.policies.agent_demo_policy import AgentReplyPlan, ToolPlan

GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
logger = logging.getLogger(__name__)

AGENT_REPLY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "text": {"type": "string"},
        "tool": {
            "type": ["object", "null"],
            "properties": {
                "toolName": {"type": "string"},
                "arguments": {"type": "object"},
                "result": {"type": ["object", "null"]},
                "confirmationRequired": {"type": "boolean"},
            },
            "required": ["toolName", "arguments", "result", "confirmationRequired"],
            "additionalProperties": False,
            "propertyOrdering": [
                "toolName",
                "arguments",
                "result",
                "confirmationRequired",
            ],
        },
    },
    "required": ["intent", "text", "tool"],
    "additionalProperties": False,
    "propertyOrdering": ["intent", "text", "tool"],
}


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiProviderError(RuntimeError):
    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class GeminiAgentResponseClient:
    def __init__(
        self,
        *,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def generate_reply(
        self,
        *,
        conversation_mode: str,
        message_text: str,
        input_type: str,
    ) -> AgentReplyPlan:
        api_key, model = self._required_settings()
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "운전 보조 Agent 응답을 JSON으로 생성하세요. "
                            "운전 안전과 사용자의 명시 요청만 처리하고, "
                            "도구 실행이 필요하면 tool에 실행 계획을 넣으세요."
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
                                {
                                    "conversationMode": conversation_mode,
                                    "inputType": input_type,
                                    "message": message_text,
                                },
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
                        "schema": AGENT_REPLY_RESPONSE_SCHEMA,
                    }
                }
            },
        }
        response_data = await self._request(model=model, api_key=api_key, payload=payload)
        return parse_agent_reply_response(response_data)

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
                "Gemini agent response request failed.",
                reason="request_timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Gemini agent response request failed reason=http_status status_code=%s",
                exc.response.status_code,
            )
            raise GeminiProviderError(
                "Gemini agent response request failed.",
                reason="http_status",
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiProviderError(
                "Gemini agent response request failed.",
                reason="transport_error",
            ) from exc
        except ValueError as exc:
            raise GeminiProviderError(
                "Gemini agent response request failed.",
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


def parse_agent_reply_response(value: object) -> AgentReplyPlan:
    try:
        payload = json.loads(_strip_complete_json_fence(_extract_response_text(value)))
    except (TypeError, ValueError, GeminiProviderError) as exc:
        raise _invalid_response("json_decode") from exc

    if not isinstance(payload, dict):
        raise _invalid_response("top_level_shape")
    intent = payload.get("intent")
    text = payload.get("text")
    tool = payload.get("tool")
    if not isinstance(intent, str) or not intent.strip():
        raise _invalid_response("intent")
    if not isinstance(text, str) or not text.strip():
        raise _invalid_response("text")
    if tool is None:
        return AgentReplyPlan(intent=intent.strip(), text=text.strip())
    if not isinstance(tool, Mapping):
        raise _invalid_response("tool")

    tool_name = tool.get("toolName")
    arguments = tool.get("arguments")
    result = tool.get("result")
    confirmation_required = tool.get("confirmationRequired")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise _invalid_response("tool_name")
    if not isinstance(arguments, dict):
        raise _invalid_response("tool_arguments")
    if result is not None and not isinstance(result, dict):
        raise _invalid_response("tool_result")
    if not isinstance(confirmation_required, bool):
        raise _invalid_response("tool_confirmation")

    return AgentReplyPlan(
        intent=intent.strip(),
        text=text.strip(),
        tool=ToolPlan(
            tool_name=tool_name.strip(),
            arguments=arguments,
            result=result,
            confirmation_required=confirmation_required,
            intent=intent.strip(),
        ),
    )


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
        "Gemini returned an invalid agent response.",
        reason=reason,
    )


def _strip_complete_json_fence(text: str) -> str:
    prefix = "```json\n"
    suffix = "\n```"
    if text.startswith(prefix) and text.endswith(suffix):
        return text[len(prefix) : -len(suffix)]
    return text
