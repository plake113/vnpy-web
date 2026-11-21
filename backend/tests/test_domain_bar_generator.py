"""``vnpy/trader/utility.py`` 的 ``BarGenerator`` → ``app/domain/bar_generator.py`` 迁移测试。

重点验证：

- Tick → 1 分钟 K 线：0 价格过滤、跨分钟收盘、同分钟极值、累计量差分与回退、日内极值吸收；
- 1 分钟 K 线 → N 分钟窗口 / 小时线 / 多小时 / 日线，且多周期通过返回列表串联；
- 原版边界：跨午夜的完整时间比较、日线缺少收盘线的跨日兜底、window / 周期参数校验；
- 结果通过返回值交付，不再依赖回调。
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from app.domain.bar_generator import BarGenerator
from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, TickData


def dt(hour: int, minute: int, second: int = 0, *, day: int = 2) -> datetime:
    return datetime(2024, 1, day, hour, minute, second)


def make_tick(
    timestamp: datetime,
    last_price: float,
    *,
    high_price: float = 0,
    low_price: float = 0,
    volume: float = 0,
    turnover: float = 0,
    open_interest: float = 0,
) -> TickData:
    return TickData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=timestamp,
        last_price=last_price,
        high_price=high_price,
        low_price=low_price,
        volume=volume,
        turnover=turnover,
        open_interest=open_interest,
    )


def make_bar(
    timestamp: datetime,
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1,
    turnover: float = 0,
    open_interest: float = 0,
) -> BarData:
    return BarData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=timestamp,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
        turnover=turnover,
        open_interest=open_interest,
    )


def test_tick_builds_one_minute_bar() -> None:
    generator = BarGenerator()

    assert generator.update_tick(make_tick(dt(9, 0, 5), 100, volume=10)) == []
    # last_price 为 0 的 tick 被忽略，也不更新 last_tick
    assert generator.update_tick(make_tick(dt(9, 0, 20), 0, volume=99)) == []
    assert generator.update_tick(make_tick(dt(9, 0, 40), 110, volume=16)) == []

    bar = generator.generate()

    assert bar is not None
    assert bar.datetime == dt(9, 0)
    assert bar.open_price == 100
    assert bar.high_price == 110
    assert bar.low_price == 100
    assert bar.close_price == 110
    assert bar.volume == 6
    assert bar.instrument_key == "rb2410.SHFE"
    assert bar.interval is Interval.MINUTE


def test_new_minute_closes_previous_bar() -> None:
    generator = BarGenerator()

    generator.update_tick(make_tick(dt(9, 0, 10), 100))
    finished = generator.update_tick(make_tick(dt(9, 1, 0), 102))

    assert len(finished) == 1
    assert finished[0].datetime == dt(9, 0)
    assert finished[0].close_price == 100

    current = generator.generate()
    assert current is not None
    assert current.datetime == dt(9, 1)
    assert current.open_price == 102


def test_same_minute_updates_extremes_and_cumulative_deltas() -> None:
    generator = BarGenerator()
    generator.update_tick(
        make_tick(dt(9, 0, 5), 100, high_price=101, low_price=99, volume=10, turnover=1000)
    )
    generator.update_tick(
        make_tick(dt(9, 0, 40), 100, high_price=103, low_price=97, volume=16, turnover=7000)
    )

    bar = generator.generate()

    assert bar is not None
    assert bar.high_price == 103
    assert bar.low_price == 97
    assert bar.volume == 6
    assert bar.turnover == 6000


def test_new_minute_absorbs_new_day_extreme() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 10), 100, high_price=101, low_price=99))
    finished = generator.update_tick(make_tick(dt(9, 1, 0), 100, high_price=105, low_price=95))
    generator.update_tick(make_tick(dt(9, 1, 30), 102, high_price=105, low_price=95))

    assert len(finished) == 1
    assert (finished[0].high_price, finished[0].low_price) == (100, 100)

    bar = generator.generate()
    assert bar is not None
    assert (bar.high_price, bar.low_price) == (105, 95)


def test_unchanged_day_extreme_is_not_absorbed_again() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 10), 100, high_price=110, low_price=90))
    generator.update_tick(make_tick(dt(9, 1, 5), 102, high_price=110, low_price=90))

    bar = generator.generate()

    assert bar is not None
    assert (bar.high_price, bar.low_price) == (102, 102)


def test_first_tick_ignores_cumulative_totals_and_day_extremes() -> None:
    generator = BarGenerator()
    generator.update_tick(
        make_tick(
            dt(9, 30),
            100,
            high_price=120,
            low_price=80,
            volume=5000,
            turnover=8_000_000,
        )
    )

    bar = generator.generate()

    assert bar is not None
    assert (bar.high_price, bar.low_price) == (100, 100)
    assert (bar.volume, bar.turnover) == (0, 0)


def test_zero_extremes_are_ignored() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 1), 100, high_price=102, low_price=96))
    generator.update_tick(make_tick(dt(9, 0, 2), 100, high_price=102, low_price=95))
    generator.update_tick(make_tick(dt(9, 0, 3), 100, high_price=102, low_price=0))

    bar = generator.generate()

    assert bar is not None
    assert bar.low_price == 95


def test_negative_extremes_are_accepted() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 5), -6, high_price=-4, low_price=-8))
    generator.update_tick(make_tick(dt(9, 0, 40), -6, high_price=-3, low_price=-10))

    bar = generator.generate()

    assert bar is not None
    assert (bar.high_price, bar.low_price) == (-3, -10)


def test_cumulative_total_rollback_is_ignored() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 1), 100, volume=100, turnover=1000))
    generator.update_tick(make_tick(dt(9, 0, 2), 100, volume=110, turnover=7000))
    generator.update_tick(make_tick(dt(9, 0, 3), 100, volume=80, turnover=2000))

    bar = generator.generate()

    assert bar is not None
    assert (bar.volume, bar.turnover) == (10, 6000)


def test_new_session_absorbs_extreme_beyond_previous_session() -> None:
    generator = BarGenerator()
    generator.update_tick(
        make_tick(
            dt(14, 59, 50),
            3960,
            high_price=4000,
            low_price=3900,
            volume=100_000,
            turnover=5_000_000,
        )
    )
    finished = generator.update_tick(
        make_tick(dt(9, 0, 1, day=3), 3960, high_price=4010, low_price=3950, volume=50)
    )

    assert len(finished) == 1
    assert (finished[0].high_price, finished[0].low_price) == (3960, 3960)

    bar = generator.generate()
    assert bar is not None
    assert (bar.high_price, bar.low_price) == (4010, 3960)
    assert (bar.volume, bar.turnover) == (0, 0)


def test_generate_returns_current_bar_once() -> None:
    generator = BarGenerator()
    generator.update_tick(make_tick(dt(9, 0, 1), 100))

    first = generator.generate()
    second = generator.generate()

    assert first is not None
    assert first.datetime == dt(9, 0)
    assert second is None


def test_invalid_zero_price_tick_does_not_create_bar() -> None:
    generator = BarGenerator()

    assert generator.update_tick(make_tick(dt(9, 0, 1), 0)) == []
    assert generator.generate() is None


def test_five_minute_window_completes_on_fifth_bar() -> None:
    generator = BarGenerator(window=5)
    prices = [10, 12, 9, 11, 13]

    completed: list[BarData] = []
    for offset, price in enumerate(prices):
        bar = make_bar(
            dt(9, offset),
            open_price=price,
            high_price=price + 1,
            low_price=price - 1,
            close_price=price,
            volume=offset + 1,
        )
        finished = generator.update_bar(bar)
        if offset < 4:
            assert finished == []
        completed.extend(finished)

    assert len(completed) == 1
    window_bar = completed[0]
    assert window_bar.datetime == dt(9, 0)
    assert window_bar.open_price == 10
    assert window_bar.high_price == 14
    assert window_bar.low_price == 8
    assert window_bar.close_price == 13
    assert window_bar.volume == 15
    assert window_bar.interval is None


def test_single_bar_window_emits_every_bar() -> None:
    generator = BarGenerator(window=1)
    bar = make_bar(
        dt(9, 0, 30),
        open_price=10,
        high_price=11,
        low_price=9,
        close_price=10,
    )

    completed = generator.update_bar(bar)

    assert len(completed) == 1
    assert completed[0].datetime == dt(9, 0)
    assert completed[0] is not bar


def test_zero_minute_window_does_not_aggregate() -> None:
    generator = BarGenerator(window=0)
    bar = make_bar(dt(9, 0), open_price=10, high_price=11, low_price=9, close_price=10)

    assert generator.update_bar(bar) == []


def test_minute_window_must_divide_an_hour() -> None:
    with pytest.raises(ValueError, match="整除 60"):
        BarGenerator(window=7)


def test_ticks_can_be_chained_into_a_window_generator() -> None:
    ticks = BarGenerator()
    windows = BarGenerator(window=5)

    minute_bars: list[BarData] = []
    for minute in range(6):
        minute_bars.extend(
            ticks.update_tick(make_tick(dt(9, minute, 30), 10 + minute))
        )

    assert [bar.datetime for bar in minute_bars] == [
        dt(9, 0),
        dt(9, 1),
        dt(9, 2),
        dt(9, 3),
        dt(9, 4),
    ]

    window_bars: list[BarData] = []
    for bar in minute_bars:
        window_bars.extend(windows.update_bar(bar))

    assert len(window_bars) == 1
    assert window_bars[0].datetime == dt(9, 0)
    assert (window_bars[0].open_price, window_bars[0].high_price) == (10, 14)
    assert (window_bars[0].low_price, window_bars[0].close_price) == (10, 14)


def test_hour_bar_completes_at_minute_59() -> None:
    generator = BarGenerator(window=1, interval=Interval.HOUR)

    assert generator.update_bar(
        make_bar(dt(9, 0), open_price=10, high_price=11, low_price=9, close_price=10, volume=1)
    ) == []
    assert generator.update_bar(
        make_bar(dt(9, 30), open_price=10, high_price=12, low_price=9, close_price=11, volume=2)
    ) == []

    completed = generator.update_bar(
        make_bar(dt(9, 59), open_price=11, high_price=13, low_price=10, close_price=12, volume=3)
    )

    assert len(completed) == 1
    hour_bar = completed[0]
    assert hour_bar.datetime == dt(9, 0)
    assert (hour_bar.open_price, hour_bar.high_price) == (10, 13)
    assert (hour_bar.low_price, hour_bar.close_price) == (9, 12)
    assert hour_bar.volume == 6


def test_hour_bar_completes_when_next_hour_starts() -> None:
    generator = BarGenerator(window=1, interval=Interval.HOUR)

    generator.update_bar(
        make_bar(dt(9, 0), open_price=10, high_price=11, low_price=9, close_price=10, volume=1)
    )
    generator.update_bar(
        make_bar(dt(9, 30), open_price=10, high_price=12, low_price=9, close_price=11, volume=2)
    )
    completed = generator.update_bar(
        make_bar(dt(10, 0), open_price=11, high_price=12, low_price=10, close_price=11, volume=3)
    )

    assert len(completed) == 1
    assert completed[0].datetime == dt(9, 0)
    assert completed[0].close_price == 11
    assert completed[0].volume == 3


def test_hour_bar_completes_across_days_with_same_hour() -> None:
    generator = BarGenerator(window=1, interval=Interval.HOUR)

    generator.update_bar(
        make_bar(dt(9, 0, day=2), open_price=10, high_price=11, low_price=9, close_price=10)
    )
    completed = generator.update_bar(
        make_bar(dt(9, 0, day=3), open_price=20, high_price=21, low_price=19, close_price=20)
    )

    assert len(completed) == 1
    assert completed[0].datetime == dt(9, 0, day=2)
    assert completed[0].close_price == 10


def test_two_hour_window_aggregates() -> None:
    generator = BarGenerator(window=2, interval=Interval.HOUR)

    generator.update_bar(
        make_bar(dt(9, 0), open_price=10, high_price=11, low_price=9, close_price=10, volume=1)
    )
    assert generator.update_bar(
        make_bar(dt(9, 59), open_price=10, high_price=12, low_price=9, close_price=11, volume=2)
    ) == []
    assert generator.update_bar(
        make_bar(dt(10, 0), open_price=11, high_price=12, low_price=10, close_price=11, volume=3)
    ) == []

    completed = generator.update_bar(
        make_bar(dt(10, 59), open_price=11, high_price=13, low_price=10, close_price=12, volume=4)
    )

    assert len(completed) == 1
    window_bar = completed[0]
    assert window_bar.datetime == dt(9, 0)
    assert (window_bar.open_price, window_bar.high_price) == (10, 13)
    assert (window_bar.low_price, window_bar.close_price) == (9, 12)
    assert window_bar.volume == 10


def test_hour_window_requires_positive_window() -> None:
    with pytest.raises(ValueError, match="window >= 1"):
        BarGenerator(window=0, interval=Interval.HOUR)


def test_daily_bar_completes_at_daily_end() -> None:
    generator = BarGenerator(interval=Interval.DAILY, daily_end=time(15, 0))

    generator.update_bar(
        make_bar(dt(9, 0), open_price=10, high_price=11, low_price=9, close_price=10, volume=1)
    )
    assert generator.update_bar(
        make_bar(dt(14, 59), open_price=10, high_price=12, low_price=9, close_price=11, volume=2)
    ) == []

    completed = generator.update_bar(
        make_bar(dt(15, 0), open_price=11, high_price=13, low_price=10, close_price=12, volume=3)
    )

    assert len(completed) == 1
    daily_bar = completed[0]
    assert daily_bar.datetime == datetime(2024, 1, 2)
    assert (daily_bar.open_price, daily_bar.high_price) == (10, 13)
    assert (daily_bar.low_price, daily_bar.close_price) == (9, 12)
    assert daily_bar.volume == 6


def test_daily_bar_closes_on_date_change_when_daily_end_is_missing() -> None:
    generator = BarGenerator(interval=Interval.DAILY, daily_end=time(15, 0))

    generator.update_bar(
        make_bar(dt(9, 0, day=2), open_price=10, high_price=11, low_price=9, close_price=10)
    )
    generator.update_bar(
        make_bar(dt(13, 0, day=2), open_price=10, high_price=12, low_price=9, close_price=11)
    )
    completed = generator.update_bar(
        make_bar(dt(9, 0, day=3), open_price=20, high_price=21, low_price=19, close_price=20)
    )

    assert len(completed) == 1
    assert completed[0].datetime == datetime(2024, 1, 2)
    assert completed[0].close_price == 11

    next_day = generator.update_bar(
        make_bar(dt(15, 0, day=3), open_price=20, high_price=22, low_price=19, close_price=21)
    )
    assert len(next_day) == 1
    assert next_day[0].datetime == datetime(2024, 1, 3)


def test_daily_bar_requires_daily_end() -> None:
    with pytest.raises(ValueError, match="daily_end"):
        BarGenerator(interval=Interval.DAILY)


def test_unsupported_intervals_are_rejected() -> None:
    for interval in (Interval.WEEKLY, Interval.TICK):
        with pytest.raises(ValueError, match="不支持周期"):
            BarGenerator(interval=interval)


def test_negative_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能为负数"):
        BarGenerator(window=-1)
