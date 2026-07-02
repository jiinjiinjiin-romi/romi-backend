import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_error_handlers
from app.api.navigation_tmap import router as navigation_tmap_router
from app.api.v1.endpoints.websocket import router as websocket_router
from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import dispose_engine
from app.realtime.connection_manager import ConnectionManager
from app.realtime.protocol import WebSocketCloseCode
from app.realtime.session_runtime import SessionRuntimeRegistry

logger = logging.getLogger(__name__)

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Content-Type", "Authorization", "X-Request-ID"]


def get_storage_root(report_storage_path: str) -> Path:
    report_root = Path(report_storage_path).resolve(strict=False)
    return report_root.parent if report_root.name == "reports" else report_root


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_realtime_state(app)
    logger.info("%s starting", settings.app_name)
    try:
        yield
    finally:
        await app.state.websocket_connection_manager.close_all(
            code=WebSocketCloseCode.SERVICE_RESTART,
            reason="SERVICE_RESTART",
        )
        await app.state.session_runtime_registry.clear()
        await dispose_engine()
        logger.info("%s stopping", settings.app_name)


def configure_realtime_state(app: FastAPI) -> None:
    if not hasattr(app.state, "websocket_connection_manager"):
        app.state.websocket_connection_manager = ConnectionManager()
    if not hasattr(app.state, "session_runtime_registry"):
        app.state.session_runtime_registry = SessionRuntimeRegistry()


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
    app.mount(
        "/storage",
        StaticFiles(directory=get_storage_root(settings.report_storage_path), check_dir=False),
        name="storage",
    )
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    app.include_router(websocket_router, prefix=settings.ws_v1_prefix)
    app.include_router(navigation_tmap_router)

    return app


app = create_app()
