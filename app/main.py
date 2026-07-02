import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.v1.endpoints.websocket import router as websocket_router
from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import dispose_engine
from app.integrations.driver_monitoring import (
    close_driver_monitoring_adapter,
    create_driver_monitoring_adapter,
)
from app.realtime.connection_manager import ConnectionManager
from app.realtime.protocol import WebSocketCloseCode
from app.realtime.session_runtime import SessionRuntimeRegistry

logger = logging.getLogger(__name__)

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Content-Type", "Authorization", "X-Request-ID"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_realtime_state(app)
    configure_driver_monitoring_adapter(app)
    logger.info("%s starting", settings.app_name)
    try:
        yield
    finally:
        await app.state.websocket_connection_manager.close_all(
            code=WebSocketCloseCode.SERVICE_RESTART,
            reason="SERVICE_RESTART",
        )
        await app.state.session_runtime_registry.clear()
        await close_driver_monitoring_adapter_from_state(app)
        await dispose_engine()
        logger.info("%s stopping", settings.app_name)


def configure_realtime_state(app: FastAPI) -> None:
    if not hasattr(app.state, "websocket_connection_manager"):
        app.state.websocket_connection_manager = ConnectionManager()
    if not hasattr(app.state, "session_runtime_registry"):
        app.state.session_runtime_registry = SessionRuntimeRegistry()


def configure_driver_monitoring_adapter(app: FastAPI) -> None:
    if hasattr(app.state, "driver_monitoring_adapter"):
        return

    settings = get_settings()
    adapter = create_driver_monitoring_adapter(settings)
    app.state.driver_monitoring_adapter = adapter
    logger.info(
        "DriverMonitoringAdapter initialized mode=%s model_version=%s",
        settings.driver_monitoring_adapter,
        adapter.model_version,
    )


async def close_driver_monitoring_adapter_from_state(app: FastAPI) -> None:
    adapter = getattr(app.state, "driver_monitoring_adapter", None)
    if adapter is None:
        return

    try:
        await close_driver_monitoring_adapter(adapter)
    except Exception:
        logger.exception("DriverMonitoringAdapter shutdown failed")
    finally:
        delattr(app.state, "driver_monitoring_adapter")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
    )
    app.add_middleware(RequestIdMiddleware)

    configure_realtime_state(app)
    register_error_handlers(app)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    app.include_router(websocket_router, prefix=settings.ws_v1_prefix)

    return app


app = create_app()
