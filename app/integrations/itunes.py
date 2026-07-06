from typing import Any

import httpx

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


class ItunesSearchClient:
    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def search_tracks(self, term: str, limit: int) -> object:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(
                ITUNES_SEARCH_URL,
                params={
                    "term": term,
                    "media": "music",
                    "entity": "song",
                    "country": "KR",
                    "explicit": "No",
                    "limit": limit,
                },
            )
            response.raise_for_status()
            return response.json()


def as_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
