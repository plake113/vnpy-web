"""交易 API：委托、成交、持仓、账户、合约、报价的只读查询。

数据由 ``TradingQueryService`` 合并 DB（事实来源）与 OMS（尚未落库的最新状态）。
当前没有下单 / 撤单接口；写操作需要等鉴权、风控与交易用例落地。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import PaginationDep, TradingQueryServiceDep
from app.schemas.common import Page
from app.schemas.trading import (
    AccountRead,
    ContractRead,
    OrderRead,
    PositionRead,
    QuoteRead,
    TradeRead,
)

router = APIRouter()


@router.get("/orders", response_model=Page[OrderRead], summary="分页查询委托")
async def list_orders(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
    instrument_key: Annotated[
        str | None,
        Query(max_length=128, description="按合约键过滤"),
    ] = None,
    active_only: Annotated[
        bool,
        Query(description="只返回提交中 / 未成交 / 部分成交的委托"),
    ] = False,
) -> Page[OrderRead]:
    return await service.list_orders(
        page=pagination.page,
        page_size=pagination.page_size,
        instrument_key=instrument_key,
        active_only=active_only,
    )


@router.get("/orders/{order_key}", response_model=OrderRead, summary="查询委托详情")
async def get_order(
    service: TradingQueryServiceDep,
    order_key: Annotated[
        str,
        Path(min_length=1, max_length=160, description="跨网关委托键，例如 CTP.12345"),
    ],
) -> OrderRead:
    return await service.get_order(order_key)


@router.get("/trades", response_model=Page[TradeRead], summary="分页查询成交")
async def list_trades(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
    instrument_key: Annotated[
        str | None,
        Query(max_length=128, description="按合约键过滤"),
    ] = None,
) -> Page[TradeRead]:
    return await service.list_trades(
        page=pagination.page,
        page_size=pagination.page_size,
        instrument_key=instrument_key,
    )


@router.get("/positions", response_model=Page[PositionRead], summary="分页查询持仓")
async def list_positions(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
) -> Page[PositionRead]:
    return await service.list_positions(
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/accounts", response_model=Page[AccountRead], summary="分页查询资金账户")
async def list_accounts(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
) -> Page[AccountRead]:
    return await service.list_accounts(
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/contracts", response_model=Page[ContractRead], summary="分页查询合约")
async def list_contracts(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
    instrument_key: Annotated[
        str | None,
        Query(max_length=128, description="按合约键精确过滤"),
    ] = None,
) -> Page[ContractRead]:
    return await service.list_contracts(
        page=pagination.page,
        page_size=pagination.page_size,
        instrument_key=instrument_key,
    )


@router.get("/quotes", response_model=Page[QuoteRead], summary="分页查询报价")
async def list_quotes(
    service: TradingQueryServiceDep,
    pagination: PaginationDep,
    instrument_key: Annotated[
        str | None,
        Query(max_length=128, description="按合约键过滤"),
    ] = None,
) -> Page[QuoteRead]:
    return await service.list_quotes(
        page=pagination.page,
        page_size=pagination.page_size,
        instrument_key=instrument_key,
    )
