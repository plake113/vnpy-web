"""``vnpy/trader/object.py`` 的委托对象 → ``app/domain/orders.py`` 的迁移测试。

重点验证：

- ``OrderData`` 字段集合 / 顺序 / 默认值与原版一致（``orderid`` → ``order_id``）；
- ``order_key`` 由 ``gateway_name`` + ``order_id`` 派生（原 ``vt_orderid``），只读且随字段变化；
- 活跃状态判断（原 ``ACTIVE_STATUSES``）覆盖全部 6 个状态；
- ``OrderRequest.create_order_data`` 与 ``OrderData.create_cancel_request`` 的转换语义。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.domain.enums import Direction, Exchange, Offset, OrderType, Status
from app.domain.orders import CancelRequest, OrderData, OrderRequest


def make_order(**overrides: object) -> OrderData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "order_id": "12345",
    }
    values.update(overrides)
    return OrderData(**values)  # type: ignore[arg-type]


def test_order_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(OrderData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "order_id",
        "type",
        "direction",
        "offset",
        "price",
        "volume",
        "traded",
        "status",
        "datetime",
        "reference",
    ]


def test_order_defaults() -> None:
    order = make_order()

    assert order.type is OrderType.LIMIT
    assert order.direction is None
    assert order.offset is Offset.NONE
    assert (order.price, order.volume, order.traded) == (0, 0, 0)
    assert order.status is Status.SUBMITTING
    assert order.datetime is None
    assert order.reference == ""
    assert order.extra is None


def test_order_keys_are_derived() -> None:
    order = make_order()

    assert order.instrument_key == "rb2410.SHFE"
    assert order.order_key == "CTP.12345"
    assert "order_key" not in {field.name for field in dataclasses.fields(order)}


def test_order_keys_follow_field_mutation() -> None:
    order = make_order()

    order.order_id = "67890"
    assert order.order_key == "CTP.67890"

    order.gateway_name = "IB"
    assert order.order_key == "IB.67890"

    order.symbol = "rb2501"
    assert order.instrument_key == "rb2501.SHFE"


def test_order_key_is_read_only() -> None:
    order = make_order()

    with pytest.raises(AttributeError):
        order.order_key = "IB.1"  # type: ignore[misc]


def test_order_key_rejects_ambiguous_gateway_name() -> None:
    order = make_order(gateway_name="CTP.SIM")

    with pytest.raises(ValueError, match="不能包含点号"):
        _ = order.order_key


def test_order_is_active_for_all_statuses() -> None:
    active = {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}
    inactive = {Status.ALLTRADED, Status.CANCELLED, Status.REJECTED}

    # 两个集合正好覆盖全部状态，避免新增状态时漏测
    assert active | inactive == set(Status)

    for status in Status:
        order = make_order(status=status)
        assert order.is_active() is (status in active)


def test_order_create_cancel_request() -> None:
    order = make_order(order_id="12345", symbol="rb2410", exchange=Exchange.SHFE)

    request = order.create_cancel_request()

    assert request == CancelRequest(
        order_id="12345",
        symbol="rb2410",
        exchange=Exchange.SHFE,
    )
    assert request.instrument_key == "rb2410.SHFE"


def test_cancel_request_positional_field_order() -> None:
    # 与原版一致：orderid → symbol → exchange
    request = CancelRequest("12345", "rb2410", Exchange.SHFE)

    assert request.order_id == "12345"
    assert request.symbol == "rb2410"
    assert request.exchange is Exchange.SHFE


def test_order_request_defaults() -> None:
    request = OrderRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=10,
    )

    assert request.price == 0
    assert request.offset is Offset.NONE
    assert request.reference == ""
    assert request.instrument_key == "rb2410.SHFE"


def test_order_request_creates_order_data() -> None:
    request = OrderRequest(
        symbol="rb2410",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=10,
        price=3500,
        offset=Offset.OPEN,
        reference="strategy-1",
    )

    order = request.create_order_data(order_id="A001", gateway_name="CTP")

    assert order.gateway_name == "CTP"
    assert order.symbol == "rb2410"
    assert order.exchange is Exchange.SHFE
    assert order.order_id == "A001"
    assert order.type is OrderType.LIMIT
    assert order.direction is Direction.LONG
    assert order.offset is Offset.OPEN
    assert order.price == 3500
    assert order.volume == 10
    assert order.reference == "strategy-1"

    # 新委托的成交与状态取默认值，等待网关回报
    assert order.traded == 0
    assert order.status is Status.SUBMITTING
    assert order.datetime is None
    assert order.order_key == "CTP.A001"


def test_order_first_fill_updates_fields() -> None:
    """网关回报是原地更新的：委托对象可变，键随字段重算。"""
    order = make_order(volume=10, price=3500, datetime=datetime(2026, 11, 16, 9, 30))

    order.status = Status.PARTTRADED
    order.traded = 4

    assert order.is_active() is True
    assert order.status.label == "部分成交"
    assert order.order_key == "CTP.12345"


def test_order_equality_covers_all_fields() -> None:
    assert make_order() == make_order()
    assert make_order(gateway_name="IB") != make_order()
    assert make_order(status=Status.ALLTRADED) != make_order()
