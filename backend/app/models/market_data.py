"""历史行情 ORM 模型：K 线（bars）与 Tick（ticks）。

来源：vnpy 4.5.0 ``vnpy/trader/database.py`` 的 ``BarOverview`` / ``TickOverview`` 与
``vnpy_sqlite`` 的表结构（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- 不再由数据库驱动动态建表；这里声明 SQLAlchemy 2.0 模型，表结构由 Alembic 迁移管理；
- 业务键使用 ``instrument_key``（跨网关复合键统一 ``*_key``），
  ``symbol`` / ``exchange`` 保留为冗余列，便于直接阅读与后续按交易所查询；
- 时间列统一存 **UTC**（时间基准统一）：写入时由仓储把
  aware ``datetime`` 转成 UTC 存储，读取时补回 UTC 时区；naive 时间在仓储边界直接拒绝；
- 枚举（``interval`` / ``exchange``）存稳定的 ``value`` 机器码，不存中文 label；
- 唯一键保证幂等写入：``bars`` 为 ``(instrument_key, interval, datetime)``，
  ``ticks`` 为 ``(instrument_key, datetime)``。

``created_at`` / ``updated_at`` 来自 :class:`~app.models.base.TimestampMixin`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

__all__ = ["BarRecord", "TickRecord"]


class BarRecord(Base, TimestampMixin):
    """一根历史 K 线。"""

    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_key",
            "interval",
            "datetime",
            name="uq_bars_instrument_interval_datetime",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据来源网关")
    instrument_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="合约键，例如 rb2410.SHFE",
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, comment="合约代码（冗余列）")
    exchange: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="交易所代码（冗余列）",
    )
    interval: Mapped[str] = mapped_column(String(16), nullable=False, comment="K 线周期机器码")
    datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="K 线时间（UTC）",
    )

    volume: Mapped[float] = mapped_column(Float, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=False)
    open_interest: Mapped[float] = mapped_column(Float, nullable=False)

    open_price: Mapped[float] = mapped_column(Float, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, nullable=False)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return (
            f"<BarRecord {self.instrument_key} {self.interval} {self.datetime.isoformat()}>"
        )


class TickRecord(Base, TimestampMixin):
    """一条历史 Tick 快照。

    盘口 5 档用平铺列存储（与 ``TickData`` 一致）；``name`` / ``localtime`` 不落库：
    前者是合约静态信息（``contracts`` 表负责），后者是网关本地时间、不参与业务。
    """

    __tablename__ = "ticks"
    __table_args__ = (
        UniqueConstraint(
            "instrument_key",
            "datetime",
            name="uq_ticks_instrument_datetime",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据来源网关")
    instrument_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="合约键，例如 rb2410.SHFE",
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, comment="合约代码（冗余列）")
    exchange: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="交易所代码（冗余列）",
    )
    datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Tick 时间（UTC）",
    )

    last_price: Mapped[float] = mapped_column(Float, nullable=False)
    last_volume: Mapped[float] = mapped_column(Float, nullable=False)
    limit_up: Mapped[float] = mapped_column(Float, nullable=False)
    limit_down: Mapped[float] = mapped_column(Float, nullable=False)

    open_price: Mapped[float] = mapped_column(Float, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, nullable=False)
    pre_close: Mapped[float] = mapped_column(Float, nullable=False)

    volume: Mapped[float] = mapped_column(Float, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=False)
    open_interest: Mapped[float] = mapped_column(Float, nullable=False)

    bid_price_1: Mapped[float] = mapped_column(Float, nullable=False)
    bid_price_2: Mapped[float] = mapped_column(Float, nullable=False)
    bid_price_3: Mapped[float] = mapped_column(Float, nullable=False)
    bid_price_4: Mapped[float] = mapped_column(Float, nullable=False)
    bid_price_5: Mapped[float] = mapped_column(Float, nullable=False)

    ask_price_1: Mapped[float] = mapped_column(Float, nullable=False)
    ask_price_2: Mapped[float] = mapped_column(Float, nullable=False)
    ask_price_3: Mapped[float] = mapped_column(Float, nullable=False)
    ask_price_4: Mapped[float] = mapped_column(Float, nullable=False)
    ask_price_5: Mapped[float] = mapped_column(Float, nullable=False)

    bid_volume_1: Mapped[float] = mapped_column(Float, nullable=False)
    bid_volume_2: Mapped[float] = mapped_column(Float, nullable=False)
    bid_volume_3: Mapped[float] = mapped_column(Float, nullable=False)
    bid_volume_4: Mapped[float] = mapped_column(Float, nullable=False)
    bid_volume_5: Mapped[float] = mapped_column(Float, nullable=False)

    ask_volume_1: Mapped[float] = mapped_column(Float, nullable=False)
    ask_volume_2: Mapped[float] = mapped_column(Float, nullable=False)
    ask_volume_3: Mapped[float] = mapped_column(Float, nullable=False)
    ask_volume_4: Mapped[float] = mapped_column(Float, nullable=False)
    ask_volume_5: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<TickRecord {self.instrument_key} {self.datetime.isoformat()}>"
