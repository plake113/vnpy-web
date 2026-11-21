"""合约领域对象：合约静态信息与期权属性。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``ContractData``
（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_symbol`` 改为 :attr:`~app.domain.base.InstrumentKeyMixin.instrument_key`
  只读派生属性（键名统一为 ``*_key``）；
- ``option_underlying`` 改名为 ``option_underlying_key``：原字段保存的是标的合约的
  ``vt_symbol``，这里显式表达为 ``*_key``（跨网关复合键命名）；
  网关适配层负责 ``vt_symbol`` → ``instrument_key`` 映射；
- 字段名、默认值不变：``min_volume=1``、其余可选字段为 ``None`` / ``False``，
  与原版保持一致，避免网关适配时漏字段。

合约是**静态参考数据**：价格精度（``pricetick``）、合约乘数（``size``）、最小 / 最大下单量
与期权属性都供后续价格取整、开平转换与风控校验使用，因此单独成模块而不是塞进行情对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as Datetime

from app.domain.base import BaseData, InstrumentKeyMixin
from app.domain.enums import Exchange, OptionType, Product

__all__ = ["ContractData"]


@dataclass
class ContractData(InstrumentKeyMixin, BaseData):
    """单个可交易合约的基础信息。

    :param gateway_name: 数据来源网关
    :param symbol: 合约代码（交易所本地格式）
    :param exchange: 交易所
    :param name: 合约中文名，例如「螺纹钢2410」
    :param product: 品种
    :param size: 合约乘数（每手对应的标的数量）
    :param pricetick: 最小变动价位，供价格取整使用
    :param min_volume: 最小下单量，默认 1
    :param max_volume: 最大下单量；``None`` 表示网关不限制
    :param stop_supported: 网关是否支持本地停止单
    :param net_position: 网关是否使用净持仓（而非多空双向持仓）
    :param history_data: 网关是否提供历史 K 线查询
    :param option_strike: 期权行权价
    :param option_underlying_key: 标的合约的 ``instrument_key``
    :param option_type: 看涨 / 看跌
    :param option_listed: 期权上市日
    :param option_expiry: 期权到期日
    :param option_portfolio: 期权组合标识
    :param option_index: 同一行权价下区分不同期权的索引
    """

    symbol: str
    exchange: Exchange
    name: str
    product: Product
    size: float
    pricetick: float

    min_volume: float = 1
    max_volume: float | None = None
    stop_supported: bool = False
    net_position: bool = False
    history_data: bool = False

    option_strike: float | None = None
    option_underlying_key: str | None = None
    option_type: OptionType | None = None
    option_listed: Datetime | None = None
    option_expiry: Datetime | None = None
    option_portfolio: str | None = None
    option_index: str | None = None
