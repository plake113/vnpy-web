"""K 线合成：Tick → 1 分钟 K 线，1 分钟 K 线 → 多分钟 / 多小时 / 日线。

来源：vnpy 4.5.0 ``vnpy/trader/utility.py`` 的 ``BarGenerator``
（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- **去掉回调**：原版构造时注入 ``on_bar`` / ``on_window_bar``；这里 ``update_tick`` /
  ``update_bar`` 直接返回「本次合成的 K 线列表」，由 service 决定怎么发布事件，
  ``domain`` 不持有回调、不关心订阅者；
- **一个实例只负责一个周期**：原版一个实例既能出 1 分钟线又能出窗口线；这里把两者拆开，
  需要多周期时把 1 分钟结果喂给另一个实例的 ``update_bar``（见下方示例）；
- **时间比较用完整分钟 / 小时**：原版只比较 ``hour`` / ``minute``，跨日同小时的数据会被
  错误地并入前一天；这里按完整日期时间比较；
- **日线跨日兜底**：数据缺少 ``daily_end`` 那根分钟线时，原版会一直累积到下一日；
  这里在检测到日期变化时先按旧日期收盘，避免跨日混线；
- **参数校验前置**：window 不合法、日线缺少 ``daily_end``、不支持的周期在构造时直接
  ``ValueError``，而不是等到第一根 K 线才除零 / 静默错线。

多周期组合示例::

    minute = BarGenerator()                    # 只出 1 分钟线
    five = BarGenerator(window=5)              # 5 分钟窗口

    for bar in minute.update_tick(tick):       # 1 分钟线完成
        for window_bar in five.update_bar(bar):
            ...                                # 5 分钟线完成

1 分钟合成约定（与原版一致）：

- ``last_price == 0`` 的 tick 视为无效快照，直接忽略（也不更新 ``last_tick``）；
- 跨分钟时先收盘上一根；同一分钟内用最新价更新 high / low / close 与持仓量；
- 成交量 / 成交额按相邻 tick 的**累计值差分**，累计值回退（如夜盘重置）时按 0 计；
- 日内高 / 低只在出现**新的非零极值**时吸收（``tick.high_price`` / ``low_price`` 为 0
  表示缺失），避免把全天极值重复算进每一分钟。

聚合后的窗口 K 线不设置 ``interval``（``BarData.interval`` 留空）：N 分钟 / N 小时没有
对应的 ``Interval`` 枚举值，窗口大小由生成器参数表达。
"""

from __future__ import annotations

from datetime import datetime as Datetime
from datetime import time as Time

from app.domain.enums import Interval
from app.domain.market import BarData, TickData

__all__ = ["BarGenerator"]

#: 分钟周期的窗口必须能整除一小时，否则窗口会跨小时错位。
_MINUTES_PER_HOUR = 60


class BarGenerator:
    """单周期 K 线合成器。

    :param window: 聚合窗口大小；``0`` 表示不做窗口聚合（仅 1 分钟线）。
        分钟周期必须整除 60（如 2 / 3 / 5 / 6 / 10 / 15 / 20 / 30），
        小时周期必须 ≥ 1（``1`` 表示每个小时线直接输出），日线忽略该参数；
    :param interval: 目标周期，仅支持 ``MINUTE`` / ``HOUR`` / ``DAILY``；
    :param daily_end: 日线的每日收盘时间（如 ``time(15, 0)``），日线周期必须提供；
    :raises ValueError: 参数不合法

    状态全部保存在实例内，非线程安全；由 runtime 在事件循环内串行调用。
    """

    def __init__(
        self,
        window: int = 0,
        *,
        interval: Interval = Interval.MINUTE,
        daily_end: Time | None = None,
    ) -> None:
        if window < 0:
            raise ValueError(f"window 不能为负数：{window}")
        if interval not in {Interval.MINUTE, Interval.HOUR, Interval.DAILY}:
            raise ValueError(f"BarGenerator 不支持周期 {interval.value!r}")
        if interval == Interval.MINUTE and window and _MINUTES_PER_HOUR % window:
            raise ValueError(f"分钟周期的 window 必须整除 {_MINUTES_PER_HOUR}：{window}")
        if interval == Interval.HOUR and window < 1:
            raise ValueError("小时周期必须设置 window >= 1")
        if interval == Interval.DAILY and daily_end is None:
            raise ValueError("日线周期必须提供 daily_end（每日收盘时间）")

        self.window: int = window
        self.interval: Interval = interval
        self.daily_end: Time | None = daily_end

        #: 当前未完成的 1 分钟 K 线
        self._bar: BarData | None = None
        #: 上一条有效 tick，用于计算累计成交量 / 成交额差值与日内极值
        self._last_tick: TickData | None = None
        #: 分钟 / 小时窗口的累积 K 线
        self._window_bar: BarData | None = None
        #: 小时窗口已累积的根数
        self._window_count: int = 0
        #: 当前未完成的小时 K 线
        self._hour_bar: BarData | None = None
        #: 当前未完成的日线
        self._daily_bar: BarData | None = None

    def update_tick(self, tick: TickData) -> list[BarData]:
        """合入一条 tick，返回本次完成的 1 分钟 K 线（0 或 1 条）。

        该方法只负责 1 分钟线；需要更高周期时，把返回的 K 线交给
        :meth:`update_bar`（同一实例或另一个实例均可）。
        """
        if not tick.last_price:
            return []

        minute_start = tick.datetime.replace(second=0, microsecond=0)
        finished: list[BarData] = []

        bar = self._bar
        if bar is not None and bar.datetime != minute_start:
            finished.append(bar)
            bar = None

        if bar is None:
            bar = BarData(
                gateway_name=tick.gateway_name,
                symbol=tick.symbol,
                exchange=tick.exchange,
                datetime=minute_start,
                interval=Interval.MINUTE,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
                open_interest=tick.open_interest,
            )
            self._bar = bar
        else:
            bar.high_price = max(bar.high_price, tick.last_price)
            bar.low_price = min(bar.low_price, tick.last_price)
            bar.close_price = tick.last_price
            bar.open_interest = tick.open_interest

        # 日内极值只在出现新极值时吸收；成交量 / 成交额按累计值差分
        last_tick = self._last_tick
        if last_tick is not None:
            if tick.high_price != 0 and tick.high_price > last_tick.high_price:
                bar.high_price = max(bar.high_price, tick.high_price)
            if tick.low_price != 0 and tick.low_price < last_tick.low_price:
                bar.low_price = min(bar.low_price, tick.low_price)

            bar.volume += max(tick.volume - last_tick.volume, 0)
            bar.turnover += max(tick.turnover - last_tick.turnover, 0)

        self._last_tick = tick
        return finished

    def generate(self) -> BarData | None:
        """强制收盘当前 1 分钟 K 线并返回；没有未完成 K 线时返回 ``None``。

        用于收盘 / 断开连接前补齐最后一根线；窗口 K 线不会被强制收盘。
        """
        bar = self._bar
        self._bar = None

        return bar

    def update_bar(self, bar: BarData) -> list[BarData]:
        """合入一根 1 分钟 K 线，返回本次完成的目标周期 K 线（0 或 1 条）。

        - ``interval=MINUTE``：按 :attr:`window` 聚合；``window=0`` 时恒返回空列表；
        - ``interval=HOUR``：先合成小时线，再按 ``window`` 聚合多小时；
        - ``interval=DAILY``：按 :attr:`daily_end` 收盘，返回日线。

        输入应为 1 分钟 K 线；缺口不会补齐，窗口从第一根输入开始累计。
        """
        if self.interval == Interval.MINUTE:
            return self._update_minute_window(bar)
        if self.interval == Interval.HOUR:
            return self._update_hour_window(bar)

        return self._update_daily_window(bar)

    def _update_minute_window(self, bar: BarData) -> list[BarData]:
        if self.window == 0:
            return []

        window_bar = self._window_bar
        if window_bar is None:
            window_bar = BarData(
                gateway_name=bar.gateway_name,
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=bar.datetime.replace(second=0, microsecond=0),
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
            )
            self._window_bar = window_bar
        else:
            window_bar.high_price = max(window_bar.high_price, bar.high_price)
            window_bar.low_price = min(window_bar.low_price, bar.low_price)

        window_bar.close_price = bar.close_price
        window_bar.volume += bar.volume
        window_bar.turnover += bar.turnover
        window_bar.open_interest = bar.open_interest

        if (bar.datetime.minute + 1) % self.window == 0:
            self._window_bar = None
            return [window_bar]

        return []

    def _update_hour_window(self, bar: BarData) -> list[BarData]:
        hour_start = bar.datetime.replace(minute=0, second=0, microsecond=0)
        finished_hours: list[BarData] = []

        hour_bar = self._hour_bar
        if hour_bar is not None and hour_bar.datetime != hour_start:
            # 跨小时（含跨日同日小时）时先收盘上一小时
            finished_hours.append(hour_bar)
            hour_bar = None

        if hour_bar is None:
            hour_bar = BarData(
                gateway_name=bar.gateway_name,
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=hour_start,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            self._hour_bar = hour_bar
        else:
            hour_bar.high_price = max(hour_bar.high_price, bar.high_price)
            hour_bar.low_price = min(hour_bar.low_price, bar.low_price)
            hour_bar.close_price = bar.close_price
            hour_bar.volume += bar.volume
            hour_bar.turnover += bar.turnover
            hour_bar.open_interest = bar.open_interest

        if bar.datetime.minute == _MINUTES_PER_HOUR - 1:
            # 分钟线到 :59 即认为本小时结束；小时线由窗口聚合决定是否输出
            finished_hours.append(hour_bar)
            self._hour_bar = None

        completed: list[BarData] = []
        for finished_hour in finished_hours:
            completed.extend(self._aggregate_hour(finished_hour))

        return completed

    def _aggregate_hour(self, hour_bar: BarData) -> list[BarData]:
        if self.window == 1:
            return [hour_bar]

        window_bar = self._window_bar
        if window_bar is None:
            window_bar = BarData(
                gateway_name=hour_bar.gateway_name,
                symbol=hour_bar.symbol,
                exchange=hour_bar.exchange,
                datetime=hour_bar.datetime,
                open_price=hour_bar.open_price,
                high_price=hour_bar.high_price,
                low_price=hour_bar.low_price,
            )
            self._window_bar = window_bar
        else:
            window_bar.high_price = max(window_bar.high_price, hour_bar.high_price)
            window_bar.low_price = min(window_bar.low_price, hour_bar.low_price)

        window_bar.close_price = hour_bar.close_price
        window_bar.volume += hour_bar.volume
        window_bar.turnover += hour_bar.turnover
        window_bar.open_interest = hour_bar.open_interest

        self._window_count += 1
        if self._window_count % self.window == 0:
            self._window_count = 0
            self._window_bar = None
            return [window_bar]

        return []

    def _update_daily_window(self, bar: BarData) -> list[BarData]:
        completed: list[BarData] = []
        daily_bar = self._daily_bar

        # 数据缺少 daily_end 那根线时，按日期变化先收盘前一天，避免跨日混线
        if daily_bar is not None and daily_bar.datetime.date() != bar.datetime.date():
            completed.append(daily_bar)
            daily_bar = None

        if daily_bar is None:
            daily_bar = BarData(
                gateway_name=bar.gateway_name,
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=Datetime.combine(bar.datetime.date(), Time.min),
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            self._daily_bar = daily_bar
        else:
            daily_bar.high_price = max(daily_bar.high_price, bar.high_price)
            daily_bar.low_price = min(daily_bar.low_price, bar.low_price)
            daily_bar.close_price = bar.close_price
            daily_bar.volume += bar.volume
            daily_bar.turnover += bar.turnover
            daily_bar.open_interest = bar.open_interest

        if self.daily_end is not None and bar.datetime.time() == self.daily_end:
            completed.append(daily_bar)
            self._daily_bar = None

        return completed
