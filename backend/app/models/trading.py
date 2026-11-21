"""交易数据 ORM 模型：合约、委托、成交、持仓、账户、报价。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 的对应数据类与 ``vnpy/trader/database.py``
的持久化方向（MIT License，© Xiaoyou Chen）。

设计约定：

- **键**：自增主键 + 业务唯一键（``instrument_key`` / ``order_key`` / ``trade_key`` /
  ``position_key`` / ``account_key`` / ``quote_key``，统一 ``*_key``）；
- **枚举存机器码**：状态、方向、开平、品种、委托类型、期权类型都存 ``value``，
  不存中文 label；
- **时间存 UTC**：可选时间列（委托 / 成交 / 报价 / 期权日期）允许为空；非空时由仓储统一
  转 UTC，读取补回 UTC（时间统一 UTC）；
- **写入语义**：合约、委托、持仓、账户、报价是最新状态快照，按业务键 upsert 覆盖；
  成交是不可变事实，按 ``trade_key`` 插入忽略。

表与领域对象一一对应，仓储层负责显式转换（``crud/trading.py``）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

__all__ = [
    "AccountRecord",
    "ContractRecord",
    "OrderRecord",
    "PositionRecord",
    "QuoteRecord",
    "TradeRecord",
]


class ContractRecord(Base, TimestampMixin):
    """合约静态信息（可被新版本覆盖）。"""

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("instrument_key", name="uq_contracts_instrument_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据来源网关")
    instrument_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="合约键，例如 rb2410.SHFE",
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, comment="交易所代码")

    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="合约中文名")
    product: Mapped[str] = mapped_column(String(16), nullable=False, comment="品种机器码")
    size: Mapped[float] = mapped_column(Float, nullable=False, comment="合约乘数")
    pricetick: Mapped[float] = mapped_column(Float, nullable=False, comment="最小变动价位")
    min_volume: Mapped[float] = mapped_column(Float, nullable=False, comment="最小下单量")
    max_volume: Mapped[float | None] = mapped_column(Float, nullable=True, comment="最大下单量")
    stop_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    net_position: Mapped[bool] = mapped_column(Boolean, nullable=False)
    history_data: Mapped[bool] = mapped_column(Boolean, nullable=False)

    option_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    option_underlying_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    option_type: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="看涨 / 看跌",
    )
    option_listed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    option_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    option_portfolio: Mapped[str | None] = mapped_column(String(64), nullable=True)
    option_index: Mapped[str | None] = mapped_column(String(16), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<ContractRecord {self.instrument_key}>"


class OrderRecord(Base, TimestampMixin):
    """委托的最新全量状态。"""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_key", name="uq_orders_order_key"),
        Index("ix_orders_instrument_key", "instrument_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="网关本地委托号")
    order_key: Mapped[str] = mapped_column(String(160), nullable=False, comment="跨网关委托键")

    type: Mapped[str] = mapped_column(String(16), nullable=False, comment="委托类型机器码")
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    offset: Mapped[str] = mapped_column(String(16), nullable=False, comment="开平机器码")
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    traded: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="委托状态机器码")
    datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<OrderRecord {self.order_key} {self.status}>"


class TradeRecord(Base, TimestampMixin):
    """一笔成交（不可变事实）。"""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("trade_key", name="uq_trades_trade_key"),
        Index("ix_trades_instrument_key", "instrument_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_key: Mapped[str] = mapped_column(String(160), nullable=False, comment="跨网关成交键")

    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    offset: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<TradeRecord {self.trade_key}>"


class PositionRecord(Base, TimestampMixin):
    """某个合约 + 方向的最新持仓快照。"""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("position_key", name="uq_positions_position_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    position_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="绑定网关 + 合约 + 方向",
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)

    volume: Mapped[float] = mapped_column(Float, nullable=False)
    frozen: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False)
    yd_volume: Mapped[float] = mapped_column(Float, nullable=False, comment="昨仓")

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<PositionRecord {self.position_key}>"


class AccountRecord(Base, TimestampMixin):
    """资金账户的最新快照。"""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("account_key", name="uq_accounts_account_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False)
    account_key: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="网关本地资金账号")
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    frozen: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<AccountRecord {self.account_key}>"


class QuoteRecord(Base, TimestampMixin):
    """双边报价的最新状态。"""

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("quote_key", name="uq_quotes_quote_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_key: Mapped[str] = mapped_column(String(160), nullable=False)

    bid_price: Mapped[float] = mapped_column(Float, nullable=False)
    bid_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    ask_price: Mapped[float] = mapped_column(Float, nullable=False)
    ask_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    bid_offset: Mapped[str] = mapped_column(String(16), nullable=False)
    ask_offset: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<QuoteRecord {self.quote_key} {self.status}>"
