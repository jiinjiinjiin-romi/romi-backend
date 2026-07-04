from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BehaviorResolutionReason, BehaviorType, DrivingState
from app.core.time import ensure_utc_datetime, utc_now_for_mysql_datetime
from app.db.session import AsyncSessionLocal
from app.models import BehaviorEvent
from app.policies.sliding_window_behavior_policy import (
    BehaviorTransition,
    BehaviorTransitionType,
)
from app.realtime.session_runtime import LocationRuntimeSnapshot, SessionRuntimeRegistry
from app.repositories.behavior_event_repository import BehaviorEventRepository
from app.utils.uuid import generate_uuid4

logger = logging.getLogger(__name__)

DECIMAL_CENT = Decimal("0.01")
DECIMAL_BASIS_POINT = Decimal("0.0001")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
RepositoryFactory = Callable[[AsyncSession], BehaviorEventRepository]


class BehaviorEventWriteStatus(StrEnum):
    IGNORED = "IGNORED"
    STARTED_CREATED = "STARTED_CREATED"
    STARTED_REUSED = "STARTED_REUSED"
    CLEARED = "CLEARED"
    OPEN_EVENT_NOT_FOUND = "OPEN_EVENT_NOT_FOUND"
    RUNTIME_NOT_FOUND = "RUNTIME_NOT_FOUND"
    STALE_GENERATION = "STALE_GENERATION"
    WRITE_FAILED = "WRITE_FAILED"


@dataclass(frozen=True, slots=True)
class BehaviorEventWriteResult:
    status: BehaviorEventWriteStatus
    behavior_event_id: str | None = None
    behavior_type: BehaviorType | None = None


class BehaviorEventService:
    def __init__(
        self,
        *,
        runtime_registry: SessionRuntimeRegistry,
        session_factory: SessionFactory = AsyncSessionLocal,
        repository_factory: RepositoryFactory = BehaviorEventRepository,
    ) -> None:
        self.runtime_registry = runtime_registry
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    async def handle_transition(
        self,
        *,
        session_id: str,
        connection_generation: int,
        transition: BehaviorTransition,
        previous_active_behavior_event_id: str | None = None,
        previous_active_event_behavior_type: BehaviorType | None = None,
    ) -> BehaviorEventWriteResult:
        if transition.transition_type not in {
            BehaviorTransitionType.STARTED,
            BehaviorTransitionType.CLEARED,
        }:
            return BehaviorEventWriteResult(BehaviorEventWriteStatus.IGNORED)

        runtime_status = await self._validate_runtime_generation(
            session_id=session_id,
            connection_generation=connection_generation,
        )
        if runtime_status is not None:
            return BehaviorEventWriteResult(runtime_status)

        location_snapshot = await self.runtime_registry.get_location_snapshot(session_id)
        async with self.session_factory() as db_session:
            try:
                repository = self.repository_factory(db_session)
                result = await self._handle_transition_in_transaction(
                    repository=repository,
                    session_id=session_id,
                    transition=transition,
                    previous_active_behavior_event_id=previous_active_behavior_event_id,
                    previous_active_event_behavior_type=previous_active_event_behavior_type,
                    location_snapshot=location_snapshot,
                )
                await db_session.flush()
                await db_session.commit()
            except SQLAlchemyError:
                await db_session.rollback()
                logger.exception("Behavior event write failed session_id=%s", session_id)
                return BehaviorEventWriteResult(BehaviorEventWriteStatus.WRITE_FAILED)
            except Exception:
                await db_session.rollback()
                raise

        if (
            result.status
            in {
                BehaviorEventWriteStatus.STARTED_CREATED,
                BehaviorEventWriteStatus.STARTED_REUSED,
            }
            and result.behavior_event_id is not None
            and result.behavior_type is not None
        ):
            await self.runtime_registry.record_active_behavior_event(
                session_id,
                connection_generation=connection_generation,
                behavior_type=result.behavior_type,
                event_id=result.behavior_event_id,
            )
        elif result.status == BehaviorEventWriteStatus.CLEARED:
            await self.runtime_registry.clear_active_behavior_event(
                session_id,
                connection_generation=connection_generation,
                event_id=result.behavior_event_id,
            )

        return result

    async def _validate_runtime_generation(
        self,
        *,
        session_id: str,
        connection_generation: int,
    ) -> BehaviorEventWriteStatus | None:
        snapshot = await self.runtime_registry.get_behavior_snapshot(session_id)
        if snapshot is None:
            return BehaviorEventWriteStatus.RUNTIME_NOT_FOUND
        if snapshot.connection_generation != connection_generation:
            return BehaviorEventWriteStatus.STALE_GENERATION
        return None

    async def _handle_transition_in_transaction(
        self,
        *,
        repository: BehaviorEventRepository,
        session_id: str,
        transition: BehaviorTransition,
        previous_active_behavior_event_id: str | None,
        previous_active_event_behavior_type: BehaviorType | None,
        location_snapshot: LocationRuntimeSnapshot | None,
    ) -> BehaviorEventWriteResult:
        if transition.transition_type == BehaviorTransitionType.STARTED:
            return await self._handle_started(
                repository=repository,
                session_id=session_id,
                transition=transition,
                location_snapshot=location_snapshot,
            )
        if transition.transition_type == BehaviorTransitionType.CLEARED:
            return await self._handle_cleared(
                repository=repository,
                session_id=session_id,
                transition=transition,
                previous_active_behavior_event_id=previous_active_behavior_event_id,
                previous_active_event_behavior_type=previous_active_event_behavior_type,
            )
        return BehaviorEventWriteResult(BehaviorEventWriteStatus.IGNORED)

    async def _handle_started(
        self,
        *,
        repository: BehaviorEventRepository,
        session_id: str,
        transition: BehaviorTransition,
        location_snapshot: LocationRuntimeSnapshot | None,
    ) -> BehaviorEventWriteResult:
        behavior_type = transition.event_behavior_type
        if behavior_type is None:
            return BehaviorEventWriteResult(BehaviorEventWriteStatus.IGNORED)

        started_at = self._transition_started_at(transition)
        if started_at is None:
            return BehaviorEventWriteResult(BehaviorEventWriteStatus.IGNORED)

        active_events = await repository.list_open_by_session_for_update(session_id)
        reusable_event = next(
            (event for event in active_events if event.behavior_type == behavior_type.value),
            None,
        )
        for event in active_events:
            if reusable_event is not None and event.id == reusable_event.id:
                continue
            repository.close(
                event,
                ended_at=started_at,
                resolution_reason=BehaviorResolutionReason.BEHAVIOR_CORRECTED,
            )

        if reusable_event is not None:
            return BehaviorEventWriteResult(
                status=BehaviorEventWriteStatus.STARTED_REUSED,
                behavior_event_id=reusable_event.id,
                behavior_type=behavior_type,
            )

        event = self._build_behavior_event(
            session_id=session_id,
            behavior_type=behavior_type,
            transition=transition,
            started_at=started_at,
            location_snapshot=location_snapshot,
        )
        repository.add(event)
        return BehaviorEventWriteResult(
            status=BehaviorEventWriteStatus.STARTED_CREATED,
            behavior_event_id=event.id,
            behavior_type=behavior_type,
        )

    async def _handle_cleared(
        self,
        *,
        repository: BehaviorEventRepository,
        session_id: str,
        transition: BehaviorTransition,
        previous_active_behavior_event_id: str | None,
        previous_active_event_behavior_type: BehaviorType | None,
    ) -> BehaviorEventWriteResult:
        ended_at = self._transition_ended_at(transition)
        event = None
        if previous_active_behavior_event_id is not None:
            event = await repository.get_open_by_id_for_update(previous_active_behavior_event_id)
        if event is None and previous_active_event_behavior_type is not None:
            event = await repository.get_open_by_session_and_type_for_update(
                session_id=session_id,
                behavior_type=previous_active_event_behavior_type.value,
            )
        if event is None:
            return BehaviorEventWriteResult(
                status=BehaviorEventWriteStatus.OPEN_EVENT_NOT_FOUND,
                behavior_type=previous_active_event_behavior_type,
            )

        repository.close(
            event,
            ended_at=ended_at,
            resolution_reason=BehaviorResolutionReason.BEHAVIOR_CORRECTED,
        )
        return BehaviorEventWriteResult(
            status=BehaviorEventWriteStatus.CLEARED,
            behavior_event_id=event.id,
            behavior_type=BehaviorType(event.behavior_type),
        )

    @classmethod
    def _build_behavior_event(
        cls,
        *,
        session_id: str,
        behavior_type: BehaviorType,
        transition: BehaviorTransition,
        started_at: datetime,
        location_snapshot: LocationRuntimeSnapshot | None,
    ) -> BehaviorEvent:
        average_confidence = (
            transition.average_confidence
            if transition.average_confidence is not None
            else transition.confidence
        )
        maximum_confidence = (
            transition.maximum_confidence
            if transition.maximum_confidence is not None
            else average_confidence
        )
        if average_confidence is None or maximum_confidence is None:
            raise ValueError("STARTED behavior transition must include confidence values.")

        latitude = None
        longitude = None
        if (
            location_snapshot is not None
            and location_snapshot.current_latitude is not None
            and location_snapshot.current_longitude is not None
        ):
            latitude = location_snapshot.current_latitude
            longitude = location_snapshot.current_longitude

        driving_state = (
            DrivingState.UNKNOWN.value
            if location_snapshot is None
            else location_snapshot.driving_state.value
        )
        speed_kph = (
            None
            if location_snapshot is None
            else cls._decimal_or_none(location_snapshot.current_speed_kph, DECIMAL_CENT)
        )

        return BehaviorEvent(
            id=generate_uuid4(),
            session_id=session_id,
            behavior_type=behavior_type.value,
            started_at=started_at,
            average_confidence=cls._decimal_or_none(
                average_confidence,
                DECIMAL_BASIS_POINT,
            ),
            maximum_confidence=cls._decimal_or_none(
                maximum_confidence,
                DECIMAL_BASIS_POINT,
            ),
            driving_state=driving_state,
            speed_kph=speed_kph,
            latitude=latitude,
            longitude=longitude,
            risk_level=0,
        )

    @classmethod
    def _transition_started_at(cls, transition: BehaviorTransition) -> datetime | None:
        value = transition.started_at or transition.captured_at
        return None if value is None else cls._mysql_datetime(value)

    @classmethod
    def _transition_ended_at(cls, transition: BehaviorTransition) -> datetime:
        value = transition.captured_at or transition.last_seen_at
        if value is None:
            return utc_now_for_mysql_datetime()
        return cls._mysql_datetime(value)

    @staticmethod
    def _mysql_datetime(value: datetime) -> datetime:
        return ensure_utc_datetime(value).replace(tzinfo=None)

    @staticmethod
    def _decimal_or_none(value: float | None, quantum: Decimal) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(quantum)
