"""报价领域对象：双边报价数据与新建报价请求。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``QuoteData``、``QuoteRequest``
（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` / ``vt_quoteid`` 改为 :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key`
  与 :attr:`QuoteData.quote_key` 只读派生属性（键名统一为 ``*_key``）；
- 网关本地 ID 改名：``quoteid`` → ``quote_id``；
- 活跃状态复用 :attr:`app.domain.enums.Status.is_active`，不再依赖模块级 ``ACTIVE_STATUSES``；
- 字段名、默认值与构造顺序不变，成交量保持 ``int``（与原版一致，报价数量是整数手）。

报价（quote）是期权做市 / RFQ 场景的双边报价单，与委托（order）是两条独立链路：
撤报价沿用 :class:`~app.domain.orders.CancelRequest`，把 ``quote_id`` 填进 ``order_id``
字段（与原版一致），由网关适配层区分。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as Datetime

from app.domain.base import BaseData, InstrumentKeyMixin
from app.domain.enums import Exchange, Offset, Status
from app.domain.orders import CancelRequest
from app.domain.symbols import build_gateway_key

__all__ = [
    "QuoteData",
    "QuoteRequest",
]


@dataclass
class QuoteData(InstrumentKeyMixin, BaseData):
    """一笔双边报价的最新状态。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码
    :param exchange: 交易所
    :param quote_id: 网关本地报价号
    :param bid_price: 买价
    :param bid_volume: 买量（整数手）
    :param ask_price: 卖价
    :param ask_volume: 卖量（整数手）
    :param bid_offset: 买方向开平
    :param ask_offset: 卖方向开平
    :param status: 报价状态，默认提交中
    :param datetime: 报价时间；网关未提供时为空
    :param reference: 策略 / 前端自定义关联字段，原样透传
    """

    symbol: str
    exchange: Exchange
    quote_id: str

    bid_price: float = 0.0
    bid_volume: int = 0
    ask_price: float = 0.0
    ask_volume: int = 0
    bid_offset: Offset = Offset.NONE
    ask_offset: Offset = Offset.NONE
    status: Status = Status.SUBMITTING
    datetime: Datetime | None = None
    reference: str = ""

    @property
    def quote_key(self) -> str:
        """跨网关唯一的报价键，例如 ``CTP.Q001``（原 ``vt_quoteid``）。"""
        return build_gateway_key(self.gateway_name, self.quote_id)

    def is_active(self) -> bool:
        """报价是否仍活跃（提交中 / 未成交 / 部分成交）。"""
        return self.status.is_active

    def create_cancel_request(self) -> CancelRequest:
        """由报价生成撤单请求，``quote_id`` 作为网关本地单号填入。"""
        return CancelRequest(
            order_id=self.quote_id,
            symbol=self.symbol,
            exchange=self.exchange,
        )


@dataclass
class QuoteRequest(InstrumentKeyMixin):
    """发给网关的新建双边报价指令。

    :param bid_price: 买价
    :param bid_volume: 买量（整数手）
    :param ask_price: 卖价
    :param ask_volume: 卖量（整数手）
    :param bid_offset: 买方向开平
    :param ask_offset: 卖方向开平
    :param reference: 自定义关联字段，会随报价数据回传
    """

    symbol: str
    exchange: Exchange
    bid_price: float
    bid_volume: int
    ask_price: float
    ask_volume: int
    bid_offset: Offset = Offset.NONE
    ask_offset: Offset = Offset.NONE
    reference: str = ""

    def create_quote_data(self, quote_id: str, gateway_name: str) -> QuoteData:
        """由请求 + 网关分配的本地报价号构造报价数据。

        新报价的 ``status=SUBMITTING``、``datetime=None`` 取 ``QuoteData`` 默认值，
        与原版一致；网关回报后再逐字段更新。
        """
        return QuoteData(
            gateway_name=gateway_name,
            symbol=self.symbol,
            exchange=self.exchange,
            quote_id=quote_id,
            bid_price=self.bid_price,
            bid_volume=self.bid_volume,
            ask_price=self.ask_price,
            ask_volume=self.ask_volume,
            bid_offset=self.bid_offset,
            ask_offset=self.ask_offset,
            reference=self.reference,
        )
