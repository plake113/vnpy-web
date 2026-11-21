"""持仓领域对象。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``PositionData``
（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` / ``vt_positionid`` 改为 :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key`
  与 :attr:`PositionData.position_key` 只读派生属性（键名统一为 ``*_key``）；
- ``position_key`` 的方向段使用新枚举代码 ``LONG`` / ``SHORT``，而 vnpy 使用
  ``Direction.value`` 的中文「多 / 空」；网关适配层负责把旧持仓键映射为新格式；
- 字段名、默认值与构造顺序不变：``direction`` 是必填字段，其余数值字段默认 0。

持仓是**按方向跟踪**的：同一合约的多头与空头是两条记录
（``rb2410.SHFE.LONG`` / ``rb2410.SHFE.SHORT``）；净持仓网关由适配层折算后同样以
多空方向上报，因此不需要单独的净仓结构。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.base import BaseData, InstrumentKeyMixin
from app.domain.enums import Direction, Exchange
from app.domain.symbols import build_position_key

__all__ = ["PositionData"]


@dataclass
class PositionData(InstrumentKeyMixin, BaseData):
    """单方向持仓。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码
    :param exchange: 交易所
    :param direction: 持仓方向（多 / 空）
    :param volume: 持仓总量
    :param frozen: 冻结数量（挂单占用）
    :param price: 持仓均价
    :param pnl: 持仓盈亏（网关口径，未实现盈亏）
    :param yd_volume: 昨仓数量，供 SHFE / INE 平今平昨换算使用
    """

    symbol: str
    exchange: Exchange
    direction: Direction

    volume: float = 0
    frozen: float = 0
    price: float = 0
    pnl: float = 0
    yd_volume: float = 0

    @property
    def position_key(self) -> str:
        """跨网关 + 合约 + 方向的持仓键，例如 ``CTP.rb2410.SHFE.LONG``（原 ``vt_positionid``）。"""
        return build_position_key(self.gateway_name, self.instrument_key, self.direction)
