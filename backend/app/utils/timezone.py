"""时区转换：仓储层统一的 UTC 边界。

来源：vnpy 4.5.0 ``vnpy/trader/database.py`` 的 ``convert_tz``（MIT License，© Xiaoyou Chen）。
原实现依赖全局 ``SETTINGS["database.timezone"]``，把时间统一转到数据库时区；
Web 版改为统一 UTC 存储，转换规则收在本模块：

- 写库：``to_utc_naive`` 只接受 aware 时间，转成 UTC naive（SQLite / PostgreSQL 通用）；
- 读库：``from_utc`` 把 naive 视为 UTC，aware 统一归一到 UTC。

naive 输入直接拒绝，避免“有时存本地时间、有时存 UTC”的脏数据；由网关入口 / 数据服务
在调用仓储前完成交易所时区 → UTC 的转换。
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["from_utc", "to_utc_naive"]


def to_utc_naive(value: datetime) -> datetime:
    """把 aware 时间转成 UTC naive。

    :raises ValueError: 时间是 naive（缺少时区）
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("仓储只接受带时区的 datetime（UTC aware）")

    return value.astimezone(UTC).replace(tzinfo=None)


def from_utc(value: datetime) -> datetime:
    """把数据库中的 UTC naive 时间补回 UTC；已带时区的先归一到 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)
