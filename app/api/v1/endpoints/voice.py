import logging

import httpx
from fastapi import APIRouter, Response, status

from app.api.dependencies import AppSettings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.schemas.voice import VoiceTtsRequest
from app.services.voice_service import (
    ClovaVoiceNotConfiguredError,
    ClovaVoiceProviderError,
    VoiceService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/tts")
async def synthesize_voice(
    payload: VoiceTtsRequest,
    settings: AppSettings,
) -> Response:
    service = VoiceService(settings=settings)

    try:
        speech = await service.synthesize(payload)
    except ClovaVoiceNotConfiguredError as exc:
        raise AppException(
            "CLOVA Voice API 키가 설정되어 있지 않습니다.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=ErrorCode.VOICE_TTS_NOT_CONFIGURED,
        ) from exc
    except (ClovaVoiceProviderError, httpx.HTTPError) as exc:
        logger.warning("CLOVA Voice TTS request failed", exc_info=exc)
        raise AppException(
            "CLOVA Voice 음성 합성에 실패했습니다.",
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code=ErrorCode.VOICE_TTS_FAILED,
        ) from exc

    return Response(
        content=speech.content,
        media_type=speech.content_type,
        headers={"Cache-Control": "no-store"},
    )
