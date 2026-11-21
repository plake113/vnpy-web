"""交易 HTTP 契约：委托、成交、持仓、账户、合约、报价。

响应由领域对象转换（``from_attributes``）；业务键（``order_key`` 等）与派生字段
（``available``）直接读领域对象的只读属性。枚举以稳定机器码序列化，时间输出 UTC ISO。
"""

from __future__ import annotations

from datetime import datetime as Datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    Direction,
    Exchange,
    Offset,
    OptionType,
    OrderType,
    Product,
    Status,
)

__all__ = [
    "AccountRead",
    "ContractRead",
    "OrderRead",
    "PositionRead",
    "QuoteRead",
    "TradeRead",
]


class OrderRead(BaseModel):
    """一笔委托的最新状态。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    instrument_key: str
    symbol: str
    exchange: Exchange
    order_key: str = Field(description="跨网关委托键，例如 CTP.12345")
    order_id: str
    type: OrderType
    direction: Direction | None
    offset: Offset
    price: float
    volume: float
    traded: float
    status: Status
    datetime: Datetime | None = Field(default=None, description="委托时间（UTC）")
    reference: str


class TradeRead(BaseModel):
    """一笔成交。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    instrument_key: str
    symbol: str
    exchange: Exchange
    order_key: str
    trade_key: str
    order_id: str
    trade_id: str
    direction: Direction | None
    offset: Offset
    price: float
    volume: float
    datetime: Datetime | None = Field(default=None, description="成交时间（UTC）")


class PositionRead(BaseModel):
    """单方向持仓快照。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    instrument_key: str
    position_key: str
    symbol: str
    exchange: Exchange
    direction: Direction
    volume: float
    frozen: float
    price: float
    pnl: float
    yd_volume: float


class AccountRead(BaseModel):
    """资金账户快照。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    account_key: str
    account_id: str
    balance: float
    frozen: float
    available: float = Field(description="可用资金 = balance - frozen")


class ContractRead(BaseModel):
    """合约静态信息。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    instrument_key: str
    symbol: str
    exchange: Exchange
    name: str
    product: Product
    size: float
    pricetick: float
    min_volume: float
    max_volume: float | None
    stop_supported: bool
    net_position: bool
    history_data: bool
    option_strike: float | None
    option_underlying_key: str | None
    option_type: OptionType | None
    option_listed: Datetime | None
    option_expiry: Datetime | None
    option_portfolio: str | None
    option_index: str | None


class QuoteRead(BaseModel):
    """双边报价的最新状态。"""

    model_config = ConfigDict(from_attributes=True)

    gateway_name: str
    instrument_key: str
    quote_key: str
    symbol: str
    exchange: Exchange
    quote_id: str
    bid_price: float
    bid_volume: int
    ask_price: float
    ask_volume: int
    bid_offset: Offset
    ask_offset: Offset
    status: Status
    datetime: Datetime | None = Field(default=None, description="报价时间（UTC）")
    reference: str
