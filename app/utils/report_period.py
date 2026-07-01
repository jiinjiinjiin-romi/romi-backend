from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import status

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException

REPORT_TIME_ZONE = ZoneInfo("Asia/Seoul")

INVALID_REPORT_PERIOD_MESSAGE = "리포트 조회 기간을 올바르게 입력해 주세요."
REVERSED_REPORT_PERIOD_MESSAGE = "리포트 시작일은 종료일보다 늦을 수 없습니다."
REPORT_PERIOD_TOO_LONG_MESSAGE = "리포트는 최대 1년 범위까지 조회할 수 있습니다."


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date
    utc_start: datetime
    utc_end_exclusive: datetime


def parse_report_period(period_start: str | None, period_end: str | None) -> ReportPeriod:
    start = _parse_report_date(period_start)
    end = _parse_report_date(period_end)

    if start > end:
        raise AppException(
            REVERSED_REPORT_PERIOD_MESSAGE,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_REPORT_PERIOD,
        )

    return build_report_period(start, end)


def build_report_period(start: date, end: date) -> ReportPeriod:
    return ReportPeriod(
        start=start,
        end=end,
        utc_start=_seoul_date_start_to_utc_naive(start),
        utc_end_exclusive=_seoul_date_start_to_utc_naive(end + timedelta(days=1)),
    )


def validate_summary_period_length(period: ReportPeriod) -> None:
    if period.end >= _add_one_year(period.start):
        raise AppException(
            REPORT_PERIOD_TOO_LONG_MESSAGE,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.REPORT_PERIOD_TOO_LONG,
        )


def previous_report_period(period: ReportPeriod) -> ReportPeriod:
    if _is_full_calendar_month(period.start, period.end):
        previous_end = period.start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        return build_report_period(previous_start, previous_end)

    day_count = (period.end - period.start).days + 1
    previous_end = period.start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=day_count - 1)
    return build_report_period(previous_start, previous_end)


def _parse_report_date(value: str | None) -> date:
    if value is None or len(value) != 10:
        raise _invalid_report_period()

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid_report_period() from exc

    if parsed.isoformat() != value:
        raise _invalid_report_period()
    return parsed


def _seoul_date_start_to_utc_naive(value: date) -> datetime:
    seoul_midnight = datetime.combine(value, time.min, tzinfo=REPORT_TIME_ZONE)
    return seoul_midnight.astimezone(UTC).replace(tzinfo=None)


def _is_full_calendar_month(start: date, end: date) -> bool:
    if start.day != 1:
        return False
    return end == _last_day_of_month(start)


def _last_day_of_month(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)


def _add_one_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return date(value.year + 1, 3, 1)


def _invalid_report_period() -> AppException:
    return AppException(
        INVALID_REPORT_PERIOD_MESSAGE,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        error_code=ErrorCode.INVALID_REPORT_PERIOD,
    )
