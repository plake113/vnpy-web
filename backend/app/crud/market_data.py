"""历史行情仓储：K 线 / Tick 的幂等写入、区间查询、删除与概览。

来源：vnpy 4.5.0 ``vnpy/trader/database.py`` 的 ``BaseDatabase`` / ``BarOverview`` /
``TickOverview``（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- 去掉全局 ``database`` 单例与 ``import_module("vnpy_xxx")``：会话由 FastAPI 依赖注入，
  本模块只做读写、只 ``flush``（实际为 Core 语句直接执行），事务由 service 层控制；
- 时间边界：写入 / 查询只接受 **aware** ``datetime``，内部统一转 UTC 存储（时间基准统一）；
  读取时补回 UTC。naive 时间抛 ``ValueError``，由网关入口 / 数据服务负责按交易所时区转换，
  仓储不做隐式猜测；
- 幂等写入：依赖 ``bars`` / ``ticks`` 的唯一键 ``ON CONFLICT DO NOTHING``。历史行情视为
  不可变数据；需要修正时先删除再写。目前支持 SQLite 与 PostgreSQL 两种方言；
- 概览返回 :class:`BarOverview` / :class:`TickOverview` 只读数据类，API 层再转 schema。

K 线唯一键是 ``(instrument_key, interval, datetime)``，因此写入的 ``BarData`` 必须带
``interval``；``TickData`` 没有周期，唯一键是 ``(instrument_key, datetime)``。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import insert_ignore
from app.domain.enums import Exchange, Interval
from app.domain.market import BarData, TickData
from app.models.market_data import BarRecord, TickRecord
from app.utils.timezone import from_utc, to_utc_naive

__all__ = [
    "BarOverview",
    "TickOverview",
    "count_bars",
    "delete_bars",
    "delete_ticks",
    "get_bar_overview",
    "get_tick_overview",
    "load_bars",
    "load_ticks",
    "save_bars",
    "save_ticks",
]



@dataclass(frozen=True, slots=True)
class BarOverview:
    """某个合约 + 周期的 K 线概览。"""

    instrument_key: str
    interval: Interval
    count: int
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class TickOverview:
    """某个合约的 Tick 概览。"""

    instrument_key: str
    count: int
    start: datetime
    end: datetime


# ---------------------------------------------------------------------------- 行转换


def _bar_values(bar: BarData) -> dict[str, Any]:
    if bar.interval is None:
        raise ValueError("持久化 K 线必须带 interval")

    return {
        "gateway_name": bar.gateway_name,
        "instrument_key": bar.instrument_key,
        "symbol": bar.symbol,
        "exchange": bar.exchange.value,
        "interval": bar.interval.value,
        "datetime": to_utc_naive(bar.datetime),
        "volume": bar.volume,
        "turnover": bar.turnover,
        "open_interest": bar.open_interest,
        "open_price": bar.open_price,
        "high_price": bar.high_price,
        "low_price": bar.low_price,
        "close_price": bar.close_price,
    }


def _tick_values(tick: TickData) -> dict[str, Any]:
    values: dict[str, Any] = {
        "gateway_name": tick.gateway_name,
        "instrument_key": tick.instrument_key,
        "symbol": tick.symbol,
        "exchange": tick.exchange.value,
        "datetime": to_utc_naive(tick.datetime),
        "last_price": tick.last_price,
        "last_volume": tick.last_volume,
        "limit_up": tick.limit_up,
        "limit_down": tick.limit_down,
        "open_price": tick.open_price,
        "high_price": tick.high_price,
        "low_price": tick.low_price,
        "pre_close": tick.pre_close,
        "volume": tick.volume,
        "turnover": tick.turnover,
        "open_interest": tick.open_interest,
    }

    for level in range(1, 6):
        values[f"bid_price_{level}"] = getattr(tick, f"bid_price_{level}")
        values[f"ask_price_{level}"] = getattr(tick, f"ask_price_{level}")
        values[f"bid_volume_{level}"] = getattr(tick, f"bid_volume_{level}")
        values[f"ask_volume_{level}"] = getattr(tick, f"ask_volume_{level}")

    return values


def _bar_to_domain(record: BarRecord) -> BarData:
    return BarData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        datetime=from_utc(record.datetime),
        interval=Interval(record.interval),
        volume=record.volume,
        turnover=record.turnover,
        open_interest=record.open_interest,
        open_price=record.open_price,
        high_price=record.high_price,
        low_price=record.low_price,
        close_price=record.close_price,
    )


def _tick_to_domain(record: TickRecord) -> TickData:
    return TickData(
        gateway_name=record.gateway_name,
        symbol=record.symbol,
        exchange=Exchange(record.exchange),
        datetime=from_utc(record.datetime),
        last_price=record.last_price,
        last_volume=record.last_volume,
        limit_up=record.limit_up,
        limit_down=record.limit_down,
        open_price=record.open_price,
        high_price=record.high_price,
        low_price=record.low_price,
        pre_close=record.pre_close,
        volume=record.volume,
        turnover=record.turnover,
        open_interest=record.open_interest,
        bid_price_1=record.bid_price_1,
        bid_price_2=record.bid_price_2,
        bid_price_3=record.bid_price_3,
        bid_price_4=record.bid_price_4,
        bid_price_5=record.bid_price_5,
        ask_price_1=record.ask_price_1,
        ask_price_2=record.ask_price_2,
        ask_price_3=record.ask_price_3,
        ask_price_4=record.ask_price_4,
        ask_price_5=record.ask_price_5,
        bid_volume_1=record.bid_volume_1,
        bid_volume_2=record.bid_volume_2,
        bid_volume_3=record.bid_volume_3,
        bid_volume_4=record.bid_volume_4,
        bid_volume_5=record.bid_volume_5,
        ask_volume_1=record.ask_volume_1,
        ask_volume_2=record.ask_volume_2,
        ask_volume_3=record.ask_volume_3,
        ask_volume_4=record.ask_volume_4,
        ask_volume_5=record.ask_volume_5,
    )


# ---------------------------------------------------------------------------- K 线


async def save_bars(db: AsyncSession, bars: Sequence[BarData]) -> None:
    """批量写入历史 K 线；同一唯一键的重复数据被忽略。

    :raises ValueError: 某根 K 线没有 ``interval``，或时间不是 aware
    """
    await insert_ignore(db, BarRecord, [_bar_values(bar) for bar in bars])


async def load_bars(
    db: AsyncSession,
    instrument_key: str,
    interval: Interval,
    start: datetime,
    end: datetime,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[BarData]:
    """按合约 + 周期 + 闭区间 ``[start, end]`` 查询 K 线，按时间升序返回。"""
    statement = (
        select(BarRecord)
        .where(
            BarRecord.instrument_key == instrument_key,
            BarRecord.interval == interval.value,
            BarRecord.datetime >= to_utc_naive(start),
            BarRecord.datetime <= to_utc_naive(end),
        )
        .order_by(BarRecord.datetime)
        .offset(offset)
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = (await db.execute(statement)).scalars().all()

    return [_bar_to_domain(row) for row in rows]


async def count_bars(
    db: AsyncSession,
    instrument_key: str,
    interval: Interval,
    start: datetime,
    end: datetime,
) -> int:
    """统计区间内 K 线数量，供分页使用。"""
    statement = select(func.count(BarRecord.id)).where(
        BarRecord.instrument_key == instrument_key,
        BarRecord.interval == interval.value,
        BarRecord.datetime >= to_utc_naive(start),
        BarRecord.datetime <= to_utc_naive(end),
    )

    return int(await db.scalar(statement) or 0)


async def delete_bars(db: AsyncSession, instrument_key: str, interval: Interval) -> int:
    """删除某合约 + 周期的全部 K 线，返回删除行数。"""
    result = await db.execute(
        delete(BarRecord).where(
            BarRecord.instrument_key == instrument_key,
            BarRecord.interval == interval.value,
        )
    )

    return int(cast(CursorResult[Any], result).rowcount or 0)


async def get_bar_overview(db: AsyncSession) -> list[BarOverview]:
    """按合约 + 周期汇总 K 线数量与时间范围。"""
    statement = (
        select(
            BarRecord.instrument_key,
            BarRecord.interval,
            func.count(BarRecord.id),
            func.min(BarRecord.datetime),
            func.max(BarRecord.datetime),
        )
        .group_by(BarRecord.instrument_key, BarRecord.interval)
        .order_by(BarRecord.instrument_key, BarRecord.interval)
    )
    rows = (await db.execute(statement)).all()

    return [
        BarOverview(
            instrument_key=instrument_key,
            interval=Interval(interval),
            count=int(count),
            start=from_utc(start),
            end=from_utc(end),
        )
        for instrument_key, interval, count, start, end in rows
    ]


# ---------------------------------------------------------------------------- Tick


async def save_ticks(db: AsyncSession, ticks: Sequence[TickData]) -> None:
    """批量写入历史 Tick；同一唯一键的重复数据被忽略。

    :raises ValueError: 某条 Tick 的时间不是 aware
    """
    await insert_ignore(db, TickRecord, [_tick_values(tick) for tick in ticks])


async def load_ticks(
    db: AsyncSession,
    instrument_key: str,
    start: datetime,
    end: datetime,
) -> list[TickData]:
    """按合约 + 闭区间 ``[start, end]`` 查询 Tick，按时间升序返回。"""
    statement = (
        select(TickRecord)
        .where(
            TickRecord.instrument_key == instrument_key,
            TickRecord.datetime >= to_utc_naive(start),
            TickRecord.datetime <= to_utc_naive(end),
        )
        .order_by(TickRecord.datetime)
    )
    rows = (await db.execute(statement)).scalars().all()

    return [_tick_to_domain(row) for row in rows]


async def delete_ticks(db: AsyncSession, instrument_key: str) -> int:
    """删除某合约的全部 Tick，返回删除行数。"""
    result = await db.execute(
        delete(TickRecord).where(TickRecord.instrument_key == instrument_key)
    )

    return int(cast(CursorResult[Any], result).rowcount or 0)


async def get_tick_overview(db: AsyncSession) -> list[TickOverview]:
    """按合约汇总 Tick 数量与时间范围。"""
    statement = (
        select(
            TickRecord.instrument_key,
            func.count(TickRecord.id),
            func.min(TickRecord.datetime),
            func.max(TickRecord.datetime),
        )
        .group_by(TickRecord.instrument_key)
        .order_by(TickRecord.instrument_key)
    )
    rows = (await db.execute(statement)).all()

    return [
        TickOverview(
            instrument_key=instrument_key,
            count=int(count),
            start=from_utc(start),
            end=from_utc(end),
        )
        for instrument_key, count, start, end in rows
    ]
