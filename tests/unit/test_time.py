from datetime import UTC

from app.core.time import utc_now_for_api_response, utc_now_for_mysql_datetime


def test_utc_now_for_api_response_returns_utc_aware_datetime() -> None:
    now = utc_now_for_api_response()

    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(now)


def test_utc_now_for_mysql_datetime_returns_utc_naive_datetime() -> None:
    now = utc_now_for_mysql_datetime()

    assert now.tzinfo is None
