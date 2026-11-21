"""行情 API：历史 K 线与数据概览。

只读接口，数据来自数据库（``MarketQueryService``）；实时行情推送属于后续 WebSocket 单元。
时间参数要求带时区（UTC ISO），与仓储的 UTC 边界一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import MarketPaginationDep, MarketQueryServiceDep
from app.domain.enums import Interval
from app.schemas.common import Page
from app.schemas.market_data import BarRead, MarketOverviewRead

router = APIRouter()


@router.get("/bars", response_model=Page[BarRead], summary="分页查询历史 K 线")
async def list_bars(
    service: MarketQueryServiceDep,
    pagination: MarketPaginationDep,
    instrument_key: Annotated[str, Query(min_length=1, max_length=128, description="合约键")],
    interval: Annotated[Interval, Query(description="K 线周期")],
    start: Annotated[datetime, Query(description="起始时间（UTC，含）")],
    end: Annotated[datetime, Query(description="结束时间（UTC，含）")],
) -> Page[BarRead]:
    return await service.list_bars(
        instrument_key=instrument_key,
        interval=interval,
        start=start,
        end=end,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/overview", response_model=MarketOverviewRead, summary="行情数据概览")
async def get_market_overview(service: MarketQueryServiceDep) -> MarketOverviewRead:
    return await service.get_overview()
