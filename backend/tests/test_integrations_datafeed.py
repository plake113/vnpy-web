"""``trader/datafeed.py`` 的 ``BaseDatafeed`` → ``app/integrations/datafeed.py`` 迁移测试。

重点验证**端口契约**（不联网、不依赖真实 SDK）：

- 去掉全局单例与按名称动态 import 后，实例由调用方创建，生命周期方法可覆盖也可默认空实现；
- 查询是异步的，一次返回一个批次；查无数据返回空列表而不是 ``None``；
- 请求被原样转发（``instrument_key`` / 周期 / 时间范围由实现自己使用）；
- 未初始化时查询由实现抛异常，端口不吞掉错误；
- Tick 历史默认显式不支持；抽象端口不能绕过 ``query_bar_history`` 直接实例化。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, HistoryRequest, TickData
from app.integrations.datafeed import DataFeed


class FakeDataFeed(DataFeed):
    """内存数据源：按合约过滤内存中的 bar，验证端口而不是 HTTP 客户端。"""

    datafeed_name = "FAKE"

    def __init__(self, bars: list[BarData] | None = None) -> None:
        self.bars = list(bars or [])
        self.initialized = False
        self.closed = False
        self.requests: list[HistoryRequest] = []

    async def init(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def query_bar_history(self, request: HistoryRequest) -> list[BarData]:
        if not self.initialized:
            raise RuntimeError("数据源未初始化")
        self.requests.append(request)
        return [bar for bar in self.bars if bar.instrument_key == request.instrument_key]


class BarOnlyDataFeed(DataFeed):
    """只实现 K 线查询的端口子类，用来验证基类的默认行为。"""

    datafeed_name = "BAR_ONLY"

    async def query_bar_history(self, request: HistoryRequest) -> list[BarData]:
        return []


def make_request(symbol: str = "rb2410") -> HistoryRequest:
    return HistoryRequest(
        symbol=symbol,
        exchange=Exchange.SHFE,
        start=datetime(2026, 11, 1),
        end=datetime(2026, 11, 17),
        interval=Interval.MINUTE,
    )


def make_bar(symbol: str = "rb2410", close_price: float = 3500) -> BarData:
    return BarData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=Exchange.SHFE,
        datetime=datetime(2026, 11, 17, 9, 30),
        interval=Interval.MINUTE,
        close_price=close_price,
    )


async def test_init_and_close_update_session_state() -> None:
    datafeed = FakeDataFeed()

    await datafeed.init()
    assert datafeed.initialized

    await datafeed.close()
    assert datafeed.closed


async def test_query_bar_history_returns_batch_and_forwards_request() -> None:
    datafeed = FakeDataFeed([make_bar(close_price=3500), make_bar(close_price=3501)])
    await datafeed.init()
    request = make_request()

    bars = await datafeed.query_bar_history(request)

    assert [bar.close_price for bar in bars] == [3500, 3501]
    assert datafeed.requests == [request]
    assert datafeed.requests[0].instrument_key == "rb2410.SHFE"


async def test_query_bar_history_filters_by_instrument() -> None:
    datafeed = FakeDataFeed([make_bar("rb2410"), make_bar("IF2412")])
    await datafeed.init()

    bars = await datafeed.query_bar_history(make_request("rb2410"))

    assert [bar.symbol for bar in bars] == ["rb2410"]


async def test_query_without_data_returns_empty_list() -> None:
    datafeed = FakeDataFeed()
    await datafeed.init()

    assert await datafeed.query_bar_history(make_request()) == []


async def test_query_before_init_raises() -> None:
    datafeed = FakeDataFeed([make_bar()])

    with pytest.raises(RuntimeError, match="未初始化"):
        await datafeed.query_bar_history(make_request())


async def test_default_lifecycle_methods_are_noops() -> None:
    datafeed = BarOnlyDataFeed()

    await datafeed.init()
    await datafeed.close()


async def test_tick_history_defaults_to_unsupported() -> None:
    datafeed = BarOnlyDataFeed()

    with pytest.raises(NotImplementedError, match="BAR_ONLY"):
        await datafeed.query_tick_history(make_request())


async def test_tick_history_can_be_implemented_by_subclass() -> None:
    class TickDataFeed(BarOnlyDataFeed):
        datafeed_name = "TICKS"

        async def query_tick_history(self, request: HistoryRequest) -> list[TickData]:
            return [
                TickData(
                    gateway_name="FAKE",
                    symbol=request.symbol,
                    exchange=request.exchange,
                    datetime=datetime(2026, 11, 17, 9, 30),
                    last_price=3500,
                )
            ]

    ticks = await TickDataFeed().query_tick_history(make_request())

    assert [tick.instrument_key for tick in ticks] == ["rb2410.SHFE"]


def test_abstract_datafeed_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="abstract"):
        DataFeed()  # type: ignore[abstract]


def test_datafeed_requires_query_bar_history() -> None:
    class PartialDataFeed(DataFeed):
        datafeed_name = "PARTIAL"

    with pytest.raises(TypeError, match="abstract"):
        PartialDataFeed()  # type: ignore[abstract]
