"""FastAPI 依赖注入定义。

集中存放依赖类型别名，endpoint 直接标注使用，例如::

    async def endpoint(db: SessionDep, service: ItemServiceDep) -> ...:
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import ServiceUnavailableError
from app.services.item import ItemService
from app.services.trading.queries import MarketQueryService, TradingQueryService
from app.services.trading.runtime import TradingRuntime

# ---------------------------------------------------------------- 基础设施依赖
SessionDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------- 分页依赖
@dataclass(frozen=True, slots=True)
class PaginationParams:
    """统一分页参数。"""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_pagination(
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量，最大 100")] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]


def get_market_pagination(
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=5000, description="每页数量；行情区间查询通常较大，上限 5000"),
    ] = 500,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


MarketPaginationDep = Annotated[PaginationParams, Depends(get_market_pagination)]


# ---------------------------------------------------------------- 业务依赖
def get_item_service(session: SessionDep) -> ItemService:
    """为单次请求构造示例资源 service。"""
    return ItemService(session)


ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]


# ---------------------------------------------------------------- 交易运行时依赖
def get_runtime(request: Request) -> TradingRuntime:
    """从 lifespan 注入的 ``app.state`` 取交易运行时。"""
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise ServiceUnavailableError("交易运行时未初始化", code="RUNTIME_NOT_READY")

    return runtime


RuntimeDep = Annotated[TradingRuntime, Depends(get_runtime)]


def get_market_query_service(session: SessionDep) -> MarketQueryService:
    return MarketQueryService(session)


MarketQueryServiceDep = Annotated[MarketQueryService, Depends(get_market_query_service)]


def get_trading_query_service(
    session: SessionDep,
    runtime: RuntimeDep,
) -> TradingQueryService:
    return TradingQueryService(session, runtime.oms)


TradingQueryServiceDep = Annotated[
    TradingQueryService,
    Depends(get_trading_query_service),
]
