"""应用入口。

本地启动::

    uvicorn app.main:app --reload

生产启动（Gunicorn + UvicornWorker 亦可）::

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, describe_database, dispose_engine
from app.core.events import EventBus
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.middleware.request_context import RequestContextMiddleware
from app.services.trading.persistence import PersistenceService
from app.services.trading.runtime import TradingRuntime

APP_DESCRIPTION = """
vnpy 重构项目后端骨架。

- 分层：api -> services -> crud -> models
- 统一错误结构与分页结构
- 请求级 request_id 与结构化日志
- Alembic 数据库迁移
"""

TAGS_METADATA = [
    {"name": "health", "description": "存活 / 就绪探针"},
    {"name": "items", "description": "示例资源（占位模块，可替换为真实业务）"},
    {"name": "market", "description": "历史行情：K 线区间查询与数据概览"},
    {"name": "trading", "description": "交易数据：委托、成交、持仓、账户、合约、报价"},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：创建交易组合根，关闭时先落库再释放连接池。"""
    logger = logging.getLogger("app.main")
    settings = get_settings()

    event_bus = EventBus()
    runtime = TradingRuntime(event_bus)
    persistence = PersistenceService(event_bus, SessionLocal)

    app.state.event_bus = event_bus
    app.state.runtime = runtime
    app.state.persistence = persistence

    logger.info(
        "application started name=%s version=%s env=%s database=%s",
        settings.app_name,
        settings.app_version,
        settings.app_env,
        describe_database(),
    )
    try:
        yield
    finally:
        await persistence.stop()
        await runtime.close()
        await dispose_engine()
        logger.info("application stopped")


def create_app() -> FastAPI:
    """应用工厂：便于测试中构造独立实例。"""
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=APP_DESCRIPTION,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
    )

    # 注意：后添加的中间件在最外层。CORS 放在外层，保证预检与错误响应也带跨域头。
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api": settings.api_v1_prefix,
        }

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_settings.app_host,
        port=_settings.app_port,
        reload=_settings.debug,
    )
