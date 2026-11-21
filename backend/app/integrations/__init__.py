"""外部系统适配层（integrations）：端口 + 适配器。

单元 7 先落两个端口：

- :class:`~app.integrations.gateway.Gateway`：交易网关异步端口，数据经窄接口
  :class:`~app.integrations.gateway.EventSink` 交给上层；
- :class:`~app.integrations.datafeed.DataFeed`：历史行情只读查询端口。

具体适配器（券商 / 交易所 / 行情源）后续放在 ``gateways/``、``datafeeds/`` 子包；
它们只依赖本层端口与 ``domain``，由组合根（单元 11 的 ``TradingRuntime``）创建并注册，
不使用全局单例，也不按字符串动态 import。
"""

from app.integrations.datafeed import DataFeed
from app.integrations.gateway import EventSink, Gateway, SettingValue

__all__ = [
    "DataFeed",
    "EventSink",
    "Gateway",
    "SettingValue",
]
