from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.driver_monitoring import InferenceFrame
from app.ai.prediction_mapper import metadata_from_class_index
from app.ai.real_vit_adapter import RealViTAdapter
from app.core.config import get_settings
from app.core.time import utc_now_for_api_response
from app.integrations.driver_monitoring import create_driver_monitoring_adapter

router = APIRouter(tags=["model-lab"])


class SessionStartMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(pattern="^session_start$")
    session_id: str = Field(alias="sessionId", min_length=1)


class FrameMetaMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(pattern="^frame_meta$")
    session_id: str = Field(alias="sessionId", min_length=1)
    frame_id: str = Field(alias="frameId", min_length=1)
    client_sent_at: str = Field(alias="clientSentAt", min_length=1)
    content_type: str = Field(alias="contentType", pattern="^image/jpeg$")
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    frame_time_seconds: float | None = Field(default=None, alias="frameTimeSeconds", ge=0)


class SessionEndMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(pattern="^session_end$")
    session_id: str = Field(alias="sessionId", min_length=1)


@dataclass(slots=True)
class QueuedFrame:
    meta: FrameMetaMessage
    frame_bytes: bytes
    server_received_at: float


@router.websocket("/api/model/v7-fast/inference/stream")
async def model_lab_inference_stream(websocket: WebSocket) -> None:
    settings = get_settings()
    adapter = getattr(websocket.app.state, "driver_monitoring_adapter", None)
    if adapter is None:
        adapter = create_driver_monitoring_adapter(settings)
    await run_model_lab_stream(websocket, adapter, max_frame_bytes=settings.ws_max_frame_bytes)


async def run_model_lab_stream(websocket: WebSocket, adapter: Any, *, max_frame_bytes: int) -> None:
    await websocket.accept()

    session_id: str | None = None
    pending_frame: QueuedFrame | None = None
    dropped_frames = 0
    frame_available = asyncio.Event()
    queue_lock = asyncio.Lock()
    send_lock = asyncio.Lock()
    stop_event = asyncio.Event()
    websocket_close_sent = False

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def close_websocket(code: int = status.WS_1000_NORMAL_CLOSURE) -> None:
        nonlocal websocket_close_sent
        if websocket_close_sent:
            return
        websocket_close_sent = True
        try:
            await websocket.close(code=code)
        except RuntimeError as exc:
            if "Unexpected ASGI message 'websocket.close'" not in str(exc):
                raise

    async def send_error(code: str, message: str, frame_id: str | None = None) -> None:
        payload: dict[str, Any] = {"type": "error", "code": code, "message": message}
        if frame_id is not None:
            payload["frameId"] = frame_id
        await send_json(payload)

    async def process_latest_frames() -> None:
        nonlocal pending_frame
        while not stop_event.is_set():
            await frame_available.wait()
            if stop_event.is_set():
                return

            async with queue_lock:
                frame = pending_frame
                pending_frame = None
                frame_available.clear()

            if frame is None:
                continue

            try:
                result = await _infer_model_lab(adapter, session_id or "", frame)
            except Exception:
                stop_event.set()
                await send_error(
                    "inference_failed",
                    "Model WebSocket inference failed. Check backend model/runtime logs.",
                    frame.meta.frame_id,
                )
                await close_websocket(code=status.WS_1011_INTERNAL_ERROR)
                return

            await send_json({
                "type": "inference_result",
                "sessionId": session_id,
                "frameId": frame.meta.frame_id,
                "clientSentAt": frame.meta.client_sent_at,
                "serverReceivedAt": frame.server_received_at,
                "serverRespondedAt": _server_time_ms(),
                "detections": result["detections"],
                "queue": {"droppedFrames": dropped_frames},
                "telemetry": result["telemetry"],
            })

    processor_task = asyncio.create_task(process_latest_frames())
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = _parse_json_message(raw_message)
            except (JSONDecodeError, ValueError) as exc:
                await send_error("invalid_json", str(exc))
                continue

            message_type = payload.get("type")
            if message_type == "session_start":
                try:
                    session_start = SessionStartMessage.model_validate(payload)
                except ValidationError as exc:
                    await send_error("invalid_session_start", exc.errors()[0]["msg"])
                    continue

                session_id = session_start.session_id
                await send_json({
                    "type": "session_started",
                    "sessionId": session_id,
                    "serverTime": _server_time_ms(),
                    "transport": "websocket",
                    "queuePolicy": "latest_pending_only",
                    "modelProfile": "roadie-driver-monitoring",
                    "apiVersion": "v7-fast",
                    "optimizedPayload": True,
                })
                continue

            if message_type == "session_end":
                try:
                    session_end = SessionEndMessage.model_validate(payload)
                except ValidationError as exc:
                    await send_error("invalid_session_end", exc.errors()[0]["msg"])
                    continue

                stop_event.set()
                frame_available.set()
                await send_json({
                    "type": "session_ended",
                    "sessionId": session_end.session_id,
                    "serverTime": _server_time_ms(),
                    "droppedFrames": dropped_frames,
                })
                await close_websocket()
                return

            if message_type != "frame_meta":
                await send_error(
                    "unsupported_message_type",
                    f"Unsupported message type: {message_type}",
                )
                continue

            if session_id is None:
                await send_error("session_not_started", "Send session_start before frame_meta.")
                continue

            try:
                frame_meta = FrameMetaMessage.model_validate(payload)
            except ValidationError as exc:
                await send_error("invalid_frame_meta", exc.errors()[0]["msg"])
                continue

            if frame_meta.session_id != session_id:
                await send_error(
                    "session_mismatch",
                    "frame_meta sessionId does not match active session.",
                    frame_meta.frame_id,
                )
                continue

            server_received_at = _server_time_ms()
            frame_bytes = await websocket.receive_bytes()
            if not frame_bytes:
                await send_error(
                    "empty_frame",
                    "Frame binary message must not be empty.",
                    frame_meta.frame_id,
                )
                continue
            if len(frame_bytes) > max_frame_bytes:
                await send_error(
                    "frame_too_large",
                    f"Frame exceeds max_frame_bytes={max_frame_bytes}.",
                    frame_meta.frame_id,
                )
                continue

            async with queue_lock:
                if pending_frame is not None:
                    dropped_frames += 1
                    await send_json({
                        "type": "frame_dropped",
                        "sessionId": session_id,
                        "frameId": pending_frame.meta.frame_id,
                        "droppedFrames": dropped_frames,
                        "reason": "replaced_by_latest",
                    })
                pending_frame = QueuedFrame(
                    meta=frame_meta,
                    frame_bytes=frame_bytes,
                    server_received_at=server_received_at,
                )
                frame_available.set()
    except WebSocketDisconnect:
        return
    finally:
        stop_event.set()
        frame_available.set()
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass


async def _infer_model_lab(adapter: Any, session_id: str, frame: QueuedFrame) -> dict[str, Any]:
    if isinstance(adapter, RealViTAdapter):
        prediction = await adapter.predict_scores(frame.frame_bytes)
        detections = _detections_from_scores(prediction.scores)
        return {
            "detections": detections,
            "telemetry": {
                "processingFps": round(1000 / max(prediction.elapsed_ms, 1), 2),
                "inferenceMs": round(prediction.elapsed_ms, 2),
                "serverTotalMs": round(prediction.elapsed_ms, 2),
            },
        }

    timestamp = utc_now_for_api_response()
    result = await adapter.predict(
        InferenceFrame(
            session_id=session_id,
            request_id=str(uuid4()),
            frame_id=frame.meta.frame_id,
            captured_at=timestamp,
            occurred_at=timestamp,
            format="JPEG",
            width=frame.meta.width,
            height=frame.meta.height,
            jpeg_bytes=frame.frame_bytes,
            received_at=timestamp,
        )
    )
    return {
        "detections": [
            {
                "variableName": result.model_class_label,
                "classId": result.model_class_code,
                "displayName": result.model_class_label,
                "score": result.confidence,
            }
        ],
        "telemetry": {
            "processingFps": round(1000 / max(result.inference_latency_ms, 1), 2),
            "inferenceMs": result.inference_latency_ms,
            "serverTotalMs": result.inference_latency_ms,
        },
    }


def _detections_from_scores(scores: list[float]) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    for index, score in enumerate(scores):
        metadata = metadata_from_class_index(index)
        detections.append({
            "variableName": metadata.class_label,
            "classId": metadata.class_code,
            "displayName": metadata.class_label,
            "score": score,
        })
    return detections


def _server_time_ms() -> float:
    return round(time.time() * 1000, 3)


def _parse_json_message(raw_message: str) -> dict[str, Any]:
    payload = json.loads(raw_message)
    if not isinstance(payload, dict):
        raise ValueError("WebSocket text messages must be JSON objects.")
    return payload
