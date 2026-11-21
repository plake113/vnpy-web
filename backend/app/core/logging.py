"""日志配置。

统一使用标准库 ``logging``：

- 开发环境输出易读的文本格式；
- 生产环境可切换为 JSON，便于日志采集；
- 每条日志自动附带当前请求的 ``request_id``（见 ``middleware.request_context``）。

日志级别等配置来自 :class:`app.core.config.Settings`。
"""

from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar, Token
from typing import Any

from app.core.config import Settings

# 当前请求 ID 的上下文变量；在请求外为 "-"
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_TEXT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | [%(request_id)s] %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_request_id() -> str:
    """返回当前上下文的请求 ID。"""
    return request_id_ctx.get()


def set_request_id(value: str) -> Token[str]:
    """设置请求 ID 并返回用于恢复的 token。"""
    return request_id_ctx.set(value)


def reset_request_id(token: Token[str]) -> None:
    """恢复上一个请求 ID。"""
    request_id_ctx.reset(token)


class RequestIdFilter(logging.Filter):
    """把 ``request_id`` 注入日志记录，供格式化字符串使用。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - 标准库命名
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    """按配置初始化日志系统（可重复调用，会重新加载配置）。"""
    formatter_name = "json" if settings.log_json else "console"

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": RequestIdFilter},
        },
        "formatters": {
            "console": {"format": _TEXT_FORMAT, "datefmt": _DATE_FORMAT},
            "json": {"()": JsonFormatter},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": settings.log_level,
                "formatter": formatter_name,
                "filters": ["request_id"],
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console"],
        },
        # uvicorn 自带 handler 会与 root 重复输出，这里交给 root 统一处理；
        # access 日志由 RequestContextMiddleware 输出（带 request_id 与耗时），避免重复
        "loggers": {
            "uvicorn": {"level": settings.log_level, "handlers": [], "propagate": True},
            "uvicorn.error": {"level": settings.log_level, "handlers": [], "propagate": True},
            "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": False},
            "sqlalchemy.engine": {
                "level": "INFO" if settings.database_echo else "WARNING",
                "handlers": [],
                "propagate": True,
            },
            "alembic": {"level": "INFO", "handlers": [], "propagate": True},
        },
    }

    logging.config.dictConfig(config)
