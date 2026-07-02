import inspect
from typing import NoReturn, Protocol

from app.ai.driver_monitoring import DriverMonitoringAdapter, InferenceFrame
from app.ai.mock_vit_adapter import MockViTAdapter
from app.core.config import Settings


class DriverMonitoringReadiness(Protocol):
    async def is_available(self) -> bool:
        pass


class UnavailableDriverMonitoringAdapter:
    def __init__(self, *, model_version: str) -> None:
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        return self._model_version

    async def is_ready(self) -> bool:
        return False

    async def predict(self, frame: InferenceFrame) -> NoReturn:
        raise RuntimeError("REAL driver monitoring adapter is not implemented.")

    async def aclose(self) -> None:
        return None


def create_driver_monitoring_adapter(settings: Settings) -> DriverMonitoringAdapter:
    if settings.driver_monitoring_adapter == "MOCK":
        return MockViTAdapter(
            model_version=settings.model_version,
            latency_ms=settings.mock_vit_inference_latency_ms,
        )

    return UnavailableDriverMonitoringAdapter(model_version=settings.model_version)


async def close_driver_monitoring_adapter(adapter: DriverMonitoringAdapter) -> None:
    close = getattr(adapter, "aclose", None)
    if close is None:
        return

    result = close()
    if inspect.isawaitable(result):
        await result


class HealthDriverMonitoringReadiness:
    def __init__(self, adapter: DriverMonitoringAdapter) -> None:
        self.adapter = adapter

    async def is_available(self) -> bool:
        return await self.adapter.is_ready()
