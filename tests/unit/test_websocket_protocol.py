from datetime import UTC, datetime

import pytest

from app.realtime.protocol import (
    InvalidLocationUpdateError,
    ProtocolError,
    make_error_message,
    make_ping_message,
    make_session_ready_message,
    parse_client_text_message,
)


def test_session_ready_message_uses_camel_case_and_utc_z() -> None:
    message = make_session_ready_message(
        session_id="67371b45-204c-4d87-b8f7-8a334229a41e",
        model_version="vit-dms-1.0.0",
        policy_version="risk-policy-1.0.0",
        recommended_frame_fps=5,
        location_interval_ms=1000,
        heartbeat_interval_ms=10000,
        occurred_at=datetime(2026, 6, 28, 3, 10, tzinfo=UTC),
    )

    assert message == {
        "type": "SESSION_READY",
        "occurredAt": "2026-06-28T03:10:00.000000Z",
        "payload": {
            "sessionId": "67371b45-204c-4d87-b8f7-8a334229a41e",
            "modelVersion": "vit-dms-1.0.0",
            "policyVersion": "risk-policy-1.0.0",
            "recommendedFrameFps": 5,
            "locationIntervalMs": 1000,
            "heartbeatIntervalMs": 10000,
        },
    }


def test_ping_message_uses_utc_z() -> None:
    message = make_ping_message(occurred_at=datetime(2026, 6, 28, 3, 10, 10, tzinfo=UTC))

    assert message == {
        "type": "PING",
        "occurredAt": "2026-06-28T03:10:10.000000Z",
        "payload": {},
    }


def test_error_message_uses_camel_case_payload() -> None:
    message = make_error_message(
        code="WEBSOCKET_PROTOCOL_ERROR",
        message="현재 지원하지 않는 WebSocket 메시지입니다.",
        recoverable=False,
        occurred_at=datetime(2026, 6, 28, 3, 15, 6, tzinfo=UTC),
    )

    assert message == {
        "type": "ERROR",
        "occurredAt": "2026-06-28T03:15:06.000000Z",
        "payload": {
            "code": "WEBSOCKET_PROTOCOL_ERROR",
            "message": "현재 지원하지 않는 WebSocket 메시지입니다.",
            "recoverable": False,
        },
    }


def test_parse_client_pong_message_normalizes_timezone_to_utc() -> None:
    envelope = parse_client_text_message(
        """
        {
          "type": "PONG",
          "occurredAt": "2026-06-28T12:10:10.100000+09:00",
          "payload": {}
        }
        """
    )

    assert envelope.type == "PONG"
    assert envelope.occurred_at == datetime(2026, 6, 28, 3, 10, 10, 100000, tzinfo=UTC)


def test_parse_location_update_message_validates_camel_case_and_normalizes_timezone() -> None:
    envelope = parse_client_text_message(
        """
        {
          "type": "LOCATION_UPDATE",
          "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
          "occurredAt": "2026-06-28T12:10:10.100000+09:00",
          "payload": {
            "latitude": 37.5501,
            "longitude": 127.0734,
            "speedKph": null,
            "accuracyMeters": null,
            "source": "GPS"
          }
        }
        """
    )

    assert envelope.type == "LOCATION_UPDATE"
    assert str(envelope.request_id) == "48dc5bde-31c7-478a-a0a0-e9e30b78899b"
    assert envelope.occurred_at == datetime(2026, 6, 28, 3, 10, 10, 100000, tzinfo=UTC)
    assert envelope.payload.latitude == 37.5501
    assert envelope.payload.longitude == 127.0734
    assert envelope.payload.speed_kph is None
    assert envelope.payload.accuracy_meters is None
    assert envelope.payload.source == "GPS"


@pytest.mark.parametrize(
    "raw_message",
    [
        "not-json",
        '{"occurredAt":"2026-06-28T03:10:10Z","payload":{}}',
        '{"type":"PONG","payload":{}}',
        '{"type":"PONG","occurredAt":"2026-06-28T03:10:10","payload":{}}',
        '{"type":"PONG","occurredAt":"2026-06-28T03:10:10Z","payload":[]}',
        '{"type":"PONG","occurredAt":"2026-06-28T03:10:10Z","payload":{},"extra":true}',
        '{"type":"UNKNOWN","occurredAt":"2026-06-28T03:10:10Z","payload":{}}',
    ],
)
def test_parse_client_message_rejects_invalid_envelopes(raw_message: str) -> None:
    with pytest.raises(ProtocolError):
        parse_client_text_message(raw_message)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 91, "longitude": 127.0734, "source": "GPS"},
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 181, "source": "GPS"},
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {
                "latitude": 37.5501,
                "longitude": 127.0734,
                "speedKph": -0.1,
                "source": "GPS",
            },
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {
                "latitude": 37.5501,
                "longitude": 127.0734,
                "accuracyMeters": -0.1,
                "source": "GPS",
            },
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 127.0734, "source": "SIMULATION"},
        },
        {
            "requestId": "not-a-uuid",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 127.0734, "source": "GPS"},
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10",
            "payload": {"latitude": 37.5501, "longitude": 127.0734, "source": "GPS"},
        },
        {
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 127.0734, "source": "GPS"},
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 127.0734},
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {
                "latitude": 37.5501,
                "longitude": 127.0734,
                "source": "GPS",
                "extra": True,
            },
        },
        {
            "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
            "occurredAt": "2026-06-28T03:10:10Z",
            "payload": {"latitude": 37.5501, "longitude": 127.0734, "source": "GPS"},
            "extra": True,
        },
    ],
)
def test_invalid_location_update_uses_recoverable_error_class(payload: dict[str, object]) -> None:
    import json

    raw_message = {"type": "LOCATION_UPDATE", **payload}

    with pytest.raises(InvalidLocationUpdateError):
        parse_client_text_message(json.dumps(raw_message))
