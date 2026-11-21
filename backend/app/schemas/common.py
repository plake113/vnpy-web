"""Pydantic 请求 / 响应契约（schema）。

命名约定：

- ``XxxCreate``：POST 请求体；
- ``XxxUpdate``：PATCH 请求体，字段全部可选；
- ``XxxRead``：响应体，``from_attributes=True`` 可直接由 ORM 对象转换。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.utils.pagination import compute_pages

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """错误详情。"""

    code: str = Field(description="稳定的错误码，前端据此判断处理方式")
    message: str = Field(description="可读的错误信息")
    details: Any | None = Field(default=None, description="附加信息，如字段校验错误列表")


class ErrorResponse(BaseModel):
    """统一错误响应外层结构。"""

    error: ErrorDetail
    request_id: str | None = Field(default=None, description="本次请求的追踪 ID")


class Page(BaseModel, Generic[T]):
    """统一分页响应结构。"""

    items: list[T] = Field(description="当前页数据")
    total: int = Field(description="总记录数")
    page: int = Field(description="当前页码，从 1 开始")
    page_size: int = Field(description="每页数量")
    pages: int = Field(description="总页数")

    @classmethod
    def create(
        cls,
        *,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> Page[T]:
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=compute_pages(total, page_size),
        )


class Message(BaseModel):
    """简单的消息响应。"""

    message: str
