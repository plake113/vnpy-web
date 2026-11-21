"""通用 CRUD 基类。

为单个模型提供最常用的增删改查能力，子类可以按需扩展查询方法。
所有方法只 ``flush`` 不 ``commit``，由 service 层控制事务。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """基于 SQLAlchemy 2.0 的通用异步 CRUD。"""

    def __init__(self, model: type[ModelType]) -> None:
        self.model = model

    async def get(self, db: AsyncSession, obj_id: Any) -> ModelType | None:
        """按主键查询。"""
        return await db.get(self.model, obj_id)

    async def get_by(self, db: AsyncSession, **filters: Any) -> ModelType | None:
        """按任意等值条件查询单条记录。"""
        stmt = select(self.model).filter_by(**filters).limit(1)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        db: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: Any = None,
    ) -> Sequence[ModelType]:
        """按偏移量查询列表。"""
        stmt: Select[Any] = select(self.model)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count(self, db: AsyncSession, **filters: Any) -> int:
        """统计满足等值条件的记录数。"""
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        return int(await db.scalar(stmt) or 0)

    async def create(self, db: AsyncSession, obj_in: CreateSchemaType) -> ModelType:
        """插入记录并回读数据库默认值。"""
        db_obj = self.model(**obj_in.model_dump(exclude_unset=True))
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: ModelType,
        obj_in: UpdateSchemaType,
    ) -> ModelType:
        """按请求体中显式传入的字段更新记录。"""
        data = obj_in.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: ModelType) -> None:
        """删除记录（不提交事务）。"""
        await db.delete(db_obj)
        await db.flush()


# ---------------------------------------------------------------------------- 批量写入
#
# 行情 / 交易数据需要两种幂等语义：
# - ``insert_ignore``：历史事实（bar / tick / trade）重复写入直接忽略；
# - ``upsert``：状态快照（contract / order / position / account / quote）以最新为准。
#
# 两者都按方言生成 ``ON CONFLICT``，并按 ``_BATCH_SIZE`` 分批，避免单条语句参数超限。

_ModelType = TypeVar("_ModelType", bound=Base)

#: 单条 INSERT 的最大行数；按最宽的 ticks 表（34 列）估算，500 行仍低于参数上限。
_BATCH_SIZE = 500


def _dialect_name(db: AsyncSession) -> str:
    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError(f"不支持的数据库方言：{dialect}")
    return dialect


def _insert_statement(dialect: str, model: type[_ModelType], rows: list[dict[str, Any]]) -> Any:
    """按方言构造插入语句。"""
    if dialect == "sqlite":
        return sqlite_insert(model).values(rows)
    return postgresql_insert(model).values(rows)


async def insert_ignore(
    db: AsyncSession,
    model: type[_ModelType],
    rows: Sequence[dict[str, Any]],
) -> None:
    """批量插入；唯一键冲突时忽略（不更新已有行）。"""
    if not rows:
        return

    dialect = _dialect_name(db)
    for offset in range(0, len(rows), _BATCH_SIZE):
        chunk = list(rows[offset : offset + _BATCH_SIZE])
        statement = _insert_statement(dialect, model, chunk).on_conflict_do_nothing()
        await db.execute(statement)


async def upsert(
    db: AsyncSession,
    model: type[_ModelType],
    rows: Sequence[dict[str, Any]],
    *,
    key_columns: Sequence[str],
    update_columns: Sequence[str] | None = None,
    set_extra: Mapping[str, Any] | None = None,
) -> None:
    """批量 upsert：唯一键冲突时用新行覆盖 ``update_columns``（默认全部非键列）。

    :param key_columns: 唯一键列名，必须与模型上的唯一约束一致
    :param update_columns: 冲突时要覆盖的列；默认取首行中除键列外的所有列
    :param set_extra: 额外的 ``SET`` 表达式，例如 ``{"updated_at": func.now()}``
    """
    if not rows:
        return

    dialect = _dialect_name(db)
    if update_columns is None:
        update_columns = [name for name in rows[0] if name not in key_columns]

    for offset in range(0, len(rows), _BATCH_SIZE):
        chunk = list(rows[offset : offset + _BATCH_SIZE])
        statement = _insert_statement(dialect, model, chunk)
        set_values: dict[str, Any] = {
            name: getattr(statement.excluded, name) for name in update_columns
        }
        if set_extra:
            set_values.update(set_extra)
        statement = statement.on_conflict_do_update(
            index_elements=list(key_columns),
            set_=set_values,
        )
        await db.execute(statement)
