"""业务层（service）。

职责：

- 事务边界：一次业务操作一个提交；
- 业务规则与校验：如唯一性、存在性；
- 组装响应 schema，对上层屏蔽 ORM 细节。
"""

from __future__ import annotations

from app.services.item import ItemService

__all__ = ["ItemService"]
