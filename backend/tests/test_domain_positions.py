"""``vnpy/trader/object.py`` 的 ``PositionData`` → ``app/domain/positions.py`` 的迁移测试。

重点验证：

- 字段集合 / 顺序 / 默认值与原版一致（``direction`` 必填）；
- ``position_key`` = ``gateway_name.instrument_key.direction``，方向段用 ``LONG`` / ``SHORT``
  （原 ``vt_positionid`` 用中文方向）；
- 派生键随轮询回报更新，且只读。
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.enums import Direction, Exchange
from app.domain.positions import PositionData


def make_position(**overrides: object) -> PositionData:
    values: dict[str, object] = {
        "gateway_name": "CTP",
        "symbol": "rb2410",
        "exchange": Exchange.SHFE,
        "direction": Direction.LONG,
    }
    values.update(overrides)
    return PositionData(**values)  # type: ignore[arg-type]


def test_position_field_set_matches_vnpy() -> None:
    assert [field.name for field in dataclasses.fields(PositionData)] == [
        "gateway_name",
        "extra",
        "symbol",
        "exchange",
        "direction",
        "volume",
        "frozen",
        "price",
        "pnl",
        "yd_volume",
    ]


def test_position_defaults() -> None:
    position = make_position()

    assert position.volume == 0
    assert position.frozen == 0
    assert position.price == 0
    assert position.pnl == 0
    assert position.yd_volume == 0
    assert position.extra is None


def test_position_requires_direction() -> None:
    with pytest.raises(TypeError):
        PositionData(  # type: ignore[call-arg]
            gateway_name="CTP",
            symbol="rb2410",
            exchange=Exchange.SHFE,
        )


def test_position_keys() -> None:
    position = make_position(volume=10, price=3500, yd_volume=4)

    assert position.instrument_key == "rb2410.SHFE"
    assert position.position_key == "CTP.rb2410.SHFE.LONG"

    # 派生键不是 dataclass 字段
    assert "position_key" not in {field.name for field in dataclasses.fields(position)}


def test_position_key_uses_direction_code() -> None:
    assert make_position(direction=Direction.SHORT).position_key == "CTP.rb2410.SHFE.SHORT"
    # 与 vnpy 的差异：键里用英文方向码，不再出现中文「多 / 空」
    assert "多" not in make_position().position_key


def test_position_key_follows_field_mutation() -> None:
    position = make_position()

    position.direction = Direction.SHORT
    assert position.position_key == "CTP.rb2410.SHFE.SHORT"

    position.symbol = "rb2501"
    position.gateway_name = "IB"
    assert position.position_key == "IB.rb2501.SHFE.SHORT"


def test_position_key_is_read_only() -> None:
    position = make_position()

    with pytest.raises(AttributeError):
        position.position_key = "IB.rb2410.SHFE.LONG"  # type: ignore[misc]


def test_position_key_rejects_ambiguous_gateway_name() -> None:
    position = make_position(gateway_name="CTP.SIM")

    with pytest.raises(ValueError, match="不能包含点号"):
        _ = position.position_key


def test_position_equality_covers_all_fields() -> None:
    assert make_position() == make_position()
    assert make_position(direction=Direction.SHORT) != make_position()
    assert make_position(volume=1) != make_position()
