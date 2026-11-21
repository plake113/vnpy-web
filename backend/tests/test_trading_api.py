"""交易 API（``/api/v1/trading`` 相关路径）集成测试。

覆盖：

- 委托 / 成交 / 持仓 / 账户 / 合约 / 报价的查询与分页；
- DB（事实来源）与 OMS（即时状态）按业务键合并，同键 OMS 覆盖；
- 活跃委托过滤、合约过滤、详情与 404；
- UTC 时间序列化与派生字段（``available``）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud.trading import (
    save_accounts,
    save_contracts,
    save_orders,
    save_positions,
    save_quotes,
    save_trades,
)
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.enums import (
    Direction,
    Exchange,
    Offset,
    OrderType,
    Product,
    Status,
)
from app.domain.orders import OrderData
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.trades import TradeData
from app.services.trading.runtime import TradingRuntime


def dt() -> datetime:
    return datetime(2024, 1, 2, 9, 0, tzinfo=UTC)


def make_order(
    order_id: str = "0001",
    *,
    status: Status = Status.NOTTRADED,
    traded: float = 0,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> OrderData:
    return OrderData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        order_id=order_id,
        type=OrderType.LIMIT,
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=3500,
        volume=2,
        traded=traded,
        status=status,
        datetime=dt(),
    )


def make_trade(trade_id: str = "T001", *, price: float = 3500) -> TradeData:
    return TradeData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        order_id="0001",
        trade_id=trade_id,
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=price,
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
        symbol="rb2410",
        exchange=Exchange.SHFE,
        name="螺纹钢2410",
        product=Product.FUTURES,
        size=10,
        pricetick=1,
        history_data=True,
    )


def make_quote() -> QuoteData:
    return QuoteData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        quote_id="Q001",
        bid_price=3499,
        bid_volume=1,
        ask_price=3501,
        ask_volume=2,
        status=Status.NOTTRADED,
        datetime=dt(),
    )


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_orders_merge_db_and_oms(
    client: AsyncClient,
    runtime: TradingRuntime,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await save_orders(
            session,
            [
                make_order("0001"),
                make_order("0003", symbol="IF2412", exchange=Exchange.CFFEX),
            ],
        )
        await session.commit()

    runtime.oms.update_order(make_order("0001", status=Status.ALLTRADED, traded=2))
    runtime.oms.update_order(make_order("0002", status=Status.SUBMITTING))

    response = await client.get("/api/v1/orders", params={"page_size": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["order_key"] for item in body["items"]] == [
        "FAKE.0001",
        "FAKE.0002",
        "FAKE.0003",
    ]
    assert body["items"][0]["status"] == "ALLTRADED"
    assert body["items"][0]["traded"] == 2
    assert parse_ts(body["items"][0]["datetime"]) == dt()
    assert body["items"][2]["instrument_key"] == "IF2412.CFFEX"


async def test_orders_support_active_and_instrument_filters(
    client: AsyncClient,
    runtime: TradingRuntime,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await save_orders(
            session,
            [
                make_order("0001"),
                make_order("0003", symbol="IF2412", exchange=Exchange.CFFEX),
            ],
        )
        await session.commit()

    runtime.oms.update_order(make_order("0001", status=Status.ALLTRADED, traded=2))
    runtime.oms.update_order(make_order("0002", status=Status.SUBMITTING))

    active = await client.get("/api/v1/orders", params={"active_only": "true"})
    rub = await client.get(
        "/api/v1/orders",
        params={"instrument_key": "rb2410.SHFE"},
    )

    assert [item["order_key"] for item in active.json()["items"]] == [
        "FAKE.0002",
        "FAKE.0003",
    ]
    assert [item["order_key"] for item in rub.json()["items"]] == [
        "FAKE.0001",
        "FAKE.0002",
    ]


async def test_orders_pagination(
    client: AsyncClient,
    runtime: TradingRuntime,
) -> None:
    for index in range(1, 4):
        runtime.oms.update_order(make_order(f"{index:04d}"))

    first = await client.get("/api/v1/orders", params={"page": 1, "page_size": 2})
    second = await client.get("/api/v1/orders", params={"page": 2, "page_size": 2})

    assert first.json()["pages"] == 2
    assert len(first.json()["items"]) == 2
    assert [item["order_key"] for item in second.json()["items"]] == ["FAKE.0003"]


async def test_order_detail_and_not_found(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await save_orders(session, [make_order("0003")])
        await session.commit()

    found = await client.get("/api/v1/orders/FAKE.0003")
    missing = await client.get("/api/v1/orders/FAKE.9999")

    assert found.status_code == 200
    assert found.json()["order_key"] == "FAKE.0003"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ORDER_NOT_FOUND"


async def test_trades_merge_and_filter(
    client: AsyncClient,
    runtime: TradingRuntime,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await save_trades(session, [make_trade("T001")])
        await session.commit()

    runtime.oms.update_trade(make_trade("T001", price=9999))
    runtime.oms.update_trade(make_trade("T002"))

    response = await client.get(
        "/api/v1/trades",
        params={"instrument_key": "rb2410.SHFE"},
    )

    body = response.json()
    assert body["total"] == 2
    assert [item["trade_key"] for item in body["items"]] == ["FAKE.T001", "FAKE.T002"]
    assert body["items"][0]["price"] == 9999


async def test_positions_accounts_contracts_quotes(
    client: AsyncClient,
    runtime: TradingRuntime,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await save_positions(session, [make_position()])
        await save_accounts(session, [make_account()])
        await save_contracts(session, [make_contract()])
        await save_quotes(session, [make_quote()])
        await session.commit()

    runtime.oms.update_account(
        AccountData(
            gateway_name="FAKE",
            account_id="ACC001",
            balance=900_000,
            frozen=20_000,
        )
    )
    updated_contract = make_contract()
    updated_contract.name = "螺纹钢2410（更新）"
    runtime.oms.update_contract(updated_contract)
    runtime.oms.update_quote(
        QuoteData(
            gateway_name="FAKE",
            symbol="rb2410",
            exchange=Exchange.SHFE,
            quote_id="Q001",
            bid_price=3499,
            bid_volume=1,
            ask_price=3501,
            ask_volume=2,
            status=Status.CANCELLED,
            datetime=dt(),
        )
    )

    positions = (await client.get("/api/v1/positions")).json()
    accounts = (await client.get("/api/v1/accounts")).json()
    contracts = (await client.get("/api/v1/contracts")).json()
    quotes = (await client.get("/api/v1/quotes")).json()

    assert positions["items"][0]["position_key"] == "FAKE.rb2410.SHFE.LONG"
    assert accounts["items"][0]["balance"] == 900_000
    assert accounts["items"][0]["available"] == 880_000
    assert contracts["items"][0]["name"] == "螺纹钢2410（更新）"
    assert quotes["items"][0]["status"] == "CANCELLED"


async def test_empty_trading_lists(client: AsyncClient) -> None:
    for path in ("/api/v1/orders", "/api/v1/trades", "/api/v1/positions"):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["items"] == []
