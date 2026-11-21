"""``trader/database.py`` → ``app/crud/market_data.py`` 的持久化测试。

全部使用 SQLite 内存库，验证：

- K 线 / Tick 批量写入与按区间查询，字段与枚举完整往返；
- 唯一键幂等：同一合约 + 周期 + 时间的重复写入被忽略；
- 时间边界：只接受 aware 时间，任意偏移统一按 UTC 存储与返回；
- 删除与概览聚合；
- 参数错误（缺 interval、naive 时间）明确失败。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.market_data import (
    delete_bars,
    delete_ticks,
    get_bar_overview,
    get_tick_overview,
    load_bars,
    load_ticks,
    save_bars,
    save_ticks,
)
from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, TickData


def dt(day: int = 2, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, minute, tzinfo=UTC)


def make_bar(
    timestamp: datetime | None = None,
    *,
    close_price: float = 3500,
    interval: Interval | None = Interval.MINUTE,
    symbol: str = "rb2410",
    exchange: Exchange = Exchange.SHFE,
) -> BarData:
    return BarData(
        gateway_name="FAKE",
        symbol=symbol,
        exchange=exchange,
        datetime=timestamp or dt(),
        interval=interval,
        open_price=close_price - 1,
        high_price=close_price + 2,
        low_price=close_price - 3,
        close_price=close_price,
        volume=10,
        turnover=35_000,
        open_interest=1_000,
    )


def make_tick(timestamp: datetime | None = None) -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=timestamp or dt(),
        last_price=3500,
        last_volume=2,
        limit_up=3850,
        limit_down=3150,
        open_price=3480,
        high_price=3520,
        low_price=3470,
        pre_close=3490,
        volume=12345,
        turnover=43_000_000,
        open_interest=6_543,
        bid_price_1=3499,
        bid_price_2=3498,
        bid_price_3=3497,
        bid_price_4=3496,
        bid_price_5=3495,
        ask_price_1=3501,
        ask_price_2=3502,
        ask_price_3=3503,
        ask_price_4=3504,
        ask_price_5=3505,
        bid_volume_1=1,
        bid_volume_2=2,
        bid_volume_3=3,
        bid_volume_4=4,
        bid_volume_5=5,
        ask_volume_1=6,
        ask_volume_2=7,
        ask_volume_3=8,
        ask_volume_4=9,
        ask_volume_5=10,
    )


async def test_save_and_load_bars_roundtrip(db_session: AsyncSession) -> None:
    await save_bars(
        db_session,
        [make_bar(dt(minute=1), close_price=3501), make_bar(dt(), close_price=3500)],
    )

    loaded = await load_bars(
        db_session,
        "rb2410.SHFE",
        Interval.MINUTE,
        dt(),
        dt(minute=5),
    )

    assert [bar.datetime for bar in loaded] == [dt(), dt(minute=1)]
    assert [bar.close_price for bar in loaded] == [3500, 3501]
    assert loaded[0].instrument_key == "rb2410.SHFE"
    assert loaded[0].exchange is Exchange.SHFE
    assert loaded[0].interval is Interval.MINUTE
    assert loaded[0].datetime.tzinfo is UTC
    assert loaded[0].volume == 10
    assert loaded[0].turnover == 35_000


async def test_save_bars_is_idempotent(db_session: AsyncSession) -> None:
    bars = [make_bar(dt()), make_bar(dt(minute=1))]

    await save_bars(db_session, bars)
    await save_bars(db_session, bars)

    overview = await get_bar_overview(db_session)
    assert len(overview) == 1
    assert overview[0].count == 2


async def test_save_bars_requires_interval(db_session: AsyncSession) -> None:
    bar = make_bar()
    bar.interval = None

    with pytest.raises(ValueError, match="interval"):
        await save_bars(db_session, [bar])


async def test_naive_datetime_is_rejected(db_session: AsyncSession) -> None:
    naive_bar = make_bar(datetime(2024, 1, 2, 9, 0))
    naive_tick = make_tick(datetime(2024, 1, 2, 9, 0))

    with pytest.raises(ValueError, match="带时区"):
        await save_bars(db_session, [naive_bar])
    with pytest.raises(ValueError, match="带时区"):
        await save_ticks(db_session, [naive_tick])
    with pytest.raises(ValueError, match="带时区"):
        await load_bars(
            db_session,
            "rb2410.SHFE",
            Interval.MINUTE,
            datetime(2024, 1, 2),
            datetime(2024, 1, 3),
        )


async def test_load_bars_filters_by_interval_and_range(db_session: AsyncSession) -> None:
    await save_bars(
        db_session,
        [
            make_bar(dt(), close_price=3500),
            make_bar(dt(minute=1), close_price=3501),
            make_bar(dt(), close_price=3600, interval=Interval.HOUR),
        ],
    )

    minute_bars = await load_bars(
        db_session,
        "rb2410.SHFE",
        Interval.MINUTE,
        dt(minute=1),
        dt(minute=2),
    )
    hour_bars = await load_bars(
        db_session,
        "rb2410.SHFE",
        Interval.HOUR,
        dt(),
        dt(),
    )

    assert [bar.close_price for bar in minute_bars] == [3501]
    assert [bar.close_price for bar in hour_bars] == [3600]

    empty = await load_bars(
        db_session,
        "rb2410.SHFE",
        Interval.MINUTE,
        dt(day=3),
        dt(day=4),
    )
    assert empty == []


async def test_delete_bars_returns_affected_rows(db_session: AsyncSession) -> None:
    await save_bars(db_session, [make_bar(dt()), make_bar(dt(minute=1))])

    removed = await delete_bars(db_session, "rb2410.SHFE", Interval.MINUTE)

    assert removed == 2
    assert await get_bar_overview(db_session) == []
    assert await delete_bars(db_session, "rb2410.SHFE", Interval.MINUTE) == 0


async def test_bar_overview_groups_by_instrument_and_interval(
    db_session: AsyncSession,
) -> None:
    await save_bars(
        db_session,
        [
            make_bar(dt(minute=1)),
            make_bar(dt(minute=2)),
            make_bar(dt(day=3), symbol="IF2412", exchange=Exchange.CFFEX, interval=Interval.HOUR),
        ],
    )

    overview = await get_bar_overview(db_session)

    assert [(item.instrument_key, item.interval, item.count) for item in overview] == [
        ("IF2412.CFFEX", Interval.HOUR, 1),
        ("rb2410.SHFE", Interval.MINUTE, 2),
    ]
    assert overview[1].start == dt(minute=1)
    assert overview[1].end == dt(minute=2)
    assert overview[1].start.tzinfo is UTC


async def test_save_and_load_ticks_roundtrip(db_session: AsyncSession) -> None:
    tick = make_tick()

    await save_ticks(db_session, [tick])
    loaded = await load_ticks(db_session, "rb2410.SHFE", dt(hour=8), dt(hour=10))

    assert len(loaded) == 1
    assert loaded[0] == tick
    assert loaded[0].datetime.tzinfo is UTC
    assert loaded[0].bid_price_5 == 3495
    assert loaded[0].ask_volume_5 == 10


async def test_save_ticks_is_idempotent_and_overview(db_session: AsyncSession) -> None:
    ticks = [make_tick(dt(minute=0)), make_tick(dt(minute=1))]

    await save_ticks(db_session, ticks)
    await save_ticks(db_session, ticks)

    overview = await get_tick_overview(db_session)

    assert len(overview) == 1
    assert overview[0].instrument_key == "rb2410.SHFE"
    assert overview[0].count == 2
    assert overview[0].start == dt(minute=0)
    assert overview[0].end == dt(minute=1)


async def test_delete_ticks_returns_affected_rows(db_session: AsyncSession) -> None:
    await save_ticks(db_session, [make_tick()])

    removed = await delete_ticks(db_session, "rb2410.SHFE")

    assert removed == 1
    assert await get_tick_overview(db_session) == []
    assert await delete_ticks(db_session, "rb2410.SHFE") == 0


async def test_timezone_offsets_are_normalized_to_utc(db_session: AsyncSession) -> None:
    beijing = timezone(timedelta(hours=8))
    utc_equivalent = datetime(2024, 1, 2, 1, 0, tzinfo=UTC)

    await save_bars(db_session, [make_bar(datetime(2024, 1, 2, 9, 0, tzinfo=beijing))])
    # 同一时刻（+08:00 09:00 == UTC 01:00）再次写入应命中唯一键
    await save_bars(db_session, [make_bar(utc_equivalent)])

    loaded = await load_bars(
        db_session,
        "rb2410.SHFE",
        Interval.MINUTE,
        utc_equivalent,
        utc_equivalent,
    )

    assert len(loaded) == 1
    assert loaded[0].datetime == utc_equivalent


async def test_empty_batches_are_noops(db_session: AsyncSession) -> None:
    await save_bars(db_session, [])
    await save_ticks(db_session, [])

    assert await get_bar_overview(db_session) == []
    assert await get_tick_overview(db_session) == []


async def test_large_bar_batches_are_chunked(db_session: AsyncSession) -> None:
    bars = [
        make_bar(dt(hour=9, minute=0) + timedelta(minutes=offset))
        for offset in range(1200)
    ]

    await save_bars(db_session, bars)

    overview = await get_bar_overview(db_session)
    assert len(overview) == 1
    assert overview[0].count == 1200
    assert overview[0].start == dt()
    assert overview[0].end == dt() + timedelta(minutes=1199)
