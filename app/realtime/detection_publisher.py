from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.ai.driver_monitoring import DetectionResult
from app.realtime.connection_manager import ConnectionManager
from app.realtime.protocol import make_detection_update_message

logger = logging.getLogger(__name__)


class DetectionPublishStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    NOT_CURRENT_CONNECTION = "NOT_CURRENT_CONNECTION"
    SEND_FAILED = "SEND_FAILED"


@dataclass(frozen=True, slots=True)
class DetectionPublishResult:
    status: DetectionPublishStatus


class DetectionUpdatePublisher:
    def __init__(self, *, connection_manager: ConnectionManager) -> None:
        self.connection_manager = connection_manager

    async def publish(
        self,
        *,
        session_id: str,
        websocket: Any,
        result: DetectionResult,
    ) -> DetectionPublishResult:
        message = make_detection_update_message(
            session_id=session_id,
            frame_id=result.frame_id,
            behavior_type=result.behavior_type.value,
            model_action_type=result.model_action_type.value,
            model_class_code=result.model_class_code,
            model_class_label=result.model_class_label,
            confidence=result.confidence,
            model_version=result.model_version,
            captured_at=result.captured_at,
            inference_latency_ms=result.inference_latency_ms,
        )

        try:
            sent = await self.connection_manager.send_json_to_current(
                session_id,
                websocket,
                message,
            )
        except Exception:
            logger.warning(
                "Failed to publish detection update session_id=%s frame_id=%s "
                "behavior_type=%s model_action_type=%s confidence=%s latency_ms=%s "
                "model_version=%s",
                session_id,
                result.frame_id,
                result.behavior_type.value,
                result.model_action_type.value,
                result.confidence,
                result.inference_latency_ms,
                result.model_version,
                exc_info=True,
            )
            return DetectionPublishResult(status=DetectionPublishStatus.SEND_FAILED)

        if not sent:
            logger.info(
                "Skipped detection update for non-current connection session_id=%s frame_id=%s",
                session_id,
                result.frame_id,
            )
            return DetectionPublishResult(status=DetectionPublishStatus.NOT_CURRENT_CONNECTION)

        return DetectionPublishResult(status=DetectionPublishStatus.PUBLISHED)
