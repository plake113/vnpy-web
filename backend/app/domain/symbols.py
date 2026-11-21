"""跨交易所合约键（``instrument_key``）的生成、解析与网关注名校验。

来源：vnpy 4.5.0 ``vnpy/trader/utility.py`` 的 ``extract_vt_symbol`` / ``generate_vt_symbol``
以及 ``trader/object.py`` 内联的 ``vt_symbol`` 拼接逻辑（MIT License，© Xiaoyou Chen）。
原 ``vt_symbol`` 工具从 1304 行的 ``utility.py`` 中抽出，成为纯标识模块。

命名与格式约定（复合键一律 ``*_key``，不使用 ``vt_`` 前缀）：

- ``instrument_key`` = ``"{symbol}.{exchange.value}"``，例如 ``rb2410.SHFE``；
- 解析用 ``rsplit(".", 1)``：合约代码本身允许包含点号（如 ``BTC.USDT``），
  只有最后一段是交易所代码；
- 交易所代码必须是 :class:`Exchange` 的成员（例如 ``EUREX`` 的代码是 ``EUX``），
  否则抛 ``ValueError``；
- ``gateway_name`` 约定不含点号，否则 ``order_key`` / ``position_key`` 等复合键
  会产生解析歧义；网关注册时应调用 :func:`validate_gateway_name`；
- ``gateway_key`` = ``"{gateway_name}.{local_id}"``（``order_key`` / ``trade_key`` /
  ``account_key`` / ``quote_key``）；解析用 ``partition(".")`` 从第一个点拆分，
  本地 ID 允许含点号（如 ``"A.B"``）。

这里不使用强类型 Key 值对象：键仍是普通 ``str``，便于 JSON / API / DB
与现有网关互通；拼接与解析只允许通过本模块完成。
"""

from __future__ import annotations

from app.domain.enums import Direction, Exchange

__all__ = [
    "build_gateway_key",
    "build_instrument_key",
    "build_position_key",
    "parse_gateway_key",
    "parse_instrument_key",
    "validate_gateway_name",
]


def build_instrument_key(symbol: str, exchange: Exchange) -> str:
    """拼接跨交易所唯一的合约键，例如 ``rb2410.SHFE``。

    只做拼接，不校验 ``symbol``；交易所代码取 ``exchange.value`` 而不是枚举名
    （``Exchange.EUREX`` → ``EUX``）。
    """
    return f"{symbol}.{exchange.value}"


def build_gateway_key(gateway_name: str, local_id: str) -> str:
    """拼接 ``gateway_name.local_id`` 形式的跨网关键。

    适用于 ``order_key`` / ``trade_key`` / ``account_key`` / ``quote_key``：前半段是网关名，
    后半段是网关本地 ID。生成前会校验网关名（不能为空、不能含点号），保证键可以安全拆分；
    ``local_id`` 由网关提供，只做拼接、不做格式假设。
    """
    validate_gateway_name(gateway_name)
    return f"{gateway_name}.{local_id}"


def build_position_key(
    gateway_name: str,
    instrument_key: str,
    direction: Direction,
) -> str:
    """拼接持仓键 ``gateway_name.instrument_key.direction``。

    方向段使用新枚举代码 ``LONG`` / ``SHORT``（原 vnpy 使用中文「多 / 空」），
    网关适配层负责格式映射。
    解析规则（首个点前为网关、末个点后为方向、中间为合约键）待持仓查询落地时补上。
    """
    return build_gateway_key(gateway_name, f"{instrument_key}.{direction.value}")


def parse_gateway_key(gateway_key: str) -> tuple[str, str]:
    """把 ``gateway_name.local_id`` 形式的复合键拆成 ``(gateway_name, local_id)``。

    从**第一个**点拆分：网关名约定不含点号，本地 ID 允许含点号，
    例如 ``"CTP.A.1"`` → ``("CTP", "A.1")``。

    :raises ValueError: 缺少点号、网关名为空或非法、本地 ID 为空
    """
    gateway_name, separator, local_id = gateway_key.partition(".")
    if not separator:
        raise ValueError(f"gateway_key 缺少点号：{gateway_key!r}")
    if not gateway_name:
        raise ValueError(f"gateway_key 缺少网关名：{gateway_key!r}")
    if not local_id:
        raise ValueError(f"gateway_key 缺少本地 ID：{gateway_key!r}")

    validate_gateway_name(gateway_name)
    return gateway_name, local_id


def parse_instrument_key(instrument_key: str) -> tuple[str, Exchange]:
    """把合约键解析为 ``(symbol, exchange)``，例如 ``("rb2410", Exchange.SHFE)``。

    :raises ValueError: 缺少分隔符、合约代码或交易所代码为空、交易所代码未知
    """
    symbol, separator, exchange_code = instrument_key.rpartition(".")
    if not separator:
        raise ValueError(f"instrument_key 缺少交易所后缀：{instrument_key!r}")
    if not symbol:
        raise ValueError(f"instrument_key 缺少合约代码：{instrument_key!r}")
    if not exchange_code:
        raise ValueError(f"instrument_key 缺少交易所代码：{instrument_key!r}")

    try:
        exchange = Exchange(exchange_code)
    except ValueError as exc:
        raise ValueError(f"instrument_key 含未知交易所代码：{instrument_key!r}") from exc

    return symbol, exchange


def validate_gateway_name(gateway_name: str) -> str:
    """校验网关名可用于复合键，并原样返回，便于链式调用。

    约定：网关名不能为空、不能包含点号；否则
    ``gateway_name.order_id`` / ``gateway_name.instrument_key.direction``
    无法可靠拆分。
    """
    if not gateway_name:
        raise ValueError("gateway_name 不能为空")
    if "." in gateway_name:
        raise ValueError(f"gateway_name 不能包含点号：{gateway_name!r}")
    return gateway_name
