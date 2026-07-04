from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.ai.driver_monitoring import DetectionBehaviorType, DetectionResult, ModelActionType
from app.core.enums import BehaviorType, DrivingState, LocationSource
from app.core.time import utc_now_for_api_response
from app.policies.sliding_window_behavior_policy import (
    BehaviorTransition,
    BehaviorTransitionType,
    SlidingWindowBehaviorPolicy,
)


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    frame_id: str
    request_id: str
    occurred_at: datetime
    format: str
    width: int
    height: int
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class AcceptedFrame:
    metadata: FrameMetadata
    jpeg_bytes: bytes
    received_at: datetime


@dataclass(frozen=True, slots=True)
class LatestFrameQueuePutResult:
    dropped_frame: AcceptedFrame | None
    queue_size: int


class LatestFrameQueue:
    def __init__(self, max_size: int) -> None:
        if max_size not in {1, 2}:
            raise ValueError("LatestFrameQueue max_size must be 1 or 2.")
        self.max_size = max_size
        self._items: deque[AcceptedFrame] = deque()

    def put_latest(self, frame: AcceptedFrame) -> LatestFrameQueuePutResult:
        dropped_frame = None
        if len(self._items) >= self.max_size:
            dropped_frame = self._items.popleft()
        self._items.append(frame)
        return LatestFrameQueuePutResult(
            dropped_frame=dropped_frame,
            queue_size=len(self._items),
        )

    def get(self) -> AcceptedFrame | None:
        if not self._items:
            return None
        return self._items.popleft()

    def qsize(self) -> int:
        return len(self._items)

    def list_frames(self) -> Sequence[AcceptedFrame]:
        return tuple(self._items)

    def clear(self) -> None:
        self._items.clear()


class FrameAcceptStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    RUNTIME_NOT_FOUND = "RUNTIME_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class FrameAcceptResult:
    status: FrameAcceptStatus
    dropped_count: int = 0


@dataclass(slots=True)
class SessionRuntime:
    session_id: str
    connected_at: datetime
    last_message_at: datetime
    last_heartbeat_at: datetime
    current_latitude: float | None = None
    current_longitude: float | None = None
    current_speed_kph: float | None = None
    current_accuracy_meters: float | None = None
    current_location_source: LocationSource | None = None
    driving_state: DrivingState = DrivingState.UNKNOWN
    last_location_occurred_at: datetime | None = None
    last_location_persisted_at: datetime | None = None
    last_location_persisted_monotonic: float | None = None
    latest_frame_queue: LatestFrameQueue | None = None
    frame_available_event: asyncio.Event | None = None
    recent_frame_ids: OrderedDict[str, None] | None = None
    frame_queue_max_size: int = 2
    frame_recent_id_cache_size: int = 256
    last_accepted_frame_id: str | None = None
    last_accepted_captured_at: datetime | None = None
    accepted_frame_count: int = 0
    dropped_frame_count: int = 0
    connection_generation: int = 0
    last_detection_result: DetectionResult | None = None
    last_inference_completed_at: datetime | None = None
    last_inference_latency_ms: int | None = None
    processed_frame_count: int = 0
    inference_failure_count: int = 0
    behavior_policy: SlidingWindowBehaviorPolicy = field(
        default_factory=SlidingWindowBehaviorPolicy
    )
    last_behavior_transition: BehaviorTransition | None = None
    active_detection_behavior_type: DetectionBehaviorType | None = None
    active_event_behavior_type: BehaviorType | None = None
    dominant_model_action_type: ModelActionType | None = None
    active_behavior_started_at: datetime | None = None
    last_behavior_seen_at: datetime | None = None
    last_behavior_transition_at: datetime | None = None
    active_behavior_event_id: str | None = None
    current_intervention_id: str | None = None
    active_conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocationRuntimeUpdate:
    latitude: float
    longitude: float
    speed_kph: float | None
    accuracy_meters: float | None
    source: LocationSource
    driving_state: DrivingState
    occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class LocationRuntimeSnapshot:
    session_id: str
    current_latitude: float | None
    current_longitude: float | None
    current_speed_kph: float | None
    current_accuracy_meters: float | None
    current_location_source: LocationSource | None
    driving_state: DrivingState
    last_location_occurred_at: datetime | None
    last_location_persisted_at: datetime | None
    last_location_persisted_monotonic: float | None


class LocationRuntimeApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class LocationRuntimeApplyResult:
    status: LocationRuntimeApplyStatus
    snapshot: LocationRuntimeSnapshot | None


@dataclass(frozen=True, slots=True)
class InferenceRuntimeSnapshot:
    session_id: str
    connection_generation: int
    last_detection_result: DetectionResult | None
    last_inference_completed_at: datetime | None
    last_inference_latency_ms: int | None
    processed_frame_count: int
    inference_failure_count: int


@dataclass(frozen=True, slots=True)
class BehaviorRuntimeSnapshot:
    session_id: str
    connection_generation: int
    last_behavior_transition: BehaviorTransition | None
    active_detection_behavior_type: DetectionBehaviorType | None
    active_event_behavior_type: BehaviorType | None
    active_behavior_event_id: str | None
    dominant_model_action_type: ModelActionType | None
    active_behavior_started_at: datetime | None
    last_behavior_seen_at: datetime | None
    last_behavior_transition_at: datetime | None
    policy_sample_count: int


class BehaviorRuntimeObserveStatus(StrEnum):
    TRANSITION_RECORDED = "TRANSITION_RECORDED"
    NO_TRANSITION = "NO_TRANSITION"
    STALE_GENERATION = "STALE_GENERATION"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class BehaviorRuntimeObserveResult:
    status: BehaviorRuntimeObserveStatus
    transition: BehaviorTransition | None
    previous_active_behavior_event_id: str | None = None
    previous_active_event_behavior_type: BehaviorType | None = None


class SessionRuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, SessionRuntime] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._runtimes)

    async def get_or_create(
        self,
        session_id: str,
        *,
        connected_at: datetime | None = None,
        frame_queue_max_size: int = 2,
        frame_recent_id_cache_size: int = 256,
    ) -> SessionRuntime:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is not None:
                return runtime

            now = connected_at or utc_now_for_api_response()
            runtime = SessionRuntime(
                session_id=session_id,
                connected_at=now,
                last_message_at=now,
                last_heartbeat_at=now,
                latest_frame_queue=LatestFrameQueue(frame_queue_max_size),
                frame_available_event=asyncio.Event(),
                recent_frame_ids=OrderedDict(),
                frame_queue_max_size=frame_queue_max_size,
                frame_recent_id_cache_size=frame_recent_id_cache_size,
            )
            self._runtimes[session_id] = runtime
            return runtime

    async def prepare_connection(
        self,
        session_id: str,
        *,
        frame_queue_max_size: int,
        frame_recent_id_cache_size: int,
    ) -> int | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None

            runtime.connection_generation += 1
            self._reset_frame_state_locked(
                runtime,
                frame_queue_max_size=frame_queue_max_size,
                frame_recent_id_cache_size=frame_recent_id_cache_size,
            )
            self._reset_inference_state_locked(runtime)
            self._reset_behavior_state_locked(runtime)
            return runtime.connection_generation

    async def get(self, session_id: str) -> SessionRuntime | None:
        async with self._lock:
            return self._runtimes.get(session_id)

    async def touch_message(self, session_id: str, occurred_at: datetime) -> SessionRuntime | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_message_at = occurred_at
            return runtime

    async def touch_heartbeat(
        self,
        session_id: str,
        occurred_at: datetime,
    ) -> SessionRuntime | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_message_at = occurred_at
            runtime.last_heartbeat_at = occurred_at
            return runtime

    async def get_location_snapshot(self, session_id: str) -> LocationRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            return self._snapshot(runtime)

    async def apply_location_update(
        self,
        session_id: str,
        update: LocationRuntimeUpdate,
    ) -> LocationRuntimeApplyResult:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return LocationRuntimeApplyResult(
                    status=LocationRuntimeApplyStatus.NOT_FOUND,
                    snapshot=None,
                )

            if runtime.last_location_occurred_at is not None:
                if update.occurred_at < runtime.last_location_occurred_at:
                    return LocationRuntimeApplyResult(
                        status=LocationRuntimeApplyStatus.STALE,
                        snapshot=self._snapshot(runtime),
                    )
                if update.occurred_at == runtime.last_location_occurred_at:
                    return LocationRuntimeApplyResult(
                        status=LocationRuntimeApplyStatus.DUPLICATE,
                        snapshot=self._snapshot(runtime),
                    )

            runtime.current_latitude = update.latitude
            runtime.current_longitude = update.longitude
            runtime.current_speed_kph = update.speed_kph
            runtime.current_accuracy_meters = update.accuracy_meters
            runtime.current_location_source = update.source
            runtime.driving_state = update.driving_state
            runtime.last_location_occurred_at = update.occurred_at
            runtime.last_message_at = update.received_at
            return LocationRuntimeApplyResult(
                status=LocationRuntimeApplyStatus.APPLIED,
                snapshot=self._snapshot(runtime),
            )

    async def mark_location_persisted(
        self,
        session_id: str,
        *,
        occurred_at: datetime,
        monotonic_value: float,
    ) -> LocationRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            runtime.last_location_persisted_at = occurred_at
            runtime.last_location_persisted_monotonic = monotonic_value
            return self._snapshot(runtime)

    async def reset_frame_state(
        self,
        session_id: str,
        *,
        frame_queue_max_size: int,
        frame_recent_id_cache_size: int,
    ) -> bool:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return False

            self._reset_frame_state_locked(
                runtime,
                frame_queue_max_size=frame_queue_max_size,
                frame_recent_id_cache_size=frame_recent_id_cache_size,
            )
            self._reset_inference_state_locked(runtime)
            self._reset_behavior_state_locked(runtime)
            return True

    async def accept_frame(self, session_id: str, frame: AcceptedFrame) -> FrameAcceptResult:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return FrameAcceptResult(status=FrameAcceptStatus.RUNTIME_NOT_FOUND)

            if runtime.latest_frame_queue is None:
                runtime.latest_frame_queue = LatestFrameQueue(runtime.frame_queue_max_size)
            if runtime.frame_available_event is None:
                runtime.frame_available_event = asyncio.Event()
            if runtime.recent_frame_ids is None:
                runtime.recent_frame_ids = OrderedDict()

            if frame.metadata.frame_id in runtime.recent_frame_ids:
                return FrameAcceptResult(status=FrameAcceptStatus.DUPLICATE)

            queue_result = runtime.latest_frame_queue.put_latest(frame)
            runtime.recent_frame_ids[frame.metadata.frame_id] = None
            while len(runtime.recent_frame_ids) > runtime.frame_recent_id_cache_size:
                runtime.recent_frame_ids.popitem(last=False)

            runtime.accepted_frame_count += 1
            runtime.last_accepted_frame_id = frame.metadata.frame_id
            runtime.last_accepted_captured_at = frame.metadata.captured_at
            dropped_count = 1 if queue_result.dropped_frame is not None else 0
            runtime.dropped_frame_count += dropped_count
            runtime.frame_available_event.set()
            return FrameAcceptResult(
                status=FrameAcceptStatus.ACCEPTED,
                dropped_count=dropped_count,
            )

    async def get_latest_frame_queue_snapshot(self, session_id: str) -> Sequence[AcceptedFrame]:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.latest_frame_queue is None:
                return ()
            return runtime.latest_frame_queue.list_frames()

    async def get_next_frame(self, session_id: str) -> AcceptedFrame | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.latest_frame_queue is None:
                return None
            return runtime.latest_frame_queue.get()

    async def wait_for_next_frame(
        self,
        session_id: str,
        *,
        connection_generation: int | None = None,
    ) -> AcceptedFrame | None:
        while True:
            async with self._lock:
                runtime = self._runtimes.get(session_id)
                if runtime is None:
                    return None
                if (
                    connection_generation is not None
                    and runtime.connection_generation != connection_generation
                ):
                    return None
                if runtime.latest_frame_queue is None:
                    runtime.latest_frame_queue = LatestFrameQueue(runtime.frame_queue_max_size)
                if runtime.frame_available_event is None:
                    runtime.frame_available_event = asyncio.Event()

                frame = runtime.latest_frame_queue.get()
                if frame is not None:
                    return frame

                event = runtime.frame_available_event
                event.clear()

            await event.wait()

    async def record_detection_result(
        self,
        session_id: str,
        *,
        connection_generation: int,
        result: DetectionResult,
    ) -> bool:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.connection_generation != connection_generation:
                return False

            runtime.last_detection_result = result
            runtime.last_inference_completed_at = result.inference_completed_at
            runtime.last_inference_latency_ms = result.inference_latency_ms
            runtime.processed_frame_count += 1
            return True

    async def record_inference_failure(
        self,
        session_id: str,
        *,
        connection_generation: int,
    ) -> bool:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.connection_generation != connection_generation:
                return False

            runtime.inference_failure_count += 1
            return True

    async def get_inference_snapshot(self, session_id: str) -> InferenceRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            return self._inference_snapshot(runtime)

    async def observe_behavior_result(
        self,
        session_id: str,
        *,
        connection_generation: int,
        result: DetectionResult,
    ) -> BehaviorRuntimeObserveResult:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return BehaviorRuntimeObserveResult(
                    status=BehaviorRuntimeObserveStatus.NOT_FOUND,
                    transition=None,
                )
            if runtime.connection_generation != connection_generation:
                return BehaviorRuntimeObserveResult(
                    status=BehaviorRuntimeObserveStatus.STALE_GENERATION,
                    transition=None,
                )

            transition = runtime.behavior_policy.observe(result)
            if transition.transition_type == BehaviorTransitionType.NONE:
                return BehaviorRuntimeObserveResult(
                    status=BehaviorRuntimeObserveStatus.NO_TRANSITION,
                    transition=transition,
                )

            previous_active_behavior_event_id = runtime.active_behavior_event_id
            previous_active_event_behavior_type = runtime.active_event_behavior_type
            self._record_behavior_transition_locked(runtime, transition)
            return BehaviorRuntimeObserveResult(
                status=BehaviorRuntimeObserveStatus.TRANSITION_RECORDED,
                transition=transition,
                previous_active_behavior_event_id=previous_active_behavior_event_id,
                previous_active_event_behavior_type=previous_active_event_behavior_type,
            )

    async def get_behavior_snapshot(self, session_id: str) -> BehaviorRuntimeSnapshot | None:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                return None
            return self._behavior_snapshot(runtime)

    async def record_active_behavior_event(
        self,
        session_id: str,
        *,
        connection_generation: int,
        behavior_type: BehaviorType,
        event_id: str,
    ) -> bool:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.connection_generation != connection_generation:
                return False
            if runtime.active_event_behavior_type != behavior_type:
                return False

            runtime.active_behavior_event_id = event_id
            return True

    async def clear_active_behavior_event(
        self,
        session_id: str,
        *,
        connection_generation: int,
        event_id: str | None = None,
    ) -> bool:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None or runtime.connection_generation != connection_generation:
                return False
            if event_id is not None and runtime.active_behavior_event_id not in {None, event_id}:
                return False

            runtime.active_behavior_event_id = None
            return True

    async def remove(self, session_id: str) -> bool:
        async with self._lock:
            runtime = self._runtimes.pop(session_id, None)
            if runtime is None:
                return False
            if runtime.frame_available_event is not None:
                runtime.frame_available_event.set()
            return True

    async def clear(self) -> None:
        async with self._lock:
            for runtime in self._runtimes.values():
                if runtime.frame_available_event is not None:
                    runtime.frame_available_event.set()
            self._runtimes.clear()

    @staticmethod
    def _snapshot(runtime: SessionRuntime) -> LocationRuntimeSnapshot:
        return LocationRuntimeSnapshot(
            session_id=runtime.session_id,
            current_latitude=runtime.current_latitude,
            current_longitude=runtime.current_longitude,
            current_speed_kph=runtime.current_speed_kph,
            current_accuracy_meters=runtime.current_accuracy_meters,
            current_location_source=runtime.current_location_source,
            driving_state=runtime.driving_state,
            last_location_occurred_at=runtime.last_location_occurred_at,
            last_location_persisted_at=runtime.last_location_persisted_at,
            last_location_persisted_monotonic=runtime.last_location_persisted_monotonic,
        )

    @staticmethod
    def _inference_snapshot(runtime: SessionRuntime) -> InferenceRuntimeSnapshot:
        return InferenceRuntimeSnapshot(
            session_id=runtime.session_id,
            connection_generation=runtime.connection_generation,
            last_detection_result=runtime.last_detection_result,
            last_inference_completed_at=runtime.last_inference_completed_at,
            last_inference_latency_ms=runtime.last_inference_latency_ms,
            processed_frame_count=runtime.processed_frame_count,
            inference_failure_count=runtime.inference_failure_count,
        )

    @staticmethod
    def _behavior_snapshot(runtime: SessionRuntime) -> BehaviorRuntimeSnapshot:
        return BehaviorRuntimeSnapshot(
            session_id=runtime.session_id,
            connection_generation=runtime.connection_generation,
            last_behavior_transition=runtime.last_behavior_transition,
            active_detection_behavior_type=runtime.active_detection_behavior_type,
            active_event_behavior_type=runtime.active_event_behavior_type,
            active_behavior_event_id=runtime.active_behavior_event_id,
            dominant_model_action_type=runtime.dominant_model_action_type,
            active_behavior_started_at=runtime.active_behavior_started_at,
            last_behavior_seen_at=runtime.last_behavior_seen_at,
            last_behavior_transition_at=runtime.last_behavior_transition_at,
            policy_sample_count=runtime.behavior_policy.sample_count,
        )

    @staticmethod
    def _record_behavior_transition_locked(
        runtime: SessionRuntime,
        transition: BehaviorTransition,
    ) -> None:
        runtime.last_behavior_transition = transition
        runtime.last_behavior_seen_at = transition.last_seen_at
        runtime.last_behavior_transition_at = transition.captured_at

        if transition.transition_type == BehaviorTransitionType.CLEARED:
            runtime.active_detection_behavior_type = None
            runtime.active_event_behavior_type = None
            runtime.dominant_model_action_type = None
            runtime.active_behavior_started_at = None
            runtime.active_behavior_event_id = None
            runtime.current_intervention_id = None
            runtime.active_conversation_id = None
            return

        runtime.active_detection_behavior_type = transition.detection_behavior_type
        runtime.active_event_behavior_type = transition.event_behavior_type
        runtime.dominant_model_action_type = transition.dominant_model_action_type
        runtime.active_behavior_started_at = transition.started_at

    @staticmethod
    def _reset_frame_state_locked(
        runtime: SessionRuntime,
        *,
        frame_queue_max_size: int,
        frame_recent_id_cache_size: int,
    ) -> None:
        if runtime.frame_available_event is not None:
            runtime.frame_available_event.set()
        runtime.latest_frame_queue = LatestFrameQueue(frame_queue_max_size)
        runtime.frame_available_event = asyncio.Event()
        runtime.recent_frame_ids = OrderedDict()
        runtime.frame_queue_max_size = frame_queue_max_size
        runtime.frame_recent_id_cache_size = frame_recent_id_cache_size
        runtime.last_accepted_frame_id = None
        runtime.last_accepted_captured_at = None
        runtime.accepted_frame_count = 0
        runtime.dropped_frame_count = 0

    @staticmethod
    def _reset_inference_state_locked(runtime: SessionRuntime) -> None:
        runtime.last_detection_result = None
        runtime.last_inference_completed_at = None
        runtime.last_inference_latency_ms = None
        runtime.processed_frame_count = 0
        runtime.inference_failure_count = 0

    @staticmethod
    def _reset_behavior_state_locked(runtime: SessionRuntime) -> None:
        runtime.behavior_policy.reset()
        runtime.last_behavior_transition = None
        runtime.active_detection_behavior_type = None
        runtime.active_event_behavior_type = None
        runtime.dominant_model_action_type = None
        runtime.active_behavior_started_at = None
        runtime.last_behavior_seen_at = None
        runtime.last_behavior_transition_at = None
        runtime.active_behavior_event_id = None
        runtime.current_intervention_id = None
        runtime.active_conversation_id = None
