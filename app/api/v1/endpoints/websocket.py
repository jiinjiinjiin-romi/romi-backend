from __future__ import annotations

import inspect
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, WebSocket, status
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import get_current_account, get_settings_dependency, load_current_account
from app.api.error_handlers import ErrorResponse
from app.api.v1.endpoints.driving_sessions import get_driver_monitoring_readiness
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_api_response
from app.db.session import AsyncSessionLocal
from app.integrations.driver_monitoring import DriverMonitoringReadiness
from app.models import Account
from app.policies.driving_context_policy import DrivingContextPolicy
from app.realtime.connection_manager import ConnectionManager, ManagedConnection
from app.realtime.heartbeat import HeartbeatController
from app.realtime.protocol import (
    InvalidLocationUpdateError,
    LocationUpdateMessage,
    ProtocolError,
    WebSocketCloseCode,
    make_error_message,
    make_session_ready_message,
    parse_client_text_message,
)
from app.realtime.session_runtime import SessionRuntimeRegistry
from app.services.location_update_service import (
    LocationUpdateResultStatus,
    LocationUpdateService,
)
from app.services.websocket_session_service import WebSocketSessionService
from app.utils.uuid import normalize_uuid_string

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
DriverMonitoringReadinessDep = Annotated[
    DriverMonitoringReadiness,
    Depends(get_driver_monitoring_readiness),
]
SessionPath = Annotated[str, Path(alias="sessionId")]

PROTOCOL_ERROR_MESSAGE = "현재 지원하지 않는 WebSocket 메시지입니다."
INTERNAL_ERROR_MESSAGE = "실시간 연결 처리 중 오류가 발생했습니다."


INVALID_LOCATION_UPDATE_MESSAGE = "Location update payload is invalid."
STALE_LOCATION_UPDATE_MESSAGE = "Older location update was ignored."
LOCATION_PERSIST_FAILED_MESSAGE = "Location update could not be persisted."
SESSION_NOT_ACTIVE_MESSAGE = "Driving session is no longer active."


@router.websocket("/driving-sessions/{sessionId}")
async def connect_driving_session_websocket(
    websocket: WebSocket,
    session_id: SessionPath,
    settings: SettingsDep,
    readiness: DriverMonitoringReadinessDep,
) -> None:
    parsed_session_id = await _parse_session_id_or_deny(websocket, session_id)
    if parsed_session_id is None:
        return

    try:
        async with AsyncSessionLocal() as db_session:
            account = await _resolve_current_account(websocket, db_session, settings)
            service = WebSocketSessionService(session=db_session, readiness=readiness)
            await service.validate_connection(account=account, session_id=parsed_session_id)
    except AppException as exc:
        await _send_app_denial_response(websocket, exc)
        return

    connection_manager = _connection_manager(websocket)
    runtime_registry = _runtime_registry(websocket)
    location_update_service = _location_update_service(
        websocket=websocket,
        settings=settings,
        runtime_registry=runtime_registry,
    )
    heartbeat: HeartbeatController | None = None

    await websocket.accept()

    previous = await connection_manager.register(parsed_session_id, websocket)
    await _close_replaced_connection(previous)
    await runtime_registry.get_or_create(parsed_session_id)

    try:
        await connection_manager.send_json_to_current(
            parsed_session_id,
            websocket,
            make_session_ready_message(
                session_id=parsed_session_id,
                model_version=settings.model_version,
                policy_version=settings.policy_version,
                recommended_frame_fps=settings.ws_recommended_frame_fps,
                location_interval_ms=settings.ws_location_interval_ms,
                heartbeat_interval_ms=settings.ws_heartbeat_interval_ms,
            ),
        )

        heartbeat = HeartbeatController(
            session_id=parsed_session_id,
            websocket=websocket,
            connection_manager=connection_manager,
            runtime_registry=runtime_registry,
            interval_seconds=settings.ws_heartbeat_interval_ms / 1000,
            timeout_seconds=settings.ws_heartbeat_timeout_ms / 1000,
        )
        heartbeat.start()

        await _receive_loop(
            websocket=websocket,
            session_id=parsed_session_id,
            account_id=account.id,
            connection_manager=connection_manager,
            runtime_registry=runtime_registry,
            location_update_service=location_update_service,
        )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected WebSocket error session_id=%s", parsed_session_id)
        await _send_internal_error_and_close(
            websocket=websocket,
            session_id=parsed_session_id,
            connection_manager=connection_manager,
        )
    finally:
        if heartbeat is not None:
            await heartbeat.stop()

        removed_current = await connection_manager.disconnect(parsed_session_id, websocket)
        if removed_current:
            await runtime_registry.remove(parsed_session_id)


async def _parse_session_id_or_deny(websocket: WebSocket, session_id: str) -> str | None:
    try:
        return normalize_uuid_string(session_id)
    except ValueError:
        await _send_denial_response(
            websocket,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message="운전 세션 ID 형식이 올바르지 않습니다.",
            error_code=ErrorCode.INVALID_SESSION_ID,
        )
        return None


async def _resolve_current_account(websocket: WebSocket, db_session, settings: Settings) -> Account:
    override = websocket.app.dependency_overrides.get(get_current_account)
    if override is not None:
        result = override()
        if inspect.isawaitable(result):
            result = await result
        return result

    return await load_current_account(db_session, settings)


async def _receive_loop(
    *,
    websocket: WebSocket,
    session_id: str,
    account_id: str,
    connection_manager: ConnectionManager,
    runtime_registry: SessionRuntimeRegistry,
    location_update_service: LocationUpdateService,
) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        if message.get("bytes") is not None:
            await _send_protocol_error_and_close(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
            )
            return

        text = message.get("text")
        if text is None:
            await _send_protocol_error_and_close(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
            )
            return

        try:
            envelope = parse_client_text_message(text)
        except InvalidLocationUpdateError:
            await _send_location_error(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
                code=ErrorCode.INVALID_LOCATION_UPDATE,
                message=INVALID_LOCATION_UPDATE_MESSAGE,
                recoverable=True,
            )
            continue
        except ProtocolError:
            await _send_protocol_error_and_close(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
            )
            return

        now = utc_now_for_api_response()
        if envelope.type == "PONG":
            await runtime_registry.touch_message(session_id, now)
            await runtime_registry.touch_heartbeat(session_id, now)
            continue

        if isinstance(envelope, LocationUpdateMessage):
            result = await location_update_service.handle(
                account_id=account_id,
                session_id=session_id,
                message=envelope,
                received_at=now,
            )
            if result.status in {
                LocationUpdateResultStatus.UPDATED_ONLY,
                LocationUpdateResultStatus.PERSISTED,
                LocationUpdateResultStatus.DUPLICATE,
            }:
                continue

            if result.status == LocationUpdateResultStatus.STALE:
                await _send_location_error(
                    websocket=websocket,
                    session_id=session_id,
                    connection_manager=connection_manager,
                    code=ErrorCode.STALE_LOCATION_UPDATE,
                    message=STALE_LOCATION_UPDATE_MESSAGE,
                    recoverable=True,
                )
                continue

            if result.status == LocationUpdateResultStatus.PERSIST_FAILED:
                await _send_location_error(
                    websocket=websocket,
                    session_id=session_id,
                    connection_manager=connection_manager,
                    code=ErrorCode.LOCATION_PERSIST_FAILED,
                    message=LOCATION_PERSIST_FAILED_MESSAGE,
                    recoverable=True,
                )
                continue

            if result.status == LocationUpdateResultStatus.SESSION_NOT_ACTIVE:
                await _send_location_error(
                    websocket=websocket,
                    session_id=session_id,
                    connection_manager=connection_manager,
                    code=ErrorCode.SESSION_NOT_ACTIVE,
                    message=SESSION_NOT_ACTIVE_MESSAGE,
                    recoverable=False,
                )
                await websocket.close(
                    code=WebSocketCloseCode.POLICY_VIOLATION,
                    reason=ErrorCode.SESSION_NOT_ACTIVE.value,
                )
                return

        await _send_protocol_error_and_close(
            websocket=websocket,
            session_id=session_id,
            connection_manager=connection_manager,
        )
        return


async def _send_protocol_error_and_close(
    *,
    websocket: WebSocket,
    session_id: str,
    connection_manager: ConnectionManager,
) -> None:
    await connection_manager.send_json_to_current(
        session_id,
        websocket,
        make_error_message(
            code="WEBSOCKET_PROTOCOL_ERROR",
            message=PROTOCOL_ERROR_MESSAGE,
            recoverable=False,
        ),
    )
    await websocket.close(
        code=WebSocketCloseCode.POLICY_VIOLATION,
        reason="WEBSOCKET_PROTOCOL_ERROR",
    )


async def _send_location_error(
    *,
    websocket: WebSocket,
    session_id: str,
    connection_manager: ConnectionManager,
    code: ErrorCode,
    message: str,
    recoverable: bool,
) -> None:
    await connection_manager.send_json_to_current(
        session_id,
        websocket,
        make_error_message(
            code=code.value,
            message=message,
            recoverable=recoverable,
        ),
    )


async def _send_internal_error_and_close(
    *,
    websocket: WebSocket,
    session_id: str,
    connection_manager: ConnectionManager,
) -> None:
    try:
        await connection_manager.send_json_to_current(
            session_id,
            websocket,
            make_error_message(
                code="INTERNAL_WEBSOCKET_ERROR",
                message=INTERNAL_ERROR_MESSAGE,
                recoverable=True,
            ),
        )
    finally:
        await websocket.close(
            code=WebSocketCloseCode.INTERNAL_ERROR,
            reason="INTERNAL_WEBSOCKET_ERROR",
        )


async def _send_app_denial_response(websocket: WebSocket, exc: AppException) -> None:
    await _send_denial_response(
        websocket,
        status_code=exc.status_code,
        message=exc.message,
        error_code=exc.error_code,
    )


async def _send_denial_response(
    websocket: WebSocket,
    *,
    status_code: int,
    message: str,
    error_code: ErrorCode | str,
) -> None:
    error = error_code.value if isinstance(error_code, ErrorCode) else error_code
    payload = ErrorResponse(
        status=status_code,
        message=message,
        error=error,
    )
    await websocket.send_denial_response(
        JSONResponse(
            status_code=status_code,
            content=payload.model_dump(by_alias=True),
        )
    )


async def _close_replaced_connection(previous: ManagedConnection | None) -> None:
    if previous is None:
        return

    try:
        await previous.close(
            code=WebSocketCloseCode.SESSION_CONNECTION_REPLACED,
            reason="SESSION_CONNECTION_REPLACED",
        )
    except Exception:
        logger.exception("Failed to close replaced WebSocket connection")


def _connection_manager(websocket: WebSocket) -> ConnectionManager:
    manager = getattr(websocket.app.state, "websocket_connection_manager", None)
    if manager is None:
        manager = ConnectionManager()
        websocket.app.state.websocket_connection_manager = manager
    return manager


def _runtime_registry(websocket: WebSocket) -> SessionRuntimeRegistry:
    registry = getattr(websocket.app.state, "session_runtime_registry", None)
    if registry is None:
        registry = SessionRuntimeRegistry()
        websocket.app.state.session_runtime_registry = registry
    return registry


def _location_update_service(
    *,
    websocket: WebSocket,
    settings: Settings,
    runtime_registry: SessionRuntimeRegistry,
) -> LocationUpdateService:
    factory = getattr(websocket.app.state, "location_update_service_factory", None)
    if factory is not None:
        return factory(settings=settings, runtime_registry=runtime_registry)

    policy = DrivingContextPolicy(
        moving_speed_threshold_kph=settings.driving_moving_speed_threshold_kph,
        max_accuracy_meters=settings.driving_location_max_accuracy_meters,
    )
    return LocationUpdateService(
        runtime_registry=runtime_registry,
        policy=policy,
        persist_interval_ms=settings.ws_location_persist_interval_ms,
    )
