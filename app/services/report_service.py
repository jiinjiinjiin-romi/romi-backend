from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BehaviorType
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.models import Account
from app.repositories.profile_repository import ProfileRepository
from app.repositories.report_repository import (
    BehaviorTypeAggregate,
    ReportRepository,
    ReportSessionAggregate,
)
from app.schemas.report import (
    BehaviorEventReportResponse,
    BehaviorTypeStatisticResponse,
    DailySafetyScoreResponse,
    HourlyBehaviorCountResponse,
    ReportComparisonResponse,
    ReportOverviewResponse,
    ReportPeriodResponse,
    ReportSessionItemResponse,
    ReportSessionPageResponse,
    ReportSummaryResponse,
)
from app.utils.report_period import (
    ReportPeriod,
    parse_report_period,
    previous_report_period,
    validate_summary_period_length,
)

logger = logging.getLogger(__name__)

DEFAULT_REPORT_SESSION_PAGE = 1
DEFAULT_REPORT_SESSION_SIZE = 20
MAX_REPORT_SESSION_SIZE = 100
CANONICAL_BEHAVIOR_TYPES = [item.value for item in BehaviorType]


class ReportService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.profile_repository = ProfileRepository(session)
        self.report_repository = ReportRepository(session)

    async def get_summary(
        self,
        account: Account,
        profile_id: str,
        *,
        period_start: str | None,
        period_end: str | None,
        behavior_types: str | None = None,
    ) -> ReportSummaryResponse:
        period = parse_report_period(period_start, period_end)
        validate_summary_period_length(period)
        selected_behavior_types = self.parse_behavior_types(behavior_types)
        comparison_period = previous_report_period(period)

        try:
            profile = await self.profile_repository.get_by_account(account.id, profile_id)
            if profile is None:
                raise self._profile_not_found()

            overview = await self.report_repository.get_session_overview(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
            )
            behavior_counts = await self.report_repository.count_events_by_behavior(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
            risk_counts = await self.report_repository.count_events_by_risk_level(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
            intervention_aggregate = await self.report_repository.get_intervention_aggregate(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
            daily_scores = await self.report_repository.list_daily_safety_scores(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
            )
            previous_average = await self.report_repository.get_average_safety_score(
                profile_id=profile.id,
                utc_start=comparison_period.utc_start,
                utc_end_exclusive=comparison_period.utc_end_exclusive,
            )
            current_phone_use = await self.report_repository.count_phone_use_events(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
            )
            previous_phone_use = await self.report_repository.count_phone_use_events(
                profile_id=profile.id,
                utc_start=comparison_period.utc_start,
                utc_end_exclusive=comparison_period.utc_end_exclusive,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Report summary query failed profile_id=%s", profile_id)
            raise self._internal_error("운전 리포트 요약을 불러오지 못했습니다.") from exc

        normalized_behavior_counts = self._zero_fill_behavior_counts(
            behavior_counts,
            selected_behavior_types,
        )
        event_count = sum(normalized_behavior_counts.values())
        current_average = self._round_float(overview.average_safety_score, 1)
        previous_average_float = self._round_float(previous_average, 1)

        return ReportSummaryResponse(
            period=self._period_response(period),
            overview=ReportOverviewResponse(
                total_sessions=overview.total_sessions,
                total_driving_seconds=overview.total_driving_seconds,
                total_distance_meters=overview.total_distance_meters,
                average_safety_score=current_average,
                behavior_event_count=event_count,
                intervention_count=intervention_aggregate.intervention_count,
                corrected_behavior_count=(
                    intervention_aggregate.corrected_intervention_count
                ),
                behavior_correction_rate=self._rate(
                    intervention_aggregate.corrected_intervention_count,
                    intervention_aggregate.intervention_count,
                ),
                average_response_latency_ms=self._round_int_or_none(
                    intervention_aggregate.average_response_latency_ms
                ),
            ),
            behavior_counts=normalized_behavior_counts,
            risk_level_counts=self._zero_fill_risk_counts(risk_counts),
            daily_safety_scores=[
                DailySafetyScoreResponse(
                    date=item.score_date,
                    score=self._round_float(item.average_safety_score, 1) or 0.0,
                )
                for item in daily_scores
            ],
            comparison=ReportComparisonResponse(
                previous_period_start=comparison_period.start,
                previous_period_end=comparison_period.end,
                previous_average_safety_score=previous_average_float,
                score_change=self._score_change(current_average, previous_average_float),
                phone_use_change_percent=self._change_percent(
                    current=current_phone_use,
                    previous=previous_phone_use,
                ),
            ),
        )

    async def get_behavior_events(
        self,
        account: Account,
        profile_id: str,
        *,
        period_start: str | None,
        period_end: str | None,
        behavior_types: str | None = None,
    ) -> BehaviorEventReportResponse:
        period = parse_report_period(period_start, period_end)
        selected_behavior_types = self.parse_behavior_types(behavior_types)

        try:
            profile = await self.profile_repository.get_by_account(account.id, profile_id)
            if profile is None:
                raise self._profile_not_found()

            aggregates = await self.report_repository.list_behavior_type_aggregates(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
            risk_counts = await self.report_repository.count_events_by_risk_level(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
            hourly_counts = await self.report_repository.list_hourly_behavior_counts(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                behavior_types=selected_behavior_types,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Behavior report query failed profile_id=%s", profile_id)
            raise self._internal_error("운전자 행동 리포트를 불러오지 못했습니다.") from exc

        statistics = [
            self._behavior_statistic_response(behavior_type, aggregates.get(behavior_type))
            for behavior_type in selected_behavior_types
        ]
        return BehaviorEventReportResponse(
            period=self._period_response(period),
            total_event_count=sum(item.event_count for item in statistics),
            statistics=statistics,
            risk_level_counts=self._zero_fill_risk_counts(risk_counts),
            hourly_counts=[
                HourlyBehaviorCountResponse(hour=item.hour, count=item.count)
                for item in hourly_counts
            ],
        )

    async def get_sessions(
        self,
        account: Account,
        profile_id: str,
        *,
        period_start: str | None,
        period_end: str | None,
        page: int = DEFAULT_REPORT_SESSION_PAGE,
        size: int = DEFAULT_REPORT_SESSION_SIZE,
    ) -> ReportSessionPageResponse:
        period = parse_report_period(period_start, period_end)
        self.validate_pagination(page, size)

        try:
            profile = await self.profile_repository.get_by_account(account.id, profile_id)
            if profile is None:
                raise self._profile_not_found()

            total = await self.report_repository.count_report_sessions(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
            )
            sessions = await self.report_repository.list_report_sessions(
                profile_id=profile.id,
                utc_start=period.utc_start,
                utc_end_exclusive=period.utc_end_exclusive,
                page=page,
                size=size,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Report sessions query failed profile_id=%s", profile_id)
            raise self._internal_error("운전 리포트 세션 목록을 불러오지 못했습니다.") from exc

        return ReportSessionPageResponse.from_items(
            items=[self._session_item_response(item) for item in sessions],
            page=page,
            size=size,
            total=total,
        )

    @staticmethod
    def parse_behavior_types(value: str | None) -> list[str]:
        if value is None:
            return CANONICAL_BEHAVIOR_TYPES.copy()

        raw_items = value.split(",")
        normalized = [item.strip() for item in raw_items]
        if any(not item for item in normalized):
            raise ReportService._invalid_behavior_type()

        requested = set(normalized)
        if not requested.issubset(set(CANONICAL_BEHAVIOR_TYPES)):
            raise ReportService._invalid_behavior_type()

        return [item for item in CANONICAL_BEHAVIOR_TYPES if item in requested]

    @staticmethod
    def validate_pagination(page: int, size: int) -> None:
        if page < 1:
            raise AppException(
                "페이지 번호는 1 이상이어야 합니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PAGE,
            )
        if size < 1 or size > MAX_REPORT_SESSION_SIZE:
            raise AppException(
                "페이지 크기는 1 이상 100 이하로 설정해야 합니다.",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                error_code=ErrorCode.INVALID_PAGE_SIZE,
            )

    @staticmethod
    def _period_response(period: ReportPeriod) -> ReportPeriodResponse:
        return ReportPeriodResponse(start=period.start, end=period.end)

    @staticmethod
    def _zero_fill_behavior_counts(
        counts: dict[str, int],
        behavior_types: list[str],
    ) -> dict[str, int]:
        return {behavior_type: counts.get(behavior_type, 0) for behavior_type in behavior_types}

    @staticmethod
    def _zero_fill_risk_counts(counts: dict[int, int]) -> dict[str, int]:
        return {str(risk_level): counts.get(risk_level, 0) for risk_level in range(4)}

    @classmethod
    def _behavior_statistic_response(
        cls,
        behavior_type: str,
        aggregate: BehaviorTypeAggregate | None,
    ) -> BehaviorTypeStatisticResponse:
        if aggregate is None:
            return BehaviorTypeStatisticResponse(
                behavior_type=behavior_type,
                event_count=0,
                total_duration_ms=0,
                average_duration_ms=None,
                average_confidence=None,
                maximum_risk_level=None,
                corrected_count=0,
                correction_rate=0.0,
            )

        return BehaviorTypeStatisticResponse(
            behavior_type=behavior_type,
            event_count=aggregate.event_count,
            total_duration_ms=aggregate.total_duration_ms,
            average_duration_ms=cls._average_duration_ms(
                aggregate.total_duration_ms,
                aggregate.event_count,
            ),
            average_confidence=cls._round_float(aggregate.average_confidence, 4),
            maximum_risk_level=aggregate.maximum_risk_level,
            corrected_count=aggregate.corrected_event_count,
            correction_rate=cls._rate(aggregate.corrected_event_count, aggregate.event_count),
        )

    @classmethod
    def _session_item_response(cls, item: ReportSessionAggregate) -> ReportSessionItemResponse:
        return ReportSessionItemResponse(
            session_id=item.session_id,
            started_at=item.started_at,
            ended_at=item.ended_at,
            destination_name=item.destination_name,
            duration_seconds=item.duration_seconds,
            distance_meters=item.distance_meters,
            average_speed_kph=None
            if item.average_speed_kph is None
            else float(item.average_speed_kph),
            safety_score=item.safety_score,
            behavior_event_count=item.behavior_event_count,
            intervention_count=item.intervention_count,
            corrected_behavior_count=item.corrected_behavior_count,
            behavior_correction_rate=cls._rate(
                item.corrected_behavior_count,
                item.intervention_count,
            ),
        )

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return ReportService._round_float(
            Decimal(numerator) / Decimal(denominator) * Decimal("100"),
            1,
        ) or 0.0

    @staticmethod
    def _change_percent(*, current: int, previous: int) -> float | None:
        if previous == 0:
            return 0.0 if current == 0 else None
        return ReportService._round_float(
            (Decimal(current) - Decimal(previous)) / Decimal(previous) * Decimal("100"),
            1,
        )

    @staticmethod
    def _score_change(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None:
            return None
        return ReportService._round_float(Decimal(str(current)) - Decimal(str(previous)), 1)

    @staticmethod
    def _average_duration_ms(total_duration_ms: int, event_count: int) -> int | None:
        if event_count == 0:
            return None
        return ReportService._round_int_or_none(
            Decimal(total_duration_ms) / Decimal(event_count)
        )

    @staticmethod
    def _round_float(value: Decimal | float | int | None, places: int) -> float | None:
        if value is None:
            return None
        exponent = Decimal("1").scaleb(-places)
        return float(Decimal(str(value)).quantize(exponent, rounding=ROUND_HALF_UP))

    @staticmethod
    def _round_int_or_none(value: Decimal | float | int | None) -> int | None:
        if value is None:
            return None
        return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _profile_not_found() -> AppException:
        return AppException(
            "운전자 프로필을 찾을 수 없습니다.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.PROFILE_NOT_FOUND,
        )

    @staticmethod
    def _invalid_behavior_type() -> AppException:
        return AppException(
            "지원하지 않는 운전자 행동 유형입니다.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=ErrorCode.INVALID_BEHAVIOR_TYPE,
        )

    @staticmethod
    def _internal_error(message: str) -> AppException:
        return AppException(
            message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        )
