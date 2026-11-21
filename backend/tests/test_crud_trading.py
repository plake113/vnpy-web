"""``trader/database.py`` + 领域对象 → ``app/crud/trading.py`` 的持久化测试。

全部使用 SQLite 内存库，验证：

- 合约 / 委托 / 持仓 / 账户 / 报价按业务键 upsert 覆盖最新状态；
- 成交按 ``trade_key`` 插入忽略（不可变事实）；
- 枚举、可选时间、盘口 / 报价字段完整往返，时间统一 UTC；
- 委托列表支持合约过滤与活跃过滤；未知键返回 ``None``。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.trading import (
    get_account,
    get_contract,
    get_order,
    get_position,
    get_quote,
    get_trade,
    load_accounts,
    load_contracts,
    load_orders,
    load_positions,
    load_quotes,
    load_trades,
    save_accounts,
    save_contracts,
    save_orders,
    save_positions,
    save_quotes,
    save_trades,
)
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


def dt(hour: int = 9, minute: int = 0, day: int = 2) -> datetime:
    return datetime(2024, 1, day, hour, minute, tzinfo=UTC)


def make_contract(**overrides: object) -> ContractData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "symbol": "IO2412",
        "exchange": Exchange.CFFEX,
        "name": "IO2412-C-4000",
        "product": Product.OPTION,
        "size": 300,
        "pricetick": 0.2,
        "min_volume": 1,
        "max_volume": 100,
        "stop_supported": False,
        "net_position": False,
        "history_data": True,
        "option_strike": 4000,
        "option_underlying_key": "IF2412.CFFEX",
        "option_type": OptionType.CALL,
        "option_listed": dt(day=1),
        "option_expiry": dt(day=30),
        "option_portfolio": "IO",
        "option_index": "1",
    }
    values.update(overrides)
    return ContractData(**values)  # type: ignore[arg-type]


def make_order(**overrides: object) -> OrderData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "order_id": "0001",
        "type": OrderType.LIMIT,
        "direction": Direction.LONG,
        "offset": Offset.OPEN,
        "price": 3500,
        "volume": 2,
        "traded": 0,
        "status": Status.NOTTRADED,
        "datetime": dt(),
        "reference": "ref-1",
    }
    values.update(overrides)
    return OrderData(**values)  # type: ignore[arg-type]


def make_trade(**overrides: object) -> TradeData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "order_id": "0001",
        "trade_id": "T001",
        "direction": Direction.LONG,
        "offset": Offset.OPEN,
        "price": 3500,
        "volume": 1,
        "datetime": dt(),
    }
    values.update(overrides)
    return TradeData(**values)  # type: ignore[arg-type]


def make_position(**overrides: object) -> PositionData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "direction": Direction.LONG,
        "volume": 10,
        "frozen": 2,
        "price": 3500,
        "pnl": 120,
        "yd_volume": 4,
    }
    values.update(overrides)
    return PositionData(**values)  # type: ignore[arg-type]


def make_account(**overrides: object) -> AccountData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "account_id": "ACC001",
        "balance": 1_000_000,
        "frozen": 10_000,
    }
    values.update(overrides)
    return AccountData(**values)  # type: ignore[arg-type]


def make_quote(**overrides: object) -> QuoteData:
    values: dict[str, object] = {
        "gateway_name": "FAKE",
        "symbol": "IO2412",
        "exchange": Exchange.CFFEX,
        "quote_id": "Q001",
        "bid_price": 3900,
        "bid_volume": 2,
        "ask_price": 3901,
        "ask_volume": 3,
        "bid_offset": Offset.OPEN,
        "ask_offset": Offset.OPEN,
        "status": Status.NOTTRADED,
        "datetime": dt(),
        "reference": "quote-ref",
    }
    values.update(overrides)
    return QuoteData(**values)  # type: ignore[arg-type]


async def test_contract_roundtrip_and_upsert(db_session: AsyncSession) -> None:
    contract = make_contract()

    await save_contracts(db_session, [contract])

    loaded = await get_contract(db_session, "IO2412.CFFEX")
    assert loaded == contract

    updated = replace(contract, name="IO2412-C-4100", pricetick=0.4)
    await save_contracts(db_session, [updated])

    reloaded = await get_contract(db_session, "IO2412.CFFEX")
    assert reloaded is not None
    assert reloaded.name == "IO2412-C-4100"
    assert reloaded.pricetick == 0.4
    assert len(await load_contracts(db_session)) == 1


async def test_contract_optional_fields_and_naive_time_rejection(
    db_session: AsyncSession,
) -> None:
    plain = make_contract(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        product=Product.FUTURES,
        option_strike=None,
        option_underlying_key=None,
        option_type=None,
        option_listed=None,
        option_expiry=None,
        option_portfolio=None,
        option_index=None,
        max_volume=None,
    )
    await save_contracts(db_session, [plain])
    assert await get_contract(db_session, "rb2410.SHFE") == plain

    naive = make_contract(option_listed=datetime(2024, 1, 1))
    with pytest.raises(ValueError, match="带时区"):
        await save_contracts(db_session, [naive])


async def test_order_roundtrip_and_upsert(db_session: AsyncSession) -> None:
    order = make_order()

    await save_orders(db_session, [order])

    assert await get_order(db_session, "FAKE.0001") == order

    updated = replace(order, status=Status.ALLTRADED, traded=2)
    await save_orders(db_session, [updated])

    reloaded = await get_order(db_session, "FAKE.0001")
    assert reloaded is not None
    assert reloaded.status is Status.ALLTRADED
    assert reloaded.traded == 2
    assert len(await load_orders(db_session)) == 1


async def test_order_optional_direction_and_datetime(db_session: AsyncSession) -> None:
    order = make_order(direction=None, datetime=None)

    await save_orders(db_session, [order])

    assert await get_order(db_session, "FAKE.0001") == order


async def test_load_orders_filters_by_instrument_and_active(
    db_session: AsyncSession,
) -> None:
    await save_orders(
        db_session,
        [
            make_order(order_id="0001", status=Status.NOTTRADED),
            make_order(order_id="0002", status=Status.ALLTRADED),
            make_order(
                order_id="0003",
                status=Status.SUBMITTING,
                symbol="IF2412",
                exchange=Exchange.CFFEX,
            ),
        ],
    )

    rub_bars = await load_orders(db_session, instrument_key="rb2410.SHFE")
    active_rub = await load_orders(db_session, instrument_key="rb2410.SHFE", active_only=True)
    all_active = await load_orders(db_session, active_only=True)

    assert [order.order_key for order in rub_bars] == ["FAKE.0001", "FAKE.0002"]
    assert [order.order_key for order in active_rub] == ["FAKE.0001"]
    assert [order.order_key for order in all_active] == ["FAKE.0001", "FAKE.0003"]


async def test_trade_insert_is_ignored_on_duplicate_key(
    db_session: AsyncSession,
) -> None:
    trade = make_trade()
    conflicting = replace(trade, price=9999, volume=9)

    await save_trades(db_session, [trade])
    await save_trades(db_session, [conflicting])

    assert await get_trade(db_session, "FAKE.T001") == trade
    assert len(await load_trades(db_session)) == 1


async def test_position_upsert_latest_snapshot(db_session: AsyncSession) -> None:
    position = make_position()
    await save_positions(db_session, [position])
    assert await get_position(db_session, "FAKE.rb2410.SHFE.LONG") == position

    updated = replace(position, volume=3, frozen=0)
    await save_positions(db_session, [updated])

    reloaded = await get_position(db_session, "FAKE.rb2410.SHFE.LONG")
    assert reloaded is not None
    assert reloaded.volume == 3
    assert len(await load_positions(db_session)) == 1


async def test_account_upsert_latest_snapshot(db_session: AsyncSession) -> None:
    account = make_account()
    await save_accounts(db_session, [account])

    updated = replace(account, balance=900_000, frozen=20_000)
    await save_accounts(db_session, [updated])

    reloaded = await get_account(db_session, "FAKE.ACC001")
    assert reloaded is not None
    assert reloaded.balance == 900_000
    assert reloaded.available == 880_000
    assert len(await load_accounts(db_session)) == 1


async def test_quote_roundtrip_and_upsert(db_session: AsyncSession) -> None:
    quote = make_quote()
    await save_quotes(db_session, [quote])
    assert await get_quote(db_session, "FAKE.Q001") == quote

    updated = replace(quote, status=Status.CANCELLED)
    await save_quotes(db_session, [updated])

    reloaded = await get_quote(db_session, "FAKE.Q001")
    assert reloaded is not None
    assert reloaded.status is Status.CANCELLED
    assert len(await load_quotes(db_session)) == 1


async def test_optional_datetimes_roundtrip(db_session: AsyncSession) -> None:
    trade = make_trade(datetime=None)
    quote = make_quote(datetime=None)

    await save_trades(db_session, [trade])
    await save_quotes(db_session, [quote])

    assert await get_trade(db_session, "FAKE.T001") == trade
    assert await get_quote(db_session, "FAKE.Q001") == quote


async def test_order_datetime_is_normalized_to_utc(db_session: AsyncSession) -> None:
    beijing = timezone(timedelta(hours=8))
    order = make_order(datetime=datetime(2024, 1, 2, 9, 0, tzinfo=beijing))

    await save_orders(db_session, [order])

    loaded = await get_order(db_session, "FAKE.0001")
    assert loaded is not None
    assert loaded.datetime == datetime(2024, 1, 2, 1, 0, tzinfo=UTC)
    assert loaded.datetime is not None
    assert loaded.datetime.tzinfo is UTC


async def test_unknown_keys_return_none_and_empty_saves_are_noops(
    db_session: AsyncSession,
) -> None:
    await save_contracts(db_session, [])
    await save_orders(db_session, [])
    await save_trades(db_session, [])
    await save_positions(db_session, [])
    await save_accounts(db_session, [])
    await save_quotes(db_session, [])

    assert await get_contract(db_session, "none.CFFEX") is None
    assert await get_order(db_session, "none.1") is None
    assert await get_trade(db_session, "none.1") is None
    assert await get_position(db_session, "none.CFFEX.LONG") is None
    assert await get_account(db_session, "none.ACC") is None
    assert await get_quote(db_session, "none.Q") is None
