"""``vnpy/trader/object.py`` 的 ``TradeData`` → ``app/domain/trades.py`` 的迁移测试。

重点验证：

- 字段集合 / 顺序 / 默认值与原版一致（``orderid`` → ``order_id``、``tradeid`` → ``trade_id``）；
- 一笔成交同时带 ``order_key``（所属委托）与 ``trade_key``（自身），均由网关名派生；
- 成交对象在网关回报中被逐字段更新，派生键随之重算。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.domain.enums import Direction, Exchange, Offset
from app.domain.trades import TradeData


def make_trade(**overrides: object) -> TradeData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "order_id": "12345",
        "trade_id": "90001",
    }
    values.update(overrides)
    return TradeData(**values)  # type: ignore[arg-type]


def test_trade_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(TradeData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "order_id",
        "trade_id",
        "direction",
        "offset",
        "price",
        "volume",
        "datetime",
    ]


def test_trade_defaults() -> None:
    trade = make_trade()

    assert trade.direction is None
    assert trade.offset is Offset.NONE
    assert (trade.price, trade.volume) == (0, 0)
    assert trade.datetime is None
    assert trade.extra is None


def test_trade_keys_are_derived() -> None:
    trade = make_trade()

    assert trade.instrument_key == "rb2410.SHFE"
    assert trade.order_key == "CTP.12345"
    assert trade.trade_key == "CTP.90001"

    # 三个键都是派生属性，不是 dataclass 字段
    field_names = {field.name for field in dataclasses.fields(trade)}
    assert {"instrument_key", "order_key", "trade_key"}.isdisjoint(field_names)


def test_trade_keys_follow_field_mutation() -> None:
    trade = make_trade()

    trade.trade_id = "90002"
    assert trade.trade_key == "CTP.90002"

    trade.order_id = "54321"
    assert trade.order_key == "CTP.54321"

    trade.gateway_name = "IB"
    assert (trade.order_key, trade.trade_key) == ("IB.54321", "IB.90002")


def test_trade_keys_are_read_only() -> None:
    trade = make_trade()

    with pytest.raises(AttributeError):
        trade.trade_key = "IB.1"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        trade.order_key = "IB.1"  # type: ignore[misc]


def test_trade_with_fill_details() -> None:
    trade = make_trade(
        direction=Direction.SHORT,
        offset=Offset.OPEN,
        price=3499.5,
        volume=2,
        datetime=datetime(2026, 11, 16, 9, 31, 5),
    )

    assert trade.direction is Direction.SHORT
    assert trade.offset is Offset.OPEN
    assert trade.price == 3499.5
    assert trade.volume == 2
    assert trade.datetime == datetime(2026, 11, 16, 9, 31, 5)


def test_trade_equality_covers_all_fields() -> None:
    assert make_trade() == make_trade()
    assert make_trade(trade_id="90002") != make_trade()
    assert make_trade(gateway_name="IB") != make_trade()
