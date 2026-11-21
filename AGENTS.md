# AGENTS.md

本文件定义本仓库（工作区根目录）的**项目定位**与协作约定，供 AI 助手和后续维护者遵循。
人类可读的使用说明见 [README.md](README.md)。

## 1. 项目定位

**vnpy Web 迁移项目**：把 [vnpy（VeighNa）](https://github.com/vnpy/vnpy) 量化交易框架从桌面端
（PySide6 + 本地事件引擎）迁移为浏览器可用的 Web 系统，同时保留 Python 作为后端语言。

目标架构：

| 层 | 技术选型 |
| --- | --- |
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0（异步）· Alembic · Pydantic v2 |
| 前端 | TypeScript · React 19 · Vite · React Router · axios · zustand |
| 数据库 | 默认 PostgreSQL；SQLite 作为可选本地轻量模式（当前骨架默认 SQLite，后续阶段再切换） |
| 部署 | Docker Compose：PostgreSQL + 后端 + Nginx 托管前端 |

仓库中的 `vnpy/` 子目录是**原始 vnpy 源码，仅供迁移参考**：不修改、不纳入版本管理
（`.gitignore` 已忽略）、不作为本项目的运行依赖。所有新代码写在 `backend/` 与 `frontend/`。

### 当前阶段

- 架构骨架已完成：分层、统一响应契约、请求追踪、数据库迁移、示例 CRUD、测试、Docker；
  前端为空白模板，等待重新设计；
- **内容审计已完成，按能力切片迁移**：不再镜像 vnpy 目录；已完成单元 1–14（`domain/` 下的
  `enums`、`base`、`market`、`contracts`、`symbols`、`orders`、`trades`、`positions`、
  `accounts`、`quotes`、`offset_converter`、`pricing`、`bar_generator`、`indicators`，`core/events.py`，
  `integrations/` 的网关 / 数据源端口，`services/trading/` 的 OMS、运行时与持久化订阅，
  `models/` / `crud/` 的行情与交易持久化，以及交易 / 行情 HTTP API）；
  后端活跃规划已完成；前端为空白模板（入口与最小数据层占位），等待重新设计，
  单元 15–17 为暂缓 / 需决策项，详见 `MIGRATION.md`；
- vnpy 的交易、行情、网关、策略、回测等业务逻辑**大部分尚未迁移**；
- `items` 是占位示例模块（跑通 model → schema → crud → service → api；前端数据层与页面待重建），
  落地第一个真实业务模块时应删除或替换；
- 尚未包含：WebSocket / SSE、任务队列、CI/CD（详见 README「尚未包含」）；
  认证授权、多租户、合规审计**明确不做**（单用户、无认证）。

## 2. 目录职责

```text
backend/app/
├── api/         路由层：参数解析、依赖注入、调用 service、返回 schema
├── services/    业务层：事务边界、业务规则、异常转换、跨 CRUD 编排
├── domain/      领域层：按业务概念拆分的纯 Python 模型（enums / market / orders 等），不镜像 vnpy 目录
├── integrations/ 外部系统端口：异步网关 Gateway / 历史数据源 DataFeed（适配器后续加入）
├── crud/        数据访问层：纯数据库读写，不提交事务
├── models/      SQLAlchemy ORM 模型（新增后需在 models/__init__.py 注册）
├── schemas/     Pydantic 请求 / 响应契约
├── core/        配置、数据库、日志、异常等基础设施
├── middleware/  请求上下文（request_id、访问日志）
└── utils/       无业务含义的通用工具

frontend/src/      # 空白模板 + 最小数据层占位，待重建
├── main.tsx / App.tsx   空白挂载点
├── api/         client.ts（axios 实例 + 错误归一）、health.ts
├── hooks/       useApiHealth.ts（占位）
├── stores/      appStore（toast / 连接状态）、preferencesStore
├── types/       api.ts（Page / ApiErrorPayload）
├── utils/       errors.ts（ApiError）
├── styles/      tokens.css（设计令牌）+ base.css（reset 与全局基础）
└── vite-env.d.ts
```

依赖方向必须单向：`api → services → domain / crud → models`，`schemas` 被各层引用；
`domain` 除指标容器（`numpy` / `TA-Lib`，见 `domain/indicators.py`）外只依赖标准库，
禁止反向依赖 app 的其他层或框架。

当前文档只保留 README / AGENTS / MIGRATION 与 UI 基线 `docs/demo/terminal-full.html`。
新的重大取舍先写决策记录（目录按需重建）。

## 3. 后端约定

- 只有 service 层可以 `commit` / `rollback`；crud 层只 `flush`。
- 业务异常继承 `AppException`（或 `NotFoundError` / `ConflictError` 等），由全局处理器统一返回：
  `{ "error": { "code", "message", "details" }, "request_id": "..." }`。
- 列表接口统一使用 `Page<T>`：`items / total / page / page_size / pages`。
- 新增表必须写 Alembic 迁移（`alembic revision --autogenerate`）；运行时与部署**禁止**依赖
  `Base.metadata.create_all` / 手工 DDL 建表（测试用内存库初始化除外）；迁移必须可 downgrade。
- 配置只从 `app.core.config.Settings`（环境变量 / `backend/.env`）读取，不硬编码密钥或环境差异。
- 新 endpoint 在 `app/api/v1/router.py` 注册；跨 endpoint 复用的依赖放到 `app/api/deps.py`。
- 字段命名遵循 vnpy 领域术语（gateway / contract / order / trade / position / tick / bar / strategy），
  数据库与 API 使用 snake_case；代码标识符英文，注释与文档中文。
- 新代码不使用 vnpy 的 `vt_` 前缀；跨网关复合键统一为 `instrument_key` / `order_key` /
  `trade_key` / `position_key` / `account_key` / `quote_key`（跨网关复合键约定）。

## 4. 前端约定

- 类型与后端字段保持 snake_case，不额外增加映射层。
- HTTP 调用集中在 `src/api/`，错误由 `src/api/client.ts` 的 axios 拦截器统一转换为 `ApiError`
  （当前为最小占位：client / health / types / errors / stores / useApiHealth，其余待重建时补齐）。
- 用户可见反馈通过 `useAppStore().pushToast(message, tone)`，不要每个页面各写一套提示
  （store 已占位，视图待重建时补齐）。
- 保持当前轻量依赖（React / Router / axios / zustand）；引入 UI 库、数据请求库或 Redux 前必须先征得同意。
- 使用路径别名 `@/`；页面级逻辑放 hooks；前端业务目录（`api/`、`hooks/`、`stores/`、`types/`、
  `utils/`、`pages/`、`components/`、`routes/`、`styles/`）在重建外壳时恢复。
- 新增页面（外壳重建后）：`pages/XxxPage.tsx` → `routes/index.tsx` 注册 → 需要时在导航配置中增加入口。
- 行情图表统一使用 TradingView Lightweight Charts（图表库选型）；
  不引入 pyqtgraph/Qt 或其他图表库；图表组件只负责渲染，数据通过 `api/` + `hooks/` 获取。

## 5. 迁移原则

1. **按能力切片迁移，不搬目录**：`MIGRATION.md` 是唯一台账；一个单元可以来自同一源文件的一部分
   （例如 `object.py` 拆成多个单元），每个单元 ≤2 个目标模块，实现 + 测试 + 更新台账后再继续。
2. **先理解再迁移**：阅读 `vnpy/` 中对应模块，明确字段、事件流与业务规则，再按 Web 架构重切；
   不要照搬 PySide6 组件、线程模型、全局单例、gettext 与文件状态。
3. **Web 原生设计**：以 FastAPI 异步服务、REST/WebSocket、数据库持久化为中心重新组织；
   事件引擎改用 asyncio；外部系统走 `integrations` 端口 + 适配器；禁止在 `domain` 引入框架依赖。
4. **不擅自引入 vnpy 依赖**：`backend/pyproject.toml` 当前不依赖 vnpy；数值依赖只允许进入
   `domain/indicators.py`（`numpy` / `TA-Lib` 是数值依赖例外）；若确需复用某个纯 Python 模块，
   先说明原因与方案，再改动依赖。
5. **控制范围**：当前仓库是迁移底座。除非任务明确要求，不要主动实现交易、行情、回测等业务逻辑；
   保持骨架可运行、可测试。
6. **保持契约稳定**：改动统一错误结构、分页结构或认证方式属于架构级变更，需要同步更新前后端、
   README 与测试。
7. **记录架构决策**：分层、事件模型、网关/持久化方向等重大变更先写决策记录
   （目录按需重建），并同步 `MIGRATION.md` / `README.md`；
   已接受的决策不直接改写，用新记录说明演进。

## 6. 常用命令

```bash
# 后端（当前工作区已初始化 backend/.venv；全新克隆请先按 README 安装依赖）
cd backend
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload      # http://127.0.0.1:8000/docs
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/alembic check                      # 模型与迁移是否有漂移

# 前端
cd frontend
npm run dev                                  # http://127.0.0.1:5173，/api 代理到 8000
npm run typecheck
npm run build

# 容器（PostgreSQL + 后端 + Nginx 前端）
docker compose up --build                    # 前端 http://localhost:8080
```

## 7. 质量门槛

- 后端改动后至少执行：`ruff check .`、`mypy app`、`pytest`；涉及模型时再执行 `alembic check`。
- 前端改动后至少执行：`npm run typecheck`、`npm run build`。
- 新增接口 / 业务规则必须有测试；测试使用独立的 SQLite 内存库，不依赖本地数据库服务。
- 修改后如做了端到端验证，应停掉自己启动的开发服务，避免端口占用。
- 不提交 `.env`、`.venv`、`node_modules`、`dist`、`backend/data` 与各类缓存（见各目录 `.gitignore`）。
  任何凭据只通过环境变量注入，不写入代码、日志或文档。

## 8. 后续迁移路线（建议顺序）

1. 领域模型与数据字典：账户、合约、委托、成交、持仓、Tick / Bar、策略配置；
2. 基础数据与账户体系：合约信息、交易日历；
3. 行情接入：数据源适配、订阅管理、实时推送（WebSocket）；
4. 交易链路：Paper/回放网关适配、委托 / 成交 / 持仓同步、风控前置校验；
5. 策略与回测：策略生命周期、参数管理、回测任务与结果查看；
6. 前端交易终端：行情看板、下单面板、持仓与委托监控；
7. 运维与交付：运行日志/操作记录、任务队列、CI/CD、生产部署。

具体模块的落地步骤与占位模块替换方法见 [README.md](README.md#新增一个业务模块)。
