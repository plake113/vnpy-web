"""``vnpy/trader/object.py`` 的 ``ContractData`` → ``app/domain/contracts.py`` 的迁移测试。

重点验证：

- 字段集合、顺序（构造参数顺序）与默认值与原版一致，仅 ``option_underlying``
  改名为 ``option_underlying_key``；
- 合约通过 :class:`InstrumentKeyMixin` 派生 ``instrument_key``；
- 期权属性可留空，也能完整表达标的合约与到期日。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.domain.contracts import ContractData
from app.domain.enums import Exchange, OptionType, Product


def make_contract(**overrides: object) -> ContractData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "name": "螺纹钢2410",
        "product": Product.FUTURES,
        "size": 10,
        "pricetick": 1,
    }
    values.update(overrides)
    return ContractData(**values)  # type: ignore[arg-type]


def test_contract_requires_core_fields() -> None:
    with pytest.raises(TypeError):
        ContractData(  # type: ignore[call-arg]
            gateway_name="CTP",
            symbol="rb2410",
            exchange=Exchange.SHFE,
            name="螺纹钢2410",
            product=Product.FUTURES,
            size=10,
        )


def test_contract_core_fields() -> None:
    contract = ContractData(
        "CTP", "rb2410", Exchange.SHFE, "螺纹钢2410", Product.FUTURES, 10, 1
    )

    assert contract.gateway_name == "CTP"
    assert contract.symbol == "rb2410"
    assert contract.exchange is Exchange.SHFE
    assert contract.name == "螺纹钢2410"
    assert contract.product is Product.FUTURES
    assert contract.size == 10
    assert contract.pricetick == 1
    assert contract.instrument_key == "rb2410.SHFE"


def test_contract_defaults() -> None:
    contract = make_contract()

    assert contract.min_volume == 1
    assert contract.max_volume is None
    assert contract.stop_supported is False
    assert contract.net_position is False
    assert contract.history_data is False
    assert contract.extra is None

    assert contract.option_strike is None
    assert contract.option_underlying_key is None
    assert contract.option_type is None
    assert contract.option_listed is None
    assert contract.option_expiry is None
    assert contract.option_portfolio is None
    assert contract.option_index is None


def test_contract_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(ContractData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "name",
        "product",
        "size",
        "pricetick",
        "min_volume",
        "max_volume",
        "stop_supported",
        "net_position",
        "history_data",
        "option_strike",
        "option_underlying_key",
        "option_type",
        "option_listed",
        "option_expiry",
        "option_portfolio",
        "option_index",
    ]


def test_contract_gateway_flags() -> None:
    contract = make_contract(
        min_volume=5,
        max_volume=100,
        stop_supported=True,
        net_position=True,
        history_data=True,
    )

    assert contract.min_volume == 5
    assert contract.max_volume == 100
    assert contract.stop_supported is True
    assert contract.net_position is True
    assert contract.history_data is True


def test_option_contract() -> None:
    contract = make_contract(
        symbol="rb2410C3500",
        name="螺纹钢2410看涨3500",
        product=Product.OPTION,
        option_strike=3500,
        option_underlying_key="rb2410.SHFE",
        option_type=OptionType.CALL,
        option_listed=datetime(2026, 1, 2),
        option_expiry=datetime(2026, 12, 15),
        option_portfolio="rb2410C",
        option_index="3500C",
    )

    assert contract.product is Product.OPTION
    assert contract.option_strike == 3500
    assert contract.option_underlying_key == "rb2410.SHFE"
    assert contract.option_type is OptionType.CALL
    assert contract.option_listed == datetime(2026, 1, 2)
    assert contract.option_expiry == datetime(2026, 12, 15)
    assert contract.option_portfolio == "rb2410C"
    assert contract.option_index == "3500C"


def test_contract_equality_covers_all_fields() -> None:
    assert make_contract() == make_contract()
    assert make_contract(gateway_name="IB") != make_contract()
    assert make_contract(pricetick=0.5) != make_contract()
