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

PROFILE_VALIDATION_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_DISPLAY_NAME.value: "프로필 이름을 입력해 주세요.",
    ErrorCode.INVALID_AGENT_PERSONALITY.value: "지원하지 않는 Agent 성격입니다.",
    ErrorCode.INVALID_WARNING_SENSITIVITY.value: "지원하지 않는 경고 민감도입니다.",
    ErrorCode.INVALID_TTS_SPEED.value: "TTS 속도는 0.5 이상 2.0 이하로 설정해야 합니다.",
    ErrorCode.INVALID_EMAIL_FORMAT.value: "올바른 이메일 주소를 입력해 주세요.",
    ErrorCode.INVALID_PROFILE_SETTING.value: "프로필 설정값이 올바르지 않습니다.",
}

PLACE_VALIDATION_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_COORDINATES.value: "위도 또는 경도 값이 올바르지 않습니다.",
    ErrorCode.EMPTY_PLACE_ADDRESS.value: "장소 주소를 입력해 주세요.",
    ErrorCode.INVALID_PLACE_SETTING.value: "장소 설정값이 올바르지 않습니다.",
}

QUERY_VALIDATION_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_PAGE.value: "페이지 번호는 1 이상이어야 합니다.",
    ErrorCode.INVALID_PAGE_SIZE.value: "페이지 크기는 1 이상 100 이하로 설정해야 합니다.",
}

MISSING_FIELD_ERROR_CODES: dict[str, ErrorCode] = {
    "displayName": ErrorCode.INVALID_DISPLAY_NAME,
    "display_name": ErrorCode.INVALID_DISPLAY_NAME,
    "agentPersonality": ErrorCode.INVALID_AGENT_PERSONALITY,
    "agent_personality": ErrorCode.INVALID_AGENT_PERSONALITY,
    "warningSensitivity": ErrorCode.INVALID_WARNING_SENSITIVITY,
    "warning_sensitivity": ErrorCode.INVALID_WARNING_SENSITIVITY,
    "ttsSpeed": ErrorCode.INVALID_TTS_SPEED,
    "tts_speed": ErrorCode.INVALID_TTS_SPEED,
}

PLACE_MISSING_FIELD_ERROR_CODES: dict[str, ErrorCode] = {
    "address": ErrorCode.EMPTY_PLACE_ADDRESS,
    "latitude": ErrorCode.INVALID_COORDINATES,
    "longitude": ErrorCode.INVALID_COORDINATES,
}


def _profile_validation_error(errors: list[dict[str, object]]) -> tuple[str, str] | None:
    if not errors:
        return None

    first_error = errors[0]
    error_type = str(first_error.get("type", ""))
    loc = first_error.get("loc", ())
    field = str(loc[-1]) if isinstance(loc, tuple | list) and loc else ""

    if error_type in PROFILE_VALIDATION_MESSAGES:
        return error_type, PROFILE_VALIDATION_MESSAGES[error_type]

    if error_type == "missing":
        error_code = MISSING_FIELD_ERROR_CODES.get(field, ErrorCode.INVALID_PROFILE_SETTING)
        return error_code.value, PROFILE_VALIDATION_MESSAGES[error_code.value]

    if error_type in {
        "extra_forbidden",
        "int_type",
        "float_type",
        "string_type",
        "model_attributes_type",
    }:
        return (
            ErrorCode.INVALID_PROFILE_SETTING.value,
            PROFILE_VALIDATION_MESSAGES[ErrorCode.INVALID_PROFILE_SETTING.value],
        )

    return None


def _place_validation_error(errors: list[dict[str, object]]) -> tuple[str, str] | None:
    if not errors:
        return None

    first_error = errors[0]
    error_type = str(first_error.get("type", ""))
    loc = first_error.get("loc", ())
    field = str(loc[-1]) if isinstance(loc, tuple | list) and loc else ""

    if error_type in PLACE_VALIDATION_MESSAGES:
        return error_type, PLACE_VALIDATION_MESSAGES[error_type]

    if error_type == "missing":
        error_code = PLACE_MISSING_FIELD_ERROR_CODES.get(field, ErrorCode.INVALID_PLACE_SETTING)
        return error_code.value, PLACE_VALIDATION_MESSAGES[error_code.value]

    if error_type in {
        "extra_forbidden",
        "float_type",
        "float_parsing",
        "string_type",
        "model_attributes_type",
    }:
        error_code = (
            ErrorCode.INVALID_COORDINATES
            if field in {"latitude", "longitude"}
            else ErrorCode.INVALID_PLACE_SETTING
        )
        return error_code.value, PLACE_VALIDATION_MESSAGES[error_code.value]

    return None


def _query_validation_error(errors: list[dict[str, object]]) -> tuple[str, str] | None:
    if not errors:
        return None

    first_error = errors[0]
    loc = first_error.get("loc", ())
    field = str(loc[-1]) if isinstance(loc, tuple | list) and loc else ""

    if field == "page":
        return ErrorCode.INVALID_PAGE.value, QUERY_VALIDATION_MESSAGES[ErrorCode.INVALID_PAGE.value]

    if field == "size":
        return (
            ErrorCode.INVALID_PAGE_SIZE.value,
            QUERY_VALIDATION_MESSAGES[ErrorCode.INVALID_PAGE_SIZE.value],
        )

    return None


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
    path = request.url.path
    if "/search-histories" in path:
        mapped_error = _query_validation_error(exc.errors())
        log_label = "Query"
    elif "/saved-places" in path or "/favorites" in path:
        mapped_error = _place_validation_error(exc.errors())
        log_label = "Saved place"
    elif "/profiles" in path:
        mapped_error = _profile_validation_error(exc.errors())
        log_label = "Profile"
    else:
        mapped_error = None
        log_label = "Validation"

    if mapped_error is not None:
        error_code, message = mapped_error
        logger.warning(
            "%s validation error request_id=%s path=%s error=%s details=%s",
            log_label,
            get_request_id(),
            request.url.path,
            error_code,
            exc.errors(),
        )
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message=message,
            error=error_code,
        )

    logger.warning(
        "Validation error request_id=%s path=%s details=%s",
        get_request_id(),
        request.url.path,
        exc.errors(),
    )
    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
