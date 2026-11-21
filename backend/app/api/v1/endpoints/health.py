"""健康检查 endpoint。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep, SettingsDep
from app.schemas.health import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="存活探针")
async def health(settings: SettingsDep) -> HealthResponse:
    """不访问数据库，用于容器 / 负载均衡存活检查。"""
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        env=settings.app_env,
        timestamp=datetime.now(UTC),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="就绪探针")
async def readiness(db: SessionDep) -> ReadinessResponse:
    """检查数据库连通性，返回 ``ready`` / ``degraded``。"""
    database: Literal["ok", "unavailable"] = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("readiness check failed: database unavailable")
        database = "unavailable"

    return ReadinessResponse(
        status="ready" if database == "ok" else "degraded",
        database=database,
        timestamp=datetime.now(UTC),
    )
