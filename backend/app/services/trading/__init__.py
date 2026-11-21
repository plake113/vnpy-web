"""交易服务（trading services）。

单元 10 起把 vnpy ``MainEngine`` 里的内置引擎逐个拆成独立服务：

- :class:`~app.services.trading.oms.OmsService`：事件驱动的实时缓存与查询；
- 后续：下单 / 撤单用例、行情订阅、交易运行时（组合根）。
"""
