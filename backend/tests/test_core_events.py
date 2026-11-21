"""``event/engine.py`` 线程版 ``EventEngine`` → ``app/core/events.py`` 的迁移测试。

重点验证：

- 发布 / 订阅 / 退订语义与原版一致（重复注册只调一次、退订未注册项静默返回）；
- 主题模型：不带范围的订阅收到同名称的所有范围事件，带范围只匹配同一范围；
- 同步与协程订阅者都受支持，按注册顺序依次处理；
- 单个订阅者抛错被隔离并记录日志，不影响其他订阅者与发布方；
- 定时器由 asyncio.Task 驱动，可启动 / 停止，停止后不再产生事件。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging

import pytest

from app.core.events import Event, EventBus, EventTopic, Topics


async def test_publish_delivers_event_to_subscriber() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(Topics.TICK, received.append)

    await bus.publish(Topics.TICK, {"last_price": 3500})

    assert len(received) == 1
    assert received[0].topic == Topics.TICK
    assert received[0].data == {"last_price": 3500}


async def test_publish_without_subscribers_is_noop() -> None:
    bus = EventBus()
    await bus.publish(Topics.TIMER)
    await bus.publish(Topics.TICK.scoped("rb2410.SHFE"), 1)


async def test_unscoped_subscription_receives_all_scopes() -> None:
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(Topics.TICK, lambda event: received.append(event.data))

    await bus.publish(Topics.TICK.scoped("rb2410.SHFE"), 1)
    await bus.publish(Topics.TICK.scoped("IF2412.CFFEX"), 2)
    await bus.publish(Topics.TICK, 3)

    assert received == [1, 2, 3]


async def test_scoped_subscription_only_receives_same_scope() -> None:
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(Topics.TICK.scoped("rb2410.SHFE"), lambda event: received.append(event.data))

    await bus.publish(Topics.TICK.scoped("rb2410.SHFE"), 1)
    await bus.publish(Topics.TICK.scoped("IF2412.CFFEX"), 2)
    await bus.publish(Topics.TICK, 3)

    assert received == [1]


async def test_subscribe_all_receives_every_event() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)

    await bus.publish(Topics.TICK.scoped("rb2410.SHFE"), 1)
    await bus.publish(Topics.ORDER, 2)

    assert [str(event.topic) for event in received] == ["eTick.rb2410.SHFE", "eOrder"]
    # 每类事件只投递一次
    assert len(received) == 2


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(Topics.TICK, handler)
    await bus.publish(Topics.TICK)
    bus.unsubscribe(Topics.TICK, handler)
    await bus.publish(Topics.TICK)

    assert len(received) == 1

    # 未注册 / 已清理的主题再退订不报错
    bus.unsubscribe(Topics.TICK, handler)
    bus.unsubscribe(Topics.TRADE, handler)


async def test_unsubscribe_bound_method() -> None:
    bus = EventBus()

    class Recorder:
        def __init__(self) -> None:
            self.events: list[Event] = []

        def handle(self, event: Event) -> None:
            self.events.append(event)

    recorder = Recorder()
    bus.subscribe(Topics.TICK, recorder.handle)
    bus.unsubscribe(Topics.TICK, recorder.handle)

    await bus.publish(Topics.TICK)

    assert recorder.events == []


async def test_duplicate_subscription_is_registered_once() -> None:
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(Topics.TICK, handler)
    bus.subscribe(Topics.TICK, handler)

    await bus.publish(Topics.TICK)

    assert len(received) == 1


async def test_handlers_called_in_registration_order() -> None:
    bus = EventBus()
    calls: list[str] = []

    bus.subscribe(Topics.TICK, lambda event: calls.append("first"))
    bus.subscribe(Topics.TICK, lambda event: calls.append("second"))

    await bus.publish(Topics.TICK)

    assert calls == ["first", "second"]


async def test_sync_and_async_handlers_are_awaited_in_order() -> None:
    bus = EventBus()
    calls: list[str] = []

    async def async_handler(event: Event) -> None:
        await asyncio.sleep(0)
        calls.append("async")

    def sync_handler(event: Event) -> None:
        calls.append("sync")

    bus.subscribe(Topics.TICK, async_handler)
    bus.subscribe(Topics.TICK, sync_handler)

    await bus.publish(Topics.TICK)

    # publish 返回时异步订阅者已处理完，顺序与注册顺序一致
    assert calls == ["async", "sync"]


async def test_handler_exception_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    bus = EventBus()
    typed: list[Event] = []
    general: list[Event] = []

    def boom(event: Event) -> None:
        raise RuntimeError("boom")

    bus.subscribe(Topics.ORDER, boom)
    bus.subscribe(Topics.ORDER, typed.append)
    bus.subscribe_all(general.append)

    # 不向发布方抛错
    await bus.publish(Topics.ORDER)

    assert len(typed) == 1
    assert len(general) == 1
    assert "event handler failed" in caplog.text
    assert "boom" in caplog.text


async def test_async_handler_exception_is_isolated() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def boom(event: Event) -> None:
        await asyncio.sleep(0)
        raise ValueError("async boom")

    bus.subscribe(Topics.TRADE, boom)
    bus.subscribe(Topics.TRADE, received.append)

    await bus.publish(Topics.TRADE)

    assert len(received) == 1


async def test_unsubscribe_all() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)

    await bus.publish(Topics.TICK)
    bus.unsubscribe_all(received.append)
    await bus.publish(Topics.TICK)

    assert len(received) == 1
    # 未注册的全局订阅者退订不报错
    bus.unsubscribe_all(received.append)


async def test_timer_publishes_periodically() -> None:
    bus = EventBus()
    received: list[Event] = []
    first_event = asyncio.Event()

    def handler(event: Event) -> None:
        received.append(event)
        first_event.set()

    bus.subscribe(Topics.TIMER, handler)
    bus.start_timer(0.01)
    try:
        await asyncio.wait_for(first_event.wait(), timeout=2)
    finally:
        await bus.stop_timer()

    assert received
    assert received[0].topic == Topics.TIMER
    assert received[0].data is None


async def test_stop_timer_prevents_further_events() -> None:
    bus = EventBus()
    received: list[Event] = []
    first_event = asyncio.Event()

    def handler(event: Event) -> None:
        received.append(event)
        first_event.set()

    bus.subscribe(Topics.TIMER, handler)
    bus.start_timer(0.005)
    await asyncio.wait_for(first_event.wait(), timeout=2)
    await bus.stop_timer()

    count_after_stop = len(received)
    await asyncio.sleep(0.05)

    assert len(received) == count_after_stop


async def test_timer_start_stop_validation() -> None:
    bus = EventBus()

    with pytest.raises(ValueError, match="正数"):
        bus.start_timer(0)

    bus.start_timer(0.01)
    try:
        with pytest.raises(RuntimeError, match="已在运行"):
            bus.start_timer(0.01)
    finally:
        await bus.stop_timer()

    # 未启动 / 重复停止都静默返回
    await bus.stop_timer()
    await bus.stop_timer()


def test_event_topic_equality_and_hash() -> None:
    first = EventTopic("eTick", "rb2410.SHFE")
    second = EventTopic("eTick", "rb2410.SHFE")

    assert first == second
    assert hash(first) == hash(second)
    assert first != EventTopic("eTick", "IF2412.CFFEX")
    assert first != Topics.TICK
    assert {first: "ok"}[second] == "ok"


def test_event_topic_string_forms() -> None:
    assert str(Topics.TICK) == "eTick"
    assert str(Topics.TICK.scoped("rb2410.SHFE")) == "eTick.rb2410.SHFE"
    assert Topics.TICK.scoped("rb2410.SHFE").unscoped == Topics.TICK

    with pytest.raises(ValueError, match="scope 不能为空"):
        Topics.TICK.scoped("")


def test_topics_match_vnpy_event_names() -> None:
    topics = [
        Topics.TIMER,
        Topics.TICK,
        Topics.ORDER,
        Topics.TRADE,
        Topics.POSITION,
        Topics.ACCOUNT,
        Topics.QUOTE,
        Topics.CONTRACT,
        Topics.LOG,
    ]

    assert [str(topic) for topic in topics] == [
        "eTimer",
        "eTick",
        "eOrder",
        "eTrade",
        "ePosition",
        "eAccount",
        "eQuote",
        "eContract",
        "eLog",
    ]


def test_event_is_immutable() -> None:
    event = Event(Topics.TICK, 1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.data = 2  # type: ignore[misc]
