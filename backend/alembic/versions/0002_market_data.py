"""创建历史行情表 bars / ticks

Revision ID: 0002_market_data
Revises: 0001_initial_items
Create Date: 2026-11-17

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_market_data"
down_revision: str | None = "0001_initial_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bars",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gateway_name", sa.String(length=64), nullable=False, comment="数据来源网关"),
        sa.Column(
            "instrument_key",
            sa.String(length=128),
            nullable=False,
            comment="合约键，例如 rb2410.SHFE",
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False, comment="合约代码（冗余列）"),
        sa.Column("exchange", sa.String(length=16), nullable=False, comment="交易所代码（冗余列）"),
        sa.Column("interval", sa.String(length=16), nullable=False, comment="K 线周期机器码"),
        sa.Column(
            "datetime",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="K 线时间（UTC）",
        ),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("open_interest", sa.Float(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("high_price", sa.Float(), nullable=False),
        sa.Column("low_price", sa.Float(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_key",
            "interval",
            "datetime",
            name="uq_bars_instrument_interval_datetime",
        ),
    )

    op.create_table(
        "ticks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gateway_name", sa.String(length=64), nullable=False, comment="数据来源网关"),
        sa.Column(
            "instrument_key",
            sa.String(length=128),
            nullable=False,
            comment="合约键，例如 rb2410.SHFE",
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False, comment="合约代码（冗余列）"),
        sa.Column("exchange", sa.String(length=16), nullable=False, comment="交易所代码（冗余列）"),
        sa.Column(
            "datetime",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Tick 时间（UTC）",
        ),
        sa.Column("last_price", sa.Float(), nullable=False),
        sa.Column("last_volume", sa.Float(), nullable=False),
        sa.Column("limit_up", sa.Float(), nullable=False),
        sa.Column("limit_down", sa.Float(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("high_price", sa.Float(), nullable=False),
        sa.Column("low_price", sa.Float(), nullable=False),
        sa.Column("pre_close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("open_interest", sa.Float(), nullable=False),
        sa.Column("bid_price_1", sa.Float(), nullable=False),
        sa.Column("bid_price_2", sa.Float(), nullable=False),
        sa.Column("bid_price_3", sa.Float(), nullable=False),
        sa.Column("bid_price_4", sa.Float(), nullable=False),
        sa.Column("bid_price_5", sa.Float(), nullable=False),
        sa.Column("ask_price_1", sa.Float(), nullable=False),
        sa.Column("ask_price_2", sa.Float(), nullable=False),
        sa.Column("ask_price_3", sa.Float(), nullable=False),
        sa.Column("ask_price_4", sa.Float(), nullable=False),
        sa.Column("ask_price_5", sa.Float(), nullable=False),
        sa.Column("bid_volume_1", sa.Float(), nullable=False),
        sa.Column("bid_volume_2", sa.Float(), nullable=False),
        sa.Column("bid_volume_3", sa.Float(), nullable=False),
        sa.Column("bid_volume_4", sa.Float(), nullable=False),
        sa.Column("bid_volume_5", sa.Float(), nullable=False),
        sa.Column("ask_volume_1", sa.Float(), nullable=False),
        sa.Column("ask_volume_2", sa.Float(), nullable=False),
        sa.Column("ask_volume_3", sa.Float(), nullable=False),
        sa.Column("ask_volume_4", sa.Float(), nullable=False),
        sa.Column("ask_volume_5", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_key",
            "datetime",
            name="uq_ticks_instrument_datetime",
        ),
    )


def downgrade() -> None:
    op.drop_table("ticks")
    op.drop_table("bars")
