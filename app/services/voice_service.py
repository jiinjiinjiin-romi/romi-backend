from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.schemas.voice import VoiceTtsRequest


class ClovaVoiceNotConfiguredError(RuntimeError):
    pass


class ClovaVoiceProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SynthesizedSpeech:
    content: bytes
    content_type: str


class VoiceService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def synthesize(self, request: VoiceTtsRequest) -> SynthesizedSpeech:
        client_id = self._settings.clova_voice_client_id.strip()
        client_secret = self._settings.clova_voice_client_secret.strip()
        if not client_id or not client_secret:
            raise ClovaVoiceNotConfiguredError("CLOVA Voice credentials are not configured.")

        payload = {
            "speaker": self.resolve_speaker(request),
            "text": request.text,
            "volume": str(request.volume),
            "speed": str(request.speed),
            "pitch": str(request.pitch),
            "format": request.format,
        }
        headers = {
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = await self._post_to_clova(payload=payload, headers=headers)
        if response.status_code >= 400:
            raise ClovaVoiceProviderError(
                f"CLOVA Voice request failed with status {response.status_code}."
            )

        content_type = response.headers.get("content-type") or f"audio/{request.format}"
        return SynthesizedSpeech(content=response.content, content_type=content_type)

    def resolve_speaker(self, request: VoiceTtsRequest) -> str:
        if request.speaker_role == "assistant":
            if request.speaker_id is not None:
                return request.speaker_id
            return self._settings.clova_voice_assistant_speaker

        profile_name = (request.profile_name or "").casefold()
        if "아빠" in profile_name or "dad" in profile_name or "father" in profile_name:
            return self._settings.clova_voice_user_male_speaker

        return self._settings.clova_voice_user_female_speaker

    async def _post_to_clova(
        self,
        *,
        payload: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                self._settings.clova_voice_tts_url,
                data=payload,
                headers=headers,
            )

        async with httpx.AsyncClient(
            timeout=self._settings.clova_voice_request_timeout_seconds,
        ) as client:
            return await client.post(
                self._settings.clova_voice_tts_url,
                data=payload,
                headers=headers,
            )
