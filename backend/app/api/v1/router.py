"""v1 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, items, market, trading

router = APIRouter()

router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(market.router, prefix="/market", tags=["market"])
router.include_router(trading.router, tags=["trading"])
