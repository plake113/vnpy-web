# vnpy 内容梳理与 Web 迁移方案

> 本文件先审计 vnpy 的真实内容与耦合，再定义目标结构与迁移单元。
> **不再按 vnpy 的目录 / 文件镜像迁移**；一个迁移单元对应一个可测试的能力切片，
> 一个单元完成后再进入下一个。
>
> 部署前提：单用户、无认证；应用仅监听本机/受信网络，远程访问由 VPN/反代承担。
> 范围决策：只做 Paper/回放；官方模块内置；PostgreSQL 默认、SQLite 可选；策略走服务端 workspace+worker；
> 第三方插件与 Excel RTD 不做；数据账号自备、不再分发。

## 1. 审计结论

1. **vnpy 是单进程桌面终端架构**：
   - `MainEngine` 是全局门面（近似单例），持有 gateways / engines / apps / exchanges；
   - `EventEngine` 用 `Queue` + `Thread` 分发事件，另起定时线程；
   - `OmsEngine` 用内存字典缓存实时 tick / order / trade / position / account / contract / quote；
   - Qt 界面订阅事件后直接刷新。
2. **真正值得迁移的交易核心很集中**：常量、数据对象、开平转换、网关 / 数据源抽象、K 线合成、
   OMS 与主引擎的编排语义；其余大量代码是桌面端基础设施（UI、图表、i18n、RPC、本地文件状态）。
3. **vnpy 的文件边界 ≠ 职责边界，照搬会继承混乱**：
   - `object.py` 427 行：10 个数据类（含 `BaseData`）+ 5 个请求类，横跨行情、交易、账户、合约、日志；
   - `utility.py` 1304 行：符号解析、本地文件、价格取整、K 线合成、TA-Lib 指标、桌面图标路径；
   - `engine.py` 887 行：`MainEngine` + 4 个内置引擎（日志 / OMS / 邮件 / 微信）；
   - 代码大量依赖全局状态与桌面假设（见下）。
4. **强耦合 / 桌面假设**：
   - 全局 `SETTINGS`（dict + `vt_setting.json`）、全局 `database` / `datafeed` 单例；
   - 网关是同步接口 + 回调，要求实现方自行保证线程安全与非阻塞；
   - `os.chdir(TRADER_DIR)`、`sys.path.append`、`.vntrader` 本地目录；
   - loguru、gettext、PySide6、pyqtgraph、ZeroMQ、TA-Lib、deap、polars/torch（alpha）。
5. **结论：按业务能力重新切分**。领域层只保留数据与规则；事件、外部适配、持久化、HTTP/WS
   分别落到 `core` / `integrations` / `services` / `models` / `api`。

> 另注：具体网关、数据库驱动、数据源（如 `vnpy_ctp`、`vnpy_sqlite`）在 vnpy 中是**独立包**，
> 核心仓库只有抽象。迁移时不会去搬这些实现，而是定义端口后按需接入或重写适配器。

## 2. 源模块审计

### 2.1 交易核心

| 源模块 | 行数 | 实际职责 | 问题 / 判断 | 目标 |
| --- | --- | --- | --- | --- |
| `trader/constant.py` | 160 | 9 个枚举：方向/开平/状态/品种/委托类型/期权/交易所/币种/周期 | 枚举值被 gettext 中文化；交易所代码参与 `vt_symbol` | `domain/enums.py` ✅ |
| `trader/object.py` | 427 | `BaseData` + 9 个数据类 + 5 个请求类 | 混合行情/交易/账户/合约/日志；naive datetime；`vt_*` 命名 | 拆为 `domain/base.py`、`market.py`、`contracts.py`、`orders.py`、`trades.py`、`positions.py`、`accounts.py`、`quotes.py` |
| `event/engine.py` | 147 | `Event` + 线程版 `EventEngine`（队列、定时器、注册/注销） | 线程 + 阻塞队列；与 async 服务不匹配 | `core/events.py`（asyncio） |
| `trader/event.py` | 14 | 事件主题字符串 | 靠字符串拼接表达 per-symbol 事件 | `core/events.py` 的 `EventTopic` |
| `trader/gateway.py` | 278 | 抽象网关：连接、订阅、下单、撤单、查询 + 回调推送 | 同步接口、直接持有 EventEngine、线程安全约定靠文档 | `integrations/gateway.py`（异步端口 + 窄接口 sink，行情按批）✅ |
| `trader/datafeed.py` | 74 | 抽象数据源 + 动态 import 单例 | 全局 `datafeed` 单例、运行时按名字 import | `integrations/datafeed.py`（异步只读端口 + 组合根注册）✅ |
| `trader/converter.py` | 448 | 多空持仓跟踪、冻结量、SHFE/INE 平今平昨、锁仓/净仓转换 | 领域规则清晰，但依赖 `OmsEngine.get_contract` | `domain/offset_converter.py`（注入合约查询）✅ |
| `trader/engine.py` | 887 | `MainEngine` + `LogEngine` / `OmsEngine` / `EmailEngine` / `WechatEngine` | 上帝对象、单例、5 种职责、阻塞线程 | `services/trading/oms.py` ✅、`services/trading/runtime.py` ✅、通知/日志后续 |
| `trader/database.py` | 165 | 抽象数据库 + `BarOverview`/`TickOverview` + 动态驱动加载 | 全局单例、按名字 import 驱动、raw SQL 风格 | `models/market_data.py` ✅、`crud/market_data.py` ✅、`models/trading.py` ✅、`crud/trading.py` ✅、Alembic；概览转 schema |
| `trader/setting.py` | 43 | 全局 `SETTINGS` dict + JSON 覆盖 | 全局可变配置、文件路径、桌面字体设置 | `core/config.py`（pydantic-settings） |
| `trader/logger.py` | 59 | loguru 控制台 / 文件日志 | loguru、桌面目录、全局配置 | `core/logging.py`（标准库 logging） |
| `trader/utility.py` | 1304 | 符号解析、`.vntrader` 文件、价格取整、`BarGenerator`、`ArrayManager`（TA-Lib） | 5 类无关职责堆在一个文件 | `domain/symbols.py` ✅、`pricing.py` ✅、`bar_generator.py` ✅、`indicators.py` ✅（TA-Lib）；路径/图标/`virtual` 丢弃 |
| `trader/app.py` | 25 | 桌面 App 描述符（模块名、路径、Qt widget、图标） | 字段绑定 Qt / 本地插件目录 | 暂缓；将来如需插件清单再设计 |
| `trader/optimize.py` | 275 | 暴力 / 遗传算法参数优化 | deap + tqdm + 多进程；重依赖 | 后续优化服务（⏸） |
| `trader/wechat.py` | 315 | 微信 iLink 协议客户端 | 外部 HTTP 服务、登录态 | 后续通知集成（⏸） |

### 2.2 外围模块

| 模块 | 行数 / 文件数 | 性质 | 处理 |
| --- | --- | --- | --- |
| `trader/ui/` | 2355 / 5 | PySide6 主窗口、监控表、组件 | ➖ 由 React 页面 / 组件替代 |
| `chart/` | 1240 / 6 | pyqtgraph 图表、坐标轴、十字光标 | ➖ 由前端 Lightweight Charts 实现 |
| `rpc/` | 372 / 4 | ZeroMQ REQ/REP + PUB/SUB + pickle | ➖ 由 HTTP / WebSocket 替代 |
| `trader/locale/` | 43 / 2 | gettext 翻译与构建钩子 | ➖ 前端 i18n |
| `alpha/` | 6114 / 26 | polars / torch / sklearn 研究、因子、模型、回测 | ⏸ 独立 research 模块，非交易终端首批 |
| `examples/` / `docs/` / `tests/` | — | 使用示例、文档、上游测试 | 不迁移，作为行为参考 |

## 3. 目标结构

```text
backend/app/
├── api/                     # FastAPI 路由（薄层：解析、依赖、调用 service；含 market / trading）
├── schemas/                 # Pydantic 请求 / 响应
├── services/                # 应用服务：用例编排、事务、生命周期
│   ├── trading/
│   │   ├── oms.py           # ✅ 事件驱动的实时缓存与查询
│   │   ├── persistence.py   # ✅ 控制事件批量落库（订阅 + 队列 + 独立会话）
│   │   ├── queries.py       # ✅ 交易 / 行情查询（DB + OMS 合并）
│   │   ├── runtime.py       # ✅ 组合根：注册、路由、生命周期（EventSink 实现）
│   │   ├── orders.py        # 下单/撤单用例（后续）
│   │   └── market_data.py   # 行情订阅 / 历史查询（后续）
│   └── notifications/       # 邮件 / 微信（后续）
├── domain/                  # 纯领域层（只依赖标准库）
│   ├── enums.py             # ✅ 共享词汇
│   ├── base.py              # ✅ BaseData + instrument_key 派生
│   ├── market.py            # ✅ TickData / BarData / 订阅 / 历史请求
│   ├── contracts.py         # ✅ ContractData（含期权属性）
│   ├── orders.py            # ✅ OrderData / OrderRequest / CancelRequest
│   ├── trades.py            # ✅ TradeData
│   ├── positions.py         # ✅ PositionData
│   ├── accounts.py          # ✅ AccountData
│   ├── quotes.py            # ✅ QuoteData / QuoteRequest
│   ├── symbols.py           # ✅ instrument_key 生成 / 解析、网关注名校验
│   ├── pricing.py           # ✅ 价格按最小变动价位取整、小数位
│   ├── offset_converter.py  # ✅ 开平 / 锁仓 / 净仓转换（注入合约查询）
│   ├── bar_generator.py     # ✅ Tick → 1 分钟 K 线、分钟 → 多周期（无回调）
│   └── indicators.py        # ✅ ArrayManager（TA-Lib，数值依赖例外）
├── integrations/            # ✅ 外部系统适配：端口 + 实现
│   ├── gateway.py           # ✅ 异步网关端口 Gateway + 窄接口 EventSink（tick 批量回调）
│   ├── datafeed.py          # ✅ 异步历史行情只读端口 DataFeed
│   ├── gateways/            # 具体券商 / 交易所网关适配器（后续）
│   └── datafeeds/           # 具体行情源适配器（后续）
├── core/                    # 基础设施
│   ├── config.py / database.py / logging.py / exceptions.py   # 已有
│   └── events.py            # ✅ Event / EventBus / EventTopic（asyncio）
├── models/                  # SQLAlchemy ORM（item、market_data、trading）
├── crud/                    # 持久化访问（item、market_data、trading）
├── middleware/
└── utils/                   # 无业务含义的通用工具
```

依赖方向（单向）：

```text
api → schemas
api → services
services → domain / integrations / models / crud / core
integrations → domain / core
domain → 标准库（指标模块可用 numpy / TA-Lib，数值依赖例外）
core → 不依赖业务层
```

## 4. 关键设计决策

1. **取消 `MainEngine` 单例**：新增 `TradingRuntime`，在 FastAPI `lifespan` 中创建、注入到
   services / endpoints；不再有全局可变引擎。桌面端的“一个门面管所有”在 Web 中拆成职责明确的服务。
2. **事件总线 asyncio 化**：`EventBus` 用异步发布/订阅 + `asyncio` 定时任务；不复制线程 +
   阻塞队列。网关 SDK 若必须使用线程，适配器用 `loop.call_soon_threadsafe` 把回调送回事件循环。
3. **网关 / 数据源走端口与适配器**：`Gateway` / `DataFeed` 是异步抽象；适配器接收一个窄接口
   `EventSink`（`on_ticks` 批量 / `on_order` / ...），由 runtime 实现并路由到事件总线 / OMS /
   行情数据平面。tick 按批而不是逐条回调，避免：
   全局单例、运行时按字符串 import、把回调直接塞进 EventEngine。
4. **OMS 定位**：`OmsService` 订阅事件、维护实时缓存并提供查询；持久化单独做。多 worker 下
   每个进程各有一份缓存，需要 DB 作为事实来源或 Redis 广播——这是部署前必须明确的决策。
5. **持久化**：SQLAlchemy 2.0 异步 + Alembic；不再有 `BaseDatabase` 动态驱动；历史 bar/tick、
   委托、成交、持仓、账户、合约按需建表；时间统一 UTC aware，出网关 / 入 API 时转换。
6. **领域对象**：继续用 dataclass，不带 ORM / Pydantic 依赖；API 边界用 Pydantic schema，
   数据库用 ORM 模型。三层之间显式转换，避免一个类横跨三种职责。
7. **标识命名**：不使用 vnpy 的 `vt_` 前缀；领域对象使用 `instrument_key`、`order_key`、
   `trade_key`、`position_key`、`account_key`、`quote_key` 作为跨网关 / OMS 的稳定键，
   字符串格式沿用 vnpy（持仓键方向段用新枚举代码）；
   数据库主键仍用自增 ID，业务键单独建唯一索引。
8. **不再迁移桌面关注点**：Qt / pyqtgraph / gettext / loguru / ZeroMQ / `.vntrader` 文件状态 /
   动态插件路径。展示文案、图表、RPC 分别由前端 / HTTP / WebSocket 承接。
9. **枚举**：稳定英文机器码 + 中文 `label`（前端也可自行映射），不把翻译值当协议值。
10. **拆分上帝模块**：`object.py` 按业务对象拆、`utility.py` 按职责拆、`engine.py` 按服务拆；
    每个迁移单元保持小步、可测试、可回溯来源。
11. **行情数据平面独立于事件总线**：行情走批量数据平面，采用成熟环缓冲 / 共享内存实现
    （Disruptor 模式、Aeron），不自研无锁结构；`EventBus` 只承载控制 / 状态事件。
    当前只落端口与基线，引擎选型待量级确认后定稿。

## 5. 迁移单元

原计划“一个源文件一个单元”会迫使保留 vnpy 的文件边界，现调整为**按能力切片**：
一个单元可以来自同一源文件的一部分（例如 `object.py` 拆成 4 个单元），仍然一次只推进一个小单元。

| # | 单元 | 主要来源 | 目标 | 验收 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 领域共享枚举 | `trader/constant.py` | `domain/enums.py` | 成员/取值/label/JSON | ✅ |
| 2 | 基础对象 + 行情对象 | `object.py` 的 BaseData / Tick / Bar / SubscribeRequest / HistoryRequest | `domain/base.py`、`domain/market.py` | `instrument_key` 派生、字段默认值、只读派生键 | ✅ |
| 3 | 合约与代码工具 | `object.py` 的 ContractData；`utility.py` 的 vt_symbol 工具 | `domain/contracts.py`、`domain/symbols.py` | 合约字段、`instrument_key` 解析/生成、gateway 名校验 | ✅ |
| 4 | 委托与成交对象 | `object.py` 的 OrderData / OrderRequest / CancelRequest / TradeData | `domain/orders.py`、`domain/trades.py` | `order_key` / `trade_key` 派生、活跃状态、请求转换 | ✅ |
| 5 | 持仓 / 账户 / 报价对象 | `object.py` 的 PositionData / AccountData / QuoteData / QuoteRequest | `domain/positions.py`、`accounts.py`、`quotes.py` | `position_key` / `account_key` / `quote_key` 派生、活跃状态 | ✅ |
| 6 | 异步事件总线 | `event/engine.py`、`trader/event.py` | `core/events.py` | 发布/订阅/定时器/退订/异常隔离 | ✅ |
| 7 | 网关与数据源端口 | `gateway.py`、`datafeed.py` | `integrations/gateway.py`、`integrations/datafeed.py` | Fake 适配器契约测试；行情端口按批量语义 | ✅ |
| 8 | 开平转换 | `converter.py` | `domain/offset_converter.py` | SHFE/INE、锁仓、净仓、冻结量 | ✅ |
| 9 | 行情加工 | `utility.py` 的取整 / `BarGenerator` | `domain/pricing.py`、`domain/bar_generator.py` | 价格取整、Tick→1m→多周期 | ✅ |
| 10 | OMS 服务 | `engine.py` 的 `OmsEngine` | `services/trading/oms.py` | 事件驱动缓存、查询、活跃委托 | ✅ |
| 11 | 交易运行时 | `engine.py` 的 `MainEngine` | `services/trading/runtime.py` | Fake 网关生命周期、下单/撤单路由 | ✅ |
| 12 | 持久化 | `database.py` + 各领域对象 | `models/`、`crud/`、Alembic | 迁移 + 仓储测试 | ✅ |
| 13 | 交易 / 行情 API | 新设计 | `schemas/`、`api/`、`services/` | 集成测试（HTTP） | ✅ |
| 14 | 指标容器 | `utility.py` 的 `ArrayManager` | `domain/indicators.py` | 41 个指标与 TA-Lib 一致、窗口语义、双返回、参数校验 | ✅ |
| 15 | 通知（邮件 / 微信） | `engine.py` 的 Email/WechatEngine、`wechat.py` | `services/notifications/` + `integrations/` | 凭证与外部服务就绪后 | ⏸ |
| 16 | 参数优化 | `optimize.py` | 独立批处理 / 任务服务 | 依赖方案确定后 | ⏸ |
| 17 | 研究模块（alpha） | `alpha/*` | 独立 research 模块 | — | ⏸ |
| 18 | 前端交易终端 | `ui/`、`chart/` | `frontend/src/` | 页面 / 图表 / WebSocket；图表用 Lightweight Charts | ☐ 待重新设计 |

> 前端为空白模板（入口、最小数据层与设计令牌）；重建顺序待重新规划。

状态图例：✅ 完成 · ☐ 待开始 · 🚧 进行中 · ⏸ 暂缓 · ➖ 不迁移。

## 6. 明确不迁移 / 替换

| 内容 | 原因 | 替代 |
| --- | --- | --- |
| Qt UI、`trader/ui/` | 桌面端专用 | React 页面 / 组件 |
| `chart/` | pyqtgraph 绑定 Qt | 前端图表：Lightweight Charts |
| `rpc/` | ZeroMQ + pickle，单机工具链 | FastAPI HTTP + WebSocket |
| `trader/locale/` | gettext 桌面国际化 | 前端 i18n |
| `BaseEngine` / `LogEngine` | 桌面插件 / 日志引擎抽象 | 普通 service / 标准 logging |
| `.vntrader` 文件、`load_json`、`save_json`、图标路径 | 本地文件状态 | DB / 环境配置 / 前端资源 |
| `virtual` 装饰器 | 无实际语义 | 移除 |
| `alpha/` | 研究栈（polars/torch） | 后续独立模块 |

## 7. 风险与待确认

1. **多 worker 的 OMS 一致性**：实时缓存在进程内。先按单 worker 设计，还是直接引入 Redis 广播？
   建议先单 worker + DB 事实来源，部署前再定。
2. **PaperGateway 语义对齐**：只做 Paper/回放，不接真实柜台；模拟撮合的到价成交、部分成交、滑点、
   冻结与持仓成本需与 vnpy PaperAccount 的语义一致，并保留 `Gateway` 端口供未来扩展。
3. **指标库**：已决策直接使用 TA-Lib，`domain` 以指标容器
   作为数值依赖例外；剩余风险是 wheel 可用性与镜像体积，不再阻塞单元 14。
4. **历史数据存储**：目标默认 PostgreSQL、SQLite 可选；tick 体量大时再评估分区 / Timescale / 专用时序库。
5. **Alpha / 优化任务**：重依赖、长任务，应与 API 进程隔离（独立 worker / 批处理）。
6. **认证与权限**：已决策不做（2026-11-20）：单用户、无认证；应用仅监听本机/受信网络，
   远程访问由 VPN/反向代理承担。
7. **前端图表**：已选 TradingView Lightweight Charts（图表库选型）；
   时区换算、许可归属、实时聚合等实施风险在重建行情页时评估。
8. **数据与行情许可**：账号与许可自备；仅本机单用户使用，不向多用户/公网再分发。

## 8. 进度日志

| 日期 | 单元 | 完成内容 | 验证 |
| --- | --- | --- | --- |
| 2026-11-16 | 内容审计 | 梳理 61 个源文件、核心耦合与拆分方案；废弃目录镜像计划 | — |
| 2026-11-16 | 架构决策 | 标识命名放弃 `vt_` 前缀，改用 `*_key` | — |
| 2026-11-16 | 架构决策 | 前端图表改用 TradingView Lightweight Charts | — |
| 2026-11-16 | 单元 1：领域枚举 | `domain/trader/constant.py` 拍平为 `domain/enums.py`；9 个枚举、StrEnum、label | ruff / mypy / 6 个测试 |
| 2026-11-16 | 单元 2：基础对象 + 行情对象 | `object.py` 的 BaseData / Tick / Bar / 订阅 / 历史请求 → `domain/base.py`、`domain/market.py`；`vt_symbol` 改为只读 `instrument_key` | ruff / mypy / 15 个测试（全套 31 个） |
| 2026-11-16 | 单元 3：合约与代码工具 | `ContractData` → `domain/contracts.py`；`extract_vt_symbol` / `generate_vt_symbol` → `domain/symbols.py`；`option_underlying` 改名为 `option_underlying_key`；补 gateway 名校验 | ruff / mypy / 19 个测试（全套 49 个） |
| 2026-11-16 | 单元 4：委托与成交对象 | `OrderData` / `OrderRequest` / `CancelRequest` → `domain/orders.py`；`TradeData` → `domain/trades.py`；`vt_orderid` / `vt_tradeid` 改为只读 `order_key` / `trade_key`；活跃状态集合改为 `Status.is_active`；网关本地 ID 改 snake_case | ruff / mypy / 23 个测试（全套 72 个） |
| 2026-11-16 | 单元 5：持仓 / 账户 / 报价对象 | `PositionData` → `domain/positions.py`（`position_key` 用英文方向码）；`AccountData` → `accounts.py`（`available` 改为派生属性）；`QuoteData` / `QuoteRequest` → `quotes.py`；`build_position_key` 入 `symbols.py` | ruff / mypy / 32 个测试（全套 104 个） |
| 2026-11-16 | 单元 6：异步事件总线 | `event/engine.py` + `trader/event.py` → `core/events.py`：`Event` / `EventTopic` / `EventBus` / `Topics`；内联分发、订阅者异常隔离、asyncio 定时器；不复制线程与阻塞队列 | ruff / mypy / 20 个测试（全套 124 个） |
| 2026-11-17 | 架构决策 | 行情数据平面采用成熟环缓冲 / 共享内存（Disruptor 模式、Aeron），独立于 `EventBus`；分阶段实施，当前不引依赖 | — |
| 2026-11-17 | 单元 7：网关与数据源端口 | `trader/gateway.py` + `trader/datafeed.py` → `integrations/gateway.py`（`Gateway` 异步端口、窄接口 `EventSink`、`SettingValue`）与 `integrations/datafeed.py`（`DataFeed` 只读端口）；去掉 EventEngine 依赖、全局 datafeed 单例与动态 import；tick 改为批量 `on_ticks`；网关名构造时校验 | ruff / mypy / 25 个测试（全套 149 个） |
| 2026-11-17 | 架构决策 | 事件载荷契约与大对象边界记录为草稿：载荷准入、大对象移出总线、快慢通道分级；阈值与实现形态待定，当前不改代码 | — |
| 2026-11-17 | 单元 8：开平转换 | `trader/converter.py` → `domain/offset_converter.py`：`PositionHolding` / `OffsetConverter`；注入合约查询以解耦 OMS；SHFE/INE 平今平昨、锁仓 / 净仓拆分、冻结量；`dataclasses.replace` 不修改原请求、可用量截断、lock/net 互斥；`symbols.py` 新增 `parse_gateway_key` | ruff / mypy / 34 个测试（全套 183 个） |
| 2026-11-17 | 单元 9：行情加工 | `utility.py` 的 `round_to` / `floor_to` / `ceil_to` / `get_digits` → `domain/pricing.py`（Decimal 取整、half-even 语义、输入校验、`get_digits` 修正科学计数法）；`BarGenerator` → `domain/bar_generator.py`（无回调、返回完成列表、完整时间比较、日线跨日兜底、参数校验） | ruff / mypy / 38 个测试（全套 221 个） |
| 2026-11-17 | 单元 10：OMS 服务 | `trader/engine.py` 的 `OmsEngine` → `services/trading/oms.py`：订阅 6 类控制事件、按业务键缓存、活跃委托 / 报价索引、查询列表快照、按网关隔离的 `OffsetConverter` 联动、tick 只走边界写入（行情不进事件总线）、非法载荷本地校验、`stop()` 退订 | ruff / mypy / 15 个测试（全套 236 个） |
| 2026-11-17 | 单元 11：交易运行时 | `trader/engine.py` 的 `MainEngine` → `services/trading/runtime.py`：组合根替代单例；网关 / 数据源注册与重名校验；connect / close 生命周期；实现 `EventSink`（控制事件单条 scoped 发布、tick 只写 OMS）；下单预冻结并跳过同步回报；close 尽力而为 | ruff / mypy / 17 个测试（全套 253 个） |
| 2026-11-17 | 单元 12（1/2）：历史行情持久化 | `trader/database.py` 的 bar/tick 存储 → `models/market_data.py`（`bars` / `ticks` 表、UTC 时间列、唯一键）、`crud/market_data.py`（按方言 ON CONFLICT 幂等写入、分批写入、区间查询、删除、概览）、迁移 `0002_market_data`；仓储只接受 aware 时间并统一 UTC 存取 | ruff / mypy / 13 个测试（全套 266 个）/ alembic upgrade + downgrade + check |
| 2026-11-17 | 单元 12（2/2）：交易数据持久化 | `trader/object.py` 各交易对象 → `models/trading.py`（contracts / orders / trades / positions / accounts / quotes 六张表、业务键唯一约束）、`crud/trading.py`（状态快照 upsert、成交 insert-ignore、列表 / 单键查询）；`crud/base.py` 抽出方言无关的 `insert_ignore` / `upsert` + 分批；迁移 `0003_trading_data`；`utils/timezone.py` 统一 UTC 边界 | ruff / mypy / 12 个测试（全套 278 个）/ alembic upgrade + downgrade + check |
| 2026-11-17 | 单元 13（1/2）：持久化订阅 | `services/trading/persistence.py`：订阅 6 类控制事件 → 有界队列 → 后台批量事务（独立会话）；成交 insert-ignore、其余 upsert；`flush` 排空、`stop` 退订收尾；非法载荷跳过并记录；队列满对发布方形成背压 | ruff / mypy / 7 个测试（全套 285 个） |
| 2026-11-17 | 单元 13（2/2）：交易 / 行情 API | `schemas/market_data.py` / `schemas/trading.py`、`services/trading/queries.py`（DB + OMS 按键合并）、`api/v1/endpoints/market.py` / `trading.py`；`GET /market/bars`（区间 + 分页）、`/market/overview`、`/orders`（active / instrument / 分页）、`/orders/{key}`、`/trades`、`/positions`、`/accounts`、`/contracts`、`/quotes`；lifespan 组合根创建 EventBus / Runtime / PersistenceService；测试依赖注入空运行时 | ruff / mypy / 17 个测试（全套 302 个） |
| 2026-11-17 | 架构决策 | 事件载荷契约（草稿）的实施时机调整：顺延到整个 vnpy 迁移完成之后，不阻塞单元 11–13；迁移期间只发布小领域对象，不把大对象塞进总线 | 维护者确认 |
| 2026-11-19 | 前端：最小数据层占位 | 新增 `api/client.ts`（axios 实例 + 错误归一）、`types/api.ts`（`Page` / `ApiErrorPayload`）、`utils/errors.ts`（`ApiError`）与五个 `index.ts`；无业务逻辑 | `npm run typecheck` / `npm run build` |
| 2026-11-19 | 前端：store / hook 占位 | 新增 `api/health.ts`（健康检查类型 + 两个薄调用）、`stores/appStore.ts`（toast / 连接状态）、`stores/preferencesStore.ts`（主题 / 配色 / 侧栏）、`hooks/useApiHealth.ts`（返回 unknown 的占位 hook）；无业务逻辑 | `npm run typecheck` / `npm run build` |
| 2026-11-20 | 单元 14：指标容器 | `utility.py` 的 `ArrayManager` → `domain/indicators.py`：41 个指标薄封装 TA-Lib（数值与 vnpy 一致）、定长滚动窗口 / `inited` / 双返回语义、周期与 matype 前置校验；`pyproject.toml` 新增 `numpy` + `TA-Lib` | ruff / mypy / 116 个测试（全套 418 个） |
| 2026-11-20 | 范围拍板 | 单用户/无认证；只做 Paper/回放；官方模块内部注册；PostgreSQL 默认、SQLite 可选；策略服务端 workspace + worker；Excel RTD/第三方插件不做；数据账号自备、不再分发 | 维护者确认 |

## 9. 架构学习笔记

- **事件驱动内核**：行情、委托、成交、持仓都通过事件总线流转，OMS 只是事件的消费者 + 缓存，
  UI 也是消费者。Web 化后 UI 换成 WebSocket 订阅者，这个“生产者 → 总线 → 消费者”模型仍然成立。
- **队列不是必需品**：桌面版用「线程 + 阻塞队列 + 定时线程」解耦生产者与消费者；在 asyncio 中
  事件循环本身就是调度器，发布直接内联分发并隔离订阅者异常，比自建队列更简单，也没有队列积压与
  停机顺序问题。慢订阅者应自行 `create_task` 或交给独立 worker，而不是拖慢总线。
- **MainEngine 是桌面端的组合根**：它把网关、引擎、App、数据库、通知都塞进一个门面，方便单进程
  桌面程序，但在 Web 中会变成上帝对象；应拆成 DI 容器 / lifespan 管理的服务。
- **Gateway / Datafeed 的扩展点设计值得保留**：抽象接口 + 独立实现包，是 vnpy 生态的关键；
  要保留“端口”思想，去掉动态 import 和全局单例。
- **`vt_` 是历史命名**：`vt` 通常被理解为 vn.py trader 的作用域标记，`vt_symbol` 等只是
  “跨网关复合键”，不是业务术语；新系统用 `*_key` 表达同一语义，只在适配层保留 `vt_*` 映射
  （复合键统一 `*_key`）。
- **领域对象很“纯”**：`object.py` 里都是 dataclass + 派生标识，没有 ORM / 校验 / IO。这正是
  domain 层该有的样子；Web 迁移只需在边界补 schema 与持久化。
- **文件不是职责**：`utility.py` / `engine.py` / `object.py` 的混乱说明，迁移时应按业务概念
  （行情 / 委托 / 持仓 / 账户 / 事件 / 适配）组织，而不是沿用文件名。
- **端口只推一次，扇出是消费者的事**：原版网关对同一 tick / order 先推全局事件、再推
  `EVENT_XXX + vt_symbol` 逐合约事件；异步总线有了 `EventTopic.scoped` 后，`Gateway`
  只把领域对象交给 sink 一次，按合约 / 委托复制是 sink 的职责，端口因此更窄、更易测。
- **批量是行情端口的第一性设计**：逐条 tick 的协程回调在 10 万 tick/s 量级会被调度与对象分配
  吃掉；`on_ticks` 批量 + `await` 背压把“可丢 / 不可丢”交给消费端显式决定
  （行情走独立数据平面），端口本身不猜丢弃策略。
- **领域规则只依赖“查询函数”**：原版 `OffsetConverter` 直接接收 `OmsEngine`，实际只用到
  `get_contract`；改成 `Callable[[str], ContractData | None]` 后，开平规则可以脱离 OMS 单测，
  OMS 只是提供方。把依赖窄化成一个函数，比为了“将来可能用到”注入整个服务更稳。
- **冻结量是活跃委托的派生值**：它不属于持仓快照，而是“未成交平仓量”的镜像；以 `order_key`
  增删活跃委托、成交后收紧上限。开平转换因此必须同时消费持仓、委托、成交三类事件，
  且持仓快照到达时不立即重算（避免快照与回报乱序时来回抖动）。
- **K 线合成用返回值而不是回调**：`BarGenerator` 只维护“当前 K 线 + 上一条 tick + 窗口累积”
  三块显式状态，`update_tick` / `update_bar` 返回本次完成的 K 线，多周期靠返回值串联。
  这样 `domain` 不需要知道事件总线，测试可以逐根断言，回调顺序问题也交给 service。
- **OMS 是事件投影，不是数据库**：控制事件按业务键覆盖式写入缓存，tick 只留最新快照（行情不进事件总线），
  活跃委托 / 报价是“状态字段的衍生索引”。查询返回列表副本、对象只读；持久化、分页与历史查询
  留给持久化 / API 单元，避免把 OMS 做成第二个事实来源。
- **组合根只做编排**：`TradingRuntime` 不实现下单规则、不写库、不碰 HTTP；它只负责注册表、
  端口路由、事件扇出与关闭顺序。网关通过构造时注入的 sink 反向把数据交回来，避免全局单例，
  也让 Fake 适配器可以完整替代真实 SDK 跑生命周期测试。
- **一条带范围的事件足够**：`EventBus` 的范围语义是“不带范围的订阅能收到所有范围”，所以 runtime
  只发布 `eOrder.CTP.12345` 一条，OMS 的全局订阅与按单订阅都能收到，不会出现全局 + 范围双发
  导致同一事件被消费两次。
- **时间边界比表结构更容易出错**：仓储只接受 aware 时间、存储时转 UTC naive、读取时补回 UTC；
  唯一键在时区归一之后才可靠（`+08:00 09:00` 与 `UTC 01:00` 必须是同一行）。把这条规则放在仓储
  入口而不是各调用方，能避免“有时存本地时间、有时存 UTC”的脏数据。
- **按数据性质选写入语义**：成交是不可变事实，重复回报必须 `INSERT ... DO NOTHING`；委托、持仓、
  账户、报价是状态快照，`UPSERT` 覆盖最新值即可，不必追加历史。把两种语义收在 `crud/base.py`
  的两个助手里，表多了也不会各写一套方言分支。
- **落库是消费者，不是事件循环的一部分**：持久化服务只订阅、入队，再用后台任务批量事务写入；
  队列满时让发布方等待（背压），而不是静默丢事件。控制面事件量小，一批几十条就能摊薄事务成本；
  代价是当前没有重试 / outbox，批量失败只能记录日志——这是后续可靠性要补的缺口。
- **查询层显式声明事实来源**：历史行情只读 DB；交易数据以 DB 为事实、OMS 为未落库的即时状态，
  按键合并时 OMS 覆盖同键。合并规则写在 service 而不是 endpoint，前端只拿到一份“最新视图”，
  也不用知道事件是否已经落库。
- **参考实现要拆成“可借的纪律”和“不要的包袱”**：vnpy-newone 的终端密度、Stage 分层、token 纪律、
  焦点管理值得借；无路由、超大单文件、把研究/回测控制台当实盘终端 IA 则不能照搬。先写清
  “借什么 / 不借什么”，比整体复制一个 5.9 万行前端更可控。
- **指标容器复用成熟内核**：`ArrayManager` 的价值是窗口 / 预热 / 双返回这套 API 形态，
  而不是指标公式本身；把公式继续交给 TA-Lib，迁移只需薄封装与参数校验，数值与 vnpy 逐位一致。
  为此让 `domain` 接受一个明确的数值依赖例外（`numpy` / `TA-Lib`），比自研 41 个公式更可控——
  边界写进决策记录，例外只开在一个模块里。

## 10. 下一步

**单元 1–14 已完成；单元 18 前端待重新设计**；其余为暂缓 / 需决策项：

| 方向 | 前置 / 阻塞 | 说明 |
| --- | --- | --- |
| 单元 15：通知 | 邮件 / 微信凭证与外部服务 | `services/notifications/` + `integrations/` |
| 单元 16：参数优化 | deap / 进程隔离方案 | 独立批处理，不进 API 进程 |
| 单元 17：研究模块（alpha） | polars / torch 等重依赖 | 独立 research 模块 |
| 单元 18：前端交易终端 | 空白模板（仅入口 + 最小数据层 + 设计令牌）；以 `docs/demo/terminal-full.html` 为 UI 基线，外壳 / 行情终端 / 移动下单待重新设计 | 重建顺序与组件拆分待定 |
| 单元 7 补全 | 包装 vnpy 网关时需要 `query_history` / `get_default_setting` 兼容面 | 待补 |
| 事件载荷契约（草稿） | 维护者此前决定放到整个迁移之后 | 大对象 / 载荷边界待定 |

建议下一步：先重新设计前端外壳与行情页（以 terminal-full 为基线），再补行情数据源与 Paper / 回放交易链路。
