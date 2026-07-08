from urllib.parse import parse_qs

import httpx
import pytest

from app.core.config import Settings
from app.schemas.voice import VoiceTtsRequest
from app.services.voice_service import ClovaVoiceNotConfiguredError, VoiceService


def make_settings() -> Settings:
    return Settings(
        clova_voice_client_id="client-id",
        clova_voice_client_secret="client-secret",
        clova_voice_assistant_speaker="nara",
        clova_voice_user_male_speaker="nminsang",
        clova_voice_user_female_speaker="nminseo",
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_synthesize_uses_assistant_female_speaker() -> None:
    captured_body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.content.decode()
        assert request.headers["X-NCP-APIGW-API-KEY-ID"] == "client-id"
        assert request.headers["X-NCP-APIGW-API-KEY"] == "client-secret"
        return httpx.Response(200, content=b"audio", headers={"content-type": "audio/mpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        speech = await VoiceService(settings=make_settings(), client=client).synthesize(
            VoiceTtsRequest(text="안녕하세요.", speaker_role="assistant")
        )

    form = parse_qs(captured_body)
    assert form["speaker"] == ["nara"]
    assert form["text"] == ["안녕하세요."]
    assert form["format"] == ["mp3"]
    assert speech.content == b"audio"
    assert speech.content_type == "audio/mpeg"


def test_resolve_speaker_uses_profile_specific_user_voice() -> None:
    service = VoiceService(settings=make_settings())

    dad_speaker = service.resolve_speaker(
        VoiceTtsRequest(text="괜찮아", speaker_role="user", profile_name="아빠 프로필")
    )
    mom_speaker = service.resolve_speaker(
        VoiceTtsRequest(text="괜찮아", speaker_role="user", profile_name="엄마")
    )
    jiwoo_speaker = service.resolve_speaker(
        VoiceTtsRequest(text="괜찮아", speaker_role="user", profile_name="지우")
    )
    assistant_speaker = service.resolve_speaker(
        VoiceTtsRequest(text="괜찮으세요?", speaker_role="assistant", profile_name="지우")
    )

    assert dad_speaker == "nminsang"
    assert mom_speaker == "nminseo"
    assert jiwoo_speaker == "nminseo"
    assert assistant_speaker == "nara"
    assert jiwoo_speaker != assistant_speaker


@pytest.mark.asyncio
async def test_synthesize_forwards_tts_tone_options() -> None:
    captured_body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.content.decode()
        return httpx.Response(200, content=b"audio")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await VoiceService(settings=make_settings(), client=client).synthesize(
            VoiceTtsRequest(text="크게 또박또박 안내할게요.", volume=3, speed=3, pitch=1)
        )

    form = parse_qs(captured_body)
    assert form["volume"] == ["3"]
    assert form["speed"] == ["3"]
    assert form["pitch"] == ["1"]


def test_request_accepts_documented_speed_range() -> None:
    assert VoiceTtsRequest(text="천천히 말해줘", speed=10).speed == 10


@pytest.mark.asyncio
async def test_synthesize_requires_clova_credentials() -> None:
    service = VoiceService(
        settings=Settings(
            clova_voice_client_id="",
            clova_voice_client_secret="",
            _env_file=None,
        )
    )

    with pytest.raises(ClovaVoiceNotConfiguredError):
        await service.synthesize(VoiceTtsRequest(text="안녕하세요."))
