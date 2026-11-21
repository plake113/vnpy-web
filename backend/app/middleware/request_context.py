"""请求上下文中间件。

为每个请求建立：

- ``request_id``：优先复用上游传入的 ``X-Request-ID``，否则生成 UUID；
- 结构化访问日志：方法、路径、状态码、耗时、客户端；
- 响应头 ``X-Request-ID`` / ``X-Process-Time``，便于前端与链路上追踪。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import reset_request_id, set_request_id

logger = logging.getLogger("app.request")

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """注入请求 ID 并输出访问日志。"""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = set_request_id(request_id)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            # 这里只记录请求级信息；异常堆栈由全局异常处理器统一记录，避免重复
            logger.warning(
                "request failed method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        else:
            duration_ms = (time.perf_counter() - started_at) * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{duration_ms:.2f}"
            logger.info(
                "request method=%s path=%s status=%d duration_ms=%.2f client=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                request.client.host if request.client else "-",
            )
            return response
        finally:
            reset_request_id(token)
