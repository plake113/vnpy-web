"""交易数据仓储：合约、委托、成交、持仓、账户、报价的读写。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 的对应数据类与 ``vnpy/trader/database.py``
（MIT License，© Xiaoyou Chen）。

写入语义（与数据性质匹配）：

- **合约 / 委托 / 持仓 / 账户 / 报价**：最新状态快照，按业务键 ``upsert`` 覆盖，
  其中委托只保留最新状态（不追加历史）；
- **成交**：不可变事实，按 ``trade_key`` 插入忽略，重复回报不覆盖已有记录。

时间：可选时间列允许为空；非空时只接受 aware 时间，统一转 UTC 存储、读取补回 UTC
（时间统一 UTC，规则见 :mod:`app.utils.timezone`）。枚举列存机器码，读回时还原为领域枚举。

本模块只做读写、不提交事务；分页、过滤组合与用户可见错误由 service / API 层负责。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import insert_ignore, upsert
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import (
    Direction,
    Exchange,
    Offset,
    OptionType,
    OrderType,
    Product,
    Status,
)
from app.domain.orders import OrderData
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.trades import TradeData
from app.models.trading import (
    AccountRecord,
    ContractRecord,
    OrderRecord,
    PositionRecord,
    QuoteRecord,
    TradeRecord,
)
from app.utils.timezone import from_utc, to_utc_naive

__all__ = [
    "get_account",
    "get_contract",
    "get_order",
    "get_position",
    "get_quote",
    "get_trade",
    "load_accounts",
    "load_contracts",
    "load_orders",
    "load_positions",
    "load_quotes",
    "load_trades",
    "save_accounts",
    "save_contracts",
    "save_orders",
    "save_positions",
    "save_quotes",
    "save_trades",
]

#: 仍活跃的委托状态机器码，用于 ``active_only`` 过滤。
_ACTIVE_STATUS_VALUES: list[str] = [status.value for status in Status if status.is_active]


def _optional_to_db(value: datetime | None) -> datetime | None:
    return None if value is None else to_utc_naive(value)


def _optional_from_db(value: datetime | None) -> datetime | None:
    return None if value is None else from_utc(value)


# ---------------------------------------------------------------------------- 合约


def _contract_values(contract: ContractData) -> dict[str, Any]:
    return {
        "gateway_name": contract.gateway_name,
        "instrument_key": contract.instrument_key,
        "symbol": contract.symbol,
        "exchange": contract.exchange.value,
        "name": contract.name,
        "product": contract.product.value,
        "size": contract.size,
        "pricetick": contract.pricetick,
        "min_volume": contract.min_volume,
        "max_volume": contract.max_volume,
        "stop_supported": contract.stop_supported,
        "net_position": contract.net_position,
        "history_data": contract.history_data,
        "option_strike": contract.option_strike,
        "option_underlying_key": contract.option_underlying_key,
        "option_type": contract.option_type.value if contract.option_type is not None else None,
        "option_listed": _optional_to_db(contract.option_listed),
        "option_expiry": _optional_to_db(contract.option_expiry),
        "option_portfolio": contract.option_portfolio,
        "option_index": contract.option_index,
    }


def _contract_to_domain(record: ContractRecord) -> ContractData:
    return ContractData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        name=record.name,
        product=Product(record.product),
        size=record.size,
        pricetick=record.pricetick,
        min_volume=record.min_volume,
        max_volume=record.max_volume,
        stop_supported=record.stop_supported,
        net_position=record.net_position,
        history_data=record.history_data,
        option_strike=record.option_strike,
        option_underlying_key=record.option_underlying_key,
        option_type=OptionType(record.option_type) if record.option_type is not None else None,
        option_listed=_optional_from_db(record.option_listed),
        option_expiry=_optional_from_db(record.option_expiry),
        option_portfolio=record.option_portfolio,
        option_index=record.option_index,
    )


async def save_contracts(db: AsyncSession, contracts: Sequence[ContractData]) -> None:
    """批量保存合约静态信息；同合约重复写入时覆盖为最新值。"""
    await upsert(
        db,
        ContractRecord,
        [_contract_values(contract) for contract in contracts],
        key_columns=["instrument_key"],
        set_extra={"updated_at": func.now()},
    )


async def get_contract(db: AsyncSession, instrument_key: str) -> ContractData | None:
    """按合约键查询。"""
    record = await db.scalar(
        select(ContractRecord).where(ContractRecord.instrument_key == instrument_key)
    )

    return None if record is None else _contract_to_domain(record)


async def load_contracts(db: AsyncSession) -> list[ContractData]:
    """返回全部合约，按合约键排序。"""
    records = (
        (await db.execute(select(ContractRecord).order_by(ContractRecord.instrument_key)))
        .scalars()
        .all()
    )

    return [_contract_to_domain(record) for record in records]


# ---------------------------------------------------------------------------- 委托


def _order_values(order: OrderData) -> dict[str, Any]:
    return {
        "gateway_name": order.gateway_name,
        "instrument_key": order.instrument_key,
        "symbol": order.symbol,
        "exchange": order.exchange.value,
        "order_id": order.order_id,
        "order_key": order.order_key,
        "type": order.type.value,
        "direction": order.direction.value if order.direction is not None else None,
        "offset": order.offset.value,
        "price": order.price,
        "volume": order.volume,
        "traded": order.traded,
        "status": order.status.value,
        "datetime": _optional_to_db(order.datetime),
        "reference": order.reference,
    }


def _order_to_domain(record: OrderRecord) -> OrderData:
    return OrderData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        order_id=record.order_id,
        type=OrderType(record.type),
        direction=Direction(record.direction) if record.direction is not None else None,
        offset=Offset(record.offset),
        price=record.price,
        volume=record.volume,
        traded=record.traded,
        status=Status(record.status),
        datetime=_optional_from_db(record.datetime),
        reference=record.reference,
    )


async def save_orders(db: AsyncSession, orders: Sequence[OrderData]) -> None:
    """批量保存委托；同一 ``order_key`` 覆盖为最新状态。"""
    await upsert(
        db,
        OrderRecord,
        [_order_values(order) for order in orders],
        key_columns=["order_key"],
        set_extra={"updated_at": func.now()},
    )


async def get_order(db: AsyncSession, order_key: str) -> OrderData | None:
    """按委托键查询。"""
    record = await db.scalar(select(OrderRecord).where(OrderRecord.order_key == order_key))

    return None if record is None else _order_to_domain(record)


async def load_orders(
    db: AsyncSession,
    *,
    instrument_key: str | None = None,
    active_only: bool = False,
) -> list[OrderData]:
    """返回委托列表；可按合约过滤、只取活跃委托，按写入顺序排列。"""
    statement = select(OrderRecord)
    if instrument_key is not None:
        statement = statement.where(OrderRecord.instrument_key == instrument_key)
    if active_only:
        statement = statement.where(OrderRecord.status.in_(_ACTIVE_STATUS_VALUES))

    records = (await db.execute(statement.order_by(OrderRecord.id))).scalars().all()

    return [_order_to_domain(record) for record in records]


# ---------------------------------------------------------------------------- 成交


def _trade_values(trade: TradeData) -> dict[str, Any]:
    return {
        "gateway_name": trade.gateway_name,
        "instrument_key": trade.instrument_key,
        "symbol": trade.symbol,
        "exchange": trade.exchange.value,
        "order_id": trade.order_id,
        "trade_id": trade.trade_id,
        "trade_key": trade.trade_key,
        "direction": trade.direction.value if trade.direction is not None else None,
        "offset": trade.offset.value,
        "price": trade.price,
        "volume": trade.volume,
        "datetime": _optional_to_db(trade.datetime),
    }


def _trade_to_domain(record: TradeRecord) -> TradeData:
    return TradeData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        order_id=record.order_id,
        trade_id=record.trade_id,
        direction=Direction(record.direction) if record.direction is not None else None,
        offset=Offset(record.offset),
        price=record.price,
        volume=record.volume,
        datetime=_optional_from_db(record.datetime),
    )


async def save_trades(db: AsyncSession, trades: Sequence[TradeData]) -> None:
    """批量保存成交；同一 ``trade_key`` 重复写入被忽略（不可变事实）。"""
    await insert_ignore(db, TradeRecord, [_trade_values(trade) for trade in trades])


async def get_trade(db: AsyncSession, trade_key: str) -> TradeData | None:
    """按成交键查询。"""
    record = await db.scalar(select(TradeRecord).where(TradeRecord.trade_key == trade_key))

    return None if record is None else _trade_to_domain(record)


async def load_trades(
    db: AsyncSession,
    *,
    instrument_key: str | None = None,
) -> list[TradeData]:
    """返回成交列表；可按合约过滤，按写入顺序排列。"""
    statement = select(TradeRecord)
    if instrument_key is not None:
        statement = statement.where(TradeRecord.instrument_key == instrument_key)

    records = (await db.execute(statement.order_by(TradeRecord.id))).scalars().all()

    return [_trade_to_domain(record) for record in records]


# ---------------------------------------------------------------------------- 持仓


def _position_values(position: PositionData) -> dict[str, Any]:
    return {
        "gateway_name": position.gateway_name,
        "instrument_key": position.instrument_key,
        "symbol": position.symbol,
        "exchange": position.exchange.value,
        "position_key": position.position_key,
        "direction": position.direction.value,
        "volume": position.volume,
        "frozen": position.frozen,
        "price": position.price,
        "pnl": position.pnl,
        "yd_volume": position.yd_volume,
    }


def _position_to_domain(record: PositionRecord) -> PositionData:
    return PositionData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        direction=Direction(record.direction),
        volume=record.volume,
        frozen=record.frozen,
        price=record.price,
        pnl=record.pnl,
        yd_volume=record.yd_volume,
    )


async def save_positions(db: AsyncSession, positions: Sequence[PositionData]) -> None:
    """批量保存持仓；同一 ``position_key`` 覆盖为最新快照。"""
    await upsert(
        db,
        PositionRecord,
        [_position_values(position) for position in positions],
        key_columns=["position_key"],
        set_extra={"updated_at": func.now()},
    )


async def get_position(db: AsyncSession, position_key: str) -> PositionData | None:
    """按持仓键查询。"""
    record = await db.scalar(
        select(PositionRecord).where(PositionRecord.position_key == position_key)
    )

    return None if record is None else _position_to_domain(record)


async def load_positions(db: AsyncSession) -> list[PositionData]:
    """返回全部持仓，按写入顺序排列。"""
    records = (
        (await db.execute(select(PositionRecord).order_by(PositionRecord.id)))
        .scalars()
        .all()
    )

    return [_position_to_domain(record) for record in records]


# ---------------------------------------------------------------------------- 账户


def _account_values(account: AccountData) -> dict[str, Any]:
    return {
        "gateway_name": account.gateway_name,
        "account_key": account.account_key,
        "account_id": account.account_id,
        "balance": account.balance,
        "frozen": account.frozen,
    }


def _account_to_domain(record: AccountRecord) -> AccountData:
    return AccountData(
        gateway_name=record.gateway_name,
        account_id=record.account_id,
        balance=record.balance,
        frozen=record.frozen,
    )


async def save_accounts(db: AsyncSession, accounts: Sequence[AccountData]) -> None:
    """批量保存账户；同一 ``account_key`` 覆盖为最新快照。"""
    await upsert(
        db,
        AccountRecord,
        [_account_values(account) for account in accounts],
        key_columns=["account_key"],
        set_extra={"updated_at": func.now()},
    )


async def get_account(db: AsyncSession, account_key: str) -> AccountData | None:
    """按账户键查询。"""
    record = await db.scalar(
        select(AccountRecord).where(AccountRecord.account_key == account_key)
    )

    return None if record is None else _account_to_domain(record)


async def load_accounts(db: AsyncSession) -> list[AccountData]:
    """返回全部账户，按写入顺序排列。"""
    records = (
        (await db.execute(select(AccountRecord).order_by(AccountRecord.id)))
        .scalars()
        .all()
    )

    return [_account_to_domain(record) for record in records]


# ---------------------------------------------------------------------------- 报价


def _quote_values(quote: QuoteData) -> dict[str, Any]:
    return {
        "gateway_name": quote.gateway_name,
        "instrument_key": quote.instrument_key,
        "symbol": quote.symbol,
        "exchange": quote.exchange.value,
        "quote_id": quote.quote_id,
        "quote_key": quote.quote_key,
        "bid_price": quote.bid_price,
        "bid_volume": quote.bid_volume,
        "ask_price": quote.ask_price,
        "ask_volume": quote.ask_volume,
        "bid_offset": quote.bid_offset.value,
        "ask_offset": quote.ask_offset.value,
        "status": quote.status.value,
        "datetime": _optional_to_db(quote.datetime),
        "reference": quote.reference,
    }


def _quote_to_domain(record: QuoteRecord) -> QuoteData:
    return QuoteData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        quote_id=record.quote_id,
        bid_price=record.bid_price,
        bid_volume=record.bid_volume,
        ask_price=record.ask_price,
        ask_volume=record.ask_volume,
        bid_offset=Offset(record.bid_offset),
        ask_offset=Offset(record.ask_offset),
        status=Status(record.status),
        datetime=_optional_from_db(record.datetime),
        reference=record.reference,
    )


async def save_quotes(db: AsyncSession, quotes: Sequence[QuoteData]) -> None:
    """批量保存报价；同一 ``quote_key`` 覆盖为最新状态。"""
    await upsert(
        db,
        QuoteRecord,
        [_quote_values(quote) for quote in quotes],
        key_columns=["quote_key"],
        set_extra={"updated_at": func.now()},
    )


async def get_quote(db: AsyncSession, quote_key: str) -> QuoteData | None:
    """按报价键查询。"""
    record = await db.scalar(select(QuoteRecord).where(QuoteRecord.quote_key == quote_key))

    return None if record is None else _quote_to_domain(record)


async def load_quotes(db: AsyncSession) -> list[QuoteData]:
    """返回全部报价，按写入顺序排列。"""
    records = (
        (await db.execute(select(QuoteRecord).order_by(QuoteRecord.id)))
        .scalars()
        .all()
    )

    return [_quote_to_domain(record) for record in records]
