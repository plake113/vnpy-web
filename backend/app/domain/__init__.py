"""领域层（domain）。

从 vnpy 迁移/重构而来的交易领域模型与规则：

- 除指标容器（`numpy` / `TA-Lib`，数值依赖例外只开在该模块）外只依赖标准库；
- 不导入 FastAPI、SQLAlchemy、Redis 或 app 的其他层；
- 按业务概念拆分（enums / market / orders / ...），**不镜像** vnpy 的目录结构。

迁移单元、来源映射与进度见仓库根目录 ``MIGRATION.md``。
"""
