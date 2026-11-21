"""示例资源 endpoint（占位，替换真实业务时可删除）。

完整演示「分页查询 -> 创建 -> 详情 -> 局部更新 -> 删除」的 RESTful 接口，
以及依赖注入、schema 校验、service 调用与错误约定。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ItemServiceDep, PaginationDep
from app.schemas.common import Page
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate

router = APIRouter()

ItemId = Annotated[int, Path(ge=1, description="资源 ID")]


@router.get(
    "",
    response_model=Page[ItemRead],
    summary="分页查询示例资源",
)
async def list_items(
    pagination: PaginationDep,
    service: ItemServiceDep,
    search: Annotated[str | None, Query(max_length=120, description="按名称模糊搜索")] = None,
    is_active: Annotated[bool | None, Query(description="按启用状态过滤")] = None,
) -> Page[ItemRead]:
    return await service.list(
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        is_active=is_active,
    )


@router.post(
    "",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建示例资源",
)
async def create_item(payload: ItemCreate, service: ItemServiceDep) -> ItemRead:
    return await service.create(payload)


@router.get("/{item_id}", response_model=ItemRead, summary="查询示例资源详情")
async def get_item(item_id: ItemId, service: ItemServiceDep) -> ItemRead:
    return await service.get(item_id)


@router.patch("/{item_id}", response_model=ItemRead, summary="局部更新示例资源")
async def update_item(
    item_id: ItemId,
    payload: ItemUpdate,
    service: ItemServiceDep,
) -> ItemRead:
    return await service.update(item_id, payload)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除示例资源",
)
async def delete_item(item_id: ItemId, service: ItemServiceDep) -> Response:
    await service.delete(item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
