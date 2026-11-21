"""应用配置。

配置来源优先级：环境变量 > ``backend/.env`` > 代码默认值。
环境变量名与字段名大小写不敏感（如 ``DATABASE_URL`` -> ``database_url``）。

生产环境请通过环境变量注入配置，不要把真实凭据写入 ``.env`` 并提交。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录，用于定位 .env 与默认的 sqlite 数据目录
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """全局配置对象，通过 :func:`get_settings` 获取单例。"""

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ 基础
    app_name: str = "vnpy-rebuild-api"
    app_version: str = "0.1.0"
    app_env: Literal["local", "dev", "test", "prod"] = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ------------------------------------------------------------------ 数据库
    # 默认使用本地 sqlite，便于零依赖启动；容器 / 生产使用 PostgreSQL。
    # 支持简写：postgresql:// 与 postgres:// 会被自动补全 asyncpg 驱动。
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # ------------------------------------------------------------------ 日志
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False

    # ------------------------------------------------------------------ 跨域
    # 逗号分隔的 Origin 列表
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_allow_credentials: bool = True

    # ------------------------------------------------------------------ 校验
    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> str:
        return str(value).upper()

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        if value.startswith("sqlite://"):
            return "sqlite+aiosqlite://" + value[len("sqlite://") :]
        return value

    # ------------------------------------------------------------------ 派生属性
    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置解析为列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回配置单例；测试中如需隔离可调用 ``get_settings.cache_clear()``。"""
    return Settings()
