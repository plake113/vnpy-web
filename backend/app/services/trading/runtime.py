"""交易运行时：网关注册、事件路由与生命周期管理（组合根）。

来源：vnpy 4.5.0 ``vnpy/trader/engine.py`` 的 ``MainEngine``（MIT License，© Xiaoyou Chen）。
原实现是桌面端的全局门面：自己启动事件线程、持有网关 / 内置引擎 / App / 数据库 /
通知，并 ``os.chdir(TRADER_DIR)``。Web 版把它拆成职责明确的组合根：

- **替代单例**：由 FastAPI ``lifespan`` 创建并注入，不提供模块级实例，也不读全局配置；
- **只做编排**：持有 ``EventBus`` / ``OmsService`` 与网关 / 数据源注册表，把请求路由到
  端口、把端口回调路由到总线和 OMS；下单规则、持久化、HTTP 契约都不在这里；
- **实现窄接口**：网关构造时把 ``TradingRuntime`` 作为 :class:`EventSink` 传入，
  控制事件发布到 ``EventBus``，tick 只写入 OMS 最新快照（行情不进事件总线）；
- **不复制桌面行为**：不 ``os.chdir``、不读写 ``.vntrader``、不创建线程、不按字符串动态
  import；网关 SDK 的线程回调由适配器 ``call_soon_threadsafe`` 送回事件循环；
- **生命周期集中**：``close`` 依次停事件总线定时器、关闭网关、关闭数据源、退订 OMS。

事件发布约定：每个控制事件只发布**一条带范围的主题**（如 ``eOrder.CTP.12345``）。
``EventBus`` 的范围语义是「订阅不带范围的主题能收到该名称下所有范围的事件」，
因此 OMS 全局订阅一次即可收到全部订单，按单订阅者也不会收到重复事件；不需要再额外
发布一条无范围事件。

行情边界：``on_ticks`` 目前只更新 OMS 的最新快照；批量行情数据平面尚未落地，
接入点保留在该方法内，落地后在这里投递缓冲区而不是逐条发布。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from app.core.events import EventBus, EventTopic, Topics
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.accounts import AccountData
from app.domain.contracts import ContractData
from app.domain.market import BarData, HistoryRequest, SubscribeRequest, TickData
from app.domain.orders import CancelRequest, OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.quotes import QuoteData, QuoteRequest
from app.domain.trades import TradeData
from app.integrations.datafeed import DataFeed
from app.integrations.gateway import EventSink, Gateway, SettingValue
from app.services.trading.oms import OmsService

__all__ = [
    "DataFeedConflictError",
    "DataFeedNotFoundError",
    "GatewayConflictError",
    "GatewayNotFoundError",
    "TradingRuntime",
]

logger = logging.getLogger(__name__)


class GatewayNotFoundError(NotFoundError):
    """请求的网关未注册。"""

    code = "GATEWAY_NOT_FOUND"


class GatewayConflictError(ConflictError):
    """同名网关已注册。"""

    code = "GATEWAY_CONFLICT"


class DataFeedNotFoundError(NotFoundError):
    """请求的数据源未注册。"""

    code = "DATAFEED_NOT_FOUND"


class DataFeedConflictError(ConflictError):
    """同名数据源已注册。"""

    code = "DATAFEED_CONFLICT"


class TradingRuntime(EventSink):
    """交易运行时（组合根）。

    **只做编排**：持有事件总线、OMS 与网关 / 数据源注册表，不实现交易业务规则：

    - 网关通过 :meth:`add_gateway` 注册；构造网关时把本对象作为 ``EventSink`` 传入；
    - 数据源通过 :meth:`add_datafeed` 注册（注册时调用 ``init``）；
    - 连接、订阅、下单、撤单、查询都按名称路由到对应端口；
    - 网关回调由本类实现：控制事件发布到 ``EventBus``，tick 写入 OMS 快照。

    由 FastAPI ``lifespan`` 创建，关闭时调用 :meth:`close`；重复调用安全，
    但关闭后不应再使用。非线程安全，所有方法都在事件循环内调用。
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._oms = OmsService(event_bus)
        self._gateways: dict[str, Gateway] = {}
        self._datafeeds: dict[str, DataFeed] = {}

    @property
    def event_bus(self) -> EventBus:
        """运行时使用的事件总线（只读）。"""
        return self._event_bus

    @property
    def oms(self) -> OmsService:
        """运行时持有的 OMS 服务（只读）。"""
        return self._oms

    # ------------------------------------------------------------------ 注册表

    def add_gateway(self, gateway: Gateway) -> None:
        """注册网关。

        网关名在 :class:`~app.integrations.gateway.Gateway` 构造时已校验，
        这里保证同一运行时内不重名。

        :raises GatewayConflictError: 同名网关已注册
        """
        name = gateway.gateway_name
        if name in self._gateways:
            raise GatewayConflictError(f"网关 {name!r} 已注册")

        self._gateways[name] = gateway
        logger.info("已注册网关：%s", name)

    def get_gateway(self, gateway_name: str) -> Gateway:
        """按名称取网关。

        :raises GatewayNotFoundError: 网关未注册
        """
        gateway = self._gateways.get(gateway_name)
        if gateway is None:
            raise GatewayNotFoundError(f"网关 {gateway_name!r} 未注册")

        return gateway

    def get_all_gateway_names(self) -> list[str]:
        """返回已注册网关名（注册顺序）。"""
        return list(self._gateways)

    async def add_datafeed(self, datafeed: DataFeed) -> None:
        """注册并初始化数据源。

        初始化失败时抛异常且不注册，避免留下不可用的“半注册”实例。

        :raises BadRequestError: 数据源没有声明 ``datafeed_name``
        :raises DataFeedConflictError: 同名数据源已注册
        """
        name = datafeed.datafeed_name
        if not name:
            raise BadRequestError("数据源必须声明非空的 datafeed_name")
        if name in self._datafeeds:
            raise DataFeedConflictError(f"数据源 {name!r} 已注册")

        await datafeed.init()
        self._datafeeds[name] = datafeed
        logger.info("已注册数据源：%s", name)

    def get_datafeed(self, datafeed_name: str) -> DataFeed:
        """按名称取数据源。

        :raises DataFeedNotFoundError: 数据源未注册
        """
        datafeed = self._datafeeds.get(datafeed_name)
        if datafeed is None:
            raise DataFeedNotFoundError(f"数据源 {datafeed_name!r} 未注册")

        return datafeed

    def get_all_datafeed_names(self) -> list[str]:
        """返回已注册数据源名（注册顺序）。"""
        return list(self._datafeeds)

    # ------------------------------------------------------------------ 网关路由

    async def connect(
        self,
        gateway_name: str,
        setting: Mapping[str, SettingValue] | None = None,
    ) -> None:
        """连接网关：合并默认配置后调用 ``Gateway.connect``。

        :param setting: 用户配置，覆盖 ``Gateway.default_setting`` 中的默认值
        :raises GatewayNotFoundError: 网关未注册
        """
        gateway = self.get_gateway(gateway_name)
        merged = dict(gateway.default_setting)
        if setting:
            merged.update(setting)

        await gateway.connect(merged)
        logger.info("网关已连接：%s", gateway_name)

    async def subscribe(self, gateway_name: str, request: SubscribeRequest) -> None:
        """订阅行情。"""
        await self.get_gateway(gateway_name).subscribe(request)

    async def unsubscribe(self, gateway_name: str, request: SubscribeRequest) -> None:
        """取消行情订阅。"""
        await self.get_gateway(gateway_name).unsubscribe(request)

    async def send_order(self, gateway_name: str, request: OrderRequest) -> str:
        """发送委托，返回跨网关唯一的 ``order_key``。

        网关未同步回报委托时，用 :meth:`OmsService.update_order_request` 预冻结平仓量；
        若网关在 ``send_order`` 内已经推送过该委托（同步回报），缓存里已有它的最新状态，
        跳过预冻结，避免用请求快照覆盖已回报的状态（如拒单）。
        """
        gateway = self.get_gateway(gateway_name)
        order_key = await gateway.send_order(request)

        if self._oms.get_order(order_key) is None:
            self._oms.update_order_request(request, order_key)

        return order_key

    async def cancel_order(self, gateway_name: str, request: CancelRequest) -> None:
        """撤销委托。"""
        await self.get_gateway(gateway_name).cancel_order(request)

    async def send_quote(self, gateway_name: str, request: QuoteRequest) -> str:
        """发送双边报价，返回 ``quote_key``；网关不支持时抛 ``NotImplementedError``。"""
        return await self.get_gateway(gateway_name).send_quote(request)

    async def cancel_quote(self, gateway_name: str, request: CancelRequest) -> None:
        """撤销报价；网关不支持时抛 ``NotImplementedError``。"""
        await self.get_gateway(gateway_name).cancel_quote(request)

    # ------------------------------------------------------------------ 历史行情

    async def query_bar_history(
        self,
        datafeed_name: str,
        request: HistoryRequest,
    ) -> list[BarData]:
        """通过数据源查询历史 K 线（不回到网关）。"""
        return await self.get_datafeed(datafeed_name).query_bar_history(request)

    async def query_tick_history(
        self,
        datafeed_name: str,
        request: HistoryRequest,
    ) -> list[TickData]:
        """通过数据源查询历史 Tick；数据源不支持时抛 ``NotImplementedError``。"""
        return await self.get_datafeed(datafeed_name).query_tick_history(request)

    # ------------------------------------------------------------------ EventSink

    async def on_ticks(self, ticks: Sequence[TickData]) -> None:
        """接收一批行情：写入 OMS 最新快照。

        行情数据平面落地后在此投递缓冲区，而不是逐条发布到
        ``EventBus``；当前只保留最新快照。
        """
        self._oms.update_ticks(ticks)

    async def on_order(self, order: OrderData) -> None:
        """发布委托事件，范围为 ``order_key``。"""
        await self._publish(Topics.ORDER, order.order_key, order)

    async def on_trade(self, trade: TradeData) -> None:
        """发布成交事件，范围为 ``trade_key``。"""
        await self._publish(Topics.TRADE, trade.trade_key, trade)

    async def on_position(self, position: PositionData) -> None:
        """发布持仓事件，范围为 ``position_key``。"""
        await self._publish(Topics.POSITION, position.position_key, position)

    async def on_account(self, account: AccountData) -> None:
        """发布账户事件，范围为 ``account_key``。"""
        await self._publish(Topics.ACCOUNT, account.account_key, account)

    async def on_contract(self, contract: ContractData) -> None:
        """发布合约事件，范围为 ``instrument_key``。"""
        await self._publish(Topics.CONTRACT, contract.instrument_key, contract)

    async def on_quote(self, quote: QuoteData) -> None:
        """发布报价事件，范围为 ``quote_key``。"""
        await self._publish(Topics.QUOTE, quote.quote_key, quote)

    async def on_log(self, gateway_name: str, message: str, level: int = logging.INFO) -> None:
        """把网关日志写入标准库日志（带上网关名）。"""
        logger.log(level, "[%s] %s", gateway_name, message)

    async def _publish(self, topic: EventTopic, scope: str, data: object) -> None:
        """发布一条带范围的控制事件；全局订阅者由总线负责扇出。"""
        await self._event_bus.publish(topic.scoped(scope), data)

    # ------------------------------------------------------------------ 生命周期

    async def close(self) -> None:
        """关闭运行时：停定时器 → 关网关 → 关数据源 → 退订 OMS。

        重复调用安全（网关 / 数据源 / OMS 的关闭与退订都允许重复），但关闭后
        不应再发起新的连接或查询。
        """
        await self._event_bus.stop_timer()

        # 关闭阶段尽力而为：单个网关 / 数据源失败不应阻塞其他资源清理
        for name, gateway in self._gateways.items():
            try:
                await gateway.close()
            except Exception:  # noqa: BLE001 - 记录后继续关闭其他资源
                logger.exception("关闭网关失败：%s", name)

        for name, datafeed in self._datafeeds.items():
            try:
                await datafeed.close()
            except Exception:  # noqa: BLE001 - 记录后继续关闭其他资源
                logger.exception("关闭数据源失败：%s", name)

        self._oms.stop()
        logger.info("交易运行时已关闭")
