"""示例 ORM 模型。

这是一个 *占位* 模型，用于演示 model -> schema -> crud -> service -> api 的完整链路，
接入真实业务（行情、交易、账户等）后可直接删除并替换为领域模型。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Item(Base, TimestampMixin):
    """示例资源。"""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        index=True,
        comment="名称，全局唯一",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="描述",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
        comment="是否启用",
    )

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<Item id={self.id} name={self.name!r}>"
