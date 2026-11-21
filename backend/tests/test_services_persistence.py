"""``PersistenceService`` 测试：事件总线 → 数据库的批量落库。

重点验证：

- 控制事件（订单 / 成交 / 持仓 / 账户 / 合约 / 报价）经队列写入数据库；
- 订单 / 持仓 / 账户 / 报价按业务键 upsert，成交重复回报被忽略；
- scoped 主题事件也能被全局订阅者收到并落库；
- 队列批量处理、``flush`` 等待排空、``stop`` 退订并收尾；
- 非法载荷被记录并跳过，不影响后台任务。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventBus, Topics
from app.crud.trading import (
    get_account,
    get_contract,
    get_order,
    get_position,
    get_quote,
    get_trade,
    load_orders,
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
from app.services.trading.persistence import PersistenceService


def dt() -> datetime:
    return datetime(2024, 1, 2, 9, 0, tzinfo=UTC)


def make_order(order_id: str = "0001", *, status: Status = Status.NOTTRADED) -> OrderData:
    return OrderData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id=order_id,
        type=OrderType.LIMIT,
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=3500,
        volume=2,
        traded=0,
        status=status,
        datetime=dt(),
    )


def make_trade() -> TradeData:
    return TradeData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id="0001",
        trade_id="T001",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=3500,
        volume=1,
        datetime=dt(),
    )


def make_position() -> PositionData:
    return PositionData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        volume=10,
        frozen=2,
        price=3500,
        pnl=120,
        yd_volume=4,
    )


def make_account() -> AccountData:
    return AccountData(
        gateway_name="FAKE",
        account_id="ACC001",
        balance=1_000_000,
        frozen=10_000,
    )


def make_contract() -> ContractData:
    return ContractData(
        gateway_name="FAKE",
        symbol="IO2412",
        exchange=Exchange.CFFEX,
        name="IO2412-C-4000",
        product=Product.OPTION,
        size=300,
        pricetick=0.2,
        option_strike=4000,
        option_underlying_key="IF2412.CFFEX",
        option_type=OptionType.CALL,
    )


def make_quote() -> QuoteData:
    return QuoteData(
        gateway_name="FAKE",
        symbol="IO2412",
        exchange=Exchange.CFFEX,
        quote_id="Q001",
        bid_price=3900,
        bid_volume=2,
        ask_price=3901,
        ask_volume=3,
        status=Status.NOTTRADED,
        datetime=dt(),
    )


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def persistence(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[PersistenceService]:
    service = PersistenceService(bus, session_factory)
    yield service
    await service.stop()


async def test_order_events_are_persisted_and_updated(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    order = make_order()
    await bus.publish(Topics.ORDER, order)
    await persistence.flush()

    async with session_factory() as session:
        assert await get_order(session, "FAKE.0001") == order

    updated = replace(order, status=Status.ALLTRADED, traded=2)
    await bus.publish(Topics.ORDER, updated)
    await persistence.flush()

    async with session_factory() as session:
        reloaded = await get_order(session, "FAKE.0001")
        assert reloaded is not None
        assert reloaded.status is Status.ALLTRADED
        assert reloaded.traded == 2


async def test_trade_duplicate_is_ignored(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    trade = make_trade()

    await bus.publish(Topics.TRADE, trade)
    await persistence.flush()
    await bus.publish(Topics.TRADE, replace(trade, price=9999))
    await persistence.flush()

    async with session_factory() as session:
        assert await get_trade(session, "FAKE.T001") == trade


async def test_all_control_events_are_persisted(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    position = make_position()
    account = make_account()
    contract = make_contract()
    quote = make_quote()

    await bus.publish(Topics.POSITION, position)
    await bus.publish(Topics.ACCOUNT, account)
    await bus.publish(Topics.CONTRACT, contract)
    await bus.publish(Topics.QUOTE, quote)
    await persistence.flush()

    async with session_factory() as session:
        assert await get_position(session, "FAKE.rb2410.SHFE.LONG") == position
        assert await get_account(session, "FAKE.ACC001") == account
        assert await get_contract(session, "IO2412.CFFEX") == contract
        assert await get_quote(session, "FAKE.Q001") == quote


async def test_scoped_order_event_is_persisted(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    order = make_order()

    await bus.publish(Topics.ORDER.scoped(order.order_key), order)
    await persistence.flush()

    async with session_factory() as session:
        assert await get_order(session, "FAKE.0001") == order


async def test_batches_are_written_in_one_flush(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    orders = [make_order(f"{index:04d}") for index in range(1, 151)]

    for order in orders:
        await bus.publish(Topics.ORDER, order)
    await persistence.flush()

    async with session_factory() as session:
        assert len(await load_orders(session)) == 150


async def test_invalid_payload_is_skipped_with_warning(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.trading.persistence"):
        await bus.publish(Topics.ORDER, {"not": "an order"})
        await persistence.flush()

    assert "忽略无法持久化的事件" in caplog.text

    async with session_factory() as session:
        assert await get_order(session, "FAKE.0001") is None


async def test_stop_flushes_pending_events_and_unsubscribes(
    bus: EventBus,
    persistence: PersistenceService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await bus.publish(Topics.ORDER, make_order())

    await persistence.stop()
    await persistence.stop()

    async with session_factory() as session:
        assert await get_order(session, "FAKE.0001") is not None

    await bus.publish(Topics.ORDER, make_order("0002"))

    async with session_factory() as session:
        assert await get_order(session, "FAKE.0002") is None
