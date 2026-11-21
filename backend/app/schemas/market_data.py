"""行情 HTTP 契约：K 线、Tick 概览。

响应直接由领域对象 / 仓储概览转换（``from_attributes``），字段保持 snake_case；
``datetime`` 统一为 UTC ISO（数据库读取时已补 UTC，序列化带 ``+00:00``）。
"""

from __future__ import annotations

from datetime import datetime as Datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Exchange, Interval

__all__ = [
    "BarOverviewRead",
    "BarRead",
    "MarketOverviewRead",
    "TickOverviewRead",
]


class BarRead(BaseModel):
    """一根 K 线。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str = Field(description="数据来源网关")
    instrument_key: str = Field(description="合约键，例如 rb2410.SHFE")
    symbol: str
    exchange: Exchange
    interval: Interval
    datetime: Datetime = Field(description="K 线时间（UTC）")

    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float
    open_interest: float


class BarOverviewRead(BaseModel):
    """某个合约 + 周期的 K 线概览。"""

    model_config = ConfigDict(from_attributes=True)

    instrument_key: str
    interval: Interval
    count: int
    start: Datetime
    end: Datetime


class TickOverviewRead(BaseModel):
    """某个合约的 Tick 概览。"""

    model_config = ConfigDict(from_attributes=True)

    instrument_key: str
    count: int
    start: Datetime
    end: Datetime


class MarketOverviewRead(BaseModel):
    """行情数据概览：数据库里已有的 K 线 / Tick 范围。"""

    bars: list[BarOverviewRead] = Field(default_factory=list)
    ticks: list[TickOverviewRead] = Field(default_factory=list)
