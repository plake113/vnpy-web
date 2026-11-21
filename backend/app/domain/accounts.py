"""账户领域对象。

来源：vnpy 4.5.0 ``vnpy/trader/object.py`` 中的 ``AccountData``
（MIT License，© Xiaoyou Chen）。

与原实现的差异：

- ``vt_accountid`` 改为 :attr:`AccountData.account_key` 只读派生属性
  （键名统一为 ``*_key``），网关本地 ID 统一 snake_case（``account_id``）；
- ``available``（原在 ``__post_init__`` 里算一次并存成属性）改为**只读派生属性**：
  余额或冻结变化后自动重新计算，不会出现 ``balance`` 已更新而 ``available`` 是旧值的情况；
- 字段名、默认值不变。

账户没有 ``symbol`` / ``exchange``，因此不继承 ``InstrumentKeyMixin``；它只用
``gateway_name + account_id`` 定位，对应 ``account_key``。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.base import BaseData
from app.domain.symbols import build_gateway_key

__all__ = ["AccountData"]


@dataclass
class AccountData(BaseData):
    """交易账户的资金与冻结信息。

    :param gateway_name: 数据来源网关
    :param account_id: 网关本地资金账号
    :param balance: 账户总权益 / 余额
    :param frozen: 冻结金额（挂单、保证金占用）
    """

    account_id: str

    balance: float = 0
    frozen: float = 0

    @property
    def account_key(self) -> str:
        """跨网关唯一的账户键，例如 ``CTP.12345678``（原 ``vt_accountid``）。"""
        return build_gateway_key(self.gateway_name, self.account_id)

    @property
    def available(self) -> float:
        """可用资金 = ``balance - frozen``；冻结超过余额时为负值，不截断。"""
        return self.balance - self.frozen
