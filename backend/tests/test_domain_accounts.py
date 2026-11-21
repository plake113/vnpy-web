"""``vnpy/trader/object.py`` 的 ``AccountData`` → ``app/domain/accounts.py`` 的迁移测试。

重点验证：

- 字段集合 / 顺序 / 默认值与原版一致（``accountid`` → ``account_id``）；
- ``account_key`` 由 ``gateway_name`` + ``account_id`` 派生（原 ``vt_accountid``）；
- ``available`` 由 ``balance - frozen`` 派生，余额变化后立即反映，且不可赋值。
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.accounts import AccountData


def make_account(**overrides: object) -> AccountData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "account_id": "12345678",
    }
    values.update(overrides)
    return AccountData(**values)  # type: ignore[arg-type]


def test_account_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(AccountData)] == [
        "gateway_name",
        "extra",
        "account_id",
        "balance",
        "frozen",
    ]


def test_account_defaults() -> None:
    account = make_account()

    assert account.balance == 0
    assert account.frozen == 0
    assert account.available == 0
    assert account.extra is None


def test_account_key_is_derived() -> None:
    account = make_account()

    assert account.account_key == "CTP.12345678"
    assert "account_key" not in {field.name for field in dataclasses.fields(account)}


def test_account_key_follows_field_mutation() -> None:
    account = make_account()

    account.account_id = "87654321"
    account.gateway_name = "IB"
    assert account.account_key == "IB.87654321"


def test_account_available_is_derived() -> None:
    account = make_account(balance=100000, frozen=25000)

    assert account.available == 75000

    # 原版只在 __post_init__ 计算一次；这里必须随字段变化重算
    account.balance = 120000
    assert account.available == 95000

    account.frozen = 20000
    assert account.available == 100000


def test_account_available_can_be_negative() -> None:
    # 冻结超过余额是可能的（例如保证金占用后行情变化），不做截断
    account = make_account(balance=1000, frozen=1500)
    assert account.available == -500


def test_account_available_is_read_only() -> None:
    account = make_account()

    with pytest.raises(AttributeError):
        account.available = 1  # type: ignore[misc]


def test_account_key_rejects_ambiguous_gateway_name() -> None:
    account = make_account(gateway_name="CTP.SIM")

    with pytest.raises(ValueError, match="不能包含点号"):
        _ = account.account_key


def test_account_equality_covers_all_fields() -> None:
    assert make_account() == make_account()
    assert make_account(balance=1) != make_account()
    assert make_account(gateway_name="IB") != make_account()
