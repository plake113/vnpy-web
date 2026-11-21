"""成交领域对象。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``TradeData``
（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` / ``vt_orderid`` / ``vt_tradeid`` 改为只读派生属性
  :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key` /
  :attr:`~app.domain.base.OrderKeyMixin.order_key` /
  :attr:`~app.domain.base.TradeKeyMixin.trade_key`（键名统一为 ``*_key``）；
- 网关本地 ID 统一 snake_case：``orderid`` → ``order_id``、``tradeid`` → ``trade_id``；
- 字段名、默认值不变：``direction`` / ``datetime`` 可为空，其余数值字段默认 0。

一笔委托可以对应多笔成交，因此成交同时携带自己的 ``trade_key`` 与所属委托的
``order_key``；OMS 与持久化层通过这两个键把成交归并到委托。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as Datetime

from app.domain.base import BaseData, InstrumentKeyMixin, TradeKeyMixin
from app.domain.enums import Direction, Exchange, Offset

__all__ = ["TradeData"]


@dataclass
class TradeData(InstrumentKeyMixin, TradeKeyMixin, BaseData):
    """一笔成交（委托的一次或部分成交）。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码
    :param exchange: 交易所
    :param order_id: 所属委托的网关本地委托号
    :param trade_id: 网关本地成交号
    :param direction: 买卖方向；网关回报补齐前可为空
    :param offset: 开平方向
    :param price: 成交价
    :param volume: 成交数量
    :param datetime: 成交时间；网关未提供时为空
    """

    symbol: str
    exchange: Exchange
    order_id: str
    trade_id: str

    direction: Direction | None = None
    offset: Offset = Offset.NONE
    price: float = 0
    volume: float = 0
    datetime: Datetime | None = None
