"""ORM 模型包。

新增模型时：

1. 继承 :class:`app.models.base.Base`（通常同时混入 ``TimestampMixin``）；
2. 在 ``app/models/__init__.py`` 中导入，确保注册进 ``Base.metadata``；
3. 使用 ``alembic revision --autogenerate -m "..."`` 生成迁移。
"""

from __future__ import annotations

from app.models.base import Base, TimestampMixin
from app.models.item import Item
from app.models.market_data import BarRecord, TickRecord
from app.models.trading import (
    AccountRecord,
    ContractRecord,
    OrderRecord,
    PositionRecord,
    QuoteRecord,
    TradeRecord,
)

__all__ = [
    "AccountRecord",
    "BarRecord",
    "Base",
    "ContractRecord",
    "Item",
    "OrderRecord",
    "PositionRecord",
    "QuoteRecord",
    "TickRecord",
    "TimestampMixin",
    "TradeRecord",
]
