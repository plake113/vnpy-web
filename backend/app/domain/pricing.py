"""价格取整与精度工具：按最小变动价位对齐、计算小数位数。

来源：vnpy 4.5.0 ``vnpy/trader/utility.py`` 的 ``round_to`` / ``floor_to`` / ``ceil_to`` /
``get_digits``（MIT License，© Xiaoyou Chen）。

与桌面版的差异：

- 保留原版 ``Decimal(str(value))`` 的做法：先把浮点转成十进制字面量再运算，
  避免 ``0.1 + 0.2`` 这类二进制误差在价格上放大；
- 补输入校验：目标值必须为正、输入必须是有限数值，否则抛 ``ValueError``
  （原版分别表现为 ``ZeroDivisionError`` 或 ``decimal.InvalidOperation``）；
- ``get_digits`` 改为按 ``Decimal`` 的指数计算小数位，修正原版按字符串切分时
  ``1.5e-05`` 只算 5 位的问题（正确是 6 位）。

这些函数属于**价格领域规则**（``target`` 通常是合约的 ``pricetick``），因此放在
``domain`` 而不是 ``utils``；``get_digits`` 只服务展示与精度校验，不参与委托价格计算。
"""

from __future__ import annotations

from decimal import Decimal
from math import ceil, floor, isfinite

__all__ = [
    "ceil_to",
    "floor_to",
    "get_digits",
    "round_to",
]


def _to_decimal(value: float, name: str) -> Decimal:
    """把有限浮点数按其十进制字面量转成 ``Decimal``。"""
    if not isfinite(value):
        raise ValueError(f"{name} 必须是有限数值：{value!r}")

    return Decimal(str(value))


def _target_decimal(target: float) -> Decimal:
    """校验并返回最小变动价位。"""
    decimal_target = _to_decimal(target, "target")
    if decimal_target <= 0:
        raise ValueError(f"target 必须为正数：{target!r}")

    return decimal_target


def round_to(value: float, target: float) -> float:
    """按最小变动价位四舍五入，返回浮点价格。

    沿用原版语义：Python ``round`` 的**银行家舍入**（half-even），例如
    ``round_to(2.5, 1) == 2.0``、``round_to(3.5, 1) == 4.0``。
    需要向下 / 向上取整时用 :func:`floor_to` / :func:`ceil_to`。

    :param value: 原始价格
    :param target: 最小变动价位，必须为正
    :raises ValueError: 输入不是有限数值，或 ``target`` 不为正
    """
    decimal_value = _to_decimal(value, "value")
    decimal_target = _target_decimal(target)

    return float(int(round(decimal_value / decimal_target)) * decimal_target)


def floor_to(value: float, target: float) -> float:
    """按最小变动价位向下取整（向负无穷方向）。

    :raises ValueError: 输入不是有限数值，或 ``target`` 不为正
    """
    decimal_value = _to_decimal(value, "value")
    decimal_target = _target_decimal(target)

    return float(int(floor(decimal_value / decimal_target)) * decimal_target)


def ceil_to(value: float, target: float) -> float:
    """按最小变动价位向上取整（向正无穷方向）。

    :raises ValueError: 输入不是有限数值，或 ``target`` 不为正
    """
    decimal_value = _to_decimal(value, "value")
    decimal_target = _target_decimal(target)

    return float(int(ceil(decimal_value / decimal_target)) * decimal_target)


def get_digits(value: float) -> int:
    """返回数值的十进制小数位数，例如 ``0.01 → 2``、``1.5e-05 → 6``。

    只用于展示（如前端 ``price_digits``）与精度校验，**不参与交易判断**；
    负数按绝对值计算，``1.0`` 这类带尾随零的表示返回 1。

    :raises ValueError: 不是有限数值
    """
    decimal_value = _to_decimal(abs(value), "value")
    exponent = int(decimal_value.as_tuple().exponent)

    return max(0, -exponent)
