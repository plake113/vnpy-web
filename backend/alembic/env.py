"""Alembic 迁移环境（异步引擎版本）。

数据库 URL 统一来自应用配置：

- 环境变量 ``DATABASE_URL``
- 或 ``backend/.env``
- 或 ``app/core/config.py`` 中的默认值

生成迁移::

    alembic revision --autogenerate -m "add xxx"

执行迁移::

    alembic upgrade head
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.database import ensure_sqlite_directory
from app.models import Base  # noqa: F401  # 导入包内所有模型以注册 metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()
# ConfigParser 使用 % 做插值，URL 中的 % 需要转义
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
# sqlite 模式下先确保数据目录存在，否则连接会报 unable to open database file
ensure_sqlite_directory(settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite 不支持大部分 ALTER，需要 batch 模式
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
