"""领域对象基类与跨网关复合键派生。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``BaseData``（MIT License，© Xiaoyou Chen）。

迁移取舍：

- ``BaseData`` 只保留 ``gateway_name``（数据来源网关）与 ``extra``（网关自定义载荷），
  保持纯 dataclass，不引入 Pydantic / SQLAlchemy；
- 原实现把 ``vt_symbol``、``vt_orderid``、``vt_tradeid`` 写在 ``__post_init__`` 里作为可变属性；
  这里改为 :attr:`InstrumentKeyMixin.instrument_key` / :attr:`OrderKeyMixin.order_key` /
  :attr:`TradeKeyMixin.trade_key` **只读派生属性**，键名统一为 ``*_key``
  （不再使用 vnpy 的 ``vt_`` 前缀）。派生值不会因为赋值而与来源字段失去同步，
  也避免 dataclass 字段在 ``__init__`` 之外被注入；
- 键的字符串格式沿用 vnpy：``"{symbol}.{exchange.value}"`` 与 ``"{gateway_name}.{local_id}"``；
  生成与解析统一放在 :mod:`app.domain.symbols`，本模块只引用生成函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Exchange
from app.domain.symbols import build_gateway_key, build_instrument_key

__all__ = [
    "BaseData",
    "InstrumentKeyMixin",
    "OrderKeyMixin",
    "TradeKeyMixin",
]


@dataclass
class BaseData:
    """所有网关推送数据的公共基类。

    :param gateway_name: 数据来源网关名，用于区分同一合约在不同网关下的数据；
        约定不含点号，否则复合键解析会产生歧义。
    """

    gateway_name: str

    #: 网关私有的附加载荷（如柜台原始字段）。不参与构造，避免污染领域契约。
    extra: dict[str, Any] | None = field(default=None, init=False)


class InstrumentKeyMixin:
    """为“带合约”的领域对象提供 :attr:`instrument_key` 派生属性。

    子类需要把 ``symbol`` / ``exchange`` 声明为 dataclass 字段；本类不含字段，
    因此不会改变子类的构造参数顺序。

    ``instrument_key`` 由 ``symbol`` 与 ``exchange`` 实时拼出：两者被修改后键随之变化，
    不需要手工刷新。
    """

    symbol: str
    exchange: Exchange

    @property
    def instrument_key(self) -> str:
        """跨交易所唯一的合约键，例如 ``rb2410.SHFE``（原 ``vt_symbol``）。"""
        return build_instrument_key(self.symbol, self.exchange)


class OrderKeyMixin:
    """为委托 / 成交提供 :attr:`order_key` 派生属性。

    委托对象与成交对象都携带 ``gateway_name``（来自 :class:`BaseData`）与网关本地
    ``order_id``，因此都具备跨网关唯一的委托键（原 ``vt_orderid``）。
    """

    gateway_name: str
    order_id: str

    @property
    def order_key(self) -> str:
        """跨网关唯一的委托键，例如 ``CTP.12345``（原 ``vt_orderid``）。"""
        return build_gateway_key(self.gateway_name, self.order_id)


class TradeKeyMixin(OrderKeyMixin):
    """为成交提供 :attr:`trade_key` 派生属性，并沿用 :attr:`order_key`。

    成交记录同时属于一笔委托和一个网关本地成交号（原 ``vt_tradeid``）。
    """

    trade_id: str

    @property
    def trade_key(self) -> str:
        """跨网关唯一的成交键，例如 ``CTP.98765``（原 ``vt_tradeid``）。"""
        return build_gateway_key(self.gateway_name, self.trade_id)
