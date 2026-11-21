"""指标容器：K 线滚动窗口与技术指标。

来源：vnpy 4.5.0 ``vnpy/trader/utility.py`` 的 ``ArrayManager``
（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- **直接使用 TA-Lib**：原版就委托 TA-Lib，这里保留同一计算内核，指标数值与 vnpy 完全一致；
  ``numpy`` / ``TA-Lib`` 是 ``domain`` 的数值依赖例外，只允许出现在本模块；
- **参数前置校验**：周期、移动平均类型与 SAR 参数在调用 TA-Lib 前校验，非法值抛
  ``TypeError`` / ``ValueError``，不再把 TA-Lib 的 ``TA_BAD_PARAM`` 以裸 ``Exception`` 透出；
- **标量返回 Python float**：``array=False`` 时把 ``np.float64`` 转成 ``float``，其余语义不变；
- **不迁移** ``virtual`` 装饰器与桌面路径 / 图标工具（见 MIGRATION 第 6 节）。

窗口语义与原版一致：

- ``size`` 固定，``update_bar`` 把最新一根写到末尾、其余左移；
- 未填满前左侧为 0（对应原版 ``np.zeros``），``inited`` 在累计 ``size`` 根 K 线后为 ``True``；
- 指标结果预热期为 ``nan``；``array=True`` 返回与窗口等长的 ``numpy.ndarray``，
  否则返回最后一个值（预热期同样为 ``nan``）；
- 属性与 ``array=True`` 返回的是内部 / TA-Lib 数组，调用方不应原地修改。

线程安全：实例可变，非线程安全；由调用方（策略 / runtime）串行更新。
"""

from __future__ import annotations

from numbers import Integral, Real
from typing import Literal, cast, overload

import numpy as np
import talib

from app.domain.market import BarData

__all__ = ["ArrayManager"]

#: TA-Lib 移动平均类型（``matype`` 参数）：0=SMA、1=EMA、2=WMA、
#: 3=DEMA、4=TEMA、5=TRIMA、6=KAMA、7=MAMA、8=T3。
_MATYPE_MIN = 0
_MATYPE_MAX = 8


def _check_size(size: int) -> int:
    """校验窗口大小：必须是正整数。"""
    if isinstance(size, bool) or not isinstance(size, Integral):
        raise TypeError(f"size 必须是整数：{size!r}")
    if size < 1:
        raise ValueError(f"size 必须为正整数：{size}")
    return int(size)


def _check_period(value: int, name: str) -> int:
    """校验指标周期：必须是正整数。"""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数：{value!r}")
    if value < 1:
        raise ValueError(f"{name} 必须为正整数：{value}")
    return int(value)


def _check_matype(value: int, name: str = "matype") -> int:
    """校验移动平均类型：TA-Lib 支持 0–8。"""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数：{value!r}")
    if not _MATYPE_MIN <= value <= _MATYPE_MAX:
        raise ValueError(f"{name} 必须在 {_MATYPE_MIN}–{_MATYPE_MAX} 之间：{value}")
    return int(value)


def _ta_matype(value: int) -> talib.MA_Type:
    """把 0–8 的整数转成 TA-Lib 存根要求的 ``MA_Type``。

    运行时 ``MA_Type`` 的成员本身就是 ``int``（枚举对象不可调用），这里只用 ``cast``
    满足类型检查，传给 TA-Lib 的值不变。
    """
    return cast(talib.MA_Type, value)


def _check_positive(value: float, name: str) -> float:
    """校验正数参数（SAR 加速因子 / 上下轨倍数等）。"""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} 必须是数值：{value!r}")
    if value <= 0:
        raise ValueError(f"{name} 必须为正数：{value}")
    return float(value)


class ArrayManager:
    """K 线滚动窗口 + 技术指标查询门面。

    :param size: 窗口长度（K 线根数），默认 100，必须为正整数
    :raises TypeError: ``size`` 不是整数
    :raises ValueError: ``size`` 小于 1

    指标方法统一接受 ``array`` 开关：``False``（默认）返回最新值，
    ``True`` 返回与窗口等长的整条序列（预热期为 ``nan``）。
    多值指标返回 tuple，顺序与原版 / TA-Lib 一致。
    """

    def __init__(self, size: int = 100) -> None:
        """构造定长窗口，数组预填 0（与原版 ``np.zeros`` 一致）。"""
        size = _check_size(size)
        self.count: int = 0
        self.size: int = size
        self.inited: bool = False

        self.open_array: np.ndarray = np.zeros(size)
        self.high_array: np.ndarray = np.zeros(size)
        self.low_array: np.ndarray = np.zeros(size)
        self.close_array: np.ndarray = np.zeros(size)
        self.volume_array: np.ndarray = np.zeros(size)
        self.turnover_array: np.ndarray = np.zeros(size)
        self.open_interest_array: np.ndarray = np.zeros(size)

    def update_bar(self, bar: BarData) -> None:
        """把一根新 K 线写入窗口：数组左移，最新值放到末尾。"""
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.open_array[:-1] = self.open_array[1:]
        self.high_array[:-1] = self.high_array[1:]
        self.low_array[:-1] = self.low_array[1:]
        self.close_array[:-1] = self.close_array[1:]
        self.volume_array[:-1] = self.volume_array[1:]
        self.turnover_array[:-1] = self.turnover_array[1:]
        self.open_interest_array[:-1] = self.open_interest_array[1:]

        self.open_array[-1] = bar.open_price
        self.high_array[-1] = bar.high_price
        self.low_array[-1] = bar.low_price
        self.close_array[-1] = bar.close_price
        self.volume_array[-1] = bar.volume
        self.turnover_array[-1] = bar.turnover
        self.open_interest_array[-1] = bar.open_interest

    @property
    def open(self) -> np.ndarray:
        """开盘价序列（旧 → 新）。"""
        return self.open_array

    @property
    def high(self) -> np.ndarray:
        """最高价序列（旧 → 新）。"""
        return self.high_array

    @property
    def low(self) -> np.ndarray:
        """最低价序列（旧 → 新）。"""
        return self.low_array

    @property
    def close(self) -> np.ndarray:
        """收盘价序列（旧 → 新）。"""
        return self.close_array

    @property
    def volume(self) -> np.ndarray:
        """成交量序列（旧 → 新）。"""
        return self.volume_array

    @property
    def turnover(self) -> np.ndarray:
        """成交额序列（旧 → 新）。"""
        return self.turnover_array

    @property
    def open_interest(self) -> np.ndarray:
        """持仓量序列（旧 → 新）。"""
        return self.open_interest_array

    # ------------------------------------------------------------------
    # 单值辅助：低层实现保持「薄封装 TA-Lib」的形态，便于逐项对照。
    # ------------------------------------------------------------------

    @overload
    def sma(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def sma(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def sma(self, n: int, array: bool = False) -> float | np.ndarray:
        """简单移动平均（SMA）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.SMA(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def ema(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def ema(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def ema(self, n: int, array: bool = False) -> float | np.ndarray:
        """指数移动平均（EMA）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.EMA(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def kama(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def kama(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def kama(self, n: int, array: bool = False) -> float | np.ndarray:
        """考夫曼自适应移动平均（KAMA）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.KAMA(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def wma(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def wma(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def wma(self, n: int, array: bool = False) -> float | np.ndarray:
        """加权移动平均（WMA）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.WMA(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def apo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: Literal[False] = False,
    ) -> float: ...

    @overload
    def apo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        *,
        array: Literal[True],
    ) -> np.ndarray: ...

    def apo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False,
    ) -> float | np.ndarray:
        """绝对价格振荡器（APO）：快慢移动平均之差。"""
        _check_period(fast_period, "fast_period")
        _check_period(slow_period, "slow_period")
        _check_matype(matype)
        result_array: np.ndarray = talib.APO(
            self.close, fast_period, slow_period, _ta_matype(matype)
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def cmo(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def cmo(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def cmo(self, n: int, array: bool = False) -> float | np.ndarray:
        """钱德动量振荡器（CMO）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.CMO(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def mom(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def mom(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def mom(self, n: int, array: bool = False) -> float | np.ndarray:
        """动量（MOM）：当前收盘价与 N 周期前收盘价之差。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.MOM(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def ppo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: Literal[False] = False,
    ) -> float: ...

    @overload
    def ppo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        *,
        array: Literal[True],
    ) -> np.ndarray: ...

    def ppo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False,
    ) -> float | np.ndarray:
        """百分比价格振荡器（PPO）。"""
        _check_period(fast_period, "fast_period")
        _check_period(slow_period, "slow_period")
        _check_matype(matype)
        result_array: np.ndarray = talib.PPO(
            self.close, fast_period, slow_period, _ta_matype(matype)
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def roc(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def roc(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def roc(self, n: int, array: bool = False) -> float | np.ndarray:
        """变动率（ROC），以百分比表示。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ROC(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def rocr(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def rocr(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def rocr(self, n: int, array: bool = False) -> float | np.ndarray:
        """变动率比率（ROCR）：当前价 / N 周期前价。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ROCR(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def rocp(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def rocp(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def rocp(self, n: int, array: bool = False) -> float | np.ndarray:
        """变动率百分比（ROCP）：(当前价 - N 周期前价) / N 周期前价。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ROCP(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def rocr_100(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def rocr_100(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def rocr_100(self, n: int, array: bool = False) -> float | np.ndarray:
        """变动率比率 ×100（ROCR100）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ROCR100(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def trix(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def trix(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def trix(self, n: int, array: bool = False) -> float | np.ndarray:
        """三重指数平滑平均线（TRIX）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.TRIX(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def std(self, n: int, nbdev: float = 1, array: Literal[False] = False) -> float: ...

    @overload
    def std(self, n: int, nbdev: float = 1, *, array: Literal[True]) -> np.ndarray: ...

    def std(self, n: int, nbdev: float = 1, array: bool = False) -> float | np.ndarray:
        """标准差（STDDEV），``nbdev`` 为倍数。"""
        _check_period(n, "n")
        _check_positive(nbdev, "nbdev")
        result_array: np.ndarray = talib.STDDEV(self.close, n, nbdev)
        if array:
            return result_array
        return float(result_array[-1])

    # ------------------------------------------------------------------
    # 量价指标
    # ------------------------------------------------------------------

    @overload
    def obv(self, array: Literal[False] = False) -> float: ...

    @overload
    def obv(self, array: Literal[True]) -> np.ndarray: ...

    def obv(self, array: bool = False) -> float | np.ndarray:
        """能量潮（OBV）。"""
        result_array: np.ndarray = talib.OBV(self.close, self.volume)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def cci(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def cci(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def cci(self, n: int, array: bool = False) -> float | np.ndarray:
        """顺势指标（CCI）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def atr(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def atr(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def atr(self, n: int, array: bool = False) -> float | np.ndarray:
        """平均真实波幅（ATR）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ATR(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def natr(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def natr(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def natr(self, n: int, array: bool = False) -> float | np.ndarray:
        """归一化平均真实波幅（NATR），以百分比表示。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.NATR(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def rsi(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def rsi(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def rsi(self, n: int, array: bool = False) -> float | np.ndarray:
        """相对强弱指标（RSI）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.RSI(self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    # ------------------------------------------------------------------
    # 多值指标
    # ------------------------------------------------------------------

    @overload
    def macd(
        self,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        array: Literal[False] = False,
    ) -> tuple[float, float, float]: ...

    @overload
    def macd(
        self,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        array: Literal[True],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...

    def macd(
        self,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        array: bool = False,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[float, float, float]:
        """MACD：返回 (DIF, DEA, 柱状值)。"""
        _check_period(fast_period, "fast_period")
        _check_period(slow_period, "slow_period")
        _check_period(signal_period, "signal_period")
        macd: np.ndarray
        signal: np.ndarray
        hist: np.ndarray
        macd, signal, hist = talib.MACD(
            self.close, fast_period, slow_period, signal_period
        )
        if array:
            return macd, signal, hist
        return float(macd[-1]), float(signal[-1]), float(hist[-1])

    # ------------------------------------------------------------------
    # 趋势 / 方向指标
    # ------------------------------------------------------------------

    @overload
    def adx(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def adx(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def adx(self, n: int, array: bool = False) -> float | np.ndarray:
        """平均趋向指数（ADX）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def adxr(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def adxr(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def adxr(self, n: int, array: bool = False) -> float | np.ndarray:
        """平均趋向指数评级（ADXR）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.ADXR(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def dx(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def dx(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def dx(self, n: int, array: bool = False) -> float | np.ndarray:
        """趋向指数（DX）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.DX(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def minus_di(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def minus_di(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def minus_di(self, n: int, array: bool = False) -> float | np.ndarray:
        """负向指标（-DI）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.MINUS_DI(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def plus_di(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def plus_di(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def plus_di(self, n: int, array: bool = False) -> float | np.ndarray:
        """正向指标（+DI）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.PLUS_DI(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def willr(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def willr(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def willr(self, n: int, array: bool = False) -> float | np.ndarray:
        """威廉指标（WILLR）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.WILLR(self.high, self.low, self.close, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def ultosc(
        self,
        time_period1: int = 7,
        time_period2: int = 14,
        time_period3: int = 28,
        array: Literal[False] = False,
    ) -> float: ...

    @overload
    def ultosc(
        self,
        time_period1: int = 7,
        time_period2: int = 14,
        time_period3: int = 28,
        *,
        array: Literal[True],
    ) -> np.ndarray: ...

    def ultosc(
        self,
        time_period1: int = 7,
        time_period2: int = 14,
        time_period3: int = 28,
        array: bool = False,
    ) -> float | np.ndarray:
        """终极振荡器（ULTOSC）。"""
        _check_period(time_period1, "time_period1")
        _check_period(time_period2, "time_period2")
        _check_period(time_period3, "time_period3")
        result_array: np.ndarray = talib.ULTOSC(
            self.high,
            self.low,
            self.close,
            time_period1,
            time_period2,
            time_period3,
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def trange(self, array: Literal[False] = False) -> float: ...

    @overload
    def trange(self, array: Literal[True]) -> np.ndarray: ...

    def trange(self, array: bool = False) -> float | np.ndarray:
        """真实波幅（TRANGE）。"""
        result_array: np.ndarray = talib.TRANGE(self.high, self.low, self.close)
        if array:
            return result_array
        return float(result_array[-1])

    # ------------------------------------------------------------------
    # 通道指标
    # ------------------------------------------------------------------

    @overload
    def boll(
        self, n: int, dev: float, array: Literal[False] = False
    ) -> tuple[float, float]: ...

    @overload
    def boll(
        self, n: int, dev: float, array: Literal[True]
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def boll(
        self,
        n: int,
        dev: float,
        array: bool = False,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """布林通道：返回 (上轨, 下轨)。"""
        _check_period(n, "n")
        _check_positive(dev, "dev")
        mid_array: np.ndarray = talib.SMA(self.close, n)
        std_array: np.ndarray = talib.STDDEV(self.close, n, 1)

        if array:
            up_array: np.ndarray = mid_array + std_array * dev
            down_array: np.ndarray = mid_array - std_array * dev
            return up_array, down_array
        mid: float = float(mid_array[-1])
        std: float = float(std_array[-1])
        return mid + std * dev, mid - std * dev

    @overload
    def keltner(
        self, n: int, dev: float, array: Literal[False] = False
    ) -> tuple[float, float]: ...

    @overload
    def keltner(
        self, n: int, dev: float, array: Literal[True]
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def keltner(
        self,
        n: int,
        dev: float,
        array: bool = False,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """肯特纳通道：返回 (上轨, 下轨)。"""
        _check_period(n, "n")
        _check_positive(dev, "dev")
        mid_array: np.ndarray = talib.SMA(self.close, n)
        atr_array: np.ndarray = talib.ATR(self.high, self.low, self.close, n)

        if array:
            up_array: np.ndarray = mid_array + atr_array * dev
            down_array: np.ndarray = mid_array - atr_array * dev
            return up_array, down_array
        mid: float = float(mid_array[-1])
        atr: float = float(atr_array[-1])
        return mid + atr * dev, mid - atr * dev

    @overload
    def donchian(
        self, n: int, array: Literal[False] = False
    ) -> tuple[float, float]: ...

    @overload
    def donchian(
        self, n: int, array: Literal[True]
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def donchian(
        self, n: int, array: bool = False
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """唐奇安通道：返回 (上轨 = N 周期最高价, 下轨 = N 周期最低价)。"""
        _check_period(n, "n")
        up: np.ndarray = talib.MAX(self.high, n)
        down: np.ndarray = talib.MIN(self.low, n)

        if array:
            return up, down
        return float(up[-1]), float(down[-1])

    # ------------------------------------------------------------------
    # 区间 / 动量指标
    # ------------------------------------------------------------------

    @overload
    def aroon(
        self, n: int, array: Literal[False] = False
    ) -> tuple[float, float]: ...

    @overload
    def aroon(
        self, n: int, array: Literal[True]
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def aroon(
        self,
        n: int,
        array: bool = False,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """阿隆指标：返回 (Aroon Up, Aroon Down)。"""
        _check_period(n, "n")
        aroon_down: np.ndarray
        aroon_up: np.ndarray
        aroon_down, aroon_up = talib.AROON(self.high, self.low, n)

        if array:
            return aroon_up, aroon_down
        return float(aroon_up[-1]), float(aroon_down[-1])

    @overload
    def aroonosc(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def aroonosc(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def aroonosc(self, n: int, array: bool = False) -> float | np.ndarray:
        """阿隆振荡器（AROONOSC）= Aroon Up - Aroon Down。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.AROONOSC(self.high, self.low, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def minus_dm(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def minus_dm(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def minus_dm(self, n: int, array: bool = False) -> float | np.ndarray:
        """负向动向（-DM）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.MINUS_DM(self.high, self.low, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def plus_dm(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def plus_dm(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def plus_dm(self, n: int, array: bool = False) -> float | np.ndarray:
        """正向动向（+DM）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.PLUS_DM(self.high, self.low, n)
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def mfi(self, n: int, array: Literal[False] = False) -> float: ...

    @overload
    def mfi(self, n: int, array: Literal[True]) -> np.ndarray: ...

    def mfi(self, n: int, array: bool = False) -> float | np.ndarray:
        """资金流量指标（MFI）。"""
        _check_period(n, "n")
        result_array: np.ndarray = talib.MFI(
            self.high, self.low, self.close, self.volume, n
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def ad(self, array: Literal[False] = False) -> float: ...

    @overload
    def ad(self, array: Literal[True]) -> np.ndarray: ...

    def ad(self, array: bool = False) -> float | np.ndarray:
        """累积 / 派发线（AD）。"""
        result_array: np.ndarray = talib.AD(
            self.high, self.low, self.close, self.volume
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def adosc(
        self, fast_period: int, slow_period: int, array: Literal[False] = False
    ) -> float: ...

    @overload
    def adosc(
        self, fast_period: int, slow_period: int, array: Literal[True]
    ) -> np.ndarray: ...

    def adosc(
        self,
        fast_period: int,
        slow_period: int,
        array: bool = False,
    ) -> float | np.ndarray:
        """累积 / 派发振荡器（ADOSC）。"""
        _check_period(fast_period, "fast_period")
        _check_period(slow_period, "slow_period")
        result_array: np.ndarray = talib.ADOSC(
            self.high, self.low, self.close, self.volume, fast_period, slow_period
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def bop(self, array: Literal[False] = False) -> float: ...

    @overload
    def bop(self, array: Literal[True]) -> np.ndarray: ...

    def bop(self, array: bool = False) -> float | np.ndarray:
        """均势指标（BOP）。"""
        result_array: np.ndarray = talib.BOP(
            self.open, self.high, self.low, self.close
        )
        if array:
            return result_array
        return float(result_array[-1])

    @overload
    def stoch(
        self,
        fastk_period: int,
        slowk_period: int,
        slowk_matype: int,
        slowd_period: int,
        slowd_matype: int,
        array: Literal[False] = False,
    ) -> tuple[float, float]: ...

    @overload
    def stoch(
        self,
        fastk_period: int,
        slowk_period: int,
        slowk_matype: int,
        slowd_period: int,
        slowd_matype: int,
        array: Literal[True],
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def stoch(
        self,
        fastk_period: int,
        slowk_period: int,
        slowk_matype: int,
        slowd_period: int,
        slowd_matype: int,
        array: bool = False,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """随机指标（STOCH）：返回 (K, D)。"""
        _check_period(fastk_period, "fastk_period")
        _check_period(slowk_period, "slowk_period")
        _check_matype(slowk_matype, "slowk_matype")
        _check_period(slowd_period, "slowd_period")
        _check_matype(slowd_matype, "slowd_matype")
        k: np.ndarray
        d: np.ndarray
        k, d = talib.STOCH(
            self.high,
            self.low,
            self.close,
            fastk_period,
            slowk_period,
            _ta_matype(slowk_matype),
            slowd_period,
            _ta_matype(slowd_matype),
        )
        if array:
            return k, d
        return float(k[-1]), float(d[-1])

    @overload
    def sar(
        self, acceleration: float, maximum: float, array: Literal[False] = False
    ) -> float: ...

    @overload
    def sar(
        self, acceleration: float, maximum: float, array: Literal[True]
    ) -> np.ndarray: ...

    def sar(
        self,
        acceleration: float,
        maximum: float,
        array: bool = False,
    ) -> float | np.ndarray:
        """抛物线转向指标（SAR）。"""
        _check_positive(acceleration, "acceleration")
        _check_positive(maximum, "maximum")
        result_array: np.ndarray = talib.SAR(self.high, self.low, acceleration, maximum)
        if array:
            return result_array
        return float(result_array[-1])
