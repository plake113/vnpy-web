"""示例资源 schema（占位，替换真实业务时可删除）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    """创建与响应共享的字段。"""

    name: str = Field(min_length=1, max_length=120, description="名称，全局唯一")
    description: str | None = Field(default=None, max_length=1000, description="描述")
    is_active: bool = Field(default=True, description="是否启用")


class ItemCreate(ItemBase):
    """创建请求体。"""

    model_config = ConfigDict(extra="forbid")


class ItemUpdate(BaseModel):
    """更新请求体，所有字段可选；显式传 null 表示清空描述。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class ItemRead(ItemBase):
    """响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
