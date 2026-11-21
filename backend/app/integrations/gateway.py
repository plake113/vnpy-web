"""异步网关端口：交易系统接入的抽象与窄接口回调。

来源：vnpy 4.5.0 ``vnpy/trader/gateway.py`` 的 ``BaseGateway``
（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- **同步方法 → 异步端口**：连接、订阅、下单、撤单、查询全部是 ``async`` 方法，
  由组合根在事件循环内调用，不再要求实现方自己保证线程安全；
- **不再持有 ``EventEngine``**：网关在构造时拿到窄接口 :class:`EventSink`，
  用 ``await`` 把领域对象交给上层；把回调路由到 ``EventBus`` / OMS / 行情平面是
  sink 实现（单元 11 的 ``TradingRuntime``）的职责；
- **只推一次、不做逐合约扇出**：原版对每个 tick / order 额外推一条
  ``EVENT_XXX + vt_symbol`` 事件；这里只推领域对象，按合约 / 委托筛选由 sink 用
  ``EventTopic.scoped`` 完成，避免同一份数据被复制多次；
- **行情批量回调**：行情走批量语义，tick 走
  :meth:`EventSink.on_ticks` 批量语义，而不是逐条 ``on_tick``；
- **不动态 import**：网关实例由组合根创建并注册，不再按名称 ``import_module``；
- ``gateway_name`` 参与 ``order_key`` / ``account_key`` 等复合键，构造时用
  :func:`app.domain.symbols.validate_gateway_name` 校验
  （网关名不能为空、不能含点号）；同一运行时内的名称唯一性
  由组合根保证。

实现约定（写适配器时必读）：

1. **线程模型**：端口本身不创建线程。底层 SDK 若为同步 + 回调线程模型，适配器必须用
   ``loop.call_soon_threadsafe`` 把回调送回事件循环，不能在该线程里直接 ``await``；
2. **数据不可变**：传给 sink 的领域对象之后不得再修改；需要缓存复用时先 ``copy.copy``；
3. **断线重连**：``connect`` 成功后网关自行处理断线与重连，不属于端口职责；
4. **生命周期**：``connect`` / ``close`` 由 runtime 调用一次；``close`` 应可重复调用并静默返回；
5. **初始化查询**：``connect`` 成功后应主动查询合约、账户、持仓、委托、成交并通过 sink 推送，
   保证 OMS 的初始快照完整。

具体适配器放在 ``integrations/gateways/`` 子包（后续单元）；本模块只定义端口与回调契约，
不引入任何 vnpy 类型或第三方 SDK。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.market import SubscribeRequest, TickData
from app.domain.orders import CancelRequest, OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData, QuoteRequest
from app.domain.symbols import validate_gateway_name
from app.domain.trades import TradeData

__all__ = [
    "EventSink",
    "Gateway",
    "SettingValue",
]

#: 网关连接的配置值类型（原版 ``dict[str, str | int | float | bool]``）。
SettingValue = str | int | float | bool


class EventSink(Protocol):
    """网关向运行时推送数据的窄接口。

    实现方（runtime）负责把每个回调路由到事件总线、OMS 缓存或行情数据平面；
    本协议不关心路由细节，也不允许回调阻塞太久——网关会在自己的 await 点上等待它，
    慢处理会形成背压。

    所有方法都是异步的：同步 SDK 的适配层需要先回到事件循环，再调用这些方法。
    """

    async def on_ticks(self, ticks: Sequence[TickData]) -> None:
        """接收一批行情快照（批量语义，避免逐条 tick 调度开销）。

        - 网关按自己的回调节奏攒批，空批次不应调用；
        - 批次内的对象在调用后不得再修改；
        - ``await`` 返回表示本批已交给上层；慢消费者在这里形成背压，
          网关不得静默丢弃（丢弃策略由消费端显式配置并记录缺口）。
        """

    async def on_order(self, order: OrderData) -> None:
        """接收一笔委托的最新**全量**状态（不是增量）。"""

    async def on_trade(self, trade: TradeData) -> None:
        """接收一笔成交回报。"""

    async def on_position(self, position: PositionData) -> None:
        """接收一条持仓快照（按合约 + 方向）。"""

    async def on_account(self, account: AccountData) -> None:
        """接收一条账户资金快照。"""

    async def on_quote(self, quote: QuoteData) -> None:
        """接收一笔双边报价的最新状态。"""

    async def on_contract(self, contract: ContractData) -> None:
        """接收一条合约静态信息（``connect`` 后批量推送）。"""

    async def on_log(self, gateway_name: str, message: str, level: int = logging.INFO) -> None:
        """接收网关诊断消息。

        日志不是交易领域对象，这里用「网关名 + 文本 + 标准库等级」表达，不引入新的
        ``LogData`` 领域类；若后续日志 / 通知单元需要结构化日志，再单独设计。

        :param gateway_name: 来源网关名（sink 由多个网关共享）
        :param message: 已格式化、可直接展示的消息
        :param level: 标准库 ``logging`` 等级，默认 INFO
        """


class Gateway(ABC):
    """交易网关异步端口。

    子类必须：声明 :attr:`gateway_name` 与 :attr:`default_setting`，实现所有
    ``@abstractmethod``；并按 :class:`EventSink` 的约定推送数据。

    实例由组合根创建，构造时传入 sink 与可选网关名覆盖::

        class CtpGateway(Gateway):
            gateway_name = "CTP"
            default_setting = {"user_id": "", "password": ""}

        gateway = CtpGateway(event_sink)
    """

    #: 网关名：出现在 ``order_key`` / ``account_key`` 等复合键中，子类必须覆盖。
    #: 也可在构造时覆盖，用于同一适配器的多账户实例（如 ``CTP_1`` / ``CTP_2``）。
    gateway_name: str = ""

    #: 连接所需的默认配置项（键 → 默认值）；runtime 合并用户配置后传给 :meth:`connect`。
    #: 该类属性只读，实例不得修改。
    default_setting: dict[str, SettingValue] = {}

    def __init__(self, event_sink: EventSink, *, gateway_name: str | None = None) -> None:
        """绑定回调 sink 并校验网关名。

        :param event_sink: 运行时实现的窄接口回调
        :param gateway_name: 覆盖类属性 :attr:`gateway_name`；``None`` 表示用类属性
        :raises ValueError: 网关名为空或包含点号（会破坏复合键拆分）
        """
        chosen = type(self).gateway_name if gateway_name is None else gateway_name
        self.gateway_name = validate_gateway_name(chosen)
        self.event_sink: EventSink = event_sink

    async def write_log(self, message: str, level: int = logging.INFO) -> None:
        """把一条网关日志交给 sink（自动带上网关名）。"""
        await self.event_sink.on_log(self.gateway_name, message, level)

    @abstractmethod
    async def connect(self, setting: Mapping[str, SettingValue]) -> None:
        """建立连接并完成初始化查询。

        实现应：连接服务端 → 查询合约 / 账户 / 持仓 / 委托 / 成交并通过
        :attr:`event_sink` 推送 → 失败时抛出异常，由 runtime 记录并暴露给前端。

        :param setting: ``default_setting`` 与用户配置合并后的结果（用户配置优先）
        """

    @abstractmethod
    async def close(self) -> None:
        """断开连接并释放资源；应可重复调用（未连接时静默返回）。"""

    @abstractmethod
    async def subscribe(self, request: SubscribeRequest) -> None:
        """订阅行情。

        实现应记住订阅关系，并在收到行情时按批调用 :meth:`EventSink.on_ticks`；
        重复订阅同一合约应幂等（不重复推送）。
        """

    @abstractmethod
    async def unsubscribe(self, request: SubscribeRequest) -> None:
        """取消行情订阅；未订阅时静默返回。"""

    @abstractmethod
    async def send_order(self, request: OrderRequest) -> str:
        """提交新委托，返回跨网关唯一的 ``order_key``。

        实现应：用 ``request.create_order_data(order_id, self.gateway_name)`` 构造委托，
        分配网关实例内唯一的 ``order_id``，按发送结果把状态置为 ``SUBMITTING``
        或 ``REJECTED``，通过 :meth:`EventSink.on_order` 推送该快照，再返回键。

        :returns: ``"{gateway_name}.{order_id}"``（复合键格式）
        """

    @abstractmethod
    async def cancel_order(self, request: CancelRequest) -> None:
        """撤销委托。

        :param request: 撤单请求，由
            :meth:`app.domain.orders.OrderData.create_cancel_request` 生成；
            目标网关由 runtime 根据 ``order_key`` 路由，网关本身不判断来源。
        """

    @abstractmethod
    async def query_account(self) -> None:
        """主动查询资金账户，并通过 :meth:`EventSink.on_account` 推送全量快照。"""

    @abstractmethod
    async def query_position(self) -> None:
        """主动查询持仓，并通过 :meth:`EventSink.on_position` 推送全量快照。"""

    async def send_quote(self, request: QuoteRequest) -> str:
        """提交双边报价，返回 ``quote_key``；默认不支持。

        报价是期权做市 / RFQ 的可选能力，只有支持的网关才覆盖本方法。

        :raises NotImplementedError: 网关未实现报价能力
        """
        raise NotImplementedError(f"网关 {self.gateway_name} 不支持报价")

    async def cancel_quote(self, request: CancelRequest) -> None:
        """撤销报价；默认不支持。

        与 :meth:`cancel_order` 一样复用 ``CancelRequest``（``quote_id`` 填入
        ``order_id`` 字段，与原版一致），由网关适配层区分委托与报价。

        :raises NotImplementedError: 网关未实现报价能力
        """
        raise NotImplementedError(f"网关 {self.gateway_name} 不支持报价")
