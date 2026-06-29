import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.constants import REQUEST_ID_HEADER

_request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id_context.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s - %(message)s",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    for handler in root_logger.handlers:
        if not any(isinstance(filter_, RequestIdFilter) for filter_ in handler.filters):
            handler.addFilter(RequestIdFilter())


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str = REQUEST_ID_HEADER) -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(self.header_name) or str(uuid4())
        token = _request_id_context.set(request_id)
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            response.headers[self.header_name] = request_id
            return response
        finally:
            _request_id_context.reset(token)
