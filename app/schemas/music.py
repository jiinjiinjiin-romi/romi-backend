from typing import Literal

from pydantic import BaseModel, Field


class MusicRecommendationTrack(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    duration: str
    duration_seconds: int = Field(alias="durationSeconds")
    cover_url: str | None = Field(alias="coverUrl")
    source_url: str = Field(alias="sourceUrl")
    provider: Literal["itunes"] = "itunes"


class MusicRecommendationResponse(BaseModel):
    tracks: list[MusicRecommendationTrack]
