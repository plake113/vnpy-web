"""``vnpy/trader/utility.py`` 的 ``ArrayManager`` → ``app/domain/indicators.py`` 迁移测试。

重点验证：

- 窗口语义：定长滚动、左移、预热期零填充、``inited`` / ``count`` 推进；
- 双返回语义：``array=True`` 返回与窗口等长的序列，``array=False`` 返回 Python ``float``
  且等于序列末值；
- 指标接线：41 个方法把正确的 OHLCV 数组与参数交给 TA-Lib（含多值指标的返回顺序）；
- 参数校验：周期、移动平均类型、通道倍数与窗口大小在调用 TA-Lib 前报错；
- 少量手算用例（SMA / EMA / BOLL）作为不依赖 TA-Lib 的独立对照。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pytest
import talib

from app.domain.enums import Exchange, Interval
from app.domain.indicators import ArrayManager
from app.domain.market import BarData


def make_bar(
    index: int,
    *,
    open_price: float | None = None,
    high_price: float | None = None,
    low_price: float | None = None,
    close_price: float | None = None,
    volume: float | None = None,
    turnover: float | None = None,
    open_interest: float | None = None,
) -> BarData:
    """构造第 ``index`` 根 K 线；默认值为可控的线性序列，便于手算。"""
    open_value = float(index) if open_price is None else open_price
    close_value = open_value + 0.5 if close_price is None else close_price
    return BarData(
        gateway_name="FAKE",
        symbol="rb2410",
        exchange=Exchange.SHFE,
        datetime=datetime(2024, 1, 2, 9, index % 60),
        interval=Interval.MINUTE,
        open_price=open_value,
        high_price=(max(open_value, close_value) + 1.0 if high_price is None else high_price),
        low_price=(min(open_value, close_value) - 1.0 if low_price is None else low_price),
        close_price=close_value,
        volume=float(10 * index) if volume is None else volume,
        turnover=float(100 * index) if turnover is None else turnover,
        open_interest=float(1000 + index) if open_interest is None else open_interest,
    )


def build_am(size: int = 100, bar_count: int | None = None) -> ArrayManager:
    """用固定种子的随机游走填满窗口，保证 OHLC 关系合理。"""
    count = size if bar_count is None else bar_count
    am = ArrayManager(size)
    rng = np.random.default_rng(20240102)
    price = 100.0
    for i in range(count):
        open_price = price
        price += float(rng.normal(0, 1))
        am.update_bar(
            BarData(
                gateway_name="FAKE",
                symbol="rb2410",
                exchange=Exchange.SHFE,
                datetime=datetime(2024, 1, 2, 9, i % 60),
                interval=Interval.MINUTE,
                open_price=open_price,
                high_price=max(open_price, price) + float(rng.uniform(0.5, 2.0)),
                low_price=min(open_price, price) - float(rng.uniform(0.5, 2.0)),
                close_price=price,
                volume=float(100 + i) + float(rng.uniform(0.0, 10.0)),
                turnover=float((100 + i) * price),
                open_interest=float(500 + i),
            )
        )
    return am


@pytest.fixture
def am() -> ArrayManager:
    return build_am()


# ----------------------------------------------------------------------
# 窗口语义
# ----------------------------------------------------------------------


def test_update_bar_rolls_window_and_inits() -> None:
    am = ArrayManager(size=3)
    assert (am.size, am.count, am.inited) == (3, 0, False)
    assert np.array_equal(am.close, np.zeros(3))

    am.update_bar(make_bar(1))
    am.update_bar(make_bar(2))
    assert (am.count, am.inited) == (2, False)
    np.testing.assert_allclose(am.open, [0.0, 1.0, 2.0])
    np.testing.assert_allclose(am.close, [0.0, 1.5, 2.5])
    np.testing.assert_allclose(am.high, [0.0, 2.5, 3.5])
    np.testing.assert_allclose(am.low, [0.0, 0.0, 1.0])
    np.testing.assert_allclose(am.volume, [0.0, 10.0, 20.0])
    np.testing.assert_allclose(am.turnover, [0.0, 100.0, 200.0])
    np.testing.assert_allclose(am.open_interest, [0.0, 1001.0, 1002.0])

    am.update_bar(make_bar(3))
    assert (am.count, am.inited) == (3, True)
    np.testing.assert_allclose(am.open, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(am.close, [1.5, 2.5, 3.5])
    np.testing.assert_allclose(am.high, [2.5, 3.5, 4.5])
    np.testing.assert_allclose(am.low, [0.0, 1.0, 2.0])


def test_properties_are_views_of_internal_arrays() -> None:
    am = ArrayManager(size=2)
    assert am.open is am.open_array
    assert am.high is am.high_array
    assert am.low is am.low_array
    assert am.close is am.close_array
    assert am.volume is am.volume_array
    assert am.turnover is am.turnover_array
    assert am.open_interest is am.open_interest_array


@pytest.mark.parametrize("size", [0, -1])
def test_size_must_be_positive(size: int) -> None:
    with pytest.raises(ValueError):
        ArrayManager(size)


@pytest.mark.parametrize("size", [3.0, True, "3"])
def test_size_must_be_int(size: Any) -> None:
    with pytest.raises(TypeError):
        ArrayManager(size)


# ----------------------------------------------------------------------
# 双返回语义
# ----------------------------------------------------------------------


SINGLE_OUTPUT_CALLS = [
    ("sma", (12,)),
    ("ema", (12,)),
    ("kama", (12,)),
    ("wma", (12,)),
    ("apo", (12, 26, 0)),
    ("cmo", (14,)),
    ("mom", (10,)),
    ("ppo", (12, 26, 0)),
    ("roc", (10,)),
    ("rocr", (10,)),
    ("rocp", (10,)),
    ("rocr_100", (10,)),
    ("trix", (12,)),
    ("std", (12, 2)),
    ("obv", ()),
    ("cci", (14,)),
    ("atr", (14,)),
    ("natr", (14,)),
    ("rsi", (14,)),
    ("adx", (14,)),
    ("adxr", (14,)),
    ("dx", (14,)),
    ("minus_di", (14,)),
    ("plus_di", (14,)),
    ("willr", (14,)),
    ("ultosc", ()),
    ("trange", ()),
    ("aroonosc", (25,)),
    ("minus_dm", (14,)),
    ("plus_dm", (14,)),
    ("mfi", (14,)),
    ("ad", ()),
    ("adosc", (3, 10)),
    ("bop", ()),
    ("sar", (0.02, 0.2)),
]


@pytest.mark.parametrize(("name", "args"), SINGLE_OUTPUT_CALLS)
def test_array_switch_returns_series_and_last_value(
    am: ArrayManager, name: str, args: tuple[Any, ...]
) -> None:
    method = getattr(am, name)
    series = method(*args, array=True)
    value = method(*args)

    assert isinstance(series, np.ndarray)
    assert series.shape == (am.size,)
    assert isinstance(value, float)
    np.testing.assert_allclose(value, series[-1], equal_nan=True)


MULTI_OUTPUT_CALLS = [
    ("macd", (12, 26, 9)),
    ("boll", (20, 2)),
    ("keltner", (20, 2)),
    ("donchian", (20,)),
    ("aroon", (25,)),
    ("stoch", (9, 3, 0, 3, 0)),
]


@pytest.mark.parametrize(("name", "args"), MULTI_OUTPUT_CALLS)
def test_multi_output_array_switch(
    am: ArrayManager, name: str, args: tuple[Any, ...]
) -> None:
    method = getattr(am, name)
    series = method(*args, array=True)
    values = method(*args)

    assert isinstance(series, tuple)
    assert isinstance(values, tuple)
    assert len(series) == len(values)
    for array_item, scalar_item in zip(series, values, strict=True):
        assert isinstance(array_item, np.ndarray)
        assert array_item.shape == (am.size,)
        assert isinstance(scalar_item, float)
        np.testing.assert_allclose(scalar_item, array_item[-1], equal_nan=True)


# ----------------------------------------------------------------------
# 指标接线：与 TA-Lib 直接调用逐一对照
# ----------------------------------------------------------------------


def _talib(
    name: str,
    *args: Any,
) -> np.ndarray:
    """调用 TA-Lib 函数，集中处理未类型化的第三方返回值。"""
    result: np.ndarray = getattr(talib, name)(*args)
    return result


WIRING_CASES = [
    pytest.param("sma", (12,), lambda op, hi, lo, cl, vol: _talib("SMA", cl, 12), id="sma"),
    pytest.param("ema", (12,), lambda op, hi, lo, cl, vol: _talib("EMA", cl, 12), id="ema"),
    pytest.param("kama", (12,), lambda op, hi, lo, cl, vol: _talib("KAMA", cl, 12), id="kama"),
    pytest.param("wma", (12,), lambda op, hi, lo, cl, vol: _talib("WMA", cl, 12), id="wma"),
    pytest.param(
        "apo", (12, 26, 1), lambda op, hi, lo, cl, vol: _talib("APO", cl, 12, 26, 1), id="apo"
    ),
    pytest.param("cmo", (14,), lambda op, hi, lo, cl, vol: _talib("CMO", cl, 14), id="cmo"),
    pytest.param("mom", (10,), lambda op, hi, lo, cl, vol: _talib("MOM", cl, 10), id="mom"),
    pytest.param(
        "ppo", (12, 26, 2), lambda op, hi, lo, cl, vol: _talib("PPO", cl, 12, 26, 2), id="ppo"
    ),
    pytest.param("roc", (10,), lambda op, hi, lo, cl, vol: _talib("ROC", cl, 10), id="roc"),
    pytest.param("rocr", (10,), lambda op, hi, lo, cl, vol: _talib("ROCR", cl, 10), id="rocr"),
    pytest.param("rocp", (10,), lambda op, hi, lo, cl, vol: _talib("ROCP", cl, 10), id="rocp"),
    pytest.param(
        "rocr_100", (10,), lambda op, hi, lo, cl, vol: _talib("ROCR100", cl, 10), id="rocr100"
    ),
    pytest.param("trix", (12,), lambda op, hi, lo, cl, vol: _talib("TRIX", cl, 12), id="trix"),
    pytest.param(
        "std", (12, 2), lambda op, hi, lo, cl, vol: _talib("STDDEV", cl, 12, 2), id="std"
    ),
    pytest.param("obv", (), lambda op, hi, lo, cl, vol: _talib("OBV", cl, vol), id="obv"),
    pytest.param("cci", (14,), lambda op, hi, lo, cl, vol: _talib("CCI", hi, lo, cl, 14), id="cci"),
    pytest.param("atr", (14,), lambda op, hi, lo, cl, vol: _talib("ATR", hi, lo, cl, 14), id="atr"),
    pytest.param(
        "natr", (14,), lambda op, hi, lo, cl, vol: _talib("NATR", hi, lo, cl, 14), id="natr"
    ),
    pytest.param("rsi", (14,), lambda op, hi, lo, cl, vol: _talib("RSI", cl, 14), id="rsi"),
    pytest.param("adx", (14,), lambda op, hi, lo, cl, vol: _talib("ADX", hi, lo, cl, 14), id="adx"),
    pytest.param(
        "adxr", (14,), lambda op, hi, lo, cl, vol: _talib("ADXR", hi, lo, cl, 14), id="adxr"
    ),
    pytest.param("dx", (14,), lambda op, hi, lo, cl, vol: _talib("DX", hi, lo, cl, 14), id="dx"),
    pytest.param(
        "minus_di",
        (14,),
        lambda op, hi, lo, cl, vol: _talib("MINUS_DI", hi, lo, cl, 14),
        id="minus_di",
    ),
    pytest.param(
        "plus_di",
        (14,),
        lambda op, hi, lo, cl, vol: _talib("PLUS_DI", hi, lo, cl, 14),
        id="plus_di",
    ),
    pytest.param(
        "willr", (14,), lambda op, hi, lo, cl, vol: _talib("WILLR", hi, lo, cl, 14), id="willr"
    ),
    pytest.param(
        "ultosc",
        (5, 10, 20),
        lambda op, hi, lo, cl, vol: _talib("ULTOSC", hi, lo, cl, 5, 10, 20),
        id="ultosc",
    ),
    pytest.param(
        "trange", (), lambda op, hi, lo, cl, vol: _talib("TRANGE", hi, lo, cl), id="trange"
    ),
    pytest.param(
        "aroonosc", (25,), lambda op, hi, lo, cl, vol: _talib("AROONOSC", hi, lo, 25), id="aroonosc"
    ),
    pytest.param(
        "minus_dm",
        (14,),
        lambda op, hi, lo, cl, vol: _talib("MINUS_DM", hi, lo, 14),
        id="minus_dm",
    ),
    pytest.param(
        "plus_dm", (14,), lambda op, hi, lo, cl, vol: _talib("PLUS_DM", hi, lo, 14), id="plus_dm"
    ),
    pytest.param(
        "mfi", (14,), lambda op, hi, lo, cl, vol: _talib("MFI", hi, lo, cl, vol, 14), id="mfi"
    ),
    pytest.param("ad", (), lambda op, hi, lo, cl, vol: _talib("AD", hi, lo, cl, vol), id="ad"),
    pytest.param(
        "adosc",
        (3, 10),
        lambda op, hi, lo, cl, vol: _talib("ADOSC", hi, lo, cl, vol, 3, 10),
        id="adosc",
    ),
    pytest.param(
        "bop", (), lambda op, hi, lo, cl, vol: _talib("BOP", op, hi, lo, cl), id="bop"
    ),
    pytest.param(
        "sar", (0.02, 0.2), lambda op, hi, lo, cl, vol: _talib("SAR", hi, lo, 0.02, 0.2), id="sar"
    ),
]


@pytest.mark.parametrize(("name", "args", "expected_call"), WIRING_CASES)
def test_single_output_wiring_matches_talib(
    am: ArrayManager,
    name: str,
    args: tuple[Any, ...],
    expected_call: Any,
) -> None:
    actual = getattr(am, name)(*args, array=True)
    expected = expected_call(am.open, am.high, am.low, am.close, am.volume)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12, equal_nan=True)


def test_macd_wiring_and_hist_identity(am: ArrayManager) -> None:
    dif, dea, hist = am.macd(12, 26, 9, array=True)
    expected_dif, expected_dea, expected_hist = talib.MACD(am.close, 12, 26, 9)
    np.testing.assert_allclose(dif, expected_dif, equal_nan=True)
    np.testing.assert_allclose(dea, expected_dea, equal_nan=True)
    np.testing.assert_allclose(hist, expected_hist, equal_nan=True)
    np.testing.assert_allclose(hist, dif - dea, equal_nan=True)


def test_boll_wiring(am: ArrayManager) -> None:
    up, down = am.boll(20, 2, array=True)
    mid = talib.SMA(am.close, 20)
    std = talib.STDDEV(am.close, 20, 1)
    np.testing.assert_allclose(up, mid + std * 2, equal_nan=True)
    np.testing.assert_allclose(down, mid - std * 2, equal_nan=True)


def test_keltner_wiring(am: ArrayManager) -> None:
    up, down = am.keltner(20, 2, array=True)
    mid = talib.SMA(am.close, 20)
    atr = talib.ATR(am.high, am.low, am.close, 20)
    np.testing.assert_allclose(up, mid + atr * 2, equal_nan=True)
    np.testing.assert_allclose(down, mid - atr * 2, equal_nan=True)


def test_donchian_wiring(am: ArrayManager) -> None:
    up, down = am.donchian(20, array=True)
    np.testing.assert_allclose(up, talib.MAX(am.high, 20), equal_nan=True)
    np.testing.assert_allclose(down, talib.MIN(am.low, 20), equal_nan=True)


def test_aroon_returns_up_then_down(am: ArrayManager) -> None:
    up, down = am.aroon(25, array=True)
    expected_down, expected_up = talib.AROON(am.high, am.low, 25)
    np.testing.assert_allclose(up, expected_up, equal_nan=True)
    np.testing.assert_allclose(down, expected_down, equal_nan=True)


@pytest.mark.parametrize(
    ("slowk_matype", "slowd_matype"),
    [(0, 0), (1, 0), (0, 1)],
)
def test_stoch_wiring(am: ArrayManager, slowk_matype: int, slowd_matype: int) -> None:
    k, d = am.stoch(9, 3, slowk_matype, 3, slowd_matype, array=True)
    expected_k, expected_d = talib.STOCH(
        am.high, am.low, am.close, 9, 3, slowk_matype, 3, slowd_matype
    )
    np.testing.assert_allclose(k, expected_k, equal_nan=True)
    np.testing.assert_allclose(d, expected_d, equal_nan=True)


# ----------------------------------------------------------------------
# 手算对照（不依赖 TA-Lib 的独立断言）
# ----------------------------------------------------------------------


def test_sma_hand_computed() -> None:
    am = ArrayManager(size=5)
    for index in range(1, 6):
        am.update_bar(make_bar(index))

    # 收盘价 1.5 / 2.5 / 3.5 / 4.5 / 5.5
    result = am.sma(3, array=True)
    np.testing.assert_allclose(
        result, [math.nan, math.nan, 2.5, 3.5, 4.5], equal_nan=True
    )
    assert am.sma(3) == pytest.approx(4.5)
    assert np.isnan(result[:2]).all()


def test_ema_hand_computed() -> None:
    am = ArrayManager(size=5)
    for index in range(1, 6):
        am.update_bar(make_bar(index))

    # n=3：种子 EMA[2] = SMA(1.5, 2.5, 3.5) = 2.5，k = 0.5
    # EMA[3] = 2.5 + (4.5 - 2.5) * 0.5 = 3.5；EMA[4] = 3.5 + (5.5 - 3.5) * 0.5 = 4.5
    result = am.ema(3, array=True)
    np.testing.assert_allclose(
        result, [math.nan, math.nan, 2.5, 3.5, 4.5], equal_nan=True
    )


def test_boll_hand_computed() -> None:
    am = ArrayManager(size=3)
    for value in (1.0, 2.0, 3.0):
        am.update_bar(make_bar(1, open_price=value, close_price=value))
    am.close_array[:] = [1.0, 2.0, 3.0]

    up, down = am.boll(3, 2, array=True)
    std = math.sqrt(2.0 / 3.0)
    assert up[-1] == pytest.approx(2.0 + 2.0 * std)
    assert down[-1] == pytest.approx(2.0 - 2.0 * std)


# ----------------------------------------------------------------------
# 参数校验
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda am: am.sma(0),
        lambda am: am.ema(-1),
        lambda am: am.wma(0),
        lambda am: am.kama(-5),
        lambda am: am.mom(0),
        lambda am: am.atr(0),
        lambda am: am.rsi(-3),
        lambda am: am.adx(0),
        lambda am: am.mfi(0),
        lambda am: am.std(10, 0),
        lambda am: am.boll(20, 0),
        lambda am: am.keltner(20, -1),
        lambda am: am.sar(0, 0.2),
        lambda am: am.sar(0.02, 0),
    ],
)
def test_invalid_parameter_raises_value_error(call: Any) -> None:
    am = build_am()
    with pytest.raises(ValueError):
        call(am)


@pytest.mark.parametrize(
    "call",
    [
        lambda am: am.sma(2.5),
        lambda am: am.apo(12, 26, 9),
        lambda am: am.ppo(12, 26, -1),
        lambda am: am.stoch(9, 3, 9, 3, 0),
        lambda am: am.stoch(9, 3, 0, 3, 9),
        lambda am: am.std(10, "2"),
    ],
)
def test_invalid_parameter_raises_type_or_value_error(call: Any) -> None:
    am = build_am()
    with pytest.raises((TypeError, ValueError)):
        call(am)


def test_numpy_scalar_parameters_accepted() -> None:
    am = build_am()
    assert am.sma(np.int64(10), array=True).shape == (am.size,)
    up, down = am.boll(np.int64(20), np.float64(2.0), array=True)
    assert up.shape == down.shape == (am.size,)
    numpy_sized = ArrayManager(np.int64(50))
    assert numpy_sized.size == 50
    assert isinstance(numpy_sized.size, int)


def test_warmup_values_are_nan(am: ArrayManager) -> None:
    sma = am.sma(10, array=True)
    assert np.isnan(sma[:9]).all()
    assert not np.isnan(sma[9:]).any()

    # TA-Lib 的 TRANGE 与 ATR 预热期分别是 1 与 14 根
    assert np.isnan(am.trange(array=True)[:1]).all()
    assert np.isnan(am.atr(14, array=True)[:14]).all()
    assert not np.isnan(am.atr(14, array=True)[14:]).any()
