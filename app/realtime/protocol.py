from __future__ import annotations

import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
)

from app.core.enums import LocationSource
from app.core.time import ensure_utc_datetime, format_utc_datetime, utc_now_for_api_response
from app.schemas.base import ApiBaseModel, to_camel


class WebSocketCloseCode:
    SESSION_CONNECTION_REPLACED = 4001
    HEARTBEAT_TIMEOUT = 4008
    POLICY_VIOLATION = 1008
    INTERNAL_ERROR = 1011
    SERVICE_RESTART = 1012


class ServerMessageType(StrEnum):
    SESSION_READY = "SESSION_READY"
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"
    DETECTION_UPDATE = "DETECTION_UPDATE"


class ClientMessageType(StrEnum):
    PONG = "PONG"
    LOCATION_UPDATE = "LOCATION_UPDATE"
    FRAME_META = "FRAME_META"


class ProtocolError(Exception):
    pass


class InvalidLocationUpdateError(ProtocolError):
    pass


class InvalidFrameMetaError(ProtocolError):
    pass


class StrictApiModel(ApiBaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class SessionReadyPayload(StrictApiModel):
    session_id: str
    model_version: str
    policy_version: str
    recommended_frame_fps: int
    location_interval_ms: int
    heartbeat_interval_ms: int


class ErrorPayload(StrictApiModel):
    code: str
    message: str
    recoverable: bool


class DetectionUpdatePayload(StrictApiModel):
    session_id: str
    frame_id: str
    behavior_type: str
    model_action_type: str = Field(min_length=1)
    model_class_code: str = Field(min_length=1)
    model_class_label: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    model_version: str = Field(min_length=1)
    captured_at: datetime
    inference_latency_ms: int = Field(ge=0)

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capturedAt must include timezone information.")
        return ensure_utc_datetime(value)

    @field_serializer("captured_at")
    def serialize_captured_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class ServerEnvelope(StrictApiModel):
    type: ServerMessageType
    occurred_at: datetime
    payload: dict[str, Any]

    @field_serializer("occurred_at")
    def serialize_occurred_at(self, value: datetime) -> str:
        return format_utc_datetime(value)

    def to_message(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ClientEnvelope(StrictApiModel):
    type: ClientMessageType
    occurred_at: datetime
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurredAt must include timezone information.")
        return ensure_utc_datetime(value)


class PongMessage(ClientEnvelope):
    type: ClientMessageType = ClientMessageType.PONG


class LocationUpdatePayload(StrictApiModel):
    latitude: float
    longitude: float
    speed_kph: float | None = None
    accuracy_meters: float | None = None
    source: LocationSource

    @field_validator("latitude", mode="before")
    @classmethod
    def validate_latitude(cls, value: object) -> float:
        coordinate = _validate_finite_number(value, "latitude must be a finite number.")
        if coordinate < -90 or coordinate > 90:
            raise ValueError("latitude must be between -90 and 90.")
        return coordinate

    @field_validator("longitude", mode="before")
    @classmethod
    def validate_longitude(cls, value: object) -> float:
        coordinate = _validate_finite_number(value, "longitude must be a finite number.")
        if coordinate < -180 or coordinate > 180:
            raise ValueError("longitude must be between -180 and 180.")
        return coordinate

    @field_validator("speed_kph", "accuracy_meters", mode="before")
    @classmethod
    def validate_optional_non_negative_number(cls, value: object) -> float | None:
        if value is None:
            return None

        number = _validate_finite_number(value, "value must be a finite number.")
        if number < 0:
            raise ValueError("value must be greater than or equal to 0.")
        return number

    @field_validator("source")
    @classmethod
    def validate_gps_source(cls, value: LocationSource) -> LocationSource:
        if value != LocationSource.GPS:
            raise ValueError("LOCATION_UPDATE source must be GPS.")
        return value


class LocationUpdateMessage(ClientEnvelope):
    type: ClientMessageType = ClientMessageType.LOCATION_UPDATE
    request_id: UUID
    payload: LocationUpdatePayload


class FrameMetaPayload(StrictApiModel):
    frame_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    format: Literal["JPEG"]
    width: StrictInt = Field(ge=1)
    height: StrictInt = Field(ge=1)
    captured_at: datetime

    @field_validator("width")
    @classmethod
    def validate_max_width(cls, value: int, info: ValidationInfo) -> int:
        max_width = int((info.context or {}).get("max_width", 1920))
        if value > max_width:
            raise ValueError("width exceeds configured maximum.")
        return value

    @field_validator("height")
    @classmethod
    def validate_max_height(cls, value: int, info: ValidationInfo) -> int:
        max_height = int((info.context or {}).get("max_height", 1080))
        if value > max_height:
            raise ValueError("height exceeds configured maximum.")
        return value

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capturedAt must include timezone information.")
        return ensure_utc_datetime(value)


class FrameMetaMessage(ClientEnvelope):
    type: ClientMessageType = ClientMessageType.FRAME_META
    request_id: UUID
    payload: FrameMetaPayload


ClientMessage = PongMessage | LocationUpdateMessage | FrameMetaMessage


def parse_client_text_message(
    raw_text: str,
    *,
    max_frame_width: int = 1920,
    max_frame_height: int = 1080,
) -> ClientMessage:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Invalid JSON WebSocket message.") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("Invalid WebSocket message envelope.")

    message_type = payload.get("type")
    if message_type == ClientMessageType.LOCATION_UPDATE:
        try:
            return LocationUpdateMessage.model_validate(payload)
        except ValidationError as exc:
            raise InvalidLocationUpdateError("Invalid LOCATION_UPDATE message.") from exc

    if message_type == ClientMessageType.FRAME_META:
        try:
            return FrameMetaMessage.model_validate(
                payload,
                context={"max_width": max_frame_width, "max_height": max_frame_height},
            )
        except ValidationError as exc:
            raise InvalidFrameMetaError("Invalid FRAME_META message.") from exc

    if message_type == ClientMessageType.PONG:
        try:
            return PongMessage.model_validate(payload)
        except ValidationError as exc:
            raise ProtocolError("Invalid WebSocket PONG message.") from exc

    try:
        return ClientEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise ProtocolError("Invalid WebSocket message envelope.") from exc


def make_session_ready_message(
    *,
    session_id: str,
    model_version: str,
    policy_version: str,
    recommended_frame_fps: int,
    location_interval_ms: int,
    heartbeat_interval_ms: int,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    payload = SessionReadyPayload(
        session_id=session_id,
        model_version=model_version,
        policy_version=policy_version,
        recommended_frame_fps=recommended_frame_fps,
        location_interval_ms=location_interval_ms,
        heartbeat_interval_ms=heartbeat_interval_ms,
    )
    return _server_message(
        ServerMessageType.SESSION_READY,
        payload.model_dump(by_alias=True),
        occurred_at=occurred_at,
    )


def make_ping_message(*, occurred_at: datetime | None = None) -> dict[str, Any]:
    return _server_message(ServerMessageType.PING, {}, occurred_at=occurred_at)


def make_pong_message(*, occurred_at: datetime | None = None) -> dict[str, Any]:
    return _server_message(ServerMessageType.PONG, {}, occurred_at=occurred_at)


def make_error_message(
    *,
    code: str,
    message: str,
    recoverable: bool,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    payload = ErrorPayload(code=code, message=message, recoverable=recoverable)
    return _server_message(
        ServerMessageType.ERROR,
        payload.model_dump(by_alias=True),
        occurred_at=occurred_at,
    )


def make_detection_update_message(
    *,
    session_id: str,
    frame_id: str,
    behavior_type: str,
    model_action_type: str,
    model_class_code: str,
    model_class_label: str,
    confidence: float,
    model_version: str,
    captured_at: datetime,
    inference_latency_ms: int,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    payload = DetectionUpdatePayload(
        session_id=session_id,
        frame_id=frame_id,
        behavior_type=behavior_type,
        model_action_type=model_action_type,
        model_class_code=model_class_code,
        model_class_label=model_class_label,
        confidence=confidence,
        model_version=model_version,
        captured_at=captured_at,
        inference_latency_ms=inference_latency_ms,
    )
    return _server_message(
        ServerMessageType.DETECTION_UPDATE,
        payload.model_dump(by_alias=True, mode="json"),
        occurred_at=occurred_at,
    )


def _server_message(
    message_type: ServerMessageType,
    payload: dict[str, Any],
    *,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    envelope = ServerEnvelope(
        type=message_type,
        occurred_at=occurred_at or utc_now_for_api_response(),
        payload=payload,
    )
    return envelope.to_message()


def _validate_finite_number(value: object, message: str) -> float:
    if isinstance(value, bool):
        raise ValueError(message)

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc

    if not math.isfinite(number):
        raise ValueError(message)

    return number
