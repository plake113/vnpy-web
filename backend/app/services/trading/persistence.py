"""交易数据持久化订阅：把事件总线上的控制事件批量写入数据库。

来源：vnpy 4.5.0 ``vnpy/trader/database.py`` 与各网关 / 引擎的落库调用
（MIT License，© Xiaoyou Chen）。原版由各调用方（``MainEngine`` / ``OmsEngine`` /
界面）在合适的时机手动调用 ``save_*``；这里改为**订阅事件总线**的独立服务：

- 订阅 ``ORDER`` / ``TRADE`` / ``POSITION`` / ``ACCOUNT`` / ``CONTRACT`` / ``QUOTE``；
- 事件先进入有界队列，后台任务按批取用**独立会话**写入（成交 insert-ignore、
  其余 upsert），不阻塞发布方的事件循环；
- 队列满时 ``await put`` 形成背压：交易链路不允许静默丢事件；
- 单批写入失败记录日志后丢弃该批（当前无重试 / outbox）；``flush`` 等待队列排空，
  ``stop`` 先退订再 flush，保证停机前尽力写完；
- 历史 bar / tick 不走事件总线（行情走独立数据平面，事件载荷契约仍是草稿），
  由数据服务或 API 直接调用 ``crud.market_data``。

前提：事件里的时间必须是 aware（仓储边界规则）。网关 / 数据源适配器负责在入口把交易所
本地时间转成 UTC；当前 Fake 测试数据已是 aware。

服务自身不创建表、不做迁移；表结构由单元 12 的 Alembic 迁移管理。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import Event, EventBus, EventTopic, Topics
from app.crud.trading import (
    save_accounts,
    save_contracts,
    save_orders,
    save_positions,
    save_quotes,
    save_trades,
)
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.orders import OrderData
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.trades import TradeData

__all__ = ["PersistenceService"]

logger = logging.getLogger(__name__)

#: 队列上限。控制面事件速率低，1000 足够吸收突发；满时发布方等待（背压）。
_QUEUE_SIZE = 1_000
#: 单次事务最多处理的队列项数，避免一批过大导致事务过长。
_BATCH_SIZE = 100

_TOPICS: tuple[EventTopic, ...] = (
    Topics.ORDER,
    Topics.TRADE,
    Topics.POSITION,
    Topics.ACCOUNT,
    Topics.CONTRACT,
    Topics.QUOTE,
)

_QueueItem = tuple[EventTopic, object]


class PersistenceService:
    """把控制事件批量写入数据库的订阅者。

    用法（组合根在 lifespan 中创建并注入）::

        persistence = PersistenceService(event_bus, session_factory)
        # 事件到达后自动开始后台写入
        ...
        await persistence.flush()   # 等待已入队事件写完
        await persistence.stop()    # 退订并收尾

    非线程安全；所有方法在事件循环内调用。后台任务懒启动：第一条事件到达时创建，
    ``stop`` 后不再启动。
    """

    def __init__(
        self,
        event_bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._event_bus = event_bus
        self._session_factory = session_factory

        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._worker: asyncio.Task[None] | None = None
        self._stopped = False

        for topic in _TOPICS:
            event_bus.subscribe(topic, self._enqueue)

    # ------------------------------------------------------------------ 事件入口

    async def _enqueue(self, event: Event) -> None:
        """把事件放入队列；队列满时等待（对发布方形成背压）。"""
        if self._stopped:
            return

        self._ensure_worker()
        await self._queue.put((event.topic.unscoped, event.data))

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run(),
                name="trading-persistence",
            )

    # ------------------------------------------------------------------ 后台写入

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            batch: list[_QueueItem] = [first]

            while len(batch) < _BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            try:
                await self._persist(batch)
            except Exception:  # noqa: BLE001 - 单批失败不能拖垮后台任务
                logger.exception("交易数据持久化失败：batch_size=%s", len(batch))
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _persist(self, batch: Sequence[_QueueItem]) -> None:
        orders: list[OrderData] = []
        trades: list[TradeData] = []
        positions: list[PositionData] = []
        accounts: list[AccountData] = []
        contracts: list[ContractData] = []
        quotes: list[QuoteData] = []

        for topic, data in batch:
            if topic == Topics.ORDER and isinstance(data, OrderData):
                orders.append(data)
            elif topic == Topics.TRADE and isinstance(data, TradeData):
                trades.append(data)
            elif topic == Topics.POSITION and isinstance(data, PositionData):
                positions.append(data)
            elif topic == Topics.ACCOUNT and isinstance(data, AccountData):
                accounts.append(data)
            elif topic == Topics.CONTRACT and isinstance(data, ContractData):
                contracts.append(data)
            elif topic == Topics.QUOTE and isinstance(data, QuoteData):
                quotes.append(data)
            else:
                logger.warning(
                    "忽略无法持久化的事件：topic=%s actual=%s",
                    topic,
                    type(data).__name__,
                )

        if not any((orders, trades, positions, accounts, contracts, quotes)):
            return

        async with self._session_factory() as session:
            if contracts:
                await save_contracts(session, contracts)
            if orders:
                await save_orders(session, orders)
            if trades:
                await save_trades(session, trades)
            if positions:
                await save_positions(session, positions)
            if accounts:
                await save_accounts(session, accounts)
            if quotes:
                await save_quotes(session, quotes)

            await session.commit()

    # ------------------------------------------------------------------ 生命周期

    async def flush(self) -> None:
        """等待当前已入队的事件全部处理完；无后台任务时立即返回。"""
        if self._worker is None:
            return

        await self._queue.join()

    async def stop(self) -> None:
        """退订事件、等待队列排空并取消后台任务；可重复调用。"""
        if not self._stopped:
            self._stopped = True
            for topic in _TOPICS:
                self._event_bus.unsubscribe(topic, self._enqueue)

        await self.flush()

        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
