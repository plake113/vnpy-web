"""路由层。

- ``app.api.router``：顶层聚合路由，挂载版本前缀；
- ``app.api.v1``：v1 版本路由；
- ``app.api.v1.endpoints``：按资源拆分的 endpoint 模块；
- ``app.api.deps``：可复用的依赖（数据库会话、分页、service 等）。

新增资源时：在 ``endpoints`` 下新建模块 -> 在 ``v1/router.py`` 注册。
"""

from __future__ import annotations
