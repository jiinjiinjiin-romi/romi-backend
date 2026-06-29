from datetime import UTC, datetime


def utc_now_for_api_response() -> datetime:
    return datetime.now(UTC)


def utc_now_for_mysql_datetime() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
