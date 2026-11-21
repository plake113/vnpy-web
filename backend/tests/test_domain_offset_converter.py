"""``trader/converter.py`` → ``app/domain/offset_converter.py`` 的迁移测试。

重点验证开平转换的领域规则（不依赖 OMS、数据库或网络）：

- 合约是否需要转换（未知合约 / ``net_position`` 合约不做转换）；
- 持仓快照与成交对今仓 / 昨仓的更新，含 SHFE / INE 与非 SHFE 的平仓差异；
- 冻结量只统计活跃平仓委托的未成交部分，且不超过实际持仓；
- SHFE / INE 平仓拆平今 + 平昨，可用持仓不足返回空列表；
- 锁仓模式（先反向开仓 / 先平昨再开）与净仓模式（先平后开）的拆分顺序；
- 下单预冻结、原请求不被修改、模式互斥与失效冻结量截断。
"""

from __future__ import annotations

import pytest

from app.domain.contracts import ContractData
from app.domain.enums import Direction, Exchange, Offset, OrderType, Product, Status
from app.domain.offset_converter import OffsetConverter, PositionHolding
from app.domain.orders import OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.trades import TradeData


def make_contract(
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
    *,
    net_position: bool = False,
) -> ContractData:
    return ContractData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        name="测试合约",
        product=Product.FUTURES,
        size=10,
        pricetick=1,
        net_position=net_position,
    )


def make_converter(*contracts: ContractData) -> OffsetConverter:
    lookup = {contract.instrument_key: contract for contract in contracts}
    return OffsetConverter(lookup.get)


def make_position(
    direction: Direction = Direction.LONG,
    volume: float = 10,
    yd_volume: float = 4,
    *,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> PositionData:
    return PositionData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        volume=volume,
        yd_volume=yd_volume,
        price=3500,
    )


def make_order(
    direction: Direction,
    offset: Offset,
    volume: float,
    *,
    order_id: str = "0001",
    traded: float = 0,
    status: Status = Status.SUBMITTING,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> OrderData:
    return OrderData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        order_id=order_id,
        direction=direction,
        offset=offset,
        volume=volume,
        traded=traded,
        price=3500,
        status=status,
    )


def make_request(
    direction: Direction,
    offset: Offset,
    volume: float,
    *,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        type=OrderType.LIMIT,
        volume=volume,
        price=3500,
        offset=offset,
    )


def make_trade(
    direction: Direction,
    offset: Offset,
    volume: float,
    *,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> TradeData:
    return TradeData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        order_id="0001",
        trade_id="T001",
        direction=direction,
        offset=offset,
        price=3500,
        volume=volume,
    )


def offsets_and_volumes(requests: list[OrderRequest]) -> list[tuple[Offset, float]]:
    return [(request.offset, request.volume) for request in requests]


def test_is_convert_required_by_contract() -> None:
    converter = make_converter(
        make_contract(),
        make_contract("IF2412", Exchange.CFFEX, net_position=True),
    )

    assert converter.is_convert_required("rb2410.SHFE")
    assert not converter.is_convert_required("IF2412.CFFEX")
    assert not converter.is_convert_required("unknown.SHFE")


def test_update_position_splits_today_and_yesterday() -> None:
    converter = make_converter(make_contract())

    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]
    assert (holding.long_pos, holding.long_yd, holding.long_td) == (10, 4, 6)

    converter.update_position(make_position(Direction.SHORT, volume=7, yd_volume=2))
    assert (holding.short_pos, holding.short_yd, holding.short_td) == (7, 2, 5)


def test_net_position_contract_is_not_tracked() -> None:
    contract = make_contract(net_position=True)
    converter = make_converter(contract)

    converter.update_position(make_position())
    converter.update_trade(make_trade(Direction.LONG, Offset.OPEN, 1))
    converter.update_order(make_order(Direction.SHORT, Offset.CLOSE, 1))
    converter.update_order_request(make_request(Direction.SHORT, Offset.CLOSE, 1), "FAKE.0001")

    assert converter.holdings == {}


def test_update_trade_applies_open_and_close_today() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    converter.update_trade(make_trade(Direction.LONG, Offset.OPEN, 2))
    assert (holding.long_pos, holding.long_td, holding.long_yd) == (12, 8, 4)

    converter.update_trade(make_trade(Direction.SHORT, Offset.CLOSETODAY, 3))
    assert (holding.long_pos, holding.long_td, holding.long_yd) == (9, 5, 4)


def test_update_trade_close_spills_to_yesterday_on_non_shfe() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    converter.update_position(
        make_position(
            Direction.LONG, volume=10, yd_volume=4, symbol="IF2412", exchange=Exchange.CFFEX
        )
    )
    holding = converter.holdings["IF2412.CFFEX"]

    # 非 SHFE / INE 的平仓按今仓优先：6 手今仓平完，再从昨仓平 2 手
    converter.update_trade(
        make_trade(
            Direction.SHORT,
            Offset.CLOSE,
            8,
            symbol="IF2412",
            exchange=Exchange.CFFEX,
        )
    )

    assert (holding.long_td, holding.long_yd, holding.long_pos) == (0, 2, 2)


def test_update_trade_close_reduces_yesterday_on_shfe() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    # SHFE 的 CLOSE 视为平昨；平今必须显式 CLOSETODAY
    converter.update_trade(make_trade(Direction.SHORT, Offset.CLOSE, 3))

    assert (holding.long_td, holding.long_yd, holding.long_pos) == (6, 1, 7)


def test_frozen_volume_counts_only_unfilled_close_orders() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    holding.update_order(make_order(Direction.SHORT, Offset.OPEN, 3, order_id="1"))
    assert holding.long_pos_frozen == 0

    holding.update_order(make_order(Direction.SHORT, Offset.CLOSE, 5, order_id="2"))
    assert (holding.long_td_frozen, holding.long_pos_frozen) == (5, 5)

    holding.update_order(make_order(Direction.SHORT, Offset.CLOSE, 5, order_id="2", traded=2))
    assert holding.long_td_frozen == 3


def test_buy_close_freezes_short_position() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    holding.update_order(make_order(Direction.LONG, Offset.CLOSE, 5))

    assert (holding.short_td_frozen, holding.short_pos_frozen) == (5, 5)
    assert holding.long_pos_frozen == 0


def test_frozen_volume_is_capped_by_position() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    holding.update_order(make_order(Direction.SHORT, Offset.CLOSE, 12))

    assert (holding.long_td_frozen, holding.long_yd_frozen) == (6, 4)
    assert holding.long_pos_frozen == 10
    assert holding.available_long == 0


def test_inactive_order_releases_frozen_volume() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))
    holding = converter.holdings["rb2410.SHFE"]

    holding.update_order(make_order(Direction.SHORT, Offset.CLOSE, 5, order_id="9"))
    assert holding.long_pos_frozen == 5

    holding.update_order(
        make_order(Direction.SHORT, Offset.CLOSE, 5, order_id="9", status=Status.CANCELLED)
    )

    assert holding.active_orders == {}
    assert holding.long_pos_frozen == 0


def test_update_order_request_reserves_frozen_volume() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=10, yd_volume=4))

    converter.update_order_request(make_request(Direction.SHORT, Offset.CLOSE, 5), "FAKE.0001")

    holding = converter.holdings["rb2410.SHFE"]
    assert set(holding.active_orders) == {"FAKE.0001"}
    assert holding.long_td_frozen == 5


def test_update_order_request_rejects_malformed_order_key() -> None:
    converter = make_converter(make_contract())

    with pytest.raises(ValueError, match="缺少点号"):
        converter.update_order_request(
            make_request(Direction.SHORT, Offset.CLOSE, 1),
            "FAKE0001",
        )


def test_shfe_close_splits_today_and_yesterday() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))
    request = make_request(Direction.LONG, Offset.CLOSE, 8)

    requests = converter.convert_order_request(request)

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 2),
    ]
    # 原请求保持不变，拆分结果互不影响
    assert (request.offset, request.volume) == (Offset.CLOSE, 8)
    assert all(item is not request for item in requests)


def test_shfe_close_uses_only_today_when_enough() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))

    requests = converter.convert_order_request(make_request(Direction.LONG, Offset.CLOSE, 4))

    assert offsets_and_volumes(requests) == [(Offset.CLOSETODAY, 4)]


def test_shfe_close_without_today_uses_yesterday() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=10))

    requests = converter.convert_order_request(make_request(Direction.LONG, Offset.CLOSE, 10))

    assert offsets_and_volumes(requests) == [(Offset.CLOSEYESTERDAY, 10)]


def test_shfe_close_returns_empty_when_position_is_insufficient() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))

    requests = converter.convert_order_request(make_request(Direction.LONG, Offset.CLOSE, 11))

    assert requests == []


def test_open_request_passes_through_unchanged() -> None:
    converter = make_converter(make_contract())
    request = make_request(Direction.LONG, Offset.OPEN, 2)

    requests = converter.convert_order_request(request)

    assert requests == [request]
    assert requests[0] is request


def test_non_shfe_close_is_not_split() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    request = make_request(
        Direction.SHORT, Offset.CLOSE, 3, symbol="IF2412", exchange=Exchange.CFFEX
    )

    requests = converter.convert_order_request(request)

    assert requests == [request]
    assert requests[0] is request


def test_lock_mode_opens_opposite_when_today_volume_exists() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    converter.update_position(
        make_position(
            Direction.LONG, volume=10, yd_volume=4, symbol="IF2412", exchange=Exchange.CFFEX
        )
    )

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 3, symbol="IF2412", exchange=Exchange.CFFEX),
        lock=True,
    )

    assert offsets_and_volumes(requests) == [(Offset.OPEN, 3)]


def test_lock_mode_closes_yesterday_then_opens_on_non_shfe() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    converter.update_position(
        make_position(
            Direction.LONG, volume=3, yd_volume=3, symbol="IF2412", exchange=Exchange.CFFEX
        )
    )

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 8, symbol="IF2412", exchange=Exchange.CFFEX),
        lock=True,
    )

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSE, 3),
        (Offset.OPEN, 5),
    ]


def test_lock_mode_closes_yesterday_then_opens_on_shfe() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=3, yd_volume=3))

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 8),
        lock=True,
    )

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSEYESTERDAY, 3),
        (Offset.OPEN, 5),
    ]


def test_lock_mode_opens_when_no_yesterday_available_on_shfe() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.LONG, volume=6, yd_volume=0))

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 3),
        lock=True,
    )

    assert offsets_and_volumes(requests) == [(Offset.OPEN, 3)]


def test_net_mode_splits_shfe_close_today_yesterday_and_open() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))

    requests = converter.convert_order_request(
        make_request(Direction.LONG, Offset.CLOSE, 12),
        net=True,
    )

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 4),
        (Offset.OPEN, 2),
    ]


def test_net_mode_shfe_partial_close_within_position() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))

    requests = converter.convert_order_request(
        make_request(Direction.LONG, Offset.CLOSE, 8),
        net=True,
    )

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSETODAY, 6),
        (Offset.CLOSEYESTERDAY, 2),
    ]


def test_net_mode_non_shfe_closes_then_opens() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    converter.update_position(
        make_position(
            Direction.LONG, volume=10, yd_volume=4, symbol="IF2412", exchange=Exchange.CFFEX
        )
    )

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 12, symbol="IF2412", exchange=Exchange.CFFEX),
        net=True,
    )

    assert offsets_and_volumes(requests) == [
        (Offset.CLOSE, 10),
        (Offset.OPEN, 2),
    ]


def test_net_mode_non_shfe_close_within_position() -> None:
    converter = make_converter(make_contract("IF2412", Exchange.CFFEX))
    converter.update_position(
        make_position(
            Direction.LONG, volume=10, yd_volume=4, symbol="IF2412", exchange=Exchange.CFFEX
        )
    )

    requests = converter.convert_order_request(
        make_request(Direction.SHORT, Offset.CLOSE, 8, symbol="IF2412", exchange=Exchange.CFFEX),
        net=True,
    )

    assert offsets_and_volumes(requests) == [(Offset.CLOSE, 8)]


def test_lock_and_net_are_mutually_exclusive() -> None:
    converter = make_converter(make_contract())

    with pytest.raises(ValueError, match="不能同时启用"):
        converter.convert_order_request(
            make_request(Direction.SHORT, Offset.CLOSE, 1),
            lock=True,
            net=True,
        )


def test_unknown_contract_passes_through_and_creates_no_holding() -> None:
    converter = make_converter()
    request = make_request(Direction.SHORT, Offset.CLOSE, 3)

    converter.update_position(make_position())

    assert converter.holdings == {}
    assert converter.convert_order_request(request) == [request]
    assert converter.convert_order_request(request, lock=True) == [request]
    assert converter.convert_order_request(request, net=True) == [request]


def test_stale_frozen_volume_does_not_inflate_close_volume() -> None:
    converter = make_converter(make_contract())
    converter.update_position(make_position(Direction.SHORT, volume=10, yd_volume=4))
    converter.update_order(
        make_order(Direction.LONG, Offset.CLOSETODAY, 6, order_id="1")
    )

    # 持仓快照变小：今仓 3、昨仓 5，冻结量仍是旧的 6（快照不重算冻结）
    converter.update_position(make_position(Direction.SHORT, volume=8, yd_volume=5))

    requests = converter.convert_order_request(make_request(Direction.LONG, Offset.CLOSE, 2))

    # 可用持仓 2（8 - 6）；今仓可用按 0 截断，拆成平昨 2，而不是 2 - (-3) = 5
    assert offsets_and_volumes(requests) == [(Offset.CLOSEYESTERDAY, 2)]


def test_position_holding_uses_contract_identity() -> None:
    holding = PositionHolding(make_contract())

    assert holding.instrument_key == "rb2410.SHFE"
    assert holding.exchange is Exchange.SHFE
    assert holding.active_orders == {}
