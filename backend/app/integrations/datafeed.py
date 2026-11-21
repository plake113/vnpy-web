"""异步数据源端口：历史 K 线 / Tick 的只读查询。

来源：vnpy 4.5.0 ``vnpy/trader/datafeed.py`` 的 ``BaseDatafeed``
（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- **去掉全局单例与动态 import**：原版 ``get_datafeed()`` 读全局 ``SETTINGS``、
  按 ``f"vnpy_{name}"`` 调 ``import_module`` 并缓存到模块级 ``datafeed``；
  这里只定义端口，实例由组合根创建并注册，运行时不再按字符串加载模块；
- **回调式输出 → 异常 + 标准 logging**：原版 ``init(output=print)``、查询失败时
  ``print`` 一条中文提示并返回空列表；这里失败抛异常、查无数据返回空列表，
  用户可见文案由 API 层决定；
- **同步 → 异步**：查询是 ``async`` 方法，一次返回一个批次；阻塞式 SDK 由适配器
  放进线程池（``asyncio.to_thread``），不阻塞事件循环；
- **只管历史查询**：实时行情走 :class:`app.integrations.gateway.Gateway` 的订阅 +
  批量 :class:`app.integrations.gateway.EventSink` 回调，不在本端口重复暴露。

实现约定：

- ``init`` 负责登录 / 校验凭证 / 建立会话，失败抛异常；``close`` 释放资源且可重复调用；
  无状态（纯 HTTP 查询）的数据源可以不覆盖这两个方法；
- ``query_bar_history`` 必须有实现，``query_tick_history`` 默认表示不支持；
- 返回值是**批次**（当前用 ``list``）。tick 体量大时的流式 / 列式传输按
  行情数据平面的分阶段计划演进，届时再修改端口签名。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.market import BarData, HistoryRequest, TickData

__all__ = ["DataFeed"]


class DataFeed(ABC):
    """历史行情只读端口。

    子类通过 :attr:`datafeed_name` 声明名字（仅用于注册、日志与错误信息；
    不参与复合键，因此没有网关名那样的点号限制）。
    """

    #: 数据源名，例如 ``"RQB"``；由组合根用于注册与日志，不进入业务键。
    datafeed_name: str = ""

    async def init(self) -> None:
        """建立数据源会话（登录 / 校验凭证 / 打开连接）。

        默认不做任何事，供无状态实现直接复用；失败时抛异常，由 runtime 决定
        是否降级或禁用历史查询。
        """
        return None

    async def close(self) -> None:
        """释放会话；默认不做任何事，应可重复调用。"""
        return None

    @abstractmethod
    async def query_bar_history(self, request: HistoryRequest) -> list[BarData]:
        """查询历史 K 线，返回一个批次。

        - 查无数据返回空列表，不返回 ``None``；
        - 查询失败抛异常，由 service / API 转换成用户可见错误；
        - ``request.interval`` 为空时由实现决定默认周期，或直接拒绝。
        """

    async def query_tick_history(self, request: HistoryRequest) -> list[TickData]:
        """查询历史 Tick，返回一个批次；默认表示该数据源只提供 K 线。

        :raises NotImplementedError: 数据源未实现 Tick 历史
        """
        name = self.datafeed_name or type(self).__name__
        raise NotImplementedError(f"数据源 {name} 不支持 Tick 历史查询")
