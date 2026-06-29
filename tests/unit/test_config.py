from app.core.config import Settings, parse_cors_origins


def test_parse_cors_origins_from_comma_separated_string() -> None:
    assert parse_cors_origins("http://localhost:5173, https://example.com") == [
        "http://localhost:5173",
        "https://example.com",
    ]


def test_parse_cors_origins_from_json_array_string() -> None:
    assert parse_cors_origins('["http://localhost:5173", "https://example.com"]') == [
        "http://localhost:5173",
        "https://example.com",
    ]


def test_settings_exposes_parsed_cors_origins() -> None:
    settings = Settings(cors_origins="http://localhost:5173,https://example.com")

    assert settings.cors_origin_list == ["http://localhost:5173", "https://example.com"]
