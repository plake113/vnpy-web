"""开平转换：按合约跟踪持仓 / 冻结量，把开平委托拆成可发送的请求列表。

来源：vnpy 4.5.0 ``vnpy/trader/converter.py`` 的 ``PositionHolding`` 与 ``OffsetConverter``
（MIT License，© Xiaoyou Chen）。

背景：期货有「锁仓 / 净仓」两种下单习惯，SHFE / INE 的平仓还必须区分平今与平昨。
是否需要转换由合约决定：

- 净持仓合约（``ContractData.net_position=True``）由柜台按净仓处理，不做转换；
- 双向持仓合约需要本模块把「平仓」拆成「平今 / 平昨」，并按可用持仓与冻结量校验。

与桌面版的差异：

- **不依赖 OMS**：原版 ``OffsetConverter.__init__(oms_engine)`` 保存
  ``oms_engine.get_contract``；这里注入 ``Callable[[str], ContractData | None]``，
  由 runtime 传入 OMS 的查询方法即可，``domain`` 不反向依赖 ``services``；
- **键名**：``vt_symbol`` / ``vt_orderid`` → ``instrument_key`` / ``order_key``
  （跨网关复合键统一 ``*_key``）；订单键用
  :func:`app.domain.symbols.parse_gateway_key` 解析；
- **不改原请求**：原版 ``copy.copy(req)`` 后原地改 ``offset`` / ``volume``；这里用
  ``dataclasses.replace`` 生成新请求，原请求始终不变，避免多个拆分结果共享可变对象；
- **可用量不为负**：持仓快照变小而冻结量尚未收紧时，可用量按 0 截断，
  避免拆出比原请求更大的平昨单；
- **模式互斥**：``lock`` 与 ``net`` 同时为真抛 ``ValueError``，不再静默按 ``lock`` 处理。

术语：

- **今仓 / 昨仓**：``td`` 为当日开仓量，``yd`` 为昨仓结转量，``pos = td + yd``；
- **冻结量**：活跃平仓委托中尚未成交的数量；开仓委托不冻结持仓；
- **锁仓（lock）**：不减少持仓，改为反向开同等数量；只有交易所允许明确平昨时才先平昨；
- **净仓（net）**：先平可用持仓，剩余数量再反向开仓；
- **SHFE / INE**：平仓必须指定平今 / 平昨，因此「平仓」会被拆成最多两条委托。

本模块是纯领域逻辑：不访问数据库、不发网络请求、不创建线程。由 runtime 在事件循环内
串行调用，非线程安全。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from app.domain.contracts import ContractData
from app.domain.enums import Direction, Exchange, Offset
from app.domain.orders import OrderData, OrderRequest
from app.domain.positions import PositionData
from app.domain.symbols import parse_gateway_key
from app.domain.trades import TradeData

__all__ = [
    "OffsetConverter",
    "PositionHolding",
]

#: 需要显式区分平今 / 平昨的交易所（上期所、上期能源）。
_CLOSE_YESTERDAY_EXCHANGES: frozenset[Exchange] = frozenset({Exchange.SHFE, Exchange.INE})


class PositionHolding:
    """单个合约的多空 / 今昨持仓与冻结量跟踪。

    :param contract: 合约静态信息；只取 ``instrument_key`` 与 ``exchange``，
        其余字段（乘数、最小变动价位等）不参与开平转换
    """

    def __init__(self, contract: ContractData) -> None:
        self.instrument_key: str = contract.instrument_key
        self.exchange: Exchange = contract.exchange

        #: 活跃委托：``order_key`` → 委托快照，用于计算冻结量
        self.active_orders: dict[str, OrderData] = {}

        self.long_pos: float = 0
        self.long_yd: float = 0
        self.long_td: float = 0

        self.short_pos: float = 0
        self.short_yd: float = 0
        self.short_td: float = 0

        self.long_pos_frozen: float = 0
        self.long_yd_frozen: float = 0
        self.long_td_frozen: float = 0

        self.short_pos_frozen: float = 0
        self.short_yd_frozen: float = 0
        self.short_td_frozen: float = 0

    @property
    def available_long(self) -> float:
        """多头可用量 = 多头持仓 - 多头冻结量（不小于 0）。"""
        return max(0.0, self.long_pos - self.long_pos_frozen)

    @property
    def available_short(self) -> float:
        """空头可用量 = 空头持仓 - 空头冻结量（不小于 0）。"""
        return max(0.0, self.short_pos - self.short_pos_frozen)

    def update_position(self, position: PositionData) -> None:
        """用持仓快照覆盖对应方向的总量与昨仓，今仓 = 总量 - 昨仓。

        与原版一致，这里**不**重算冻结量：快照可能先于回报到达，下一次委托 / 成交
        更新会用 :meth:`sum_pos_frozen` 把冻结量重新收紧到持仓以内。
        """
        if position.direction == Direction.LONG:
            self.long_pos = position.volume
            self.long_yd = position.yd_volume
            self.long_td = self.long_pos - self.long_yd
        else:
            self.short_pos = position.volume
            self.short_yd = position.yd_volume
            self.short_td = self.short_pos - self.short_yd

    def update_order(self, order: OrderData) -> None:
        """登记活跃委托或移除已终结委托，并重算冻结量。"""
        if order.is_active():
            self.active_orders[order.order_key] = order
        else:
            self.active_orders.pop(order.order_key, None)

        self.calculate_frozen()

    def update_order_request(self, request: OrderRequest, order_key: str) -> None:
        """在网关回报到达前，用下单请求与运行时分配的 ``order_key`` 预冻结平仓量。

        :param order_key: ``"{gateway_name}.{order_id}"``，由 ``Gateway.send_order`` 返回
        :raises ValueError: ``order_key`` 不是合法的复合键
        """
        gateway_name, order_id = parse_gateway_key(order_key)
        self.update_order(request.create_order_data(order_id, gateway_name))

    def update_trade(self, trade: TradeData) -> None:
        """把成交应用到今仓 / 昨仓，并把冻结量收紧到最新持仓以内。

        平仓对今昨仓的影响与原版一致：

        - SHFE / INE 的 ``CLOSE`` 视为平昨（平今必须显式 ``CLOSETODAY``）；
        - 其他交易所的 ``CLOSE`` 按今仓优先，今仓不足时再平昨仓。
        """
        if trade.direction == Direction.LONG:
            if trade.offset == Offset.OPEN:
                self.long_td += trade.volume
            elif trade.offset == Offset.CLOSETODAY:
                self.short_td -= trade.volume
            elif trade.offset == Offset.CLOSEYESTERDAY:
                self.short_yd -= trade.volume
            elif trade.offset == Offset.CLOSE:
                if trade.exchange in _CLOSE_YESTERDAY_EXCHANGES:
                    self.short_yd -= trade.volume
                else:
                    self.short_td -= trade.volume

                    if self.short_td < 0:
                        self.short_yd += self.short_td
                        self.short_td = 0
        else:
            if trade.offset == Offset.OPEN:
                self.short_td += trade.volume
            elif trade.offset == Offset.CLOSETODAY:
                self.long_td -= trade.volume
            elif trade.offset == Offset.CLOSEYESTERDAY:
                self.long_yd -= trade.volume
            elif trade.offset == Offset.CLOSE:
                if trade.exchange in _CLOSE_YESTERDAY_EXCHANGES:
                    self.long_yd -= trade.volume
                else:
                    self.long_td -= trade.volume

                    if self.long_td < 0:
                        self.long_yd += self.long_td
                        self.long_td = 0

        self.long_pos = self.long_td + self.long_yd
        self.short_pos = self.short_td + self.short_yd

        # 成交后持仓可能变小，冻结量不能超过持仓
        self.sum_pos_frozen()

    def calculate_frozen(self) -> None:
        """按活跃委托重算冻结量：只统计尚未成交的平仓数量，并收紧到持仓以内。"""
        self.long_pos_frozen = 0
        self.long_yd_frozen = 0
        self.long_td_frozen = 0

        self.short_pos_frozen = 0
        self.short_yd_frozen = 0
        self.short_td_frozen = 0

        for order in self.active_orders.values():
            # 开仓委托不占用持仓
            if order.offset == Offset.OPEN:
                continue

            frozen: float = order.volume - order.traded

            # 买平冻结空头，卖平冻结多头
            if order.direction == Direction.LONG:
                if order.offset == Offset.CLOSETODAY:
                    self.short_td_frozen += frozen
                elif order.offset == Offset.CLOSEYESTERDAY:
                    self.short_yd_frozen += frozen
                elif order.offset == Offset.CLOSE:
                    self.short_td_frozen += frozen

                    if self.short_td_frozen > self.short_td:
                        self.short_yd_frozen += self.short_td_frozen - self.short_td
                        self.short_td_frozen = self.short_td
            elif order.direction == Direction.SHORT:
                if order.offset == Offset.CLOSETODAY:
                    self.long_td_frozen += frozen
                elif order.offset == Offset.CLOSEYESTERDAY:
                    self.long_yd_frozen += frozen
                elif order.offset == Offset.CLOSE:
                    self.long_td_frozen += frozen

                    if self.long_td_frozen > self.long_td:
                        self.long_yd_frozen += self.long_td_frozen - self.long_td
                        self.long_td_frozen = self.long_td

        self.sum_pos_frozen()

    def sum_pos_frozen(self) -> None:
        """把各方向今昨仓冻结量分别限制在持仓内，并汇总到 ``*_pos_frozen``。"""
        self.long_td_frozen = min(self.long_td_frozen, self.long_td)
        self.long_yd_frozen = min(self.long_yd_frozen, self.long_yd)

        self.short_td_frozen = min(self.short_td_frozen, self.short_td)
        self.short_yd_frozen = min(self.short_yd_frozen, self.short_yd)

        self.long_pos_frozen = self.long_td_frozen + self.long_yd_frozen
        self.short_pos_frozen = self.short_td_frozen + self.short_yd_frozen

    def convert_order_request_shfe(self, request: OrderRequest) -> list[OrderRequest]:
        """SHFE / INE 平仓：按可用今仓 / 昨仓拆成平今 + 平昨。

        - ``OPEN`` 委托原样返回；
        - 可用持仓不足时返回**空列表**，调用方应按拒单处理（与原版一致）；
        - 否则尽量用平今，剩余部分拆成平昨。

        :returns: 0–2 条请求；原请求对象不变
        """
        if request.offset == Offset.OPEN:
            return [request]

        if request.direction == Direction.LONG:
            pos_available = self.available_short
            td_available = max(0.0, self.short_td - self.short_td_frozen)
        else:
            pos_available = self.available_long
            td_available = max(0.0, self.long_td - self.long_td_frozen)

        if request.volume > pos_available:
            return []

        if request.volume <= td_available:
            return [replace(request, offset=Offset.CLOSETODAY)]

        requests: list[OrderRequest] = []

        if td_available > 0:
            requests.append(replace(request, offset=Offset.CLOSETODAY, volume=td_available))

        requests.append(
            replace(
                request,
                offset=Offset.CLOSEYESTERDAY,
                volume=request.volume - td_available,
            )
        )
        return requests

    def convert_order_request_lock(self, request: OrderRequest) -> list[OrderRequest]:
        """锁仓模式：优先反向开仓锁住持仓，只有可明确平昨时才先平昨。

        - 非 SHFE / INE 交易所存在今仓时，平仓会被柜台按今仓优先成交、从而破坏锁仓，
          因此直接反向开同等数量；
        - 其余情况先平昨仓（可平数量），剩余反向开仓。

        :returns: 1–2 条请求；原请求对象不变
        """
        if request.direction == Direction.LONG:
            td_volume = self.short_td
            yd_available = max(0.0, self.short_yd - self.short_yd_frozen)
        else:
            td_volume = self.long_td
            yd_available = max(0.0, self.long_yd - self.long_yd_frozen)

        if td_volume and self.exchange not in _CLOSE_YESTERDAY_EXCHANGES:
            return [replace(request, offset=Offset.OPEN)]

        close_volume = min(request.volume, yd_available)
        open_volume = max(0.0, request.volume - yd_available)

        requests: list[OrderRequest] = []

        if close_volume > 0:
            close_offset = (
                Offset.CLOSEYESTERDAY
                if self.exchange in _CLOSE_YESTERDAY_EXCHANGES
                else Offset.CLOSE
            )
            requests.append(replace(request, offset=close_offset, volume=close_volume))

        if open_volume > 0:
            requests.append(replace(request, offset=Offset.OPEN, volume=open_volume))

        return requests

    def convert_order_request_net(self, request: OrderRequest) -> list[OrderRequest]:
        """净仓模式：先平可用持仓，剩余反向开仓；SHFE / INE 再拆平今 + 平昨。

        :returns: 1–3 条请求；原请求对象不变
        """
        if request.direction == Direction.LONG:
            pos_available = self.available_short
            td_available = max(0.0, self.short_td - self.short_td_frozen)
            yd_available = max(0.0, self.short_yd - self.short_yd_frozen)
        else:
            pos_available = self.available_long
            td_available = max(0.0, self.long_td - self.long_td_frozen)
            yd_available = max(0.0, self.long_yd - self.long_yd_frozen)

        volume_left = request.volume
        requests: list[OrderRequest] = []

        if self.exchange in _CLOSE_YESTERDAY_EXCHANGES:
            if td_available > 0:
                td_volume = min(td_available, volume_left)
                volume_left -= td_volume
                requests.append(replace(request, offset=Offset.CLOSETODAY, volume=td_volume))

            if volume_left > 0 and yd_available > 0:
                yd_volume = min(yd_available, volume_left)
                volume_left -= yd_volume
                requests.append(
                    replace(request, offset=Offset.CLOSEYESTERDAY, volume=yd_volume)
                )
        elif pos_available > 0:
            close_volume = min(pos_available, volume_left)
            volume_left -= close_volume
            requests.append(replace(request, offset=Offset.CLOSE, volume=close_volume))

        if volume_left > 0:
            requests.append(replace(request, offset=Offset.OPEN, volume=volume_left))

        return requests


class OffsetConverter:
    """按合约缓存持仓跟踪，把开平委托转换成可发送的请求列表。

    :param get_contract: 按 ``instrument_key`` 查合约的函数，通常直接传 OMS 的查询方法；
        返回 ``None`` 表示合约未知，此时不做任何转换（请求原样发送，交给柜台校验）

    使用顺序：runtime 收到持仓 / 成交 / 委托回报时调用对应的 ``update_*``，
    下单前调用 :meth:`convert_order_request`；所有方法都在事件循环内串行执行。
    """

    def __init__(self, get_contract: Callable[[str], ContractData | None]) -> None:
        self.get_contract = get_contract
        self.holdings: dict[str, PositionHolding] = {}

    def update_position(self, position: PositionData) -> None:
        """持仓快照到达时更新跟踪；未知合约或净持仓合约直接忽略。"""
        if not self.is_convert_required(position.instrument_key):
            return

        holding = self.get_position_holding(position.instrument_key)
        if holding is not None:
            holding.update_position(position)

    def update_trade(self, trade: TradeData) -> None:
        """成交回报到达时更新跟踪；未知合约或净持仓合约直接忽略。"""
        if not self.is_convert_required(trade.instrument_key):
            return

        holding = self.get_position_holding(trade.instrument_key)
        if holding is not None:
            holding.update_trade(trade)

    def update_order(self, order: OrderData) -> None:
        """委托回报到达时更新冻结量；未知合约或净持仓合约直接忽略。"""
        if not self.is_convert_required(order.instrument_key):
            return

        holding = self.get_position_holding(order.instrument_key)
        if holding is not None:
            holding.update_order(order)

    def update_order_request(self, request: OrderRequest, order_key: str) -> None:
        """下单请求发出后、回报到达前预冻结平仓量；未知合约或净持仓合约直接忽略。

        :raises ValueError: ``order_key`` 不是合法的复合键
        """
        if not self.is_convert_required(request.instrument_key):
            return

        holding = self.get_position_holding(request.instrument_key)
        if holding is not None:
            holding.update_order_request(request, order_key)

    def get_position_holding(self, instrument_key: str) -> PositionHolding | None:
        """返回该合约的持仓跟踪；不存在时按合约创建，合约未知返回 ``None``。

        本方法不检查 ``net_position``：调用方应先用 :meth:`is_convert_required`
        判断是否需要转换。
        """
        holding = self.holdings.get(instrument_key)
        if holding is None:
            contract = self.get_contract(instrument_key)
            if contract is None:
                return None
            holding = PositionHolding(contract)
            self.holdings[instrument_key] = holding

        return holding

    def convert_order_request(
        self,
        request: OrderRequest,
        *,
        lock: bool = False,
        net: bool = False,
    ) -> list[OrderRequest]:
        """按模式转换下单请求；无需转换时原样返回 ``[request]``。

        :param lock: 锁仓模式（优先反向开仓）；与 ``net`` 互斥
        :param net: 净仓模式（先平后开）；与 ``lock`` 互斥
        :returns: 0–3 条请求；空列表表示可用持仓不足，调用方应按拒单处理
        :raises ValueError: ``lock`` 与 ``net`` 同时为真
        """
        if lock and net:
            raise ValueError("lock 与 net 不能同时启用")

        if not self.is_convert_required(request.instrument_key):
            return [request]

        holding = self.get_position_holding(request.instrument_key)
        if holding is None:
            return [request]

        if lock:
            return holding.convert_order_request_lock(request)
        if net:
            return holding.convert_order_request_net(request)
        if request.exchange in _CLOSE_YESTERDAY_EXCHANGES:
            return holding.convert_order_request_shfe(request)

        return [request]

    def is_convert_required(self, instrument_key: str) -> bool:
        """该合约是否需要开平转换：合约未知或 ``net_position`` 为真时返回 ``False``。"""
        contract = self.get_contract(instrument_key)

        return contract is not None and not contract.net_position
