"""``MainEngine`` → ``app/services/trading/runtime.py`` 的迁移测试。

重点验证组合根职责（全部使用 Fake 网关 / 数据源，不联网、不依赖真实 SDK）：

- 网关注册与重名 / 未知网关错误；数据源注册、初始化、重名 / 未知数据源错误；
- 连接时合并默认配置，并把网关初始化快照路由到 OMS 与 EventBus；
- ``EventSink`` 只发布一条带范围的主题，OMS / 全局订阅者都能收到且不重复；
- tick 只写 OMS 快照，不进入事件总线（行情走独立数据平面）；
- 下单预冻结与「网关同步回报时跳过预冻结」；撤单 / 订阅 / 报价路由；
- 关闭顺序：数据源、网关、OMS 退订，且可重复调用。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

import pytest

from app.core.events import Event, EventBus, Topics
from app.core.exceptions import BadRequestError
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import Direction, Exchange, Interval, Offset, OrderType, Product, Status
from app.domain.market import BarData, HistoryRequest, SubscribeRequest, TickData
from app.domain.orders import CancelRequest, OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteRequest
from app.domain.trades import TradeData
from app.integrations.datafeed import DataFeed
from app.integrations.gateway import EventSink, Gateway, SettingValue
from app.services.trading.runtime import (
    DataFeedConflictError,
    DataFeedNotFoundError,
    GatewayConflictError,
    GatewayNotFoundError,
    TradingRuntime,
)


def make_contract(*, gateway_name: str = "FAKE") -> ContractData:
    return ContractData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        name="螺纹钢2410",
        product=Product.FUTURES,
        size=10,
        pricetick=1,
    )


def make_account(*, gateway_name: str = "FAKE") -> AccountData:
    return AccountData(
        gateway_name=gateway_name,
        account_id="ACC001",
        balance=1_000_000,
        frozen=10_000,
    )


def make_position(*, gateway_name: str = "FAKE") -> PositionData:
    return PositionData(
        gateway_name=gateway_name,
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.SHORT,
        volume=10,
        yd_volume=4,
        price=3500,
    )


def make_order(*, status: Status = Status.SUBMITTING) -> OrderData:
    return OrderData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id="0001",
        direction=Direction.LONG,
        offset=Offset.CLOSE,
        volume=3,
        price=3500,
        status=status,
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
    )


def make_tick(last_price: float = 3500) -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=datetime(2024, 1, 2, 9, 30),
        last_price=last_price,
    )


def make_request(*, volume: float = 3) -> OrderRequest:
    return OrderRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=volume,
        price=3500,
        offset=Offset.CLOSE,
    )


def make_history_request() -> HistoryRequest:
    return HistoryRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        start=datetime(2024, 1, 1),
        end=datetime(2024, 1, 2),
        interval=Interval.MINUTE,
    )


class FakeGateway(Gateway):
    """最小 Fake 网关：记录调用，并通过 sink 推送初始化快照。"""

    gateway_name = "FAKE"
    default_setting = {"user_id": "", "password": ""}

    def __init__(
        self,
        event_sink: EventSink,
        *,
        gateway_name: str | None = None,
        sync_order_status: Status | None = None,
    ) -> None:
        super().__init__(event_sink, gateway_name=gateway_name)
        self.connected = False
        self.closed = False
        self.connect_settings: list[Mapping[str, SettingValue]] = []
        self.subscriptions: list[str] = []
        self.unsubscriptions: list[str] = []
        self.cancelled: list[CancelRequest] = []
        self.sync_order_status = sync_order_status
        self._order_seq = 0

    async def connect(self, setting: Mapping[str, SettingValue]) -> None:
        self.connected = True
        self.connect_settings.append(setting)
        await self.event_sink.on_contract(make_contract(gateway_name=self.gateway_name))
        await self.event_sink.on_account(make_account(gateway_name=self.gateway_name))
        await self.event_sink.on_position(make_position(gateway_name=self.gateway_name))

    async def close(self) -> None:
        self.closed = True
        self.connected = False

    async def subscribe(self, request: SubscribeRequest) -> None:
        self.subscriptions.append(request.instrument_key)

    async def unsubscribe(self, request: SubscribeRequest) -> None:
        self.unsubscriptions.append(request.instrument_key)

    async def send_order(self, request: OrderRequest) -> str:
        self._order_seq += 1
        order = request.create_order_data(f"{self._order_seq:04d}", self.gateway_name)

        if self.sync_order_status is not None:
            order.status = self.sync_order_status
            await self.event_sink.on_order(order)

        return order.order_key

    async def cancel_order(self, request: CancelRequest) -> None:
        self.cancelled.append(request)

    async def query_account(self) -> None:
        await self.event_sink.on_account(make_account(gateway_name=self.gateway_name))

    async def query_position(self) -> None:
        await self.event_sink.on_position(make_position(gateway_name=self.gateway_name))


class FakeDataFeed(DataFeed):
    datafeed_name = "FAKE_FEED"

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False
        self.bar_requests: list[HistoryRequest] = []

    async def init(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def query_bar_history(self, request: HistoryRequest) -> list[BarData]:
        self.bar_requests.append(request)
        return [
            BarData(
                gateway_name="FAKE_FEED",
                symbol=request.symbol,
                exchange=request.exchange,
                datetime=datetime(2024, 1, 2, 9, 0),
                close_price=3500,
            )
        ]

    async def query_tick_history(self, request: HistoryRequest) -> list[TickData]:
        return [make_tick()]


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def runtime(bus: EventBus) -> TradingRuntime:
    return TradingRuntime(bus)


async def test_add_gateway_and_lookup(runtime: TradingRuntime) -> None:
    gateway = FakeGateway(runtime)

    runtime.add_gateway(gateway)

    assert runtime.get_gateway("FAKE") is gateway
    assert runtime.get_all_gateway_names() == ["FAKE"]


def test_duplicate_gateway_is_rejected(runtime: TradingRuntime) -> None:
    runtime.add_gateway(FakeGateway(runtime))

    with pytest.raises(GatewayConflictError, match="已注册"):
        runtime.add_gateway(FakeGateway(runtime))


async def test_unknown_gateway_raises(runtime: TradingRuntime) -> None:
    with pytest.raises(GatewayNotFoundError, match="未注册"):
        runtime.get_gateway("NOPE")

    with pytest.raises(GatewayNotFoundError):
        await runtime.subscribe(
            "NOPE",
            SubscribeRequest(symbol="rb2410", exchange=Exchange.SHFE),
        )


async def test_connect_merges_settings_and_routes_initial_snapshots(
    bus: EventBus,
    runtime: TradingRuntime,
) -> None:
    gateway = FakeGateway(runtime)
    runtime.add_gateway(gateway)
    received: list[Event] = []
    bus.subscribe_all(received.append)

    await runtime.connect("FAKE", {"user_id": "u1"})

    assert gateway.connect_settings == [{"user_id": "u1", "password": ""}]
    assert runtime.oms.get_contract("rb2410.SHFE") is not None
    assert runtime.oms.get_account("FAKE.ACC001") is not None
    assert runtime.oms.get_position("FAKE.rb2410.SHFE.SHORT") is not None

    topics = [str(event.topic) for event in received]
    assert topics == [
        "eContract.rb2410.SHFE",
        "eAccount.FAKE.ACC001",
        "ePosition.FAKE.rb2410.SHFE.SHORT",
    ]


async def test_control_events_use_single_scoped_topic(
    bus: EventBus,
    runtime: TradingRuntime,
) -> None:
    received: list[Event] = []
    bus.subscribe(Topics.ORDER, received.append)
    order = make_order()

    await runtime.on_order(order)

    assert len(received) == 1
    assert received[0].topic == Topics.ORDER.scoped("FAKE.0001")
    assert runtime.oms.get_order("FAKE.0001") is order


async def test_trade_position_account_quote_events_are_published(
    bus: EventBus,
    runtime: TradingRuntime,
) -> None:
    received: list[Event] = []
    bus.subscribe_all(received.append)

    trade = make_trade()
    position = make_position()
    account = make_account()
    contract = make_contract()

    await runtime.on_trade(trade)
    await runtime.on_position(position)
    await runtime.on_account(account)
    await runtime.on_contract(contract)

    assert [str(event.topic) for event in received] == [
        "eTrade.FAKE.T001",
        "ePosition.FAKE.rb2410.SHFE.SHORT",
        "eAccount.FAKE.ACC001",
        "eContract.rb2410.SHFE",
    ]
    assert runtime.oms.get_trade("FAKE.T001") is trade
    assert runtime.oms.get_position("FAKE.rb2410.SHFE.SHORT") is position


async def test_ticks_only_update_oms_snapshot(
    bus: EventBus,
    runtime: TradingRuntime,
) -> None:
    received: list[Event] = []
    bus.subscribe_all(received.append)
    tick = make_tick()

    await runtime.on_ticks([tick])

    assert runtime.oms.get_tick("rb2410.SHFE") is tick
    assert received == []


async def test_on_log_writes_standard_logger(
    runtime: TradingRuntime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.services.trading.runtime"):
        await runtime.on_log("FAKE", "行情断开", logging.ERROR)

    assert "FAKE" in caplog.text
    assert "行情断开" in caplog.text


async def test_send_order_returns_key_and_prefreezes(runtime: TradingRuntime) -> None:
    gateway = FakeGateway(runtime)
    runtime.add_gateway(gateway)
    await runtime.connect("FAKE")

    order_key = await runtime.send_order("FAKE", make_request(volume=3))

    assert order_key == "FAKE.0001"
    assert runtime.oms.get_order(order_key) is None

    # 空头 10 手（今 6 / 昨 4），预冻结 3 手后可用 7 手
    converted = runtime.oms.convert_order_request(make_request(volume=7), "FAKE")
    assert [(item.offset, item.volume) for item in converted] == [
        (Offset.CLOSETODAY, 3),
        (Offset.CLOSEYESTERDAY, 4),
    ]
    assert runtime.oms.convert_order_request(make_request(volume=8), "FAKE") == []


async def test_send_order_skips_prefreeze_when_gateway_replies_synchronously(
    runtime: TradingRuntime,
) -> None:
    gateway = FakeGateway(runtime, sync_order_status=Status.REJECTED)
    runtime.add_gateway(gateway)
    await runtime.connect("FAKE")

    order_key = await runtime.send_order("FAKE", make_request(volume=3))

    cached = runtime.oms.get_order(order_key)
    assert cached is not None
    assert cached.status is Status.REJECTED

    # 拒单已回报，不应再用请求快照预冻结；8 手平仓按完整持仓拆分
    converted = runtime.oms.convert_order_request(make_request(volume=8), "FAKE")
    assert [(item.offset, item.volume) for item in converted] == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 2),
    ]


async def test_subscribe_unsubscribe_and_cancel_are_routed(runtime: TradingRuntime) -> None:
    gateway = FakeGateway(runtime)
    runtime.add_gateway(gateway)
    await runtime.connect("FAKE")
    request = SubscribeRequest(symbol="rb2410", exchange=Exchange.SHFE)
    cancel_request = CancelRequest(order_id="0001", symbol="rb2410", exchange=Exchange.SHFE)

    await runtime.subscribe("FAKE", request)
    await runtime.unsubscribe("FAKE", request)
    await runtime.cancel_order("FAKE", cancel_request)

    assert gateway.subscriptions == ["rb2410.SHFE"]
    assert gateway.unsubscriptions == ["rb2410.SHFE"]
    assert gateway.cancelled == [cancel_request]


async def test_quote_support_is_explicitly_unsupported(runtime: TradingRuntime) -> None:
    runtime.add_gateway(FakeGateway(runtime))
    quote_request = QuoteRequest(
        symbol="IO2412",
        exchange=Exchange.CFFEX,
        bid_price=3900,
        bid_volume=1,
        ask_price=3901,
        ask_volume=1,
    )
    cancel_request = CancelRequest(order_id="Q001", symbol="IO2412", exchange=Exchange.CFFEX)

    with pytest.raises(NotImplementedError, match="不支持报价"):
        await runtime.send_quote("FAKE", quote_request)
    with pytest.raises(NotImplementedError, match="不支持报价"):
        await runtime.cancel_quote("FAKE", cancel_request)


async def test_datafeed_registration_and_history_queries(runtime: TradingRuntime) -> None:
    datafeed = FakeDataFeed()

    await runtime.add_datafeed(datafeed)

    assert datafeed.initialized
    assert runtime.get_datafeed("FAKE_FEED") is datafeed
    assert runtime.get_all_datafeed_names() == ["FAKE_FEED"]

    request = make_history_request()
    bars = await runtime.query_bar_history("FAKE_FEED", request)
    ticks = await runtime.query_tick_history("FAKE_FEED", request)

    assert [bar.instrument_key for bar in bars] == ["rb2410.SHFE"]
    assert [tick.instrument_key for tick in ticks] == ["rb2410.SHFE"]
    assert datafeed.bar_requests == [request]


async def test_duplicate_and_unnamed_datafeeds_are_rejected(
    runtime: TradingRuntime,
) -> None:
    await runtime.add_datafeed(FakeDataFeed())
    duplicate = FakeDataFeed()

    with pytest.raises(DataFeedConflictError, match="已注册"):
        await runtime.add_datafeed(duplicate)
    assert not duplicate.initialized

    class UnnamedDataFeed(FakeDataFeed):
        datafeed_name = ""

    with pytest.raises(BadRequestError, match="datafeed_name"):
        await runtime.add_datafeed(UnnamedDataFeed())


async def test_unknown_datafeed_raises(runtime: TradingRuntime) -> None:
    with pytest.raises(DataFeedNotFoundError, match="未注册"):
        runtime.get_datafeed("NOPE")

    with pytest.raises(DataFeedNotFoundError):
        await runtime.query_bar_history("NOPE", make_history_request())


async def test_close_closes_gateways_and_datafeeds_and_stops_oms(
    bus: EventBus,
    runtime: TradingRuntime,
) -> None:
    gateway = FakeGateway(runtime)
    runtime.add_gateway(gateway)
    await runtime.connect("FAKE")
    datafeed = FakeDataFeed()
    await runtime.add_datafeed(datafeed)

    await runtime.close()
    await runtime.close()

    assert gateway.closed
    assert datafeed.closed

    # OMS 已退订，关闭后的事件不再进入缓存
    await bus.publish(Topics.ORDER, make_order())
    assert runtime.oms.get_order("FAKE.0001") is None

async def test_close_continues_when_one_gateway_fails(
    bus: EventBus,
    runtime: TradingRuntime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingGateway(FakeGateway):
        gateway_name = "BAD"

        async def close(self) -> None:
            raise RuntimeError("close failed")

    healthy = FakeGateway(runtime)
    failing = FailingGateway(runtime)
    runtime.add_gateway(healthy)
    runtime.add_gateway(failing)
    datafeed = FakeDataFeed()
    await runtime.add_datafeed(datafeed)

    with caplog.at_level(logging.ERROR, logger="app.services.trading.runtime"):
        await runtime.close()

    assert healthy.closed
    assert datafeed.closed
    assert "关闭网关失败：BAD" in caplog.text

    await bus.publish(Topics.ORDER, make_order())
    assert runtime.oms.get_order("FAKE.0001") is None

