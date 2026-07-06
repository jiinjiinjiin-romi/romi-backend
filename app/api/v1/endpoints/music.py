import httpx
from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.integrations.itunes import ItunesSearchClient
from app.schemas.music import MusicRecommendationResponse
from app.services.music_recommendation_service import DEFAULT_LIMIT, MusicRecommendationService

router = APIRouter(prefix="/music", tags=["music"])


def get_music_recommendation_service() -> MusicRecommendationService:
    return MusicRecommendationService(client=ItunesSearchClient())


@router.get("/recommendations", response_model=MusicRecommendationResponse)
async def get_music_recommendations(
    mood: str = Query(default="drive"),
    keyword: str = Query(default=""),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=25),
) -> MusicRecommendationResponse | JSONResponse:
    service = get_music_recommendation_service()

    try:
        tracks = await service.search_recommendations(mood=mood, keyword=keyword, limit=limit)
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"message": "Music recommendation request failed.", "detail": str(exc)},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    return MusicRecommendationResponse.model_validate({"tracks": tracks})
