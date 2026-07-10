from typing import Literal

from pydantic import Field, field_validator

from app.core.voice import SUPPORTED_TTS_ASSISTANT_SPEAKER_IDS
from app.schemas.base import ApiRequestModel


class VoiceTtsRequest(ApiRequestModel):
    text: str = Field(min_length=1, max_length=2000)
    speaker_role: Literal["assistant", "user"] = "assistant"
    speaker_id: str | None = Field(default=None, max_length=100)
    profile_name: str | None = Field(default=None, max_length=50)
    format: Literal["mp3", "wav"] = "mp3"
    volume: int = Field(default=0, ge=-5, le=5)
    speed: int = Field(default=0, ge=-5, le=10)
    pitch: int = Field(default=0, ge=-5, le=5)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("TTS text must not be empty.")
        return text

    @field_validator("profile_name", mode="before")
    @classmethod
    def normalize_profile_name(cls, value: object) -> str | None:
        if value is None:
            return None
        profile_name = str(value).strip()
        return profile_name or None

    @field_validator("speaker_id", mode="before")
    @classmethod
    def validate_speaker_id(cls, value: object) -> str | None:
        if value is None:
            return None
        speaker_id = str(value).strip()
        if not speaker_id:
            return None
        if speaker_id not in SUPPORTED_TTS_ASSISTANT_SPEAKER_IDS:
            raise ValueError("Unsupported CLOVA Voice speaker.")
        return speaker_id
