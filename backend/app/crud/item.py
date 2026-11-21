"""示例资源 CRUD（占位，替换真实业务时可删除）。"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.item import Item
from app.schemas.item import ItemCreate, ItemUpdate
from app.utils.pagination import compute_offset


class CRUDItem(CRUDBase[Item, ItemCreate, ItemUpdate]):
    """示例资源的定制查询。"""

    async def get_by_name(self, db: AsyncSession, name: str) -> Item | None:
        return await self.get_by(db, name=name)

    async def list_paginated(
        self,
        db: AsyncSession,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[Item], int]:
        """按名称模糊搜索 + 启用状态过滤的分页查询。"""
        conditions: list[ColumnElement[bool]] = []
        if search:
            conditions.append(Item.name.ilike(f"%{search.strip()}%"))
        if is_active is not None:
            conditions.append(Item.is_active.is_(is_active))

        total = int(
            await db.scalar(
                select(func.count()).select_from(Item).where(*conditions)
            )
            or 0
        )

        stmt = (
            select(Item)
            .where(*conditions)
            .order_by(Item.id.desc())
            .offset(compute_offset(page, page_size))
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return list(rows), total


item_crud = CRUDItem(Item)
