from app.core.error_codes import ErrorCode


class AppException(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        error_code: ErrorCode | str = ErrorCode.INTERNAL_SERVER_ERROR,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code.value if isinstance(error_code, ErrorCode) else error_code
        super().__init__(message)
