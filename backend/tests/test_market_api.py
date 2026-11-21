"""行情 API（``/api/v1/market``）集成测试。

覆盖：

- K 线区间查询与分页（``Page<BarRead>``），UTC 时间序列化；
- 时间参数校验：naive 时间 / start > end 返回统一错误结构；
- 空区间返回空页；
- 概览聚合 K 线 / Tick 的数量与范围。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud.market_data import save_bars, save_ticks
from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, TickData


def dt(minute: int = 0, hour: int = 9) -> datetime:
    return datetime(2024, 1, 2, hour, minute, tzinfo=UTC)


def make_bar(minute: int = 0, close_price: float = 3500) -> BarData:
    return BarData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=dt(minute),
        interval=Interval.MINUTE,
        open_price=close_price - 1,
        high_price=close_price + 1,
        low_price=close_price - 2,
        close_price=close_price,
        volume=10,
        turnover=35_000,
        open_interest=1_000,
    )


def make_tick() -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=dt(),
        last_price=3500,
    )


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def seed_bars(
    session_factory: async_sessionmaker[AsyncSession],
    bars: list[BarData],
) -> None:
    async with session_factory() as session:
        await save_bars(session, bars)
        await session.commit()


async def seed_ticks(
    session_factory: async_sessionmaker[AsyncSession],
    ticks: list[TickData],
) -> None:
    async with session_factory() as session:
        await save_ticks(session, ticks)
        await session.commit()


async def test_list_bars_with_pagination(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_bars(
        session_factory,
        [make_bar(0, 3500), make_bar(1, 3501), make_bar(2, 3502)],
    )

    response = await client.get(
        "/api/v1/market/bars",
        params={
            "instrument_key": "rb2410.SHFE",
            "interval": "1m",
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-03T00:00:00Z",
            "page": 1,
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (3, 1, 2, 2)
    assert [item["close_price"] for item in body["items"]] == [3500, 3501]
    assert body["items"][0]["instrument_key"] == "rb2410.SHFE"
    assert body["items"][0]["exchange"] == "SHFE"
    assert body["items"][0]["interval"] == "1m"
    assert parse_ts(body["items"][0]["datetime"]) == dt()


async def test_list_bars_second_page(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_bars(
        session_factory,
        [make_bar(0, 3500), make_bar(1, 3501), make_bar(2, 3502)],
    )

    response = await client.get(
        "/api/v1/market/bars",
        params={
            "instrument_key": "rb2410.SHFE",
            "interval": "1m",
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-03T00:00:00Z",
            "page": 2,
            "page_size": 2,
        },
    )

    body = response.json()
    assert [item["close_price"] for item in body["items"]] == [3502]
    assert body["pages"] == 2


async def test_list_bars_empty_range(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/market/bars",
        params={
            "instrument_key": "rb2410.SHFE",
            "interval": "1m",
            "start": "2024-01-03T00:00:00Z",
            "end": "2024-01-04T00:00:00Z",
        },
    )

    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["pages"] == 0


async def test_list_bars_rejects_naive_datetime(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/market/bars",
        params={
            "instrument_key": "rb2410.SHFE",
            "interval": "1m",
            "start": "2024-01-02T00:00:00",
            "end": "2024-01-03T00:00:00Z",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_DATETIME"
    assert body["request_id"]


async def test_list_bars_rejects_reversed_range(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/market/bars",
        params={
            "instrument_key": "rb2410.SHFE",
            "interval": "1m",
            "start": "2024-01-03T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_TIME_RANGE"


@pytest.mark.parametrize(
    "params",
    [
        {"instrument_key": "rb2410.SHFE", "interval": "bad", "start": "x", "end": "y"},
        {"instrument_key": "rb2410.SHFE", "interval": "1m"},
    ],
)
async def test_list_bars_validates_query_params(
    client: AsyncClient,
    params: dict[str, str],
) -> None:
    response = await client.get("/api/v1/market/bars", params=params)

    assert response.status_code == 422


async def test_market_overview(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_bars(session_factory, [make_bar(0), make_bar(1)])
    await seed_ticks(session_factory, [make_tick()])

    response = await client.get("/api/v1/market/overview")

    assert response.status_code == 200
    body = response.json()
    bar_overview = body["bars"][0]
    assert bar_overview["instrument_key"] == "rb2410.SHFE"
    assert bar_overview["interval"] == "1m"
    assert bar_overview["count"] == 2
    assert parse_ts(bar_overview["start"]) == dt()
    assert parse_ts(bar_overview["end"]) == dt(minute=1)

    tick_overview = body["ticks"][0]
    assert tick_overview["instrument_key"] == "rb2410.SHFE"
    assert tick_overview["count"] == 1
