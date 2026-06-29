import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.logging import get_request_id
from app.schemas.base import ApiBaseModel

logger = logging.getLogger(__name__)


class ErrorResponse(ApiBaseModel):
    status: int
    message: str
    error: str


def _error_response(
    *,
    status_code: int,
    message: str,
    error: ErrorCode | str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        status=status_code,
        message=message,
        error=error.value if isinstance(error, ErrorCode) else error,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(by_alias=True),
        headers=headers,
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.warning(
        "Application error request_id=%s status=%s error=%s path=%s",
        get_request_id(),
        exc.status_code,
        exc.error_code,
        request.url.path,
    )
    return _error_response(
        status_code=exc.status_code,
        message=exc.message,
        error=exc.error_code,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    logger.warning(
        "Validation error request_id=%s path=%s details=%s",
        get_request_id(),
        request.url.path,
        exc.errors(),
    )
    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Request validation failed.",
        error=ErrorCode.VALIDATION_ERROR,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    error_code = (
        ErrorCode.NOT_FOUND
        if exc.status_code == status.HTTP_404_NOT_FOUND
        else ErrorCode.HTTP_ERROR
    )
    message = (
        "Requested resource was not found."
        if exc.status_code == status.HTTP_404_NOT_FOUND
        else str(exc.detail)
    )
    logger.warning(
        "HTTP error request_id=%s status=%s error=%s path=%s",
        get_request_id(),
        exc.status_code,
        error_code.value,
        request.url.path,
    )
    return _error_response(
        status_code=exc.status_code,
        message=message,
        error=error_code,
        headers=exc.headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception request_id=%s path=%s",
        get_request_id(),
        request.url.path,
    )
    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="Internal server error.",
        error=ErrorCode.INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
