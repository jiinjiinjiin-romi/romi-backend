from app.services.music_recommendation_service import MusicRecommendationService


class FakeMusicClient:
    def __init__(self) -> None:
        self.searches: list[tuple[str, int]] = []

    async def search_tracks(self, term: str, limit: int) -> object:
        self.searches.append((term, limit))
        return {
            "results": [
                {
                    "trackId": 123,
                    "trackName": "Soft Focus",
                    "artistName": "Evening Route",
                    "collectionName": "Bright Pop Drive",
                    "trackTimeMillis": 188000,
                    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/Music/aa/bb/100x100bb.jpg",
                    "trackViewUrl": "https://music.apple.com/kr/album/soft-focus/123?i=123",
                },
                {
                    "trackName": "Missing Identifier",
                    "artistName": "Unknown Artist",
                },
            ]
        }


async def test_search_recommendations_maps_itunes_tracks_for_navigation_ui() -> None:
    client = FakeMusicClient()
    service = MusicRecommendationService(client=client)  # type: ignore[arg-type]

    tracks = await service.search_recommendations(mood="calm", keyword="", limit=10)

    assert client.searches == [("calm acoustic", 10)]
    assert tracks == [
        {
            "id": "123",
            "title": "Soft Focus",
            "artist": "Evening Route",
            "album": "Bright Pop Drive",
            "duration": "3:08",
            "durationSeconds": 188,
            "coverUrl": "https://is1-ssl.mzstatic.com/image/thumb/Music/aa/bb/300x300bb.jpg",
            "sourceUrl": "https://music.apple.com/kr/album/soft-focus/123?i=123",
            "provider": "itunes",
        }
    ]


async def test_search_recommendations_uses_keyword_before_mood() -> None:
    client = FakeMusicClient()
    service = MusicRecommendationService(client=client)  # type: ignore[arg-type]

    await service.search_recommendations(mood="bright", keyword="city night", limit=3)

    assert client.searches == [("city night", 3)]
