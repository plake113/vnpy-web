"""应用组合根接线测试。

HTTP 测试用依赖覆盖注入测试运行时；这里单独验证真实 ``lifespan`` 会创建
``EventBus`` / ``TradingRuntime`` / ``PersistenceService``，并检查 OpenAPI 已注册
行情与交易路径。
"""

from __future__ import annotations

from app.main import create_app, lifespan
from app.services.trading.persistence import PersistenceService
from app.services.trading.runtime import TradingRuntime


async def test_lifespan_creates_runtime_and_persistence() -> None:
    app = create_app()

    async with lifespan(app):
        runtime = app.state.runtime
        assert isinstance(runtime, TradingRuntime)
        assert isinstance(app.state.persistence, PersistenceService)
        assert app.state.event_bus is runtime.event_bus


def test_openapi_contains_market_and_trading_paths() -> None:
    paths = create_app().openapi()["paths"]

    assert "/api/v1/market/bars" in paths
    assert "/api/v1/market/overview" in paths
    assert "/api/v1/orders" in paths
    assert "/api/v1/orders/{order_key}" in paths
    for resource in ("trades", "positions", "accounts", "contracts", "quotes"):
        assert f"/api/v1/{resource}" in paths
