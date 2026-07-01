from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import desc, distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DrivingSessionStatus
from app.models import BehaviorEvent, DriverResponse, DrivingSession, Intervention

FINALIZED_SESSION_STATUSES = (
    DrivingSessionStatus.COMPLETED.value,
    DrivingSessionStatus.ABORTED.value,
)


@dataclass(frozen=True)
class SessionOverviewAggregate:
    total_sessions: int
    total_driving_seconds: int
    total_distance_meters: int
    average_safety_score: Decimal | None


@dataclass(frozen=True)
class InterventionAggregate:
    intervention_count: int
    corrected_intervention_count: int
    average_response_latency_ms: Decimal | None


@dataclass(frozen=True)
class DailySafetyScoreAggregate:
    score_date: date
    average_safety_score: Decimal


@dataclass(frozen=True)
class BehaviorTypeAggregate:
    behavior_type: str
    event_count: int
    total_duration_ms: int
    average_confidence: Decimal | None
    maximum_risk_level: int | None
    corrected_event_count: int


@dataclass(frozen=True)
class HourlyBehaviorAggregate:
    hour: int
    count: int


@dataclass(frozen=True)
class ReportSessionAggregate:
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    destination_name: str | None
    duration_seconds: int
    distance_meters: int
    average_speed_kph: Decimal | None
    safety_score: int | None
    behavior_event_count: int
    intervention_count: int
    corrected_behavior_count: int


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_session_overview(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> SessionOverviewAggregate:
        result = await self.session.execute(
            select(
                func.count(DrivingSession.id),
                func.coalesce(func.sum(DrivingSession.duration_seconds), 0),
                func.coalesce(func.sum(DrivingSession.distance_meters), 0),
                func.avg(DrivingSession.safety_score),
            )
            .select_from(DrivingSession)
            .where(
                *self._session_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                )
            )
        )
        row = result.one()
        return SessionOverviewAggregate(
            total_sessions=int(row[0] or 0),
            total_driving_seconds=int(row[1] or 0),
            total_distance_meters=int(row[2] or 0),
            average_safety_score=row[3],
        )

    async def get_average_safety_score(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> Decimal | None:
        return await self.session.scalar(
            select(func.avg(DrivingSession.safety_score))
            .select_from(DrivingSession)
            .where(
                *self._session_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                ),
                DrivingSession.safety_score.is_not(None),
            )
        )

    async def count_events_by_behavior(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> dict[str, int]:
        result = await self.session.execute(
            select(BehaviorEvent.behavior_type, func.count(BehaviorEvent.id))
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                )
            )
            .group_by(BehaviorEvent.behavior_type)
        )
        return {str(row[0]): int(row[1] or 0) for row in result.all()}

    async def count_events_by_risk_level(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> dict[int, int]:
        result = await self.session.execute(
            select(BehaviorEvent.risk_level, func.count(BehaviorEvent.id))
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                )
            )
            .group_by(BehaviorEvent.risk_level)
        )
        return {int(row[0]): int(row[1] or 0) for row in result.all()}

    async def get_intervention_aggregate(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> InterventionAggregate:
        event_ids = self._event_ids_select(
            profile_id=profile_id,
            utc_start=utc_start,
            utc_end_exclusive=utc_end_exclusive,
            behavior_types=behavior_types,
        )
        intervention_count = (
            select(func.count(Intervention.id))
            .select_from(Intervention)
            .where(Intervention.behavior_event_id.in_(event_ids))
            .scalar_subquery()
        )
        corrected_count = (
            select(func.count(distinct(Intervention.id)))
            .select_from(Intervention)
            .join(DriverResponse, DriverResponse.intervention_id == Intervention.id)
            .where(
                Intervention.behavior_event_id.in_(event_ids),
                DriverResponse.behavior_corrected.is_(True),
            )
            .scalar_subquery()
        )
        average_latency = (
            select(func.avg(DriverResponse.response_latency_ms))
            .select_from(DriverResponse)
            .join(Intervention, DriverResponse.intervention_id == Intervention.id)
            .where(
                Intervention.behavior_event_id.in_(event_ids),
                DriverResponse.response_latency_ms.is_not(None),
            )
            .scalar_subquery()
        )
        row = (
            await self.session.execute(
                select(intervention_count, corrected_count, average_latency)
            )
        ).one()
        return InterventionAggregate(
            intervention_count=int(row[0] or 0),
            corrected_intervention_count=int(row[1] or 0),
            average_response_latency_ms=row[2],
        )

    async def list_daily_safety_scores(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> list[DailySafetyScoreAggregate]:
        seoul_started_date = func.date(
            func.date_add(DrivingSession.started_at, text("INTERVAL 9 HOUR"))
        )
        result = await self.session.execute(
            select(seoul_started_date.label("score_date"), func.avg(DrivingSession.safety_score))
            .select_from(DrivingSession)
            .where(
                *self._session_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                ),
                DrivingSession.safety_score.is_not(None),
            )
            .group_by(seoul_started_date)
            .order_by(seoul_started_date)
        )
        return [
            DailySafetyScoreAggregate(
                score_date=self._to_date(row[0]),
                average_safety_score=row[1],
            )
            for row in result.all()
        ]

    async def count_phone_use_events(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> int:
        count = await self.session.scalar(
            select(func.count(BehaviorEvent.id))
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=["PHONE_USE"],
                )
            )
        )
        return int(count or 0)

    async def list_behavior_type_aggregates(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> dict[str, BehaviorTypeAggregate]:
        event_stats = await self.session.execute(
            select(
                BehaviorEvent.behavior_type,
                func.count(BehaviorEvent.id),
                func.coalesce(func.sum(func.coalesce(BehaviorEvent.duration_ms, 0)), 0),
                func.avg(BehaviorEvent.average_confidence),
                func.max(BehaviorEvent.risk_level),
            )
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                )
            )
            .group_by(BehaviorEvent.behavior_type)
        )
        corrected_event_stats = await self.session.execute(
            select(BehaviorEvent.behavior_type, func.count(distinct(BehaviorEvent.id)))
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .join(Intervention, Intervention.behavior_event_id == BehaviorEvent.id)
            .join(DriverResponse, DriverResponse.intervention_id == Intervention.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                ),
                DriverResponse.behavior_corrected.is_(True),
            )
            .group_by(BehaviorEvent.behavior_type)
        )
        corrected_by_type = {
            str(row[0]): int(row[1] or 0) for row in corrected_event_stats.all()
        }
        aggregates: dict[str, BehaviorTypeAggregate] = {}
        for row in event_stats.all():
            behavior_type = str(row[0])
            aggregates[behavior_type] = BehaviorTypeAggregate(
                behavior_type=behavior_type,
                event_count=int(row[1] or 0),
                total_duration_ms=int(row[2] or 0),
                average_confidence=row[3],
                maximum_risk_level=None if row[4] is None else int(row[4]),
                corrected_event_count=corrected_by_type.get(behavior_type, 0),
            )
        return aggregates

    async def list_hourly_behavior_counts(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> list[HourlyBehaviorAggregate]:
        seoul_started_hour = func.hour(
            func.date_add(BehaviorEvent.started_at, text("INTERVAL 9 HOUR"))
        )
        result = await self.session.execute(
            select(seoul_started_hour.label("hour"), func.count(BehaviorEvent.id))
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                )
            )
            .group_by(seoul_started_hour)
            .order_by(seoul_started_hour)
        )
        return [
            HourlyBehaviorAggregate(hour=int(row[0]), count=int(row[1] or 0))
            for row in result.all()
        ]

    async def count_report_sessions(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> int:
        count = await self.session.scalar(
            select(func.count(DrivingSession.id))
            .select_from(DrivingSession)
            .where(
                *self._session_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                )
            )
        )
        return int(count or 0)

    async def list_report_sessions(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        page: int,
        size: int,
    ) -> list[ReportSessionAggregate]:
        offset = (page - 1) * size
        behavior_counts = (
            select(
                BehaviorEvent.session_id.label("session_id"),
                func.count(BehaviorEvent.id).label("behavior_event_count"),
            )
            .group_by(BehaviorEvent.session_id)
            .subquery()
        )
        intervention_counts = (
            select(
                BehaviorEvent.session_id.label("session_id"),
                func.count(Intervention.id).label("intervention_count"),
            )
            .select_from(Intervention)
            .join(BehaviorEvent, Intervention.behavior_event_id == BehaviorEvent.id)
            .group_by(BehaviorEvent.session_id)
            .subquery()
        )
        corrected_counts = (
            select(
                BehaviorEvent.session_id.label("session_id"),
                func.count(distinct(Intervention.id)).label("corrected_behavior_count"),
            )
            .select_from(Intervention)
            .join(BehaviorEvent, Intervention.behavior_event_id == BehaviorEvent.id)
            .join(DriverResponse, DriverResponse.intervention_id == Intervention.id)
            .where(DriverResponse.behavior_corrected.is_(True))
            .group_by(BehaviorEvent.session_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                DrivingSession.id,
                DrivingSession.started_at,
                DrivingSession.ended_at,
                DrivingSession.destination_name,
                DrivingSession.duration_seconds,
                DrivingSession.distance_meters,
                DrivingSession.average_speed_kph,
                DrivingSession.safety_score,
                func.coalesce(behavior_counts.c.behavior_event_count, 0),
                func.coalesce(intervention_counts.c.intervention_count, 0),
                func.coalesce(corrected_counts.c.corrected_behavior_count, 0),
            )
            .select_from(DrivingSession)
            .outerjoin(behavior_counts, behavior_counts.c.session_id == DrivingSession.id)
            .outerjoin(intervention_counts, intervention_counts.c.session_id == DrivingSession.id)
            .outerjoin(corrected_counts, corrected_counts.c.session_id == DrivingSession.id)
            .where(
                *self._session_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                )
            )
            .order_by(desc(DrivingSession.started_at), desc(DrivingSession.id))
            .offset(offset)
            .limit(size)
        )
        return [
            ReportSessionAggregate(
                session_id=str(row[0]),
                started_at=row[1],
                ended_at=row[2],
                destination_name=row[3],
                duration_seconds=int(row[4] or 0),
                distance_meters=int(row[5] or 0),
                average_speed_kph=row[6],
                safety_score=row[7],
                behavior_event_count=int(row[8] or 0),
                intervention_count=int(row[9] or 0),
                corrected_behavior_count=int(row[10] or 0),
            )
            for row in result.all()
        ]

    def _event_ids_select(
        self,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ):
        return (
            select(BehaviorEvent.id)
            .select_from(BehaviorEvent)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .where(
                *self._event_conditions(
                    profile_id=profile_id,
                    utc_start=utc_start,
                    utc_end_exclusive=utc_end_exclusive,
                    behavior_types=behavior_types,
                )
            )
        )

    @staticmethod
    def _session_conditions(
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
    ) -> list[object]:
        return [
            DrivingSession.profile_id == profile_id,
            DrivingSession.status.in_(FINALIZED_SESSION_STATUSES),
            DrivingSession.started_at >= utc_start,
            DrivingSession.started_at < utc_end_exclusive,
        ]

    @classmethod
    def _event_conditions(
        cls,
        *,
        profile_id: str,
        utc_start: datetime,
        utc_end_exclusive: datetime,
        behavior_types: list[str],
    ) -> list[object]:
        return [
            *cls._session_conditions(
                profile_id=profile_id,
                utc_start=utc_start,
                utc_end_exclusive=utc_end_exclusive,
            ),
            BehaviorEvent.behavior_type.in_(behavior_types),
        ]

    @staticmethod
    def _to_date(value: object) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return date.fromisoformat(str(value))
