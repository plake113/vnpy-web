"""``vnpy/trader/object.py`` → ``app/domain/base.py`` / ``market.py`` 的迁移测试。

重点验证：

- 字段集合、顺序与默认值与原版一致（网关适配层无需重新映射）；
- ``instrument_key`` 由 ``symbol`` + ``exchange`` 派生（原 ``vt_symbol``），
  且交易所代码使用 ``exchange.value``（如 ``EUREX`` → ``EUX``）；
- ``BaseData.extra`` 不参与构造、默认 ``None``；
- dataclass 的相等性与可变性语义保持（行情对象会在网关回调中被逐字段更新）。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.domain.base import BaseData
from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, HistoryRequest, SubscribeRequest, TickData

TICK_DATETIME = datetime(2026, 11, 16, 9, 30)


def make_tick(**overrides: object) -> TickData:
    """构造一个字段取值可覆盖的 tick，便于逐项断言默认值。"""
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "datetime": TICK_DATETIME,
    }
    values.update(overrides)
    return TickData(**values)  # type: ignore[arg-type]


def test_base_data_extra_defaults_to_none_and_is_not_constructible() -> None:
    data = BaseData(gateway_name="CTP")

    assert data.gateway_name == "CTP"
    assert data.extra is None

    with pytest.raises(TypeError):
        BaseData(gateway_name="CTP", extra={"raw": 1})  # type: ignore[call-arg]

    # 网关适配层可以在收到原始报文后补充私有载荷
    data.extra = {"raw": 1}
    assert data.extra == {"raw": 1}


def test_base_data_requires_gateway_name() -> None:
    with pytest.raises(TypeError):
        BaseData()  # type: ignore[call-arg]


def test_tick_instrument_key_is_derived_from_symbol_and_exchange() -> None:
    tick = make_tick()

    assert tick.instrument_key == "rb2410.SHFE"
    # 派生属性不是 dataclass 字段，避免与 symbol / exchange 失去同步
    assert "instrument_key" not in {field.name for field in dataclasses.fields(tick)}


def test_tick_instrument_key_follows_field_mutation() -> None:
    tick = make_tick()

    tick.symbol = "rb2501"
    assert tick.instrument_key == "rb2501.SHFE"

    tick.exchange = Exchange.INE
    assert tick.instrument_key == "rb2501.INE"


def test_instrument_key_is_read_only() -> None:
    tick = make_tick()

    with pytest.raises(AttributeError):
        tick.instrument_key = "rb2410.DCE"  # type: ignore[misc]


def test_tick_field_order_and_defaults() -> None:
    """位置参数顺序与原版一致：gateway_name → symbol → exchange → datetime。"""
    tick = TickData("CTP", "rb2410", Exchange.SHFE, TICK_DATETIME)

    assert tick.gateway_name == "CTP"
    assert tick.symbol == "rb2410"
    assert tick.exchange is Exchange.SHFE
    assert tick.datetime == TICK_DATETIME

    assert tick.name == ""
    assert tick.volume == 0
    assert tick.turnover == 0
    assert tick.open_interest == 0
    assert tick.last_price == 0
    assert tick.last_volume == 0
    assert tick.limit_up == 0
    assert tick.limit_down == 0

    assert tick.open_price == 0
    assert tick.high_price == 0
    assert tick.low_price == 0
    assert tick.pre_close == 0

    assert tick.bid_price_1 == 0
    assert tick.bid_price_5 == 0
    assert tick.ask_price_1 == 0
    assert tick.ask_price_5 == 0
    assert tick.bid_volume_1 == 0
    assert tick.bid_volume_5 == 0
    assert tick.ask_volume_1 == 0
    assert tick.ask_volume_5 == 0

    assert tick.localtime is None
    assert tick.extra is None


def test_tick_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(TickData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "datetime",
        "name",
        "volume",
        "turnover",
        "open_interest",
        "last_price",
        "last_volume",
        "limit_up",
        "limit_down",
        "open_price",
        "high_price",
        "low_price",
        "pre_close",
        "bid_price_1",
        "bid_price_2",
        "bid_price_3",
        "bid_price_4",
        "bid_price_5",
        "ask_price_1",
        "ask_price_2",
        "ask_price_3",
        "ask_price_4",
        "ask_price_5",
        "bid_volume_1",
        "bid_volume_2",
        "bid_volume_3",
        "bid_volume_4",
        "bid_volume_5",
        "ask_volume_1",
        "ask_volume_2",
        "ask_volume_3",
        "ask_volume_4",
        "ask_volume_5",
        "localtime",
    ]


def test_tick_holds_orderbook_and_statistics() -> None:
    tick = make_tick(
        last_price=3500.0,
        volume=1000.0,
        open_interest=2000.0,
        bid_price_1=3499.0,
        bid_volume_1=10.0,
        ask_price_1=3501.0,
        ask_volume_1=12.0,
    )

    assert tick.last_price == 3500.0
    assert tick.volume == 1000.0
    assert tick.open_interest == 2000.0
    assert (tick.bid_price_1, tick.bid_volume_1) == (3499.0, 10.0)
    assert (tick.ask_price_1, tick.ask_volume_1) == (3501.0, 12.0)


def test_bar_fields_and_defaults() -> None:
    bar = BarData(
        gateway_name="CTP",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=TICK_DATETIME,
    )

    assert bar.interval is None
    assert (bar.open_price, bar.high_price, bar.low_price, bar.close_price) == (0, 0, 0, 0)
    assert bar.volume == 0
    assert bar.turnover == 0
    assert bar.open_interest == 0
    assert bar.instrument_key == "rb2410.SHFE"
    assert bar.extra is None


def test_bar_with_interval() -> None:
    bar = BarData(
        gateway_name="CTP",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=TICK_DATETIME,
        interval=Interval.MINUTE,
        open_price=3500,
        high_price=3510,
        low_price=3490,
        close_price=3505,
        volume=100,
    )

    assert bar.interval is Interval.MINUTE
    assert bar.close_price == 3505


def test_subscribe_request_requires_symbol_and_exchange() -> None:
    # 请求对象不承载网关数据，与原版一致：不是 BaseData 子类
    request = SubscribeRequest(symbol="rb2410", exchange=Exchange.SHFE)

    assert request.instrument_key == "rb2410.SHFE"
    assert not isinstance(request, BaseData)

    with pytest.raises(TypeError):
        SubscribeRequest(symbol="rb2410")  # type: ignore[call-arg]


def test_history_request_defaults() -> None:
    request = HistoryRequest(symbol="rb2410", exchange=Exchange.SHFE, start=TICK_DATETIME)

    assert request.end is None
    assert request.interval is None
    assert request.instrument_key == "rb2410.SHFE"


def test_history_request_with_range_and_interval() -> None:
    start = datetime(2026, 11, 1)
    end = datetime(2026, 11, 16)
    request = HistoryRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        start=start,
        end=end,
        interval=Interval.DAILY,
    )

    assert (request.start, request.end) == (start, end)
    assert request.interval is Interval.DAILY


def test_dataclass_equality_covers_all_fields() -> None:
    assert make_tick() == make_tick()
    assert make_tick(gateway_name="IB") != make_tick()
    assert make_tick(bid_price_1=1.0) != make_tick()

    # 派生属性不参与相等性比较：同 symbol / exchange 即同合约
    assert make_tick().instrument_key == make_tick(last_price=9.0).instrument_key
