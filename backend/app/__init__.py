"""vnpy-rebuild 后端应用包。

技术栈：FastAPI + SQLAlchemy 2.0（异步）+ Alembic + Pydantic v2。

分层约定（自外向内）：

- ``app.api``      路由层：只做参数解析、依赖注入、调用 service、返回 schema；
- ``app.services`` 业务层：事务边界、业务规则、跨 CRUD 编排；
- ``app.domain``   纯领域层：dataclass 领域对象与规则，只依赖标准库；
- ``app.integrations`` 外部系统端口：异步网关 / 数据源抽象与适配器；
- ``app.crud``     数据访问层：纯粹的数据库读写，不含业务规则；
- ``app.models``   SQLAlchemy ORM 模型；
- ``app.schemas``  Pydantic 请求/响应契约；
- ``app.core``     基础设施：配置、数据库、日志、异常；
- ``app.utils``    无业务含义的通用工具。
"""
