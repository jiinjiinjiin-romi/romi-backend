from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.ai.driver_monitoring import DriverMonitoringAdapter, InferenceFrame
from app.realtime.connection_manager import ConnectionManager
from app.realtime.detection_publisher import DetectionUpdatePublisher
from app.realtime.session_runtime import AcceptedFrame, SessionRuntimeRegistry

logger = logging.getLogger(__name__)


class InferenceWorker:
    def __init__(
        self,
        *,
        session_id: str,
        websocket: Any,
        connection_generation: int,
        connection_manager: ConnectionManager,
        runtime_registry: SessionRuntimeRegistry,
        adapter: DriverMonitoringAdapter,
        detection_publisher: DetectionUpdatePublisher | None = None,
    ) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.connection_generation = connection_generation
        self.connection_manager = connection_manager
        self.runtime_registry = runtime_registry
        self.adapter = adapter
        self.detection_publisher = detection_publisher
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run(), name=f"inference-worker:{self.session_id}")
        self._task.add_done_callback(self._consume_task_result)

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        try:
            while True:
                frame = await self.runtime_registry.wait_for_next_frame(
                    self.session_id,
                    connection_generation=self.connection_generation,
                )
                if frame is None:
                    return

                if not await self.connection_manager.is_current(self.session_id, self.websocket):
                    return

                await self._process_frame(frame)
        except asyncio.CancelledError:
            raise

    def _consume_task_result(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Inference worker crashed session_id=%s", self.session_id)

    async def _process_frame(self, frame: AcceptedFrame) -> None:
        inference_frame = _to_inference_frame(self.session_id, frame)
        try:
            result = await self.adapter.predict(inference_frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            if await self.connection_manager.is_current(self.session_id, self.websocket):
                await self.runtime_registry.record_inference_failure(
                    self.session_id,
                    connection_generation=self.connection_generation,
                )
            logger.exception(
                "Driver monitoring inference failed session_id=%s frame_id=%s",
                self.session_id,
                frame.metadata.frame_id,
            )
            return

        if not await self.connection_manager.is_current(self.session_id, self.websocket):
            return

        recorded = await self.runtime_registry.record_detection_result(
            self.session_id,
            connection_generation=self.connection_generation,
            result=result,
        )
        if not recorded or self.detection_publisher is None:
            return

        await self.detection_publisher.publish(
            session_id=self.session_id,
            websocket=self.websocket,
            result=result,
        )


def _to_inference_frame(session_id: str, frame: AcceptedFrame) -> InferenceFrame:
    return InferenceFrame(
        session_id=session_id,
        request_id=frame.metadata.request_id,
        frame_id=frame.metadata.frame_id,
        captured_at=frame.metadata.captured_at,
        occurred_at=frame.metadata.occurred_at,
        format=frame.metadata.format,
        width=frame.metadata.width,
        height=frame.metadata.height,
        jpeg_bytes=frame.jpeg_bytes,
        received_at=frame.received_at,
    )
