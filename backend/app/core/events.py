"""异步事件总线。

来源：vnpy 4.5.0 ``vnpy/event/engine.py`` 的线程版 ``EventEngine`` 与
``vnpy/trader/event.py`` 的事件主题常量（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- 不复制后台线程、阻塞队列与定时线程：发布与订阅都在事件循环内完成，
  :meth:`EventBus.publish` 内联分发，天然形成背压；
- 事件主题从字符串加法（``"eTick." + vt_symbol``）改为 :class:`EventTopic`：
  主题由「名称 + 可选范围」组成，订阅不带范围的主题即可收到该名称下所有事件；
- 单个订阅者抛错只记录日志，不影响同主题的其他订阅者，也不中断发布方；
- 定时事件由 ``asyncio.Task`` 周期发布，见 :meth:`EventBus.start_timer`；
- 本模块不提供线程安全：网关 SDK 的线程回调由适配层用
  ``loop.call_soon_threadsafe`` 投递回事件循环。

主题名称沿用 vnpy 的事件类型字符串（去掉尾部点号），带范围的主题字符串化为
``"eTick.rb2410.SHFE"``，与 vnpy 拼接 ``vt_symbol`` 的结果一致，便于适配层对照。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Event",
    "EventBus",
    "EventTopic",
    "HandlerType",
    "Topics",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EventTopic:
    """事件主题：稳定的名称 + 可选范围（如 ``instrument_key`` / ``order_key``）。

    ``scope`` 为空表示「该名称下所有事件」。订阅不带范围的主题可收到该名称下
    所有范围的事件；订阅带范围的主题只匹配同一范围，因此不需要通配符字符串。
    """

    name: str
    scope: str = ""

    def scoped(self, scope: str) -> EventTopic:
        """返回同一名称、指定范围的主题，例如 ``Topics.TICK.scoped("rb2410.SHFE")``。"""
        if not scope:
            raise ValueError("scope 不能为空")
        return EventTopic(self.name, scope)

    @property
    def unscoped(self) -> EventTopic:
        """返回同一名称、不带范围的主题（用于订阅全部同类事件）。"""
        return EventTopic(self.name)

    def __str__(self) -> str:
        """日志与适配层使用的字符串形式，例如 ``eTick.rb2410.SHFE``。"""
        return f"{self.name}.{self.scope}" if self.scope else self.name


@dataclass(frozen=True, slots=True)
class Event:
    """总线上的事件：主题 + 载荷。载荷类型由生产者与订阅者约定。"""

    topic: EventTopic
    data: Any = None


# 订阅者可以是同步函数（更新内存缓存）或协程函数（写库、推送 WebSocket）
HandlerType = Callable[[Event], Awaitable[None] | None]


class Topics:
    """内置事件主题。

    名称与 vnpy 的 ``EVENT_*`` 常量一一对应（去掉了原实现用于拼接的尾部点号）；
    需要按合约 / 委托过滤时用 ``Topics.TICK.scoped(instrument_key)``。
    """

    TIMER = EventTopic("eTimer")
    TICK = EventTopic("eTick")
    ORDER = EventTopic("eOrder")
    TRADE = EventTopic("eTrade")
    POSITION = EventTopic("ePosition")
    ACCOUNT = EventTopic("eAccount")
    QUOTE = EventTopic("eQuote")
    CONTRACT = EventTopic("eContract")
    LOG = EventTopic("eLog")


class EventBus:
    """asyncio 事件总线：按主题分发事件。

    - 订阅：:meth:`subscribe`；同一订阅者对同一主题只登记一次；
    - 全局订阅：:meth:`subscribe_all` 接收所有事件（WebSocket 广播、审计等场景）；
    - 发布：``await publish(topic, data)``，按注册顺序依次调用订阅者；
    - 定时器：:meth:`start_timer` / :meth:`stop_timer`，由应用生命周期管理。

    分发是内联的：慢订阅者会延迟发布方；需要并行处理的订阅者应自行
    ``asyncio.create_task``。订阅者异常会被记录，但不会中断其他订阅者。
    """

    def __init__(self) -> None:
        self._handlers: dict[EventTopic, list[HandlerType]] = {}
        self._all_handlers: list[HandlerType] = []
        self._timer_task: asyncio.Task[None] | None = None

    def subscribe(self, topic: EventTopic, handler: HandlerType) -> None:
        """订阅指定主题（不带范围的主题会收到该名称下所有范围的事件）。"""
        handlers = self._handlers.setdefault(topic, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, topic: EventTopic, handler: HandlerType) -> None:
        """取消订阅；未登记时静默返回，与原版 ``unregister`` 一致。"""
        handlers = self._handlers.get(topic)
        if not handlers:
            return
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(topic, None)

    def subscribe_all(self, handler: HandlerType) -> None:
        """订阅所有主题的事件（原版的 general handler）。"""
        if handler not in self._all_handlers:
            self._all_handlers.append(handler)

    def unsubscribe_all(self, handler: HandlerType) -> None:
        """取消全局订阅；未登记时静默返回。"""
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    async def publish(self, topic: EventTopic, data: Any = None) -> None:
        """发布事件并依次等待订阅者处理。

        订阅者抛出的异常被记录为 ERROR 日志后忽略，保证一个订阅者的故障
        不会影响其他订阅者；任务取消（``CancelledError``）不在此捕获。
        """
        event = Event(topic, data)
        handlers: list[HandlerType] = list(self._handlers.get(topic, ()))
        if topic.scope:
            # 订阅「eTick」可收到「eTick.<instrument_key>」的事件
            handlers.extend(self._handlers.get(topic.unscoped, ()))
        handlers.extend(self._all_handlers)

        for handler in handlers:
            await self._dispatch(handler, event)

    async def _dispatch(self, handler: HandlerType, event: Event) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - 订阅者异常必须隔离，不能让总线中断
            logger.exception(
                "event handler failed: topic=%s handler=%r",
                event.topic,
                handler,
            )

    def start_timer(self, interval: float = 1.0) -> None:
        """启动周期定时事件（主题 :attr:`Topics.TIMER`，载荷为空）。

        :param interval: 间隔秒数，必须为正数
        :raises ValueError: 间隔不是正数
        :raises RuntimeError: 定时器已在运行
        """
        if interval <= 0:
            raise ValueError("定时器间隔必须为正数")
        if self._timer_task is not None and not self._timer_task.done():
            raise RuntimeError("定时器已在运行")
        self._timer_task = asyncio.create_task(
            self._run_timer(interval),
            name="event-bus-timer",
        )

    async def stop_timer(self) -> None:
        """停止定时事件；未启动时静默返回，可重复调用。"""
        task = self._timer_task
        if task is None:
            return
        self._timer_task = None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run_timer(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.publish(Topics.TIMER)
