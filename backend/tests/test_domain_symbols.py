"""``vnpy/trader/utility.py`` 的 ``vt_symbol`` 工具 → ``app/domain/symbols.py`` 的迁移测试。

重点验证：

- ``instrument_key`` 生成使用 ``exchange.value``（``EUREX`` → ``EUX``）；
- 解析用 ``rsplit(".", 1)``，兼容合约代码内含点号；
- 非法输入给出明确 ``ValueError``，不返回半解析结果；
- 网关名点号约定（不能为空、不能含点号）校验。
"""

from __future__ import annotations

import pytest

from app.domain.enums import Direction, Exchange
from app.domain.symbols import (
    build_gateway_key,
    build_instrument_key,
    build_position_key,
    parse_gateway_key,
    parse_instrument_key,
    validate_gateway_name,
)


def test_build_instrument_key_uses_exchange_code() -> None:
    assert build_instrument_key("rb2410", Exchange.SHFE) == "rb2410.SHFE"
    # 与原版 vt_symbol 一致：EUREX 的代码是 EUX，而不是枚举名
    assert build_instrument_key("FESX", Exchange.EUREX) == "FESX.EUX"


def test_parse_instrument_key() -> None:
    symbol, exchange = parse_instrument_key("rb2410.SHFE")

    assert symbol == "rb2410"
    assert exchange is Exchange.SHFE


def test_parse_instrument_key_maps_short_exchange_code_back() -> None:
    assert parse_instrument_key("FESX.EUX") == ("FESX", Exchange.EUREX)


def test_roundtrip_for_multiple_exchanges() -> None:
    cases = [
        ("rb2410", Exchange.SHFE),
        ("IF2412", Exchange.CFFEX),
        ("600000", Exchange.SSE),
        ("FESX", Exchange.EUREX),
        ("BTCUSDT", Exchange.GLOBAL),
    ]

    for symbol, exchange in cases:
        key = build_instrument_key(symbol, exchange)
        assert parse_instrument_key(key) == (symbol, exchange)


def test_parse_instrument_key_allows_dots_in_symbol() -> None:
    # 只有最后一段是交易所代码，前面的点号属于合约代码本身
    assert parse_instrument_key("BTC.USDT.GLOBAL") == ("BTC.USDT", Exchange.GLOBAL)
    assert parse_instrument_key("a.b.c.SHFE") == ("a.b.c", Exchange.SHFE)


def test_parse_instrument_key_rejects_missing_separator() -> None:
    with pytest.raises(ValueError, match="缺少交易所后缀"):
        parse_instrument_key("rb2410")


def test_parse_instrument_key_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError, match="缺少合约代码"):
        parse_instrument_key(".SHFE")


def test_parse_instrument_key_rejects_empty_exchange() -> None:
    with pytest.raises(ValueError, match="缺少交易所代码"):
        parse_instrument_key("rb2410.")

    with pytest.raises(ValueError, match="缺少交易所后缀"):
        parse_instrument_key("")


def test_parse_instrument_key_rejects_unknown_exchange() -> None:
    with pytest.raises(ValueError, match="未知交易所代码"):
        parse_instrument_key("rb2410.UNKNOWN")

    # 交易所代码区分大小写，避免静默接受非规范写法
    with pytest.raises(ValueError, match="未知交易所代码"):
        parse_instrument_key("rb2410.shfe")


def test_build_gateway_key() -> None:
    # 委托 / 成交 / 账户 / 报价键：网关名 + 本地 ID
    assert build_gateway_key("CTP", "12345") == "CTP.12345"
    assert build_gateway_key("IB_SIM", "A-1") == "IB_SIM.A-1"


def test_build_gateway_key_validates_gateway_name() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        build_gateway_key("", "12345")

    with pytest.raises(ValueError, match="不能包含点号"):
        build_gateway_key("CTP.SIM", "12345")


def test_parse_gateway_key_roundtrip() -> None:
    assert parse_gateway_key("CTP.12345") == ("CTP", "12345")
    assert parse_gateway_key(build_gateway_key("IB_SIM", "A-1")) == ("IB_SIM", "A-1")


def test_parse_gateway_key_splits_on_first_dot() -> None:
    # 网关名不含点号，因此第一个点之后都属于本地 ID
    assert parse_gateway_key("CTP.A.B") == ("CTP", "A.B")


def test_parse_gateway_key_rejects_missing_separator() -> None:
    with pytest.raises(ValueError, match="缺少点号"):
        parse_gateway_key("CTP12345")


def test_parse_gateway_key_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="缺少网关名"):
        parse_gateway_key(".12345")

    with pytest.raises(ValueError, match="缺少本地 ID"):
        parse_gateway_key("CTP.")


def test_build_position_key() -> None:
    # 三段结构：网关.合约键.方向，方向段用英文代码
    assert build_position_key("CTP", "rb2410.SHFE", Direction.LONG) == "CTP.rb2410.SHFE.LONG"
    assert build_position_key("IB", "AAPL.NASDAQ", Direction.SHORT) == "IB.AAPL.NASDAQ.SHORT"


def test_build_position_key_validates_gateway_name() -> None:
    with pytest.raises(ValueError, match="不能包含点号"):
        build_position_key("CTP.SIM", "rb2410.SHFE", Direction.LONG)


def test_validate_gateway_name_accepts_plain_names() -> None:
    assert validate_gateway_name("CTP") == "CTP"
    assert validate_gateway_name("IB_SIM") == "IB_SIM"


def test_validate_gateway_name_rejects_empty() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        validate_gateway_name("")


def test_validate_gateway_name_rejects_dots() -> None:
    with pytest.raises(ValueError, match="不能包含点号"):
        validate_gateway_name("CTP.SIM")
