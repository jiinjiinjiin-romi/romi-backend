import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.enums import DrivingState
from app.policies.driving_context_policy import DrivingContextPolicy
from app.realtime.protocol import LocationUpdateMessage, parse_client_text_message
from app.realtime.session_runtime import SessionRuntimeRegistry
from app.services.location_update_service import (
    LocationUpdateResultStatus,
    LocationUpdateService,
)


class FakeMonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def make_message(
    *,
    occurred_at: datetime,
    latitude: float = 37.5501,
    longitude: float = 127.0734,
    speed_kph: float | None = 32.4,
    accuracy_meters: float | None = 8.2,
) -> LocationUpdateMessage:
    message = parse_client_text_message(
        json.dumps(
            {
                "type": "LOCATION_UPDATE",
                "requestId": str(uuid4()),
                "occurredAt": occurred_at.isoformat().replace("+00:00", "Z"),
                "payload": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "speedKph": speed_kph,
                    "accuracyMeters": accuracy_meters,
                    "source": "GPS",
                },
            }
        )
    )
    assert isinstance(message, LocationUpdateMessage)
    return message


def make_service(
    registry: SessionRuntimeRegistry,
    clock: FakeMonotonicClock,
) -> LocationUpdateService:
    return LocationUpdateService(
        runtime_registry=registry,
        policy=DrivingContextPolicy(
            moving_speed_threshold_kph=5.0,
            max_accuracy_meters=100.0,
        ),
        persist_interval_ms=5000,
        monotonic_clock=clock,
    )


@pytest.mark.asyncio
async def test_location_update_service_persists_first_update_then_uses_monotonic_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    clock = FakeMonotonicClock(100.0)
    service = make_service(registry, clock)
    persisted_at: list[datetime] = []

    async def fake_persist_location_sample(**kwargs) -> LocationUpdateResultStatus:
        persisted_at.append(kwargs["message"].occurred_at)
        return LocationUpdateResultStatus.PERSISTED

    monkeypatch.setattr(service, "_persist_location_sample", fake_persist_location_sample)

    base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    first = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time),
        received_at=base_time + timedelta(milliseconds=100),
    )
    clock.advance(1)
    second = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(
            occurred_at=base_time + timedelta(seconds=1),
            latitude=37.5502,
            speed_kph=0.0,
        ),
        received_at=base_time + timedelta(seconds=1, milliseconds=100),
    )
    clock.advance(4)
    third = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(
            occurred_at=base_time + timedelta(seconds=2),
            latitude=37.5503,
            speed_kph=None,
        ),
        received_at=base_time + timedelta(seconds=2, milliseconds=100),
    )

    snapshot = await registry.get_location_snapshot("session-1")

    assert first.status == LocationUpdateResultStatus.PERSISTED
    assert second.status == LocationUpdateResultStatus.UPDATED_ONLY
    assert third.status == LocationUpdateResultStatus.PERSISTED
    assert persisted_at == [base_time, base_time + timedelta(seconds=2)]
    assert snapshot is not None
    assert snapshot.current_latitude == 37.5503
    assert snapshot.driving_state == DrivingState.UNKNOWN
    assert snapshot.last_location_persisted_at == base_time + timedelta(seconds=2)
    assert snapshot.last_location_persisted_monotonic == 105.0


@pytest.mark.asyncio
async def test_location_update_service_uses_monotonic_not_client_time_for_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    clock = FakeMonotonicClock(200.0)
    service = make_service(registry, clock)
    persist_count = 0

    async def fake_persist_location_sample(**kwargs) -> LocationUpdateResultStatus:
        nonlocal persist_count
        persist_count += 1
        return LocationUpdateResultStatus.PERSISTED

    monkeypatch.setattr(service, "_persist_location_sample", fake_persist_location_sample)

    base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time),
        received_at=base_time,
    )
    clock.advance(1)
    result = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time + timedelta(hours=1)),
        received_at=base_time + timedelta(seconds=1),
    )

    assert result.status == LocationUpdateResultStatus.UPDATED_ONLY
    assert persist_count == 1


@pytest.mark.asyncio
async def test_location_update_service_does_not_advance_marker_on_persist_failure_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    clock = FakeMonotonicClock(300.0)
    service = make_service(registry, clock)
    statuses = [
        LocationUpdateResultStatus.PERSIST_FAILED,
        LocationUpdateResultStatus.PERSISTED,
    ]

    async def fake_persist_location_sample(**kwargs) -> LocationUpdateResultStatus:
        return statuses.pop(0)

    monkeypatch.setattr(service, "_persist_location_sample", fake_persist_location_sample)

    base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    failed = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time),
        received_at=base_time,
    )
    failed_snapshot = await registry.get_location_snapshot("session-1")
    clock.advance(1)
    retried = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time + timedelta(seconds=1)),
        received_at=base_time + timedelta(seconds=1),
    )
    retried_snapshot = await registry.get_location_snapshot("session-1")

    assert failed.status == LocationUpdateResultStatus.PERSIST_FAILED
    assert failed_snapshot is not None
    assert failed_snapshot.last_location_persisted_at is None
    assert failed_snapshot.last_location_persisted_monotonic is None
    assert retried.status == LocationUpdateResultStatus.PERSISTED
    assert retried_snapshot is not None
    assert retried_snapshot.last_location_persisted_at == base_time + timedelta(seconds=1)
    assert retried_snapshot.last_location_persisted_monotonic == 301.0
    assert statuses == []


@pytest.mark.asyncio
async def test_location_update_service_returns_stale_and_duplicate_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    clock = FakeMonotonicClock(400.0)
    service = make_service(registry, clock)
    persist_count = 0

    async def fake_persist_location_sample(**kwargs) -> LocationUpdateResultStatus:
        nonlocal persist_count
        persist_count += 1
        return LocationUpdateResultStatus.PERSISTED

    monkeypatch.setattr(service, "_persist_location_sample", fake_persist_location_sample)

    base_time = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time),
        received_at=base_time,
    )
    duplicate = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time, latitude=38.0),
        received_at=base_time + timedelta(seconds=1),
    )
    stale = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=base_time - timedelta(seconds=1), latitude=39.0),
        received_at=base_time + timedelta(seconds=2),
    )

    snapshot = await registry.get_location_snapshot("session-1")

    assert duplicate.status == LocationUpdateResultStatus.DUPLICATE
    assert stale.status == LocationUpdateResultStatus.STALE
    assert persist_count == 1
    assert snapshot is not None
    assert snapshot.current_latitude == 37.5501


@pytest.mark.asyncio
async def test_location_update_service_surfaces_session_not_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    clock = FakeMonotonicClock(500.0)
    service = make_service(registry, clock)

    async def fake_persist_location_sample(**kwargs) -> LocationUpdateResultStatus:
        return LocationUpdateResultStatus.SESSION_NOT_ACTIVE

    monkeypatch.setattr(service, "_persist_location_sample", fake_persist_location_sample)

    occurred_at = datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC)
    result = await service.handle(
        account_id="account-1",
        session_id="session-1",
        message=make_message(occurred_at=occurred_at),
        received_at=occurred_at,
    )

    assert result.status == LocationUpdateResultStatus.SESSION_NOT_ACTIVE


def test_location_update_service_normalizes_persisted_values() -> None:
    occurred_at = datetime(2026, 6, 28, 12, 10, 10, 123456, tzinfo=UTC)

    assert LocationUpdateService._recorded_at_for_mysql(occurred_at).tzinfo is None
    assert LocationUpdateService._recorded_at_for_mysql(occurred_at) == datetime(
        2026,
        6,
        28,
        12,
        10,
        10,
        123456,
    )
    assert LocationUpdateService._decimal_or_none(None) is None
    assert LocationUpdateService._decimal_or_none(32.445) == Decimal("32.44")
