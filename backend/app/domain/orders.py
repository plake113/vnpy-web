"""委托领域对象：委托状态、下单请求与撤单请求。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``OrderData``、``OrderRequest``、
``CancelRequest`` 与模块级 ``ACTIVE_STATUSES``（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` / ``vt_orderid`` 改为 :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key`
  与 :attr:`~app.domain.base.OrderKeyMixin.order_key` 只读派生属性（键名统一为 ``*_key``）；
- 网关本地 ID 统一 snake_case：``orderid`` → ``order_id``；
- 活跃状态判断改为 :attr:`app.domain.enums.Status.is_active`，不再依赖模块级
  ``ACTIVE_STATUSES`` 集合；``OrderData.is_active()`` 保留原方法名，网关与后续服务可直接调用；
- ``__post_init__`` 不再做动态属性注入，字段全部由 dataclass 声明。

``OrderRequest`` / ``CancelRequest`` 是发给网关的**指令**，不携带 ``gateway_name``
（与原版一致）：网关在收单时确定来源，委托数据才记录网关名。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as Datetime

from app.domain.base import BaseData, InstrumentKeyMixin, OrderKeyMixin
from app.domain.enums import Direction, Exchange, Offset, OrderType, Status

__all__ = [
    "CancelRequest",
    "OrderData",
    "OrderRequest",
]


@dataclass
class OrderData(InstrumentKeyMixin, OrderKeyMixin, BaseData):
    """一笔委托的最新状态。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码
    :param exchange: 交易所
    :param order_id: 网关本地委托号
    :param type: 委托类型，默认限价
    :param direction: 买卖方向；网关回报补齐前可为空
    :param offset: 开平方向
    :param price: 委托价
    :param volume: 委托数量
    :param traded: 已成交数量
    :param status: 委托状态，默认提交中
    :param datetime: 委托时间；网关未提供时为空
    :param reference: 策略 / 前端自定义关联字段，原样透传
    """

    symbol: str
    exchange: Exchange
    order_id: str

    type: OrderType = OrderType.LIMIT
    direction: Direction | None = None
    offset: Offset = Offset.NONE
    price: float = 0
    volume: float = 0
    traded: float = 0
    status: Status = Status.SUBMITTING
    datetime: Datetime | None = None
    reference: str = ""

    def is_active(self) -> bool:
        """委托是否仍可能继续成交（提交中 / 未成交 / 部分成交）。"""
        return self.status.is_active

    def create_cancel_request(self) -> CancelRequest:
        """由委托生成撤单请求。

        与原版一致，撤单请求只包含网关本地委托号与合约；调用方（运行时 / 网关路由）
        通过 :attr:`order_key` 确定目标网关。
        """
        return CancelRequest(
            order_id=self.order_id,
            symbol=self.symbol,
            exchange=self.exchange,
        )


@dataclass
class OrderRequest(InstrumentKeyMixin):
    """发给网关的新建委托指令。

    :param direction: 买卖方向
    :param type: 委托类型
    :param volume: 委托数量
    :param price: 委托价；市价单可为 0
    :param offset: 开平方向
    :param reference: 自定义关联字段，会随委托数据回传
    """

    symbol: str
    exchange: Exchange
    direction: Direction
    type: OrderType
    volume: float
    price: float = 0
    offset: Offset = Offset.NONE
    reference: str = ""

    def create_order_data(self, order_id: str, gateway_name: str) -> OrderData:
        """由请求 + 网关分配的本地委托号构造委托数据。

        新委托的 ``traded=0``、``status=SUBMITTING``、``datetime=None`` 均取 ``OrderData``
        默认值，与原版一致；网关回报后再逐字段更新。
        """
        return OrderData(
            gateway_name=gateway_name,
            symbol=self.symbol,
            exchange=self.exchange,
            order_id=order_id,
            type=self.type,
            direction=self.direction,
            offset=self.offset,
            price=self.price,
            volume=self.volume,
            reference=self.reference,
        )


@dataclass
class CancelRequest(InstrumentKeyMixin):
    """发给网关的撤单指令。

    字段顺序与原版一致：``order_id`` → ``symbol`` → ``exchange``。
    """

    order_id: str
    symbol: str
    exchange: Exchange
