"""示例资源业务逻辑（占位，替换真实业务时可删除）。

演示 service 层的典型职责：事务、业务校验、异常转换。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.crud.item import item_crud
from app.schemas.common import Page
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate


class ItemService:
    """示例资源业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> Page[ItemRead]:
        rows, total = await item_crud.list_paginated(
            self.session,
            page=page,
            page_size=page_size,
            search=search,
            is_active=is_active,
        )
        return Page[ItemRead].create(
            items=[ItemRead.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get(self, item_id: int) -> ItemRead:
        item = await item_crud.get(self.session, item_id)
        if item is None:
            raise NotFoundError(f"Item {item_id} 不存在", code="ITEM_NOT_FOUND")
        return ItemRead.model_validate(item)

    async def create(self, data: ItemCreate) -> ItemRead:
        if await item_crud.get_by_name(self.session, data.name) is not None:
            raise ConflictError(f"名称 {data.name!r} 已存在", code="ITEM_NAME_CONFLICT")

        try:
            item = await item_crud.create(self.session, data)
            await self.session.commit()
        except IntegrityError as exc:  # 并发写入时兜底
            await self.session.rollback()
            raise ConflictError(
                f"名称 {data.name!r} 已存在", code="ITEM_NAME_CONFLICT"
            ) from exc

        await self.session.refresh(item)
        return ItemRead.model_validate(item)

    async def update(self, item_id: int, data: ItemUpdate) -> ItemRead:
        item = await item_crud.get(self.session, item_id)
        if item is None:
            raise NotFoundError(f"Item {item_id} 不存在", code="ITEM_NOT_FOUND")

        if data.name is not None and data.name != item.name:
            duplicate = await item_crud.get_by_name(self.session, data.name)
            if duplicate is not None and duplicate.id != item_id:
                raise ConflictError(
                    f"名称 {data.name!r} 已存在", code="ITEM_NAME_CONFLICT"
                )

        try:
            item = await item_crud.update(self.session, item, data)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                f"名称 {data.name!r} 已存在", code="ITEM_NAME_CONFLICT"
            ) from exc

        await self.session.refresh(item)
        return ItemRead.model_validate(item)

    async def delete(self, item_id: int) -> None:
        item = await item_crud.get(self.session, item_id)
        if item is None:
            raise NotFoundError(f"Item {item_id} 不存在", code="ITEM_NOT_FOUND")
        await item_crud.delete(self.session, item)
        await self.session.commit()
