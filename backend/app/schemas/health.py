"""健康检查相关 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """存活探针响应。"""

    status: Literal["ok"] = "ok"
    app: str = Field(description="应用名称")
    version: str = Field(description="应用版本")
    env: str = Field(description="运行环境")
    timestamp: datetime = Field(description="服务器当前时间（UTC）")


class ReadinessResponse(BaseModel):
    """就绪探针响应，附带关键依赖状态。"""

    status: Literal["ready", "degraded"]
    database: Literal["ok", "unavailable"]
    timestamp: datetime
