"""``vnpy/trader/utility.py`` 的价格取整工具 → ``app/domain/pricing.py`` 迁移测试。

重点验证：

- 按最小变动价位四舍五入 / 向下 / 向上取整，沿用原版的 half-even 语义；
- 用 ``Decimal(str(...))`` 计算，避免二进制浮点误差；
- 非法目标值与非有限数值给出明确 ``ValueError``；
- ``get_digits`` 按十进制指数计算小数位（含科学计数法），且只用于展示。
"""

from __future__ import annotations

import pytest

from app.domain.pricing import ceil_to, floor_to, get_digits, round_to


def test_round_to_price_tick() -> None:
    assert round_to(123.456, 0.01) == 123.46
    assert round_to(123.454, 0.01) == 123.45
    assert round_to(100.15, 0.1) == 100.2
    assert round_to(3500, 1) == 3500


def test_round_to_uses_half_even_like_python_round() -> None:
    # 原版用 Python round，属于 half-even（银行家舍入），这里保持不变
    assert round_to(2.5, 1) == 2.0
    assert round_to(3.5, 1) == 4.0


def test_round_to_avoids_binary_float_drift() -> None:
    assert round_to(0.1 + 0.2, 0.01) == 0.3
    assert round_to(1.1, 0.1) == 1.1
    assert round_to(0.30000000000000004, 0.0001) == 0.3


def test_floor_and_ceil_to_price_tick() -> None:
    assert floor_to(123.459, 0.01) == 123.45
    assert floor_to(123.456, 1) == 123
    assert ceil_to(123.451, 0.01) == 123.46
    assert ceil_to(123.456, 1) == 124


def test_floor_and_ceil_toward_negative_infinity_and_positive_infinity() -> None:
    assert floor_to(-1.234, 0.01) == -1.24
    assert ceil_to(-1.234, 0.01) == -1.23


def test_round_to_rejects_non_positive_target() -> None:
    for target in (0, -0.01):
        with pytest.raises(ValueError, match="target 必须为正数"):
            round_to(100, target)


def test_round_to_rejects_non_finite_values() -> None:
    nan = float("nan")
    inf = float("inf")

    with pytest.raises(ValueError, match="有限数值"):
        round_to(nan, 0.01)
    with pytest.raises(ValueError, match="有限数值"):
        round_to(inf, 0.01)
    with pytest.raises(ValueError, match="有限数值"):
        round_to(100, inf)


def test_get_digits_counts_decimal_places() -> None:
    assert get_digits(0.01) == 2
    assert get_digits(0.001) == 3
    assert get_digits(0.0001) == 4
    assert get_digits(1.234567) == 6


def test_get_digits_handles_scientific_notation() -> None:
    assert get_digits(1e-05) == 5
    # 原版按字符串切分会把 1.5e-05 算成 5 位，这里按十进制指数得到 6 位
    assert get_digits(1.5e-05) == 6


def test_get_digits_handles_integers_and_trailing_zero() -> None:
    assert get_digits(0) == 0
    assert get_digits(100) == 0
    assert get_digits(100.0) == 1
    assert get_digits(-0.5) == 1


def test_get_digits_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="有限数值"):
        get_digits(float("nan"))
    with pytest.raises(ValueError, match="有限数值"):
        get_digits(float("inf"))
