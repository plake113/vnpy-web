"""数据访问层（CRUD）。

CRUD 层只负责数据库读写，不包含业务规则、不提交事务；
事务边界统一放在 service 层。
"""

from __future__ import annotations

from app.crud.base import CRUDBase
from app.crud.item import CRUDItem, item_crud
from app.crud.market_data import (
    BarOverview,
    TickOverview,
    count_bars,
    delete_bars,
    delete_ticks,
    get_bar_overview,
    get_tick_overview,
    load_bars,
    load_ticks,
    save_bars,
    save_ticks,
)
from app.crud.trading import (
    get_account,
    get_contract,
    get_order,
    get_position,
    get_quote,
    get_trade,
    load_accounts,
    load_contracts,
    load_orders,
    load_positions,
    load_quotes,
    load_trades,
    save_accounts,
    save_contracts,
    save_orders,
    save_positions,
    save_quotes,
    save_trades,
)

__all__ = [
    "BarOverview",
    "CRUDBase",
    "CRUDItem",
    "TickOverview",
    "count_bars",
    "delete_bars",
    "delete_ticks",
    "get_account",
    "get_bar_overview",
    "get_contract",
    "get_order",
    "get_position",
    "get_quote",
    "get_tick_overview",
    "get_trade",
    "item_crud",
    "load_accounts",
    "load_bars",
    "load_contracts",
    "load_orders",
    "load_positions",
    "load_quotes",
    "load_ticks",
    "load_trades",
    "save_accounts",
    "save_bars",
    "save_contracts",
    "save_orders",
    "save_positions",
    "save_quotes",
    "save_ticks",
    "save_trades",
]
