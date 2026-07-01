from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.core.enums import DrivingState, LocationSource
from app.core.time import utc_now_for_api_response


@dataclass(slots=True)
class SessionRuntime:
    session_id: str
    connected_at: datetime
    last_message_at: datetime
    last_heartbeat_at: datetime
    current_latitude: float | None = None
    current_longitude: float | None = None
    current_speed_kph: float | None = None
    current_accuracy_meters: float | None = None
    current_location_source: LocationSource | None = None
    driving_state: DrivingState = DrivingState.UNKNOWN
    last_location_occurred_at: datetime | None = None
    last_location_persisted_at: datetime | None = None
    last_location_persisted_monotonic: float | None = None
    active_behavior_event_id: str | None = None
    current_intervention_id: str | None = None
    active_conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocationRuntimeUpdate:
    latitude: float
    longitude: float
    speed_kph: float | None
    accuracy_meters: float | None
    source: LocationSource
    driving_state: DrivingState
    occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class LocationRuntimeSnapshot:
    session_id: str
    current_latitude: float | None
    current_longitude: float | None
    current_speed_kph: float | None
    current_accuracy_meters: float | None
    current_location_source: LocationSource | None
    driving_state: DrivingState
    last_location_occurred_at: datetime | None
    last_location_persisted_at: datetime | None
    last_location_persisted_monotonic: float | None


class LocationRuntimeApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class LocationRuntimeApplyResult:
    status: LocationRuntimeApplyStatus
    snapshot: LocationRuntimeSnapshot | None


class SessionRuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, SessionRuntime] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._runtimes)

    async def get_or_create(
        self,
        session_id: str,
        *,
        connected_at: datetime | None = None,
    ) -> SessionRuntime:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is not None:
                return runtime

            now = connected_at or utc_now_for_api_response()
            runtime = SessionRuntime(
                session_id=session_id,
                connected_at=now,
                last_message_at=now,
                last_heartbeat_at=now,
            )
            self._runtimes[session_id] = runtime
            return runtime

    async def get(self, session_id: str) -> SessionRuntime | None:
        async with self._lock:
            return self._runtimes.get(session_id)

    async def touch_message(self, session_id: str, occurred_at: datetime) -> SessionRuntime | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_message_at = occurred_at
            return runtime

    async def touch_heartbeat(
        self,
        session_id: str,
        occurred_at: datetime,
    ) -> SessionRuntime | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_message_at = occurred_at
            runtime.last_heartbeat_at = occurred_at
            return runtime

    async def get_location_snapshot(self, session_id: str) -> LocationRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            return self._snapshot(runtime)

    async def apply_location_update(
        self,
        session_id: str,
        update: LocationRuntimeUpdate,
    ) -> LocationRuntimeApplyResult:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return LocationRuntimeApplyResult(
                    status=LocationRuntimeApplyStatus.NOT_FOUND,
                    snapshot=None,
                )

            if runtime.last_location_occurred_at is not None:
                if update.occurred_at < runtime.last_location_occurred_at:
                    return LocationRuntimeApplyResult(
                        status=LocationRuntimeApplyStatus.STALE,
                        snapshot=self._snapshot(runtime),
                    )
                if update.occurred_at == runtime.last_location_occurred_at:
                    return LocationRuntimeApplyResult(
                        status=LocationRuntimeApplyStatus.DUPLICATE,
                        snapshot=self._snapshot(runtime),
                    )

            runtime.current_latitude = update.latitude
            runtime.current_longitude = update.longitude
            runtime.current_speed_kph = update.speed_kph
            runtime.current_accuracy_meters = update.accuracy_meters
            runtime.current_location_source = update.source
            runtime.driving_state = update.driving_state
            runtime.last_location_occurred_at = update.occurred_at
            runtime.last_message_at = update.received_at
            return LocationRuntimeApplyResult(
                status=LocationRuntimeApplyStatus.APPLIED,
                snapshot=self._snapshot(runtime),
            )

    async def mark_location_persisted(
        self,
        session_id: str,
        *,
        occurred_at: datetime,
        monotonic_value: float,
    ) -> LocationRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_location_persisted_at = occurred_at
            runtime.last_location_persisted_monotonic = monotonic_value
            return self._snapshot(runtime)

    async def remove(self, session_id: str) -> bool:
        async with self._lock:
            return self._runtimes.pop(session_id, None) is not None

    async def clear(self) -> None:
        async with self._lock:
            self._runtimes.clear()

    @staticmethod
    def _snapshot(runtime: SessionRuntime) -> LocationRuntimeSnapshot:
        return LocationRuntimeSnapshot(
            session_id=runtime.session_id,
            current_latitude=runtime.current_latitude,
            current_longitude=runtime.current_longitude,
            current_speed_kph=runtime.current_speed_kph,
            current_accuracy_meters=runtime.current_accuracy_meters,
            current_location_source=runtime.current_location_source,
            driving_state=runtime.driving_state,
            last_location_occurred_at=runtime.last_location_occurred_at,
            last_location_persisted_at=runtime.last_location_persisted_at,
            last_location_persisted_monotonic=runtime.last_location_persisted_monotonic,
        )
