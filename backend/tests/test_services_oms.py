"""``engine.py`` 的 ``OmsEngine`` → ``app/services/trading/oms.py`` 迁移测试。

重点验证：

- 订阅控制事件后缓存委托 / 成交 / 持仓 / 账户 / 合约 / 报价，并维护活跃项索引；
- tick 走行情边界方法而不是事件总线（行情走独立数据平面），批量写入取最新；
- 查询未知键返回 ``None``，``get_all_*`` 返回与缓存解耦的列表快照；
- 按网关隔离的开平转换器：下单预冻结、撤单释放、成交更新、多网关互不影响；
- 非法事件载荷被本地校验拦下；``stop`` 退订后可重复调用。
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from app.core.events import EventBus, Topics
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import Direction, Exchange, Offset, OrderType, Product, Status
from app.domain.market import TickData
from app.domain.orders import OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.trades import TradeData
from app.services.trading.oms import OmsService


def make_order(
    *,
    order_id: str = "0001",
    gateway_name: str = "FAKE",
    status: Status = Status.SUBMITTING,
    direction: Direction = Direction.LONG,
    offset: Offset = Offset.OPEN,
    volume: float = 1,
    traded: float = 0,
) -> OrderData:
    return OrderData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id=order_id,
        direction=direction,
        offset=offset,
        volume=volume,
        traded=traded,
        price=3500,
        status=status,
    )


def make_trade(
    *,
    trade_id: str = "T001",
    order_id: str = "0001",
    gateway_name: str = "FAKE",
    direction: Direction = Direction.LONG,
    offset: Offset = Offset.OPEN,
    volume: float = 1,
) -> TradeData:
    return TradeData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id=order_id,
        trade_id=trade_id,
        direction=direction,
        offset=offset,
        price=3500,
        volume=volume,
    )


def make_position(
    *,
    gateway_name: str = "FAKE",
    direction: Direction = Direction.LONG,
    volume: float = 10,
    yd_volume: float = 4,
) -> PositionData:
    return PositionData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=direction,
        volume=volume,
        yd_volume=yd_volume,
        price=3500,
    )


def make_account(*, gateway_name: str = "FAKE") -> AccountData:
    return AccountData(
        gateway_name=gateway_name,
        account_id="ACC001",
        balance=1_000_000,
        frozen=10_000,
    )


def make_contract(
    *,
    gateway_name: str = "FAKE",
    net_position: bool = False,
) -> ContractData:
    return ContractData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        name="螺纹钢2410",
        product=Product.FUTURES,
        size=10,
        pricetick=1,
        net_position=net_position,
    )


def make_quote(
    *,
    quote_id: str = "Q001",
    status: Status = Status.SUBMITTING,
) -> QuoteData:
    return QuoteData(
        gateway_name="FAKE",
        symbol="IO2412",
        exchange=Exchange.CFFEX,
        quote_id=quote_id,
        bid_price=3900,
        bid_volume=1,
        ask_price=3901,
        ask_volume=1,
        status=status,
    )


def make_tick(last_price: float = 3500) -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=datetime(2024, 1, 2, 9, 30),
        last_price=last_price,
    )


def make_request(
    *,
    direction: Direction = Direction.LONG,
    offset: Offset = Offset.CLOSE,
    volume: float = 1,
) -> OrderRequest:
    return OrderRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=direction,
        type=OrderType.LIMIT,
        volume=volume,
        price=3500,
        offset=offset,
    )


def offsets_and_volumes(requests: list[OrderRequest]) -> list[tuple[Offset, float]]:
    return [(request.offset, request.volume) for request in requests]


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def oms(bus: EventBus) -> OmsService:
    return OmsService(bus)


async def test_order_event_caches_and_tracks_active_orders(
    bus: EventBus,
    oms: OmsService,
) -> None:
    order = make_order()

    await bus.publish(Topics.ORDER, order)

    assert oms.get_order("FAKE.0001") is order
    assert oms.get_all_active_orders() == [order]

    finished = make_order(status=Status.ALLTRADED, traded=1)
    await bus.publish(Topics.ORDER, finished)

    cached = oms.get_order("FAKE.0001")
    assert cached is not None
    assert cached.status is Status.ALLTRADED
    assert oms.get_all_active_orders() == []


async def test_trade_position_account_contract_and_quote_events(
    bus: EventBus,
    oms: OmsService,
) -> None:
    trade = make_trade()
    position = make_position()
    account = make_account()
    contract = make_contract()
    quote = make_quote()

    await bus.publish(Topics.TRADE, trade)
    await bus.publish(Topics.POSITION, position)
    await bus.publish(Topics.ACCOUNT, account)
    await bus.publish(Topics.CONTRACT, contract)
    await bus.publish(Topics.QUOTE, quote)

    assert oms.get_trade("FAKE.T001") is trade
    assert oms.get_position("FAKE.rb2410.SHFE.LONG") is position
    assert oms.get_account("FAKE.ACC001") is account
    assert oms.get_contract("rb2410.SHFE") is contract
    assert oms.get_quote("FAKE.Q001") is quote
    assert oms.get_all_active_quotes() == [quote]

    await bus.publish(Topics.QUOTE, make_quote(status=Status.CANCELLED))

    cached_quote = oms.get_quote("FAKE.Q001")
    assert cached_quote is not None
    assert cached_quote.status is Status.CANCELLED
    assert oms.get_all_active_quotes() == []


async def test_scoped_order_event_is_cached(bus: EventBus, oms: OmsService) -> None:
    order = make_order()

    await bus.publish(Topics.ORDER.scoped(order.order_key), order)

    assert oms.get_order(order.order_key) is order


async def test_unknown_keys_return_none_and_empty_lists(oms: OmsService) -> None:
    assert oms.get_tick("unknown.SHFE") is None
    assert oms.get_order("unknown.1") is None
    assert oms.get_trade("unknown.1") is None
    assert oms.get_position("unknown.SHFE.LONG") is None
    assert oms.get_account("unknown.ACC") is None
    assert oms.get_contract("unknown.SHFE") is None
    assert oms.get_quote("unknown.Q") is None
    assert oms.get_all_orders() == []
    assert oms.get_all_active_orders() == []


async def test_get_all_returns_detached_list_snapshots(
    bus: EventBus,
    oms: OmsService,
) -> None:
    order = make_order()
    await bus.publish(Topics.ORDER, order)

    snapshot = oms.get_all_orders()
    snapshot.clear()

    assert oms.get_all_orders() == [order]


async def test_ticks_are_written_at_boundary_and_not_from_bus(
    bus: EventBus,
    oms: OmsService,
) -> None:
    first = make_tick(3500)
    oms.update_ticks([first])
    assert oms.get_tick("rb2410.SHFE") is first

    second = make_tick(3501)
    oms.update_tick(second)
    assert oms.get_tick("rb2410.SHFE") is second

    # OMS 不订阅 TICK：行情走数据平面，不能从总线改动快照
    await bus.publish(Topics.TICK, make_tick(9999))
    assert oms.get_tick("rb2410.SHFE") is second
    assert oms.get_all_ticks() == [second]


async def test_illegal_payload_is_ignored_with_warning(
    bus: EventBus,
    oms: OmsService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.trading.oms"):
        await bus.publish(Topics.ORDER, {"not": "an order"})

    assert oms.get_all_orders() == []
    assert "非法事件载荷" in caplog.text


async def test_stop_unsubscribes_and_is_idempotent(
    bus: EventBus,
    oms: OmsService,
) -> None:
    oms.stop()
    oms.stop()

    await bus.publish(Topics.ORDER, make_order())

    assert oms.get_all_orders() == []


async def test_prefreeze_affects_close_conversion(
    bus: EventBus,
    oms: OmsService,
) -> None:
    await bus.publish(Topics.CONTRACT, make_contract())
    await bus.publish(Topics.POSITION, make_position(direction=Direction.SHORT))

    oms.update_order_request(
        make_request(direction=Direction.LONG, volume=3),
        "FAKE.0001",
    )

    converted = oms.convert_order_request(
        make_request(direction=Direction.LONG, volume=7),
        "FAKE",
    )
    assert offsets_and_volumes(converted) == [
        (Offset.CLOSETODAY, 3),
        (Offset.CLOSEYESTERDAY, 4),
    ]

    # 可用持仓 7 手，再要 8 手应拒绝
    assert oms.convert_order_request(make_request(volume=8), "FAKE") == []


async def test_cancelled_order_releases_frozen_volume(
    bus: EventBus,
    oms: OmsService,
) -> None:
    await bus.publish(Topics.CONTRACT, make_contract())
    await bus.publish(Topics.POSITION, make_position(direction=Direction.SHORT))

    oms.update_order_request(
        make_request(direction=Direction.LONG, volume=3),
        "FAKE.0001",
    )
    await bus.publish(
        Topics.ORDER,
        make_order(
            status=Status.CANCELLED,
            direction=Direction.LONG,
            offset=Offset.CLOSE,
            volume=3,
        ),
    )

    converted = oms.convert_order_request(
        make_request(direction=Direction.LONG, volume=8),
        "FAKE",
    )
    assert offsets_and_volumes(converted) == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 2),
    ]


async def test_trade_event_updates_offset_converter(
    bus: EventBus,
    oms: OmsService,
) -> None:
    await bus.publish(Topics.CONTRACT, make_contract())
    await bus.publish(Topics.POSITION, make_position(direction=Direction.SHORT))

    # 买平 6 手今仓：剩余空头 4 手（全是昨仓）
    await bus.publish(
        Topics.TRADE,
        make_trade(direction=Direction.LONG, offset=Offset.CLOSETODAY, volume=6),
    )

    converted = oms.convert_order_request(
        make_request(direction=Direction.LONG, volume=4),
        "FAKE",
    )
    assert offsets_and_volumes(converted) == [(Offset.CLOSEYESTERDAY, 4)]

    assert oms.convert_order_request(make_request(volume=5), "FAKE") == []


async def test_offset_converters_are_isolated_per_gateway(
    bus: EventBus,
    oms: OmsService,
) -> None:
    await bus.publish(Topics.CONTRACT, make_contract(gateway_name="FAKE_A"))
    await bus.publish(Topics.CONTRACT, make_contract(gateway_name="FAKE_B"))
    await bus.publish(
        Topics.POSITION,
        make_position(gateway_name="FAKE_A", direction=Direction.SHORT, volume=10, yd_volume=4),
    )
    await bus.publish(
        Topics.POSITION,
        make_position(gateway_name="FAKE_B", direction=Direction.SHORT, volume=2, yd_volume=2),
    )

    converted_a = oms.convert_order_request(make_request(volume=8), "FAKE_A")
    assert offsets_and_volumes(converted_a) == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 2),
    ]

    assert oms.convert_order_request(make_request(volume=8), "FAKE_B") == []


async def test_convert_unknown_contract_passes_through(oms: OmsService) -> None:
    request = make_request()

    assert oms.convert_order_request(request, "FAKE") == [request]
    assert oms.convert_order_request(request, "FAKE", lock=True) == [request]


async def test_net_position_contract_is_not_converted(
    bus: EventBus,
    oms: OmsService,
) -> None:
    await bus.publish(Topics.CONTRACT, make_contract(net_position=True))
    await bus.publish(Topics.POSITION, make_position(direction=Direction.SHORT))
    request = make_request(direction=Direction.LONG, volume=3)

    assert oms.convert_order_request(request, "FAKE") == [request]


async def test_update_order_request_rejects_malformed_key(oms: OmsService) -> None:
    with pytest.raises(ValueError, match="缺少点号"):
        oms.update_order_request(make_request(), "FAKE0001")
