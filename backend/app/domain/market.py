"""行情领域对象：Tick、Bar 与订阅 / 历史查询请求。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``TickData``、``BarData``、
``SubscribeRequest``、``HistoryRequest``（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` 改为 :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key` 只读派生属性
  （键名统一为 ``*_key``）；
- 去掉 ``__post_init__`` 里的动态属性赋值，字段全部由 dataclass 声明，便于静态检查；
- 时间字段语义暂与原版一致（网关给出的 naive ``datetime``，通常已是交易所所在时区）；
  统一为 UTC aware 放在持久化单元处理，避免现在改动网关适配层的约定；
- 字段名、默认值、精度（``float``）保持不变，网关适配层不需要额外映射。

``TickData`` 的 5 档买卖盘用平铺字段表达（与 vnpy 一致）；如后续需要统一遍历，
再以属性视图补充，不改变存储结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as Datetime

from app.domain.base import BaseData, InstrumentKeyMixin
from app.domain.enums import Exchange, Interval

__all__ = [
    "BarData",
    "HistoryRequest",
    "SubscribeRequest",
    "TickData",
]


@dataclass
class TickData(InstrumentKeyMixin, BaseData):
    """行情快照：最新成交、盘口与当日统计。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码（交易所本地格式）
    :param exchange: 交易所
    :param datetime: 交易所时间；naive，时区约定见模块说明
    :param localtime: 网关补充的本地时间，核心不写入；保留以兼容原字段
    """

    symbol: str
    exchange: Exchange
    datetime: Datetime

    name: str = ""
    volume: float = 0
    turnover: float = 0
    open_interest: float = 0
    last_price: float = 0
    last_volume: float = 0
    limit_up: float = 0
    limit_down: float = 0

    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    pre_close: float = 0

    bid_price_1: float = 0
    bid_price_2: float = 0
    bid_price_3: float = 0
    bid_price_4: float = 0
    bid_price_5: float = 0

    ask_price_1: float = 0
    ask_price_2: float = 0
    ask_price_3: float = 0
    ask_price_4: float = 0
    ask_price_5: float = 0

    bid_volume_1: float = 0
    bid_volume_2: float = 0
    bid_volume_3: float = 0
    bid_volume_4: float = 0
    bid_volume_5: float = 0

    ask_volume_1: float = 0
    ask_volume_2: float = 0
    ask_volume_3: float = 0
    ask_volume_4: float = 0
    ask_volume_5: float = 0

    localtime: Datetime | None = None


@dataclass
class BarData(InstrumentKeyMixin, BaseData):
    """某个周期的 K 线（烛台）数据。

    :param interval: K 线周期；历史查询结果里通常由请求带入，聚合场景下可留空
    """

    symbol: str
    exchange: Exchange
    datetime: Datetime

    interval: Interval | None = None
    volume: float = 0
    turnover: float = 0
    open_interest: float = 0
    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    close_price: float = 0


@dataclass
class SubscribeRequest(InstrumentKeyMixin):
    """向网关发起行情订阅的请求。"""

    symbol: str
    exchange: Exchange


@dataclass
class HistoryRequest(InstrumentKeyMixin):
    """向网关 / 数据源查询历史 K 线的请求。

    :param start: 起始时间（含）
    :param end: 结束时间；为空表示取到最新
    :param interval: K 线周期；为空表示由数据源决定或查询 tick
    """

    symbol: str
    exchange: Exchange
    start: Datetime
    end: Datetime | None = None
    interval: Interval | None = None
