# vnpy Web 迁移项目 · 全栈架构骨架

将 vnpy（VeighNa）量化交易框架从桌面端迁移为 Web 系统：
**Python 后端（FastAPI + SQLAlchemy 异步 + Alembic）+ TypeScript 前端（React 19 + Vite）**。
原始 vnpy 源码位于 `vnpy/`，仅作迁移参考。

当前阶段：架构骨架已就绪，vnpy 核心内容审计完成，已完成领域对象、异步事件总线、网关 / 数据源端口、
开平转换、行情加工、指标容器、OMS 服务、交易运行时、持久化与交易 / 行情 API 共十四个迁移单元
（`domain/` + `core/events.py` + `integrations/` + `services/trading/` + `models/` / `crud/` +
`api/`）；前端为空白模板（入口 + 最小数据层 + 设计令牌），等待重新设计；
交易、具体网关适配等业务逻辑大部分尚未接入。
协作约定见 [AGENTS.md](AGENTS.md)。

## 特性

- **后端分层**：`api → services → domain / crud → models`，依赖方向单向，职责清晰；
- **统一契约**：分页响应 `Page<T>`、错误响应 `{ error: { code, message, details }, request_id }`；
- **可观测性**：请求级 `request_id`、访问日志、`X-Request-ID` / `X-Process-Time` 响应头、JSON 日志开关；
- **数据库**：SQLAlchemy 2.0 异步会话 + Alembic 迁移；目标默认 PostgreSQL、SQLite 可选（当前骨架默认 SQLite，后续阶段再切换）；
- **前端**：Vite + React + TS 空白模板 + 最小数据层占位（axios 实例、健康检查、契约类型、
  UI 状态与错误工具）+ 设计令牌，UI 待重新设计；
- **工程化**：pytest（异步 HTTP 集成测试）、ruff、mypy、Docker Compose 一键启动；
- **按能力迁移**：新增 `backend/app/domain` 纯领域层与 `backend/app/integrations` 外部系统端口，
  先审计再按业务概念拆分，不镜像 vnpy 目录；进度与映射见 [MIGRATION.md](MIGRATION.md)。

## 目录结构

```text
vnpy/                            # 仓库根目录
├── .env / .env.example          # docker compose 变量（PostgreSQL 凭据等）
├── docker-compose.yml           # db + backend + frontend
├── README.md                    # 使用说明
├── AGENTS.md                    # 项目定位与协作约定
├── MIGRATION.md                 # vnpy 内容审计、迁移方案与进度
├── docs/
│   └── demo/terminal-full.html   # UI 基线原型
├── backend/
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py               # 异步迁移环境，URL 来自应用配置
│   │   ├── script.py.mako
│   │   └── versions/            # 迁移脚本
│   ├── app/
│   │   ├── main.py              # 应用工厂 + 生命周期 + 中间件装配
│   │   ├── api/
│   │   │   ├── deps.py          # SessionDep / SettingsDep / PaginationDep / ServiceDep
│   │   │   ├── router.py        # 聚合 v1 路由
│   │   │   └── v1/
│   │   │       ├── router.py
│   │   │       └── endpoints/   # health.py、items.py、market.py、trading.py
│   │   ├── core/                # config / database / logging / exceptions / events（异步事件总线）
│   │   ├── domain/              # 纯领域层（enums/base/market/contracts/symbols/orders/trades/positions/accounts/quotes/offset_converter/pricing/bar_generator/indicators）
│   │   ├── integrations/        # 网关 / 数据源异步端口（gateway.py、datafeed.py）
│   │   ├── middleware/          # request_context.py
│   │   ├── models/              # base.py（Base + TimestampMixin）、item.py、market_data.py、trading.py
│   │   ├── schemas/             # common.py、health.py、item.py、market_data.py、trading.py
│   │   ├── crud/                # base.py（通用 CRUD）、item.py、market_data.py、trading.py
│   │   ├── services/            # item.py、trading/oms.py、runtime.py、persistence.py、queries.py（业务规则与交易运行时）
│   │   └── utils/               # pagination.py、timezone.py（UTC 边界）
│   ├── tests/                   # conftest.py、接口 / 领域 / 端口契约 / OMS / 持久化测试
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── .env.example
└── frontend/
    ├── index.html
    ├── vite.config.ts           # @ 别名、/api 开发代理
    ├── tsconfig.json            # strict + 路径别名
    ├── nginx.conf               # 生产静态托管 + SPA 回退 + /api 代理
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── main.tsx / App.tsx   # 空白挂载点（外壳待重建）
        ├── api/                 # client.ts（axios 实例 + 错误归一）、health.ts、index.ts
        ├── hooks/               # useApiHealth.ts（占位）、index.ts
        ├── stores/              # appStore（toast / 连接状态）、preferencesStore、index.ts
        ├── types/               # api.ts（Page / ApiErrorPayload）、index.ts
        ├── utils/               # errors.ts（ApiError）、index.ts
        ├── styles/              # tokens.css（设计令牌）+ base.css（reset 与全局基础）
        └── vite-env.d.ts
```

## 本地启动

### 后端（当前骨架默认 SQLite，零外部依赖；目标默认 PostgreSQL）

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # 按需修改
alembic upgrade head          # 建表 / 升级到最新版本
uvicorn app.main:app --reload
```

- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>、`/api/v1/health/ready`
- SQLite 文件：`backend/data/app.db`（可在 `.env` 中切换为 PostgreSQL）

### 前端

```bash
cd frontend
npm install
cp .env.example .env.local    # 可选
npm run dev
```

访问 <http://localhost:5173>，开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端（Nginx） | <http://localhost:8080> |
| 后端（FastAPI） | <http://localhost:8000/docs> |
| PostgreSQL | `localhost:5432`，库名 `vnpy_rebuild` |

后端容器启动时自动执行 `alembic upgrade head`。首次构建需要拉取依赖，耗时较长。

## 环境变量

### 后端（`backend/.env` 或环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `local` | `local` / `dev` / `test` / `prod` |
| `DEBUG` | `false` | 调试开关 |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | 服务监听地址 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | 支持 `postgresql://` 简写并自动补 asyncpg |
| `DATABASE_ECHO` | `false` | 是否打印 SQL |
| `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` | `5` / `10` | 非 SQLite 连接池参数 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_JSON` | `false` | 输出 JSON 结构化日志 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔 |
| `CORS_ALLOW_CREDENTIALS` | `true` | 是否允许携带凭据 |

### 前端（`frontend/.env.local`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api/v1` | API 基地址 |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | 开发代理目标 |
| `VITE_API_DOCS_URL` | `http://localhost:8000/docs` | API 文档地址（前端可选用） |

## API 约定

- 所有业务接口位于 `/api/v1` 下；
- 分页响应：

  ```json
  { "items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0 }
  ```

- 错误响应（校验失败、业务异常、404、500 一致）：

  ```json
  {
    "error": {
      "code": "ITEM_NAME_CONFLICT",
      "message": "名称 'alpha' 已存在",
      "details": null
    },
    "request_id": "d36b41c28b4e4f2e8605a7e7c89b0d57"
  }
  ```

- 每个响应都带 `X-Request-ID` 与 `X-Process-Time`，便于前后端日志串联；
- 新增业务异常只需继承 `AppException`（或现成的 `NotFoundError` / `ConflictError` 等）。

## 新增一个业务模块

以 `order` 为例，按层依次添加：

1. `app/models/order.py`：定义 ORM 模型，并在 `app/models/__init__.py` 导入；
2. `app/schemas/order.py`：`OrderCreate` / `OrderUpdate` / `OrderRead`；
3. `app/crud/order.py`：继承 `CRUDBase[Order, OrderCreate, OrderUpdate]` 并扩展查询；
4. `app/services/order.py`：业务规则与事务（`commit` / `rollback` 只出现在这一层）；
5. `app/api/v1/endpoints/orders.py`：路由，并在 `app/api/v1/router.py` 注册；
6. 生成并执行迁移：

   ```bash
   alembic revision --autogenerate -m "create orders"
   alembic upgrade head
   ```

7. 前端：`types/order.ts` → `api/orders.ts` → `hooks/useOrders.ts` → `pages/OrdersPage.tsx` →
   在 `routes/index.tsx` 注册路由（前端数据层、页面与路由待重建，外壳重建后按此链路添加）。

`items` 模块就是按上述链路实现的完整示例，接入真实业务后可直接删除：

- 后端：`models/item.py`、`schemas/item.py`、`crud/item.py`、`services/item.py`、
  `api/v1/endpoints/items.py`、`get_item_service`（`api/deps.py`）、`alembic/versions/0001_initial_items.py`；
- 前端：数据层、页面、导航与路由项尚未重建；外壳重建后如需示例页，按上面的链路自行接入。

## 测试与质量

```bash
cd backend
pytest                 # 异步集成测试（每个用例独立内存库）
ruff check .           # 静态检查
mypy app               # 可选：类型检查

cd ../frontend
npm run typecheck      # tsc --noEmit
npm run build          # 生产构建
```

## 尚未包含（后续迭代）

- PaperGateway / 回放、下单 / 撤单写接口、回测引擎；真实柜台不接，数据源适配器 TuShare/XT 优先；
- WebSocket / SSE 实时推送；
- 行情图表实时更新（WebSocket 推送；图表页待重建）；
- 行情数据平面（分阶段实施，引擎选型待定）；
- 前端重建（分组侧栏、行情终端与移动下单待重新设计）；
- 任务队列（Celery / ARQ）与定时任务；
- CI / CD 流水线与生产部署配置。

## 明确不做（单用户前提）

本项目定位为**单用户、本机/受信网络**使用，以下能力不做：

- 认证授权（JWT / RBAC）、登录会话、多租户与用户体系；应用自身不做认证，
  远程访问由 VPN / 反向代理承担；
- 合规审计与不可篡改操作审计；保留运行日志、请求追踪与操作时间线用于排查；
- 真实柜台接入（CTP/IB/易盛等）；只做 PaperGateway 与回放，保留 `Gateway` 端口；
- 第三方动态应用插件、Excel RTD / PyXLL 兼容；分别用内部 manifest、CSV/Excel 导出 + API 替代；
- 行情与历史数据的对外再分发；账号与许可自备，仅本机单用户使用。
