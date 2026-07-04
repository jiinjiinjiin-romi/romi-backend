from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.ai.driver_monitoring import DetectionResult
from app.policies.sliding_window_behavior_policy import BehaviorTransitionType
from app.realtime.connection_manager import ConnectionManager
from app.realtime.detection_publisher import DetectionPublishResult, DetectionUpdatePublisher
from app.realtime.session_runtime import (
    BehaviorRuntimeObserveResult,
    BehaviorRuntimeObserveStatus,
    SessionRuntimeRegistry,
)
from app.services.behavior_event_service import (
    BehaviorEventService,
    BehaviorEventWriteResult,
    BehaviorEventWriteStatus,
)

logger = logging.getLogger(__name__)


class DetectionPipelineStatus(StrEnum):
    PROCESSED = "PROCESSED"
    NOT_CURRENT_CONNECTION = "NOT_CURRENT_CONNECTION"
    STALE_GENERATION = "STALE_GENERATION"
    BEHAVIOR_EVALUATION_FAILED = "BEHAVIOR_EVALUATION_FAILED"


@dataclass(frozen=True, slots=True)
class DetectionPipelineResult:
    status: DetectionPipelineStatus
    detection_recorded: bool
    publish_result: DetectionPublishResult | None = None
    behavior_observe_result: BehaviorRuntimeObserveResult | None = None
    behavior_event_write_result: BehaviorEventWriteResult | None = None


class DetectionPipeline:
    def __init__(
        self,
        *,
        session_id: str,
        websocket: Any,
        connection_generation: int,
        connection_manager: ConnectionManager,
        runtime_registry: SessionRuntimeRegistry,
        detection_publisher: DetectionUpdatePublisher | None = None,
        behavior_event_service: BehaviorEventService | None = None,
    ) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.connection_generation = connection_generation
        self.connection_manager = connection_manager
        self.runtime_registry = runtime_registry
        self.detection_publisher = detection_publisher
        self.behavior_event_service = behavior_event_service

    async def handle_detection_result(self, result: DetectionResult) -> DetectionPipelineResult:
        if not await self.connection_manager.is_current(self.session_id, self.websocket):
            return DetectionPipelineResult(
                status=DetectionPipelineStatus.NOT_CURRENT_CONNECTION,
                detection_recorded=False,
            )

        recorded = await self.runtime_registry.record_detection_result(
            self.session_id,
            connection_generation=self.connection_generation,
            result=result,
        )
        if not recorded:
            return DetectionPipelineResult(
                status=DetectionPipelineStatus.STALE_GENERATION,
                detection_recorded=False,
            )

        publish_result = None
        if self.detection_publisher is not None:
            publish_result = await self.detection_publisher.publish(
                session_id=self.session_id,
                websocket=self.websocket,
                result=result,
            )

        if not await self.connection_manager.is_current(self.session_id, self.websocket):
            return DetectionPipelineResult(
                status=DetectionPipelineStatus.NOT_CURRENT_CONNECTION,
                detection_recorded=True,
                publish_result=publish_result,
            )

        try:
            behavior_result = await self.runtime_registry.observe_behavior_result(
                self.session_id,
                connection_generation=self.connection_generation,
                result=result,
            )
        except Exception:
            logger.exception(
                "Sliding Window behavior evaluation failed session_id=%s frame_id=%s",
                self.session_id,
                result.frame_id,
            )
            return DetectionPipelineResult(
                status=DetectionPipelineStatus.BEHAVIOR_EVALUATION_FAILED,
                detection_recorded=True,
                publish_result=publish_result,
            )

        if behavior_result.status in {
            BehaviorRuntimeObserveStatus.NOT_FOUND,
            BehaviorRuntimeObserveStatus.STALE_GENERATION,
        }:
            return DetectionPipelineResult(
                status=DetectionPipelineStatus.STALE_GENERATION,
                detection_recorded=True,
                publish_result=publish_result,
                behavior_observe_result=behavior_result,
            )

        behavior_event_write_result = await self._handle_behavior_event_write(behavior_result)
        if behavior_event_write_result is not None:
            if behavior_event_write_result.status in {
                BehaviorEventWriteStatus.RUNTIME_NOT_FOUND,
                BehaviorEventWriteStatus.STALE_GENERATION,
            }:
                return DetectionPipelineResult(
                    status=DetectionPipelineStatus.STALE_GENERATION,
                    detection_recorded=True,
                    publish_result=publish_result,
                    behavior_observe_result=behavior_result,
                    behavior_event_write_result=behavior_event_write_result,
                )
            if behavior_event_write_result.status == BehaviorEventWriteStatus.WRITE_FAILED:
                return DetectionPipelineResult(
                    status=DetectionPipelineStatus.BEHAVIOR_EVALUATION_FAILED,
                    detection_recorded=True,
                    publish_result=publish_result,
                    behavior_observe_result=behavior_result,
                    behavior_event_write_result=behavior_event_write_result,
                )

        return DetectionPipelineResult(
            status=DetectionPipelineStatus.PROCESSED,
            detection_recorded=True,
            publish_result=publish_result,
            behavior_observe_result=behavior_result,
            behavior_event_write_result=behavior_event_write_result,
        )

    async def _handle_behavior_event_write(
        self,
        behavior_result: BehaviorRuntimeObserveResult,
    ) -> BehaviorEventWriteResult | None:
        if self.behavior_event_service is None:
            return None
        if behavior_result.status != BehaviorRuntimeObserveStatus.TRANSITION_RECORDED:
            return None

        transition = behavior_result.transition
        if transition is None or transition.transition_type not in {
            BehaviorTransitionType.STARTED,
            BehaviorTransitionType.CLEARED,
        }:
            return None
        if not await self.connection_manager.is_current(self.session_id, self.websocket):
            return BehaviorEventWriteResult(BehaviorEventWriteStatus.STALE_GENERATION)

        try:
            return await self.behavior_event_service.handle_transition(
                session_id=self.session_id,
                connection_generation=self.connection_generation,
                transition=transition,
                previous_active_behavior_event_id=(
                    behavior_result.previous_active_behavior_event_id
                ),
                previous_active_event_behavior_type=(
                    behavior_result.previous_active_event_behavior_type
                ),
            )
        except Exception:
            logger.exception(
                "Behavior event writer failed session_id=%s transition_type=%s",
                self.session_id,
                transition.transition_type,
            )
            return BehaviorEventWriteResult(BehaviorEventWriteStatus.WRITE_FAILED)
