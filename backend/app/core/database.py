"""数据库连接与会话管理。

使用 SQLAlchemy 2.0 异步 API：

- PostgreSQL：``postgresql+asyncpg://...``
- SQLite：``sqlite+aiosqlite:///...``（默认，零依赖本地开发）

每个 HTTP 请求通过 ``get_db`` 依赖获得独立 ``AsyncSession``，
事务边界由 service 层显式 ``commit`` / ``rollback``。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def ensure_sqlite_directory(database_url: str) -> None:
    """sqlite 文件所在目录不存在时自动创建（Alembic 迁移也会复用）。"""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    database = url.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _create_engine() -> AsyncEngine:
    ensure_sqlite_directory(settings.database_url)

    kwargs: dict[str, Any] = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }
    # sqlite（尤其内存库）不支持 / 不需要连接池参数
    if not settings.is_sqlite:
        kwargs.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_recycle=1800,
        )

    return create_async_engine(settings.database_url, **kwargs)


engine: AsyncEngine = _create_engine()

# expire_on_commit=False：commit 之后仍可安全读取 ORM 对象属性（用于组装响应）
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：为单次请求提供数据库会话。"""
    async with SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    """应用关闭时释放连接池。"""
    await engine.dispose()


def describe_database() -> str:
    """用于启动日志的安全描述（不包含用户名 / 密码）。"""
    url = make_url(settings.database_url)
    return f"{url.get_backend_name()}://{url.host or 'local'}/{url.database or ''}"
