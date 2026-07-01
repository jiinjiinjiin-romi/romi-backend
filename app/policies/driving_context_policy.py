from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import DrivingSessionStatus, DrivingState


@dataclass(frozen=True, slots=True)
class DrivingContextPolicy:
    moving_speed_threshold_kph: float
    max_accuracy_meters: float

    def determine_state(
        self,
        *,
        speed_kph: float | None,
        accuracy_meters: float | None,
        session_status: str,
    ) -> DrivingState:
        if session_status != DrivingSessionStatus.ACTIVE.value:
            return DrivingState.UNKNOWN

        if accuracy_meters is not None and accuracy_meters > self.max_accuracy_meters:
            return DrivingState.UNKNOWN

        if speed_kph is None:
            return DrivingState.UNKNOWN

        if speed_kph >= self.moving_speed_threshold_kph:
            return DrivingState.MOVING

        return DrivingState.TEMPORARY_STOP
