"""pytest 公共 fixture。

每个测试使用独立的 SQLite 内存库，并通过依赖覆盖注入到应用中，
因此测试之间互不影响，也不依赖本地数据库服务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 确保所有 ORM 模型注册到 metadata
from app.api.deps import get_runtime
from app.core.database import get_db
from app.core.events import EventBus
from app.main import create_app
from app.models.base import Base
from app.services.trading.runtime import TradingRuntime


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """每个测试一个独立的内存数据库。"""
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
def runtime() -> TradingRuntime:
    """交易运行时（空网关）；HTTP 测试通过依赖覆盖注入。"""
    return TradingRuntime(EventBus())


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """与会话工厂同款的独立会话工厂，供 crud / 持久化测试直接使用。"""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """直接操作 crud 的数据库会话（不经过 HTTP 层）。"""
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(
    engine: AsyncEngine,
    runtime: TradingRuntime,
) -> AsyncIterator[AsyncClient]:
    """指向测试数据库与空交易运行时的 HTTP 客户端。"""
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_runtime] = lambda: runtime

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
