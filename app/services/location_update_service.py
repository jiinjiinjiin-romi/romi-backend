from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DrivingSessionStatus
from app.core.time import ensure_utc_datetime
from app.db.session import AsyncSessionLocal
from app.models import LocationSample
from app.policies.driving_context_policy import DrivingContextPolicy
from app.realtime.protocol import LocationUpdateMessage
from app.realtime.session_runtime import (
    LocationRuntimeApplyStatus,
    LocationRuntimeUpdate,
    SessionRuntimeRegistry,
)
from app.repositories.driving_session_repository import DrivingSessionRepository
from app.repositories.location_sample_repository import LocationSampleRepository

logger = logging.getLogger(__name__)

DECIMAL_CENT = Decimal("0.01")
LOCATION_SAMPLE_UNIQUE_CONSTRAINT = "uq_location_samples_time"

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class LocationUpdateResultStatus(StrEnum):
    UPDATED_ONLY = "UPDATED_ONLY"
    PERSISTED = "PERSISTED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    SESSION_NOT_ACTIVE = "SESSION_NOT_ACTIVE"
    PERSIST_FAILED = "PERSIST_FAILED"


@dataclass(frozen=True, slots=True)
class LocationUpdateResult:
    status: LocationUpdateResultStatus


class LocationUpdateService:
    def __init__(
        self,
        *,
        runtime_registry: SessionRuntimeRegistry,
        policy: DrivingContextPolicy,
        persist_interval_ms: int,
        session_factory: SessionFactory = AsyncSessionLocal,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.runtime_registry = runtime_registry
        self.policy = policy
        self.persist_interval_seconds = persist_interval_ms / 1000
        self.session_factory = session_factory
        self.monotonic_clock = monotonic_clock

    async def handle(
        self,
        *,
        account_id: str,
        session_id: str,
        message: LocationUpdateMessage,
        received_at: datetime,
    ) -> LocationUpdateResult:
        payload = message.payload
        driving_state = self.policy.determine_state(
            speed_kph=payload.speed_kph,
            accuracy_meters=payload.accuracy_meters,
            session_status=DrivingSessionStatus.ACTIVE.value,
        )
        apply_result = await self.runtime_registry.apply_location_update(
            session_id,
            LocationRuntimeUpdate(
                latitude=payload.latitude,
                longitude=payload.longitude,
                speed_kph=payload.speed_kph,
                accuracy_meters=payload.accuracy_meters,
                source=payload.source,
                driving_state=driving_state,
                occurred_at=message.occurred_at,
                received_at=received_at,
            ),
        )

        if apply_result.status == LocationRuntimeApplyStatus.STALE:
            return LocationUpdateResult(LocationUpdateResultStatus.STALE)
        if apply_result.status == LocationRuntimeApplyStatus.DUPLICATE:
            return LocationUpdateResult(LocationUpdateResultStatus.DUPLICATE)
        if apply_result.status == LocationRuntimeApplyStatus.NOT_FOUND:
            return LocationUpdateResult(LocationUpdateResultStatus.PERSIST_FAILED)

        snapshot = apply_result.snapshot
        if snapshot is None:
            return LocationUpdateResult(LocationUpdateResultStatus.PERSIST_FAILED)

        monotonic_now = self.monotonic_clock()
        if not self._should_persist(
            last_persisted_monotonic=snapshot.last_location_persisted_monotonic,
            monotonic_now=monotonic_now,
        ):
            return LocationUpdateResult(LocationUpdateResultStatus.UPDATED_ONLY)

        persist_status = await self._persist_location_sample(
            account_id=account_id,
            session_id=session_id,
            message=message,
            driving_state=driving_state.value,
        )
        if persist_status in {
            LocationUpdateResultStatus.PERSISTED,
            LocationUpdateResultStatus.DUPLICATE,
        }:
            persisted_monotonic = self.monotonic_clock()
            await self.runtime_registry.mark_location_persisted(
                session_id,
                occurred_at=message.occurred_at,
                monotonic_value=persisted_monotonic,
            )

        return LocationUpdateResult(persist_status)

    def _should_persist(
        self,
        *,
        last_persisted_monotonic: float | None,
        monotonic_now: float,
    ) -> bool:
        if last_persisted_monotonic is None:
            return True

        return monotonic_now - last_persisted_monotonic >= self.persist_interval_seconds

    async def _persist_location_sample(
        self,
        *,
        account_id: str,
        session_id: str,
        message: LocationUpdateMessage,
        driving_state: str,
    ) -> LocationUpdateResultStatus:
        recorded_at = self._recorded_at_for_mysql(message.occurred_at)

        async with self.session_factory() as db_session:
            try:
                driving_session_repository = DrivingSessionRepository(db_session)
                driving_session = await driving_session_repository.get_owned_by_account_for_update(
                    account_id=account_id,
                    session_id=session_id,
                )
                if (
                    driving_session is None
                    or driving_session.status != DrivingSessionStatus.ACTIVE.value
                ):
                    await db_session.rollback()
                    return LocationUpdateResultStatus.SESSION_NOT_ACTIVE

                location_repository = LocationSampleRepository(db_session)
                if await location_repository.exists_at(
                    session_id=session_id,
                    recorded_at=recorded_at,
                ):
                    await db_session.rollback()
                    return LocationUpdateResultStatus.DUPLICATE

                payload = message.payload
                location_repository.add(
                    LocationSample(
                        session_id=session_id,
                        latitude=payload.latitude,
                        longitude=payload.longitude,
                        speed_kph=self._decimal_or_none(payload.speed_kph),
                        driving_state=driving_state,
                        accuracy_meters=self._decimal_or_none(payload.accuracy_meters),
                        source=payload.source.value,
                        recorded_at=recorded_at,
                    )
                )
                await db_session.flush()
                await db_session.commit()
                return LocationUpdateResultStatus.PERSISTED
            except IntegrityError as exc:
                await db_session.rollback()
                if self._is_duplicate_location_sample(exc):
                    return LocationUpdateResultStatus.DUPLICATE

                logger.exception("Location sample integrity error session_id=%s", session_id)
                return LocationUpdateResultStatus.PERSIST_FAILED
            except SQLAlchemyError:
                await db_session.rollback()
                logger.exception("Location sample persist failed session_id=%s", session_id)
                return LocationUpdateResultStatus.PERSIST_FAILED

    @staticmethod
    def _recorded_at_for_mysql(value: datetime) -> datetime:
        return ensure_utc_datetime(value).replace(tzinfo=None)

    @staticmethod
    def _decimal_or_none(value: float | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(DECIMAL_CENT)

    @staticmethod
    def _is_duplicate_location_sample(exc: IntegrityError) -> bool:
        return LOCATION_SAMPLE_UNIQUE_CONSTRAINT in str(exc.orig)
