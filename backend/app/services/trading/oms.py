"""OMS 服务：订阅控制事件、维护实时缓存并提供查询。

来源：vnpy 4.5.0 ``vnpy/trader/engine.py`` 的 ``OmsEngine``（MIT License，© Xiaoyou Chen）。
原实现是 ``MainEngine`` 里的内置引擎，继承 ``BaseEngine`` 并直接绑定 ``EventEngine``；
这里拆成独立服务，由组合根（单元 11 的 ``TradingRuntime``）创建并注入。

与桌面版的差异：

- **不持有网关 / 主引擎**：OMS 只消费事件总线与 runtime 写入的行情快照，不发起连接、
  不下单；下单 / 撤单属于后续用例，网关生命周期属于 runtime；
- **键名**：``vt_*`` → ``instrument_key`` / ``order_key`` / ``trade_key`` / ``position_key`` /
  ``account_key`` / ``quote_key``（跨网关复合键统一 ``*_key``）；
- **tick 不进事件总线**：行情走独立数据平面；
  OMS 只保留“最新价快照”，由 runtime 在边界调用 :meth:`update_ticks` 写入，不逐 tick 进总线。
  因此 OMS **不订阅** ``Topics.TICK``；
- **开平转换按网关隔离**：原版为每个网关创建一个 ``OffsetConverter``；这里保持同样语义
  （同一合约在不同网关的持仓不能混算），首次遇到事件时惰性创建；
- **查询返回列表快照**：``get_all_*`` 都返回新的 ``list``，外部改列表不会影响缓存；
  但列表中的领域对象是缓存引用，调用方应只读（领域对象可变，修改会污染缓存）；
- **事件载荷做本地校验**：事件载荷契约（草稿）尚未落地，
  这里对每个控制事件做 ``isinstance`` 校验，非法载荷记录警告后忽略，不修改总线契约；
- **无持久化**：缓存只在进程内（多 worker 一致性问题留到持久化 / 部署阶段）。

生命周期：构造时订阅 ``ORDER`` / ``TRADE`` / ``POSITION`` / ``ACCOUNT`` / ``CONTRACT`` /
``QUOTE``；runtime 关闭时调用 :meth:`stop` 退订。缓存不清空，便于关闭前查询。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TypeVar

from app.core.events import Event, EventBus, EventTopic, HandlerType, Topics
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.market import TickData
from app.domain.offset_converter import OffsetConverter
from app.domain.orders import OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData
from app.domain.symbols import parse_gateway_key
from app.domain.trades import TradeData

__all__ = ["OmsService"]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class OmsService:
    """订单管理系统的实时缓存与查询。

    用法::

        oms = OmsService(event_bus)
        await event_bus.publish(Topics.ORDER, order)   # 由 runtime 路由
        oms.update_ticks(ticks)                        # 由行情边界写入
        order = oms.get_order("CTP.12345")
        oms.stop()
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

        self._ticks: dict[str, TickData] = {}
        self._orders: dict[str, OrderData] = {}
        self._trades: dict[str, TradeData] = {}
        self._positions: dict[str, PositionData] = {}
        self._accounts: dict[str, AccountData] = {}
        self._contracts: dict[str, ContractData] = {}
        self._quotes: dict[str, QuoteData] = {}

        self._active_orders: dict[str, OrderData] = {}
        self._active_quotes: dict[str, QuoteData] = {}

        #: 网关名 → 开平转换器；不同网关的持仓与冻结量互不覆盖
        self._offset_converters: dict[str, OffsetConverter] = {}
        self._subscriptions: list[tuple[EventTopic, HandlerType]] = []

        self._subscribe(Topics.ORDER, self._on_order)
        self._subscribe(Topics.TRADE, self._on_trade)
        self._subscribe(Topics.POSITION, self._on_position)
        self._subscribe(Topics.ACCOUNT, self._on_account)
        self._subscribe(Topics.CONTRACT, self._on_contract)
        self._subscribe(Topics.QUOTE, self._on_quote)

    # ------------------------------------------------------------------ 事件入口

    def _subscribe(self, topic: EventTopic, handler: HandlerType) -> None:
        self._event_bus.subscribe(topic, handler)
        self._subscriptions.append((topic, handler))

    def _payload(self, event: Event, expected: type[_T]) -> _T | None:
        """校验事件载荷类型；不符合时记录警告并返回 ``None``。"""
        if isinstance(event.data, expected):
            return event.data

        logger.warning(
            "OMS 忽略非法事件载荷：topic=%s expected=%s actual=%s",
            event.topic,
            expected.__name__,
            type(event.data).__name__,
        )
        return None

    def _on_order(self, event: Event) -> None:
        order = self._payload(event, OrderData)
        if order is not None:
            self.update_order(order)

    def _on_trade(self, event: Event) -> None:
        trade = self._payload(event, TradeData)
        if trade is not None:
            self.update_trade(trade)

    def _on_position(self, event: Event) -> None:
        position = self._payload(event, PositionData)
        if position is not None:
            self.update_position(position)

    def _on_account(self, event: Event) -> None:
        account = self._payload(event, AccountData)
        if account is not None:
            self.update_account(account)

    def _on_contract(self, event: Event) -> None:
        contract = self._payload(event, ContractData)
        if contract is not None:
            self.update_contract(contract)

    def _on_quote(self, event: Event) -> None:
        quote = self._payload(event, QuoteData)
        if quote is not None:
            self.update_quote(quote)

    # ------------------------------------------------------------------ 缓存更新

    def update_ticks(self, ticks: Iterable[TickData]) -> None:
        """写入一批最新行情快照（由 runtime 在行情数据平面边界调用）。

        同一合约后到的快照覆盖先到的；不同网关的同名合约共用 ``instrument_key``，
        以最后写入者为准。
        """
        for tick in ticks:
            self._ticks[tick.instrument_key] = tick

    def update_tick(self, tick: TickData) -> None:
        """写入单条最新行情快照；批量场景优先用 :meth:`update_ticks`。"""
        self._ticks[tick.instrument_key] = tick

    def update_order(self, order: OrderData) -> None:
        """缓存委托最新**全量**状态，并维护活跃委托索引与开平转换器。"""
        self._orders[order.order_key] = order

        if order.is_active():
            self._active_orders[order.order_key] = order
        else:
            self._active_orders.pop(order.order_key, None)

        self._converter_for(order.gateway_name).update_order(order)

    def update_trade(self, trade: TradeData) -> None:
        """缓存成交回报，并更新开平转换器。"""
        self._trades[trade.trade_key] = trade
        self._converter_for(trade.gateway_name).update_trade(trade)

    def update_position(self, position: PositionData) -> None:
        """缓存持仓快照，并更新开平转换器。"""
        self._positions[position.position_key] = position
        self._converter_for(position.gateway_name).update_position(position)

    def update_account(self, account: AccountData) -> None:
        """缓存账户资金快照。"""
        self._accounts[account.account_key] = account

    def update_contract(self, contract: ContractData) -> None:
        """缓存合约静态信息（开平转换与价格精度都依赖它）。"""
        self._contracts[contract.instrument_key] = contract

    def update_quote(self, quote: QuoteData) -> None:
        """缓存报价最新状态，并维护活跃报价索引。"""
        self._quotes[quote.quote_key] = quote

        if quote.is_active():
            self._active_quotes[quote.quote_key] = quote
        else:
            self._active_quotes.pop(quote.quote_key, None)

    # ------------------------------------------------------------------ 查询

    def get_tick(self, instrument_key: str) -> TickData | None:
        """按合约取最新行情快照。"""
        return self._ticks.get(instrument_key)

    def get_order(self, order_key: str) -> OrderData | None:
        """按委托键取最新委托。"""
        return self._orders.get(order_key)

    def get_trade(self, trade_key: str) -> TradeData | None:
        """按成交键取成交记录。"""
        return self._trades.get(trade_key)

    def get_position(self, position_key: str) -> PositionData | None:
        """按持仓键（网关 + 合约 + 方向）取持仓。"""
        return self._positions.get(position_key)

    def get_account(self, account_key: str) -> AccountData | None:
        """按账户键取资金账户。"""
        return self._accounts.get(account_key)

    def get_contract(self, instrument_key: str) -> ContractData | None:
        """按合约键取合约信息；同时作为开平转换器的合约查询函数。"""
        return self._contracts.get(instrument_key)

    def get_quote(self, quote_key: str) -> QuoteData | None:
        """按报价键取最新报价。"""
        return self._quotes.get(quote_key)

    def get_all_ticks(self) -> list[TickData]:
        """返回全部最新行情快照的列表副本（元素仍是缓存引用）。"""
        return list(self._ticks.values())

    def get_all_orders(self) -> list[OrderData]:
        """返回全部委托的列表副本（元素仍是缓存引用）。"""
        return list(self._orders.values())

    def get_all_trades(self) -> list[TradeData]:
        """返回全部成交的列表副本（元素仍是缓存引用）。"""
        return list(self._trades.values())

    def get_all_positions(self) -> list[PositionData]:
        """返回全部持仓的列表副本（元素仍是缓存引用）。"""
        return list(self._positions.values())

    def get_all_accounts(self) -> list[AccountData]:
        """返回全部账户的列表副本（元素仍是缓存引用）。"""
        return list(self._accounts.values())

    def get_all_contracts(self) -> list[ContractData]:
        """返回全部合约的列表副本（元素仍是缓存引用）。"""
        return list(self._contracts.values())

    def get_all_quotes(self) -> list[QuoteData]:
        """返回全部报价的列表副本（元素仍是缓存引用）。"""
        return list(self._quotes.values())

    def get_all_active_orders(self) -> list[OrderData]:
        """返回全部活跃委托（提交中 / 未成交 / 部分成交）。"""
        return list(self._active_orders.values())

    def get_all_active_quotes(self) -> list[QuoteData]:
        """返回全部活跃报价。"""
        return list(self._active_quotes.values())

    # ------------------------------------------------------------------ 开平转换

    def update_order_request(self, request: OrderRequest, order_key: str) -> None:
        """下单请求发出后、回报到达前预冻结平仓量。

        :param order_key: ``"{gateway_name}.{order_id}"``，由 ``Gateway.send_order`` 返回；
            网关名从键中解析，用于路由到对应网关的转换器
        :raises ValueError: ``order_key`` 不是合法的复合键
        """
        gateway_name, _ = parse_gateway_key(order_key)
        self._converter_for(gateway_name).update_order_request(request, order_key)

    def convert_order_request(
        self,
        request: OrderRequest,
        gateway_name: str,
        *,
        lock: bool = False,
        net: bool = False,
    ) -> list[OrderRequest]:
        """按网关的开平转换器转换下单请求。

        :param gateway_name: 目标网关；``OrderRequest`` 不带网关名，必须由调用方指定
        :returns: 0–3 条请求；空列表表示可用持仓不足（调用方应按拒单处理）
        :raises ValueError: ``lock`` 与 ``net`` 同时为真
        """
        return self._converter_for(gateway_name).convert_order_request(
            request,
            lock=lock,
            net=net,
        )

    def _converter_for(self, gateway_name: str) -> OffsetConverter:
        converter = self._offset_converters.get(gateway_name)
        if converter is None:
            converter = OffsetConverter(self.get_contract)
            self._offset_converters[gateway_name] = converter

        return converter

    # ------------------------------------------------------------------ 生命周期

    def stop(self) -> None:
        """取消全部事件订阅；缓存保留供查询，可重复调用。"""
        for topic, handler in self._subscriptions:
            self._event_bus.unsubscribe(topic, handler)

        self._subscriptions.clear()
