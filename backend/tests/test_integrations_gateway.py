"""``trader/gateway.py`` 的 ``BaseGateway`` → ``app/integrations/gateway.py`` 迁移测试。

重点验证**端口契约**（不联网、不依赖真实 SDK）：

- ``gateway_name`` 校验：来自类属性、可按实例覆盖、空名 / 带点号被拒绝；
- 生命周期：``connect`` 收到配置并推送初始化快照，``close`` 断开；
- 订阅 / 退订 / 下单 / 撤单 / 查询请求被正确转发；
- 下单返回 ``order_key`` 并推送 ``SUBMITTING`` 快照；
- 行情按**批次**回调（批量语义），而不是逐条 tick；
- 报价默认显式不支持，抽象端口不能绕过实现直接实例化。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime

import pytest

from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import Direction, Exchange, OrderType, Product, Status
from app.domain.market import SubscribeRequest, TickData
from app.domain.orders import CancelRequest, OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData, QuoteRequest
from app.domain.trades import TradeData
from app.integrations.gateway import EventSink, Gateway, SettingValue


class RecordingSink:
    """记录全部回调的窄接口实现；真实 runtime 由单元 11 提供。"""

    def __init__(self) -> None:
        self.tick_batches: list[tuple[TickData, ...]] = []
        self.orders: list[OrderData] = []
        self.trades: list[TradeData] = []
        self.positions: list[PositionData] = []
        self.accounts: list[AccountData] = []
        self.quotes: list[QuoteData] = []
        self.contracts: list[ContractData] = []
        self.logs: list[tuple[str, str, int]] = []

    async def on_ticks(self, ticks: Sequence[TickData]) -> None:
        self.tick_batches.append(tuple(ticks))

    async def on_order(self, order: OrderData) -> None:
        self.orders.append(order)

    async def on_trade(self, trade: TradeData) -> None:
        self.trades.append(trade)

    async def on_position(self, position: PositionData) -> None:
        self.positions.append(position)

    async def on_account(self, account: AccountData) -> None:
        self.accounts.append(account)

    async def on_quote(self, quote: QuoteData) -> None:
        self.quotes.append(quote)

    async def on_contract(self, contract: ContractData) -> None:
        self.contracts.append(contract)

    async def on_log(self, gateway_name: str, message: str, level: int = logging.INFO) -> None:
        self.logs.append((gateway_name, message, level))


class FakeGateway(Gateway):
    """最小可用网关：内存状态 + 通过 sink 推送快照，验证端口而不是 SDK。"""

    gateway_name = "FAKE"
    default_setting = {"user_id": "", "password": "", "md_address": ""}

    def __init__(self, event_sink: EventSink, *, gateway_name: str | None = None) -> None:
        super().__init__(event_sink, gateway_name=gateway_name)
        self.connected = False
        self.closed = False
        self.connect_settings: list[Mapping[str, SettingValue]] = []
        self.subscriptions: list[str] = []
        self.cancel_requests: list[CancelRequest] = []
        self.account_queries = 0
        self.position_queries = 0
        self._order_seq = 0

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("网关未连接")

    async def connect(self, setting: Mapping[str, SettingValue]) -> None:
        self.connected = True
        self.connect_settings.append(setting)
        await self.event_sink.on_contract(
            ContractData(
                gateway_name=self.gateway_name,
                symbol="rb2410",
                exchange=Exchange.SHFE,
                name="螺纹钢2410",
                product=Product.FUTURES,
                size=10,
                pricetick=1,
            )
        )
        await self.event_sink.on_account(
            AccountData(
                gateway_name=self.gateway_name,
                account_id="ACC001",
                balance=1_000_000,
                frozen=10_000,
            )
        )

    async def close(self) -> None:
        self.closed = True
        self.connected = False

    async def subscribe(self, request: SubscribeRequest) -> None:
        self._require_connected()
        if request.instrument_key not in self.subscriptions:
            self.subscriptions.append(request.instrument_key)

    async def unsubscribe(self, request: SubscribeRequest) -> None:
        self._require_connected()
        if request.instrument_key in self.subscriptions:
            self.subscriptions.remove(request.instrument_key)

    async def send_order(self, request: OrderRequest) -> str:
        self._require_connected()
        self._order_seq += 1
        order = request.create_order_data(f"{self._order_seq:04d}", self.gateway_name)
        await self.event_sink.on_order(order)
        return order.order_key

    async def cancel_order(self, request: CancelRequest) -> None:
        self._require_connected()
        self.cancel_requests.append(request)

    async def query_account(self) -> None:
        self._require_connected()
        self.account_queries += 1
        await self.event_sink.on_account(
            AccountData(
                gateway_name=self.gateway_name,
                account_id="ACC001",
                balance=900_000,
                frozen=20_000,
            )
        )

    async def query_position(self) -> None:
        self._require_connected()
        self.position_queries += 1
        await self.event_sink.on_position(
            PositionData(
                gateway_name=self.gateway_name,
                symbol="rb2410",
                exchange=Exchange.SHFE,
                direction=Direction.LONG,
                volume=2,
                price=3500,
            )
        )

    async def push_ticks(self, ticks: Sequence[TickData]) -> None:
        """模拟行情回调：把攒好的一批 tick 交给 sink。"""
        await self.event_sink.on_ticks(ticks)


def make_tick(price: float = 3500.0) -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=datetime(2026, 11, 17, 9, 30),
        last_price=price,
    )


def make_order_request() -> OrderRequest:
    return OrderRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=3500,
    )


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def gateway(sink: RecordingSink) -> FakeGateway:
    return FakeGateway(sink)


def test_gateway_name_defaults_to_class_attribute(gateway: FakeGateway) -> None:
    assert gateway.gateway_name == "FAKE"


def test_gateway_name_can_be_overridden_per_instance(sink: RecordingSink) -> None:
    gateway = FakeGateway(sink, gateway_name="FAKE_2")
    assert gateway.gateway_name == "FAKE_2"


def test_empty_gateway_name_is_rejected(sink: RecordingSink) -> None:
    class UnnamedGateway(FakeGateway):
        gateway_name = ""

    with pytest.raises(ValueError, match="不能为空"):
        UnnamedGateway(sink)


def test_dotted_gateway_name_is_rejected(sink: RecordingSink) -> None:
    with pytest.raises(ValueError, match="点号"):
        FakeGateway(sink, gateway_name="FAKE.X")


async def test_connect_forwards_settings_and_pushes_initial_snapshots(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    setting: dict[str, SettingValue] = {"user_id": "u1", "password": "p1"}

    await gateway.connect(setting)

    assert gateway.connected
    assert gateway.connect_settings == [setting]
    assert sink.contracts[0].instrument_key == "rb2410.SHFE"
    assert sink.contracts[0].product is Product.FUTURES
    assert sink.accounts[0].account_key == "FAKE.ACC001"
    assert sink.accounts[0].available == 990_000


def test_default_setting_is_declared_metadata(gateway: FakeGateway) -> None:
    assert set(gateway.default_setting) == {"user_id", "password", "md_address"}


async def test_subscribe_and_unsubscribe_are_forwarded(gateway: FakeGateway) -> None:
    await gateway.connect({})
    request = SubscribeRequest(symbol="rb2410", exchange=Exchange.SHFE)

    await gateway.subscribe(request)
    await gateway.subscribe(request)
    assert gateway.subscriptions == ["rb2410.SHFE"]

    await gateway.unsubscribe(request)
    await gateway.unsubscribe(request)
    assert gateway.subscriptions == []


async def test_send_order_returns_order_key_and_pushes_snapshot(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    await gateway.connect({})

    order_key = await gateway.send_order(make_order_request())

    assert order_key == "FAKE.0001"
    order = sink.orders[0]
    assert order.order_key == order_key
    assert order.gateway_name == "FAKE"
    assert order.status is Status.SUBMITTING
    assert order.is_active()
    assert order.volume == 1
    assert order.price == 3500


async def test_cancel_order_forwards_cancel_request(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    await gateway.connect({})
    await gateway.send_order(make_order_request())
    cancel_request = sink.orders[0].create_cancel_request()

    await gateway.cancel_order(cancel_request)

    assert gateway.cancel_requests == [cancel_request]
    assert cancel_request.instrument_key == "rb2410.SHFE"


async def test_queries_push_fresh_snapshots(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    await gateway.connect({})

    await gateway.query_account()
    await gateway.query_position()

    assert gateway.account_queries == 1
    assert gateway.position_queries == 1
    assert sink.accounts[-1].balance == 900_000
    assert sink.accounts[-1].available == 880_000
    assert sink.positions[-1].position_key == "FAKE.rb2410.SHFE.LONG"


async def test_ticks_are_delivered_as_one_batch(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    await gateway.connect({})
    ticks = [make_tick(3500), make_tick(3501), make_tick(3502)]

    await gateway.push_ticks(ticks)

    assert len(sink.tick_batches) == 1
    assert sink.tick_batches[0] == tuple(ticks)
    assert [tick.last_price for tick in sink.tick_batches[0]] == [3500, 3501, 3502]


async def test_write_log_includes_gateway_name_and_level(
    gateway: FakeGateway,
    sink: RecordingSink,
) -> None:
    await gateway.write_log("登录成功")
    await gateway.write_log("行情连接断开", logging.ERROR)

    assert sink.logs == [
        ("FAKE", "登录成功", logging.INFO),
        ("FAKE", "行情连接断开", logging.ERROR),
    ]


async def test_quote_support_is_explicitly_unsupported(gateway: FakeGateway) -> None:
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
        await gateway.send_quote(quote_request)
    with pytest.raises(NotImplementedError, match="不支持报价"):
        await gateway.cancel_quote(cancel_request)


def test_abstract_gateway_cannot_be_instantiated(sink: RecordingSink) -> None:
    with pytest.raises(TypeError, match="abstract"):
        Gateway(sink)  # type: ignore[abstract]


def test_gateway_requires_all_abstract_methods(sink: RecordingSink) -> None:
    class PartialGateway(Gateway):
        gateway_name = "PARTIAL"

    with pytest.raises(TypeError, match="abstract"):
        PartialGateway(sink)  # type: ignore[abstract]
