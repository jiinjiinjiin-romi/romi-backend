from datetime import date, datetime

import pytest

from app.core.exceptions import AppException
from app.utils.report_period import (
    parse_report_period,
    previous_report_period,
    validate_summary_period_length,
)


def test_report_period_parses_seoul_dates_to_utc_half_open_bounds() -> None:
    period = parse_report_period("2026-06-01", "2026-06-30")

    assert period.start == date(2026, 6, 1)
    assert period.end == date(2026, 6, 30)
    assert period.utc_start == datetime(2026, 5, 31, 15, 0, 0)
    assert period.utc_end_exclusive == datetime(2026, 6, 30, 15, 0, 0)


def test_report_period_accepts_same_start_and_end_date() -> None:
    period = parse_report_period("2026-06-01", "2026-06-01")

    assert period.utc_start == datetime(2026, 5, 31, 15, 0, 0)
    assert period.utc_end_exclusive == datetime(2026, 6, 1, 15, 0, 0)


@pytest.mark.parametrize(
    ("period_start", "period_end", "message"),
    [
        (None, "2026-06-30", "리포트 조회 기간을 올바르게 입력해 주세요."),
        ("2026-06-01", None, "리포트 조회 기간을 올바르게 입력해 주세요."),
        ("2026-6-01", "2026-06-30", "리포트 조회 기간을 올바르게 입력해 주세요."),
        ("bad-date", "2026-06-30", "리포트 조회 기간을 올바르게 입력해 주세요."),
        ("2026-07-01", "2026-06-30", "리포트 시작일은 종료일보다 늦을 수 없습니다."),
    ],
)
def test_report_period_validation_errors(
    period_start: str | None,
    period_end: str | None,
    message: str,
) -> None:
    with pytest.raises(AppException) as exc_info:
        parse_report_period(period_start, period_end)

    assert exc_info.value.error_code == "INVALID_REPORT_PERIOD"
    assert exc_info.value.message == message


def test_summary_period_one_year_limit() -> None:
    validate_summary_period_length(parse_report_period("2026-01-01", "2026-12-31"))

    with pytest.raises(AppException) as exc_info:
        validate_summary_period_length(parse_report_period("2026-01-01", "2027-01-01"))

    assert exc_info.value.error_code == "REPORT_PERIOD_TOO_LONG"


def test_previous_period_uses_previous_full_month_for_calendar_month() -> None:
    previous = previous_report_period(parse_report_period("2026-06-01", "2026-06-30"))

    assert previous.start == date(2026, 5, 1)
    assert previous.end == date(2026, 5, 31)


def test_previous_period_uses_same_inclusive_day_count_for_partial_period() -> None:
    previous = previous_report_period(parse_report_period("2026-06-10", "2026-06-16"))

    assert previous.start == date(2026, 6, 3)
    assert previous.end == date(2026, 6, 9)
