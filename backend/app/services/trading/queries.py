"""交易 / 行情查询 service。

职责边界：

- **行情历史**：只查数据库（``crud.market_data``），支持区间 + 分页；
- **交易数据**：DB 是事实来源，OMS 是尚未落库的即时状态；查询时按业务键合并，
  同一键以 OMS 为准（更新鲜），从而掩盖“事件已到、持久化还没写完”的窗口；
- 当前合并后再内存分页，交易数据量小可以接受；数据量上来后应改为 DB 分页 +
  对当前页的键做 OMS 覆盖（已在 ``MIGRATION.md`` 记录）。

API 层只依赖本 service；时间参数在这里做 aware 校验，统一交给仓储转 UTC。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.crud.market_data import (
    count_bars,
    get_bar_overview,
    get_tick_overview,
    load_bars,
)
from app.crud.trading import (
    get_order as get_order_record,
)
from app.crud.trading import (
    load_accounts,
    load_contracts,
    load_orders,
    load_positions,
    load_quotes,
    load_trades,
)
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import Interval
from app.domain.orders import OrderData
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.trades import TradeData
from app.schemas.common import Page
from app.schemas.market_data import (
    BarOverviewRead,
    BarRead,
    MarketOverviewRead,
    TickOverviewRead,
)
from app.schemas.trading import (
    AccountRead,
    ContractRead,
    OrderRead,
    PositionRead,
    QuoteRead,
    TradeRead,
)
from app.services.trading.oms import OmsService

__all__ = ["MarketQueryService", "TradingQueryService"]

_T = TypeVar("_T")


def _merge_by_key(
    db_items: list[_T],
    oms_items: list[_T],
    key: Callable[[_T], str],
) -> list[_T]:
    """按业务键合并 DB 与 OMS，OMS 覆盖同键的 DB 记录，结果按键排序。"""
    merged: dict[str, _T] = {key(item): item for item in db_items}
    for item in oms_items:
        merged[key(item)] = item

    return [merged[item_key] for item_key in sorted(merged)]


def _paginate(items: list[_T], page: int, page_size: int) -> list[_T]:
    offset = (page - 1) * page_size
    return items[offset : offset + page_size]


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BadRequestError(
            f"{name} 必须带时区（ISO 8601，例如 2024-01-01T00:00:00Z）",
            code="INVALID_DATETIME",
        )


class MarketQueryService:
    """历史行情查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_bars(
        self,
        *,
        instrument_key: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        page: int,
        page_size: int,
    ) -> Page[BarRead]:
        """按合约 + 周期 + 时间区间分页查询 K 线。"""
        _require_aware("start", start)
        _require_aware("end", end)
        if start > end:
            raise BadRequestError("start 不能晚于 end", code="INVALID_TIME_RANGE")

        try:
            total = await count_bars(self._session, instrument_key, interval, start, end)
            bars = await load_bars(
                self._session,
                instrument_key,
                interval,
                start,
                end,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        except ValueError as exc:
            raise BadRequestError(str(exc), code="INVALID_DATETIME") from exc

        return Page[BarRead].create(
            items=[BarRead.model_validate(bar) for bar in bars],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_overview(self) -> MarketOverviewRead:
        """返回数据库里 K 线 / Tick 的概览。"""
        bars = await get_bar_overview(self._session)
        ticks = await get_tick_overview(self._session)

        return MarketOverviewRead(
            bars=[BarOverviewRead.model_validate(item) for item in bars],
            ticks=[TickOverviewRead.model_validate(item) for item in ticks],
        )


class TradingQueryService:
    """交易数据查询：DB 事实 + OMS 即时状态。"""

    def __init__(self, session: AsyncSession, oms: OmsService) -> None:
        self._session = session
        self._oms = oms

    async def list_orders(
        self,
        *,
        page: int,
        page_size: int,
        instrument_key: str | None = None,
        active_only: bool = False,
    ) -> Page[OrderRead]:
        """分页查询委托；同键以 OMS 最新状态为准。"""
        orders: list[OrderData] = _merge_by_key(
            await load_orders(self._session),
            self._oms.get_all_orders(),
            lambda order: order.order_key,
        )
        if instrument_key is not None:
            orders = [order for order in orders if order.instrument_key == instrument_key]
        if active_only:
            orders = [order for order in orders if order.is_active()]

        return Page[OrderRead].create(
            items=[OrderRead.model_validate(order) for order in _paginate(orders, page, page_size)],
            total=len(orders),
            page=page,
            page_size=page_size,
        )

    async def get_order(self, order_key: str) -> OrderRead:
        """按委托键查询；OMS 未命中时回落数据库。"""
        order: OrderData | None = self._oms.get_order(order_key)
        if order is None:
            order = await get_order_record(self._session, order_key)

        if order is None:
            raise NotFoundError(
                f"委托 {order_key!r} 不存在",
                code="ORDER_NOT_FOUND",
            )

        return OrderRead.model_validate(order)

    async def list_trades(
        self,
        *,
        page: int,
        page_size: int,
        instrument_key: str | None = None,
    ) -> Page[TradeRead]:
        """分页查询成交；同键以 OMS 为准。"""
        trades: list[TradeData] = _merge_by_key(
            await load_trades(self._session),
            self._oms.get_all_trades(),
            lambda trade: trade.trade_key,
        )
        if instrument_key is not None:
            trades = [trade for trade in trades if trade.instrument_key == instrument_key]

        return Page[TradeRead].create(
            items=[TradeRead.model_validate(trade) for trade in _paginate(trades, page, page_size)],
            total=len(trades),
            page=page,
            page_size=page_size,
        )

    async def list_positions(self, *, page: int, page_size: int) -> Page[PositionRead]:
        """分页查询持仓；同键以 OMS 为准。"""
        positions: list[PositionData] = _merge_by_key(
            await load_positions(self._session),
            self._oms.get_all_positions(),
            lambda position: position.position_key,
        )

        return Page[PositionRead].create(
            items=[
                PositionRead.model_validate(position)
                for position in _paginate(positions, page, page_size)
            ],
            total=len(positions),
            page=page,
            page_size=page_size,
        )

    async def list_accounts(self, *, page: int, page_size: int) -> Page[AccountRead]:
        """分页查询账户；同键以 OMS 为准。"""
        accounts: list[AccountData] = _merge_by_key(
            await load_accounts(self._session),
            self._oms.get_all_accounts(),
            lambda account: account.account_key,
        )

        return Page[AccountRead].create(
            items=[
                AccountRead.model_validate(account)
                for account in _paginate(accounts, page, page_size)
            ],
            total=len(accounts),
            page=page,
            page_size=page_size,
        )

    async def list_contracts(
        self,
        *,
        page: int,
        page_size: int,
        instrument_key: str | None = None,
    ) -> Page[ContractRead]:
        """分页查询合约；可按合约键精确过滤。"""
        contracts: list[ContractData] = _merge_by_key(
            await load_contracts(self._session),
            self._oms.get_all_contracts(),
            lambda contract: contract.instrument_key,
        )
        if instrument_key is not None:
            contracts = [
                contract for contract in contracts if contract.instrument_key == instrument_key
            ]

        return Page[ContractRead].create(
            items=[
                ContractRead.model_validate(contract)
                for contract in _paginate(contracts, page, page_size)
            ],
            total=len(contracts),
            page=page,
            page_size=page_size,
        )

    async def list_quotes(
        self,
        *,
        page: int,
        page_size: int,
        instrument_key: str | None = None,
    ) -> Page[QuoteRead]:
        """分页查询报价；同键以 OMS 为准。"""
        quotes: list[QuoteData] = _merge_by_key(
            await load_quotes(self._session),
            self._oms.get_all_quotes(),
            lambda quote: quote.quote_key,
        )
        if instrument_key is not None:
            quotes = [quote for quote in quotes if quote.instrument_key == instrument_key]

        return Page[QuoteRead].create(
            items=[QuoteRead.model_validate(quote) for quote in _paginate(quotes, page, page_size)],
            total=len(quotes),
            page=page,
            page_size=page_size,
        )
