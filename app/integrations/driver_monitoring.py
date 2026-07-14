import inspect
from typing import Protocol

from app.ai.driver_monitoring import DriverMonitoringAdapter
from app.ai.mock_vit_adapter import MockViTAdapter
from app.ai.real_vit_adapter import RealViTAdapter
from app.core.config import Settings


class DriverMonitoringReadiness(Protocol):
    async def is_available(self) -> bool:
        pass


def create_driver_monitoring_adapter(settings: Settings) -> DriverMonitoringAdapter:
    if settings.driver_monitoring_adapter == "MOCK":
        return MockViTAdapter(
            model_version=settings.model_version,
            latency_ms=settings.mock_vit_inference_latency_ms,
        )

    return RealViTAdapter(settings)


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
