"""``vnpy/trader/object.py`` 的报价对象 → ``app/domain/quotes.py`` 的迁移测试。

重点验证：

- ``QuoteData`` / ``QuoteRequest`` 字段集合 / 顺序 / 默认值与原版一致
  （``quoteid`` → ``quote_id``，数量保持 ``int``）；
- ``quote_key`` 由 ``gateway_name`` + ``quote_id`` 派生（原 ``vt_quoteid``）；
- 活跃状态（原 ``ACTIVE_STATUSES``）与撤单请求复用委托链路；
- ``QuoteRequest.create_quote_data`` 的转换语义。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.domain.enums import Exchange, Offset, Status
from app.domain.orders import CancelRequest
from app.domain.quotes import QuoteData, QuoteRequest


def make_quote(**overrides: object) -> QuoteData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410C3500",
        "exchange": Exchange.SHFE,
        "quote_id": "Q001",
    }
    values.update(overrides)
    return QuoteData(**values)  # type: ignore[arg-type]


def test_quote_data_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(QuoteData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "quote_id",
        "bid_price",
        "bid_volume",
        "ask_price",
        "ask_volume",
        "bid_offset",
        "ask_offset",
        "status",
        "datetime",
        "reference",
    ]


def test_quote_data_defaults() -> None:
    quote = make_quote()

    assert quote.bid_price == 0.0
    assert quote.bid_volume == 0
    assert quote.ask_price == 0.0
    assert quote.ask_volume == 0
    assert quote.bid_offset is Offset.NONE
    assert quote.ask_offset is Offset.NONE
    assert quote.status is Status.SUBMITTING
    assert quote.datetime is None
    assert quote.reference == ""
    assert quote.extra is None


def test_quote_volumes_stay_int() -> None:
    quote = make_quote(bid_price=10.5, bid_volume=3, ask_price=11.5, ask_volume=4)

    assert quote.bid_volume == 3
    assert quote.ask_volume == 4
    assert isinstance(quote.bid_volume, int)


def test_quote_keys() -> None:
    quote = make_quote()

    assert quote.instrument_key == "rb2410C3500.SHFE"
    assert quote.quote_key == "CTP.Q001"

    field_names = {field.name for field in dataclasses.fields(quote)}
    assert {"instrument_key", "quote_key"}.isdisjoint(field_names)


def test_quote_key_follows_field_mutation() -> None:
    quote = make_quote()

    quote.quote_id = "Q002"
    quote.gateway_name = "IB"
    assert quote.quote_key == "IB.Q002"


def test_quote_key_is_read_only() -> None:
    quote = make_quote()

    with pytest.raises(AttributeError):
        quote.quote_key = "IB.Q001"  # type: ignore[misc]


def test_quote_is_active_for_all_statuses() -> None:
    active = {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}
    inactive = {Status.ALLTRADED, Status.CANCELLED, Status.REJECTED}
    assert active | inactive == set(Status)

    for status in Status:
        quote = make_quote(status=status)
        assert quote.is_active() is (status in active)


def test_quote_create_cancel_request() -> None:
    quote = make_quote(quote_id="Q001", symbol="rb2410C3500", exchange=Exchange.SHFE)

    request = quote.create_cancel_request()

    # 与原版一致：报价号填进 CancelRequest.order_id，由网关适配层区分委托 / 报价
    assert request == CancelRequest(
        order_id="Q001",
        symbol="rb2410C3500",
        exchange=Exchange.SHFE,
    )
    assert request.instrument_key == "rb2410C3500.SHFE"


def test_quote_request_defaults() -> None:
    request = QuoteRequest(
        symbol="rb2410C3500",
        exchange=Exchange.SHFE,
        bid_price=10.5,
        bid_volume=3,
        ask_price=11.5,
        ask_volume=4,
    )

    assert request.bid_offset is Offset.NONE
    assert request.ask_offset is Offset.NONE
    assert request.reference == ""
    assert request.instrument_key == "rb2410C3500.SHFE"


def test_quote_request_requires_both_sides() -> None:
    with pytest.raises(TypeError):
        QuoteRequest(  # type: ignore[call-arg]
            symbol="rb2410C3500",
            exchange=Exchange.SHFE,
            bid_price=10.5,
            bid_volume=3,
        )


def test_quote_request_creates_quote_data() -> None:
    request = QuoteRequest(
        symbol="rb2410C3500",
        exchange=Exchange.SHFE,
        bid_price=10.5,
        bid_volume=3,
        ask_price=11.5,
        ask_volume=4,
        bid_offset=Offset.OPEN,
        ask_offset=Offset.OPEN,
        reference="mm-1",
    )

    quote = request.create_quote_data(quote_id="Q009", gateway_name="CTP")

    assert quote.gateway_name == "CTP"
    assert quote.symbol == "rb2410C3500"
    assert quote.exchange is Exchange.SHFE
    assert quote.quote_id == "Q009"
    assert (quote.bid_price, quote.bid_volume) == (10.5, 3)
    assert (quote.ask_price, quote.ask_volume) == (11.5, 4)
    assert quote.bid_offset is Offset.OPEN
    assert quote.ask_offset is Offset.OPEN
    assert quote.reference == "mm-1"

    # 新报价等待网关回报
    assert quote.status is Status.SUBMITTING
    assert quote.datetime is None
    assert quote.quote_key == "CTP.Q009"


def test_quote_equality_covers_all_fields() -> None:
    assert make_quote() == make_quote()
    assert make_quote(quote_id="Q002") != make_quote()
    assert make_quote(status=Status.ALLTRADED) != make_quote()
    assert make_quote(datetime=datetime(2026, 11, 16, 9, 30)) != make_quote()
