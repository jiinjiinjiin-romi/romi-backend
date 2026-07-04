from __future__ import annotations

import inspect
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, WebSocket, status
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import (
    DriverMonitoringAdapterDep,
    get_current_account,
    get_settings_dependency,
    load_current_account,
)
from app.api.error_handlers import ErrorResponse
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_api_response
from app.db.session import AsyncSessionLocal
from app.integrations.driver_monitoring import HealthDriverMonitoringReadiness
from app.models import Account
from app.policies.driving_context_policy import DrivingContextPolicy
from app.realtime.connection_manager import ConnectionManager, ManagedConnection
from app.realtime.detection_pipeline import DetectionPipeline
from app.realtime.detection_publisher import DetectionUpdatePublisher
from app.realtime.frame_handler import FrameIngressService, FrameIngressStatus
from app.realtime.frame_pairing import FramePairingController
from app.realtime.heartbeat import HeartbeatController
from app.realtime.inference_worker import InferenceWorker
from app.realtime.protocol import (
    FrameMetaMessage,
    InvalidFrameMetaError,
    InvalidLocationUpdateError,
    LocationUpdateMessage,
    ProtocolError,
    WebSocketCloseCode,
    make_error_message,
    make_session_ready_message,
    parse_client_text_message,
)
from app.realtime.session_runtime import SessionRuntimeRegistry
from app.services.behavior_event_service import BehaviorEventService
from app.services.location_update_service import (
    LocationUpdateResultStatus,
    LocationUpdateService,
)
from app.services.websocket_session_service import WebSocketSessionService
from app.utils.uuid import normalize_uuid_string

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
SessionPath = Annotated[str, Path(alias="sessionId")]

PROTOCOL_ERROR_MESSAGE = "현재 지원하지 않는 WebSocket 메시지입니다."
INTERNAL_ERROR_MESSAGE = "실시간 연결 처리 중 오류가 발생했습니다."


INVALID_LOCATION_UPDATE_MESSAGE = "Location update payload is invalid."
STALE_LOCATION_UPDATE_MESSAGE = "Older location update was ignored."
LOCATION_PERSIST_FAILED_MESSAGE = "Location update could not be persisted."
SESSION_NOT_ACTIVE_MESSAGE = "Driving session is no longer active."
INVALID_FRAME_META_MESSAGE = "Frame metadata payload is invalid."
FRAME_BINARY_EXPECTED_MESSAGE = "FRAME_META must be followed by JPEG binary data."
FRAME_BINARY_TIMEOUT_MESSAGE = "Frame binary data was not received before timeout."
ORPHAN_FRAME_BINARY_MESSAGE = "Frame binary data was received without frame metadata."
FRAME_TOO_LARGE_MESSAGE = "Frame binary data exceeds the configured maximum size."
INVALID_JPEG_FRAME_MESSAGE = "Frame binary data is not a valid JPEG frame."
DUPLICATE_FRAME_ID_MESSAGE = "Frame ID has already been accepted."


@router.websocket("/driving-sessions/{sessionId}")
async def connect_driving_session_websocket(
    websocket: WebSocket,
    session_id: SessionPath,
    settings: SettingsDep,
    adapter: DriverMonitoringAdapterDep,
) -> None:
    parsed_session_id = await _parse_session_id_or_deny(websocket, session_id)
    if parsed_session_id is None:
        return

    try:
        async with AsyncSessionLocal() as db_session:
            account = await _resolve_current_account(websocket, db_session, settings)
            service = WebSocketSessionService(
                session=db_session,
                readiness=HealthDriverMonitoringReadiness(adapter),
            )
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
    inference_worker: InferenceWorker | None = None

    await websocket.accept()

    previous = await connection_manager.register(parsed_session_id, websocket)
    await _close_replaced_connection(previous)
    await runtime_registry.get_or_create(
        parsed_session_id,
        frame_queue_max_size=settings.ws_frame_queue_max_size,
        frame_recent_id_cache_size=settings.ws_frame_recent_id_cache_size,
    )
    connection_generation = await runtime_registry.prepare_connection(
        parsed_session_id,
        frame_queue_max_size=settings.ws_frame_queue_max_size,
        frame_recent_id_cache_size=settings.ws_frame_recent_id_cache_size,
    )
    if connection_generation is None:
        await _send_internal_error_and_close(
            websocket=websocket,
            session_id=parsed_session_id,
            connection_manager=connection_manager,
        )
        return

    frame_ingress_service = FrameIngressService(
        connection_manager=connection_manager,
        runtime_registry=runtime_registry,
        max_frame_bytes=settings.ws_max_frame_bytes,
    )
    detection_publisher = DetectionUpdatePublisher(connection_manager=connection_manager)
    behavior_event_service = _behavior_event_service(
        websocket=websocket,
        runtime_registry=runtime_registry,
    )
    detection_pipeline = DetectionPipeline(
        session_id=parsed_session_id,
        websocket=websocket,
        connection_generation=connection_generation,
        connection_manager=connection_manager,
        runtime_registry=runtime_registry,
        detection_publisher=detection_publisher,
        behavior_event_service=behavior_event_service,
    )

    async def send_frame_timeout_error(_: FrameMetaMessage) -> None:
        await _send_frame_error(
            websocket=websocket,
            session_id=parsed_session_id,
            connection_manager=connection_manager,
            code=ErrorCode.FRAME_BINARY_TIMEOUT,
            message=FRAME_BINARY_TIMEOUT_MESSAGE,
        )

    frame_pairing = FramePairingController(
        timeout_seconds=settings.ws_frame_binary_timeout_ms / 1000,
        on_timeout=send_frame_timeout_error,
    )

    try:
        inference_worker = InferenceWorker(
            session_id=parsed_session_id,
            websocket=websocket,
            connection_generation=connection_generation,
            connection_manager=connection_manager,
            runtime_registry=runtime_registry,
            adapter=adapter,
            detection_pipeline=detection_pipeline,
        )
        inference_worker.start()

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
            frame_pairing=frame_pairing,
            frame_ingress_service=frame_ingress_service,
            settings=settings,
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
        await frame_pairing.close()

        if inference_worker is not None:
            await inference_worker.stop()

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
    frame_pairing: FramePairingController,
    frame_ingress_service: FrameIngressService,
    settings: Settings,
) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        if message.get("bytes") is not None:
            frame_meta = await frame_pairing.claim_binary()
            if frame_meta is None:
                await _send_frame_error(
                    websocket=websocket,
                    session_id=session_id,
                    connection_manager=connection_manager,
                    code=ErrorCode.ORPHAN_FRAME_BINARY,
                    message=ORPHAN_FRAME_BINARY_MESSAGE,
                )
                continue

            await _handle_frame_binary(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
                frame_ingress_service=frame_ingress_service,
                frame_meta=frame_meta,
                frame_bytes=message["bytes"],
            )
            continue

        text = message.get("text")
        if text is None:
            await _send_protocol_error_and_close(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
            )
            return

        try:
            envelope = parse_client_text_message(
                text,
                max_frame_width=settings.ws_frame_max_width,
                max_frame_height=settings.ws_frame_max_height,
            )
        except InvalidLocationUpdateError:
            await frame_pairing.drop_pending()
            await _send_location_error(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
                code=ErrorCode.INVALID_LOCATION_UPDATE,
                message=INVALID_LOCATION_UPDATE_MESSAGE,
                recoverable=True,
            )
            continue
        except InvalidFrameMetaError:
            await frame_pairing.drop_pending()
            await _send_frame_error(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
                code=ErrorCode.INVALID_FRAME_META,
                message=INVALID_FRAME_META_MESSAGE,
            )
            continue
        except ProtocolError:
            await frame_pairing.drop_pending()
            await _send_protocol_error_and_close(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
            )
            return

        if await frame_pairing.has_pending():
            await frame_pairing.drop_pending()
            await _send_frame_error(
                websocket=websocket,
                session_id=session_id,
                connection_manager=connection_manager,
                code=ErrorCode.FRAME_BINARY_EXPECTED,
                message=FRAME_BINARY_EXPECTED_MESSAGE,
            )

        now = utc_now_for_api_response()
        if envelope.type == "PONG":
            await runtime_registry.touch_message(session_id, now)
            await runtime_registry.touch_heartbeat(session_id, now)
            continue

        if isinstance(envelope, FrameMetaMessage):
            await runtime_registry.touch_message(session_id, now)
            await frame_pairing.replace_pending(envelope)
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


async def _handle_frame_binary(
    *,
    websocket: WebSocket,
    session_id: str,
    connection_manager: ConnectionManager,
    frame_ingress_service: FrameIngressService,
    frame_meta: FrameMetaMessage,
    frame_bytes: bytes,
) -> None:
    result = await frame_ingress_service.handle(
        session_id=session_id,
        websocket=websocket,
        message=frame_meta,
        frame_bytes=frame_bytes,
        received_at=utc_now_for_api_response(),
    )
    if result.status == FrameIngressStatus.ACCEPTED:
        return

    if result.status == FrameIngressStatus.TOO_LARGE:
        await _send_frame_error(
            websocket=websocket,
            session_id=session_id,
            connection_manager=connection_manager,
            code=ErrorCode.FRAME_TOO_LARGE,
            message=FRAME_TOO_LARGE_MESSAGE,
        )
        return

    if result.status == FrameIngressStatus.INVALID_JPEG:
        await _send_frame_error(
            websocket=websocket,
            session_id=session_id,
            connection_manager=connection_manager,
            code=ErrorCode.INVALID_JPEG_FRAME,
            message=INVALID_JPEG_FRAME_MESSAGE,
        )
        return

    if result.status == FrameIngressStatus.DUPLICATE:
        await _send_frame_error(
            websocket=websocket,
            session_id=session_id,
            connection_manager=connection_manager,
            code=ErrorCode.DUPLICATE_FRAME_ID,
            message=DUPLICATE_FRAME_ID_MESSAGE,
        )
        return

    if result.status == FrameIngressStatus.RUNTIME_NOT_FOUND:
        await _send_internal_error_and_close(
            websocket=websocket,
            session_id=session_id,
            connection_manager=connection_manager,
        )


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


async def _send_frame_error(
    *,
    websocket: WebSocket,
    session_id: str,
    connection_manager: ConnectionManager,
    code: ErrorCode,
    message: str,
) -> None:
    await connection_manager.send_json_to_current(
        session_id,
        websocket,
        make_error_message(
            code=code.value,
            message=message,
            recoverable=True,
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


def _behavior_event_service(
    *,
    websocket: WebSocket,
    runtime_registry: SessionRuntimeRegistry,
) -> BehaviorEventService:
    factory = getattr(websocket.app.state, "behavior_event_service_factory", None)
    if factory is not None:
        return factory(runtime_registry=runtime_registry)

    return BehaviorEventService(runtime_registry=runtime_registry)
