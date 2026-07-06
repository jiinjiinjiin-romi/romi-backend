from collections.abc import Mapping

from app.integrations.itunes import ItunesSearchClient, as_mapping

MOOD_SEARCH_TERMS = {
    "bright": "bright pop",
    "calm": "calm acoustic",
    "drive": "driving music",
    "focus": "lofi focus",
}
DEFAULT_MOOD = "drive"
DEFAULT_LIMIT = 10
MAX_LIMIT = 25


class MusicRecommendationService:
    def __init__(self, *, client: ItunesSearchClient) -> None:
        self._client = client

    async def search_recommendations(
        self,
        *,
        mood: str,
        keyword: str,
        limit: int,
    ) -> list[dict[str, object]]:
        term = get_search_term(mood=mood, keyword=keyword)
        response = await self._client.search_tracks(term, clamp_limit(limit))
        data = as_mapping(response)
        results = data.get("results")

        if not isinstance(results, list):
            return []

        return [
            track
            for item in results
            if (track := normalize_itunes_track(item)) is not None
        ]


def get_search_term(*, mood: str, keyword: str) -> str:
    trimmed_keyword = keyword.strip()
    if trimmed_keyword:
        return trimmed_keyword

    return MOOD_SEARCH_TERMS.get(mood.strip().lower(), MOOD_SEARCH_TERMS[DEFAULT_MOOD])


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def normalize_itunes_track(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None

    track_id = value.get("trackId")
    title = normalize_text(value.get("trackName"))
    artist = normalize_text(value.get("artistName"))

    if track_id is None or title is None or artist is None:
        return None

    duration_seconds = normalize_duration_seconds(value.get("trackTimeMillis"))
    return {
        "id": str(track_id),
        "title": title,
        "artist": artist,
        "album": normalize_text(value.get("collectionName")) or "Single",
        "duration": format_duration(duration_seconds),
        "durationSeconds": duration_seconds,
        "coverUrl": normalize_cover_url(value.get("artworkUrl100")),
        "sourceUrl": normalize_text(value.get("trackViewUrl")) or "",
        "provider": "itunes",
    }


def normalize_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_duration_seconds(value: object) -> int:
    if isinstance(value, bool):
        return 0

    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, milliseconds // 1000)


def format_duration(duration_seconds: int) -> str:
    minutes = duration_seconds // 60
    seconds = duration_seconds % 60
    return f"{minutes}:{seconds:02d}"


def normalize_cover_url(value: object) -> str | None:
    url = normalize_text(value)
    if url is None:
        return None

    return url.replace("100x100bb", "300x300bb")
