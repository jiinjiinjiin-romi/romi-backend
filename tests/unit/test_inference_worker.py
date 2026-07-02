import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ai.driver_monitoring import DetectionBehaviorType, DetectionResult, InferenceFrame
from app.realtime.inference_worker import InferenceWorker
from app.realtime.session_runtime import (
    AcceptedFrame,
    FrameMetadata,
    InferenceRuntimeSnapshot,
    SessionRuntimeRegistry,
)


class FakeConnectionManager:
    def __init__(self, *, current: bool = True) -> None:
        self.current = current

    async def is_current(self, session_id: str, websocket: object) -> bool:
        return self.current


class RecordingAdapter:
    model_version = "vit-test"

    def __init__(self) -> None:
        self.frames: list[InferenceFrame] = []

    async def is_ready(self) -> bool:
        return True

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.frames.append(frame)
        return detection_result(frame)


class FailingThenSuccessAdapter(RecordingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.calls += 1
        self.frames.append(frame)
        if self.calls == 1:
            raise RuntimeError("model failed")
        return detection_result(frame)


class BlockingAdapter(RecordingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def predict(self, frame: InferenceFrame) -> DetectionResult:
        self.frames.append(frame)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return detection_result(frame)


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, DetectionResult]] = []

    async def publish(
        self,
        *,
        session_id: str,
        websocket: object,
        result: DetectionResult,
    ) -> None:
        self.calls.append((session_id, websocket, result))


def accepted_frame(frame_id: str = "frame-1") -> AcceptedFrame:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    return AcceptedFrame(
        metadata=FrameMetadata(
            frame_id=frame_id,
            request_id="6a972e7b-2151-4997-acbd-19b01facb6b0",
            occurred_at=timestamp,
            format="JPEG",
            width=640,
            height=360,
            captured_at=timestamp,
        ),
        jpeg_bytes=b"\xff\xd8\xff\xd9",
        received_at=timestamp + timedelta(milliseconds=10),
    )


def detection_result(frame: InferenceFrame) -> DetectionResult:
    timestamp = datetime(2026, 6, 28, 3, 10, tzinfo=UTC)
    return DetectionResult(
        session_id=frame.session_id,
        frame_id=frame.frame_id,
        behavior_type=DetectionBehaviorType.NORMAL,
        confidence=0.99,
        model_version="vit-test",
        captured_at=frame.captured_at,
        inference_started_at=timestamp,
        inference_completed_at=timestamp + timedelta(milliseconds=7),
        inference_latency_ms=7,
    )


async def prepare_registry() -> tuple[SessionRuntimeRegistry, int]:
    registry = SessionRuntimeRegistry()
    await registry.get_or_create("session-1")
    generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    assert generation is not None
    return registry, generation


def make_worker(
    *,
    registry: SessionRuntimeRegistry,
    generation: int,
    adapter: Any,
    manager: FakeConnectionManager | None = None,
    publisher: RecordingPublisher | None = None,
) -> InferenceWorker:
    return InferenceWorker(
        session_id="session-1",
        websocket=object(),
        connection_generation=generation,
        connection_manager=manager or FakeConnectionManager(),
        runtime_registry=registry,
        adapter=adapter,
        detection_publisher=publisher,
    )


async def wait_for_snapshot(
    registry: SessionRuntimeRegistry,
    predicate,
) -> InferenceRuntimeSnapshot:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while True:
        snapshot = await registry.get_inference_snapshot("session-1")
        assert snapshot is not None
        if predicate(snapshot):
            return snapshot
        if loop.time() >= deadline:
            raise AssertionError("Inference snapshot condition was not met.")
        await asyncio.sleep(0)


async def wait_until_worker_stops(worker: InferenceWorker) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while worker.is_running:
        if loop.time() >= deadline:
            raise AssertionError("Inference worker did not stop.")
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_worker_consumes_frame_and_records_detection_result() -> None:
    registry, generation = await prepare_registry()
    adapter = RecordingAdapter()
    publisher = RecordingPublisher()
    worker = make_worker(
        registry=registry,
        generation=generation,
        adapter=adapter,
        publisher=publisher,
    )
    worker.start()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    snapshot = await wait_for_snapshot(registry, lambda item: item.processed_frame_count == 1)
    await worker.stop()

    assert [frame.frame_id for frame in adapter.frames] == ["frame-1"]
    assert snapshot.last_detection_result is not None
    assert snapshot.last_detection_result.frame_id == "frame-1"
    assert snapshot.last_inference_latency_ms == 7
    assert snapshot.inference_failure_count == 0
    assert [(session_id, result.frame_id) for session_id, _, result in publisher.calls] == [
        ("session-1", "frame-1")
    ]


@pytest.mark.asyncio
async def test_worker_records_failure_and_continues_to_next_frame() -> None:
    registry, generation = await prepare_registry()
    adapter = FailingThenSuccessAdapter()
    publisher = RecordingPublisher()
    worker = make_worker(
        registry=registry,
        generation=generation,
        adapter=adapter,
        publisher=publisher,
    )
    worker.start()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await wait_for_snapshot(registry, lambda item: item.inference_failure_count == 1)
    await registry.accept_frame("session-1", accepted_frame("frame-2"))
    snapshot = await wait_for_snapshot(registry, lambda item: item.processed_frame_count == 1)
    await worker.stop()

    assert [frame.frame_id for frame in adapter.frames] == ["frame-1", "frame-2"]
    assert snapshot.inference_failure_count == 1
    assert snapshot.last_detection_result is not None
    assert snapshot.last_detection_result.frame_id == "frame-2"
    assert [(session_id, result.frame_id) for session_id, _, result in publisher.calls] == [
        ("session-1", "frame-2")
    ]


@pytest.mark.asyncio
async def test_worker_stop_is_idempotent_while_waiting_for_frame() -> None:
    registry, generation = await prepare_registry()
    worker = make_worker(registry=registry, generation=generation, adapter=RecordingAdapter())
    worker.start()

    await worker.stop()
    await worker.stop()

    snapshot = await registry.get_inference_snapshot("session-1")
    assert snapshot is not None
    assert snapshot.processed_frame_count == 0
    assert snapshot.inference_failure_count == 0


@pytest.mark.asyncio
async def test_worker_cancellation_during_inference_does_not_record_failure() -> None:
    registry, generation = await prepare_registry()
    adapter = BlockingAdapter()
    publisher = RecordingPublisher()
    worker = make_worker(
        registry=registry,
        generation=generation,
        adapter=adapter,
        publisher=publisher,
    )
    worker.start()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await asyncio.wait_for(adapter.started.wait(), timeout=1)
    await worker.stop()

    snapshot = await registry.get_inference_snapshot("session-1")
    assert adapter.cancelled.is_set()
    assert snapshot is not None
    assert snapshot.processed_frame_count == 0
    assert snapshot.inference_failure_count == 0
    assert snapshot.last_detection_result is None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_old_worker_result_is_ignored_after_replacement_generation() -> None:
    registry, generation = await prepare_registry()
    manager = FakeConnectionManager()
    adapter = BlockingAdapter()
    publisher = RecordingPublisher()
    worker = make_worker(
        registry=registry,
        generation=generation,
        adapter=adapter,
        manager=manager,
        publisher=publisher,
    )
    worker.start()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await asyncio.wait_for(adapter.started.wait(), timeout=1)
    manager.current = False
    new_generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    adapter.release.set()
    await wait_until_worker_stops(worker)
    await worker.stop()
    snapshot = await registry.get_inference_snapshot("session-1")

    assert new_generation == generation + 1
    assert snapshot is not None
    assert snapshot.connection_generation == new_generation
    assert snapshot.processed_frame_count == 0
    assert snapshot.inference_failure_count == 0
    assert snapshot.last_detection_result is None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_generation_mismatch_record_failure_does_not_publish() -> None:
    registry, generation = await prepare_registry()
    adapter = BlockingAdapter()
    publisher = RecordingPublisher()
    worker = make_worker(
        registry=registry,
        generation=generation,
        adapter=adapter,
        publisher=publisher,
    )
    worker.start()

    await registry.accept_frame("session-1", accepted_frame("frame-1"))
    await asyncio.wait_for(adapter.started.wait(), timeout=1)
    new_generation = await registry.prepare_connection(
        "session-1",
        frame_queue_max_size=2,
        frame_recent_id_cache_size=256,
    )
    adapter.release.set()
    await wait_until_worker_stops(worker)
    await worker.stop()
    snapshot = await registry.get_inference_snapshot("session-1")

    assert new_generation == generation + 1
    assert snapshot is not None
    assert snapshot.connection_generation == new_generation
    assert snapshot.processed_frame_count == 0
    assert snapshot.last_detection_result is None
    assert publisher.calls == []
