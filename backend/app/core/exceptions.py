"""统一异常体系与错误响应。

约定所有错误响应结构一致：

.. code-block:: json

    {
      "error": {
        "code": "ITEM_NOT_FOUND",
        "message": "Item 42 不存在",
        "details": null
      },
      "request_id": "3f2a..."
    }

前端 axios 拦截器据此统一提示，无需各页面分别解析错误。
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id
from app.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def _default_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:  # 非标准状态码
        return "Error"


class AppException(Exception):
    """业务异常基类，子类只需覆盖 ``status_code`` / ``code``。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.message = message or _default_phrase(self.status_code)
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppException):
    """请求本身不合法（参数组合、业务前置条件等）。"""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"


class UnauthorizedError(AppException):
    """未认证。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class ForbiddenError(AppException):
    """已认证但无权限。"""

    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class NotFoundError(AppException):
    """资源不存在。"""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppException):
    """资源冲突（如名称重复）。"""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ServiceUnavailableError(AppException):
    """依赖服务不可用。"""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=get_request_id(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


async def _handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, str):
        message, details = exc.detail, None
    else:
        message, details = _default_phrase(exc.status_code), exc.detail
    return _error_response(exc.status_code, f"HTTP_{exc.status_code}", message, details)


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return _error_response(
        # 直接写 422，避免依赖不同 starlette 版本里改名的常量
        422,
        "VALIDATION_ERROR",
        "请求参数校验失败",
        details,
    )


async def _handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled exception: %s %s", request.method, request.url.path
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_SERVER_ERROR",
        "服务器内部错误，请稍后重试",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """把异常处理器挂到应用上，保证错误响应结构统一。

    Starlette 的 handler 签名以 ``Exception`` 为参数类型，这里的具体异常类型更精确，
    因此统一忽略该参数类型告警。
    """
    app.add_exception_handler(AppException, _handle_app_exception)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected_exception)
