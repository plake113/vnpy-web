"""``vnpy/trader/constant.py`` → ``app/domain/enums.py`` 的迁移测试。

重点验证：

- 枚举成员与原 vnpy 一致（名称、顺序、数量）；
- 机器码为英文（API / DB 使用），中文展示名保留在 ``label``；
- Exchange / Currency / Interval 的取值不变（影响 vt_symbol 等标识）；
- StrEnum 可直接 JSON 序列化。
"""

from __future__ import annotations

import json

from app.domain.enums import (
    Currency,
    Direction,
    Exchange,
    Interval,
    Offset,
    OptionType,
    OrderType,
    Product,
    Status,
)


def test_enum_members_match_vnpy() -> None:
    assert [member.name for member in Direction] == ["LONG", "SHORT", "NET"]
    assert [member.name for member in Offset] == [
        "NONE",
        "OPEN",
        "CLOSE",
        "CLOSETODAY",
        "CLOSEYESTERDAY",
    ]
    assert [member.name for member in Status] == [
        "SUBMITTING",
        "NOTTRADED",
        "PARTTRADED",
        "ALLTRADED",
        "CANCELLED",
        "REJECTED",
    ]
    assert [member.name for member in Product] == [
        "EQUITY",
        "FUTURES",
        "OPTION",
        "INDEX",
        "FOREX",
        "SPOT",
        "ETF",
        "BOND",
        "WARRANT",
        "SPREAD",
        "FUND",
        "CFD",
        "SWAP",
    ]
    assert [member.name for member in OrderType] == [
        "LIMIT",
        "MARKET",
        "STOP",
        "FAK",
        "FOK",
        "RFQ",
        "ETF",
    ]
    assert [member.name for member in OptionType] == ["CALL", "PUT"]


def test_machine_codes_are_stable_english() -> None:
    assert Direction.LONG.value == "LONG"
    assert Direction.NET.value == "NET"
    assert Offset.NONE.value == "NONE"
    assert Offset.CLOSEYESTERDAY.value == "CLOSEYESTERDAY"
    assert Status.PARTTRADED.value == "PARTTRADED"
    assert Product.FUTURES.value == "FUTURES"
    assert OrderType.MARKET.value == "MARKET"
    assert OptionType.PUT.value == "PUT"


def test_labels_keep_original_chinese_text() -> None:
    assert Direction.SHORT.label == "空"
    assert Offset.CLOSETODAY.label == "平今"
    assert Status.REJECTED.label == "拒单"
    assert Product.WARRANT.label == "权证"
    assert OrderType.RFQ.label == "询价"
    assert OptionType.CALL.label == "看涨期权"


def test_exchange_codes_preserved() -> None:
    # 与原版一致：EUREX 的代码是 EUX，而不是枚举名
    assert len(Exchange) == 49
    assert Exchange.CFFEX.value == "CFFEX"
    assert Exchange.XBOND.value == "XBOND"
    assert Exchange.EUREX.value == "EUX"
    assert Exchange.IBKRATS.value == "IBKRATS"
    assert Exchange.LOCAL.value == "LOCAL"
    assert Exchange.GLOBAL.value == "GLOBAL"


def test_currency_and_interval_codes_preserved() -> None:
    assert {member.value for member in Currency} == {"USD", "HKD", "CNY", "CAD"}
    assert {member.value for member in Interval} == {"1m", "1h", "d", "w", "tick"}


def test_str_enum_json_serialization() -> None:
    payload = {"direction": Direction.LONG, "interval": Interval.MINUTE}

    assert json.dumps(payload) == '{"direction": "LONG", "interval": "1m"}'


def test_status_is_active_matches_active_statuses() -> None:
    # 原 ACTIVE_STATUSES 集合（SUBMITTING / NOTTRADED / PARTTRADED）改为枚举属性
    active = {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}

    assert {status for status in Status if status.is_active} == active
    assert Status.ALLTRADED.is_active is False
    assert Status.CANCELLED.is_active is False
    assert Status.REJECTED.is_active is False
