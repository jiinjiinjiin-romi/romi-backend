from __future__ import annotations

from datetime import date, datetime

from pydantic import field_serializer

from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel


class ReportPeriodResponse(ApiBaseModel):
    start: date
    end: date


class ReportOverviewResponse(ApiBaseModel):
    total_sessions: int
    total_driving_seconds: int
    total_distance_meters: int
    average_safety_score: float | None
    behavior_event_count: int
    intervention_count: int
    corrected_behavior_count: int
    behavior_correction_rate: float
    average_response_latency_ms: int | None


class DailySafetyScoreResponse(ApiBaseModel):
    date: date
    score: float


class ReportComparisonResponse(ApiBaseModel):
    previous_period_start: date
    previous_period_end: date
    previous_average_safety_score: float | None
    score_change: float | None
    phone_use_change_percent: float | None


class ReportSummaryResponse(ApiBaseModel):
    period: ReportPeriodResponse
    overview: ReportOverviewResponse
    behavior_counts: dict[str, int]
    risk_level_counts: dict[str, int]
    daily_safety_scores: list[DailySafetyScoreResponse]
    comparison: ReportComparisonResponse


class BehaviorTypeStatisticResponse(ApiBaseModel):
    behavior_type: str
    event_count: int
    total_duration_ms: int
    average_duration_ms: int | None
    average_confidence: float | None
    maximum_risk_level: int | None
    corrected_count: int
    correction_rate: float


class HourlyBehaviorCountResponse(ApiBaseModel):
    hour: int
    count: int


class BehaviorEventReportResponse(ApiBaseModel):
    period: ReportPeriodResponse
    total_event_count: int
    statistics: list[BehaviorTypeStatisticResponse]
    risk_level_counts: dict[str, int]
    hourly_counts: list[HourlyBehaviorCountResponse]


class ReportSessionItemResponse(ApiBaseModel):
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    destination_name: str | None
    duration_seconds: int
    distance_meters: int
    average_speed_kph: float | None
    safety_score: int | None
    behavior_event_count: int
    intervention_count: int
    corrected_behavior_count: int
    behavior_correction_rate: float

    @field_serializer("started_at", "ended_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc_datetime(value)


class ReportSessionPageResponse(ApiBaseModel):
    items: list[ReportSessionItemResponse]
    page: int
    size: int
    total: int
    total_pages: int

    @classmethod
    def from_items(
        cls,
        *,
        items: list[ReportSessionItemResponse],
        page: int,
        size: int,
        total: int,
    ) -> ReportSessionPageResponse:
        total_pages = 0 if total == 0 else (total + size - 1) // size
        return cls(items=items, page=page, size=size, total=total, total_pages=total_pages)
