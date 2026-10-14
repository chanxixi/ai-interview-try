# bff — Node.js 适配层

链路位置：`Vue → **BFF** → job-service → analyzer`

> 分层依据：`docs/architecture/layered-architecture-guide.md` §2
> 目录结构 = 架构本身。**读代码先读目录，再读文件头注释，最后读实现。**

## 职责与禁止（spec.md §2.6）

| 必须做 | 禁止做 |
|---|---|
| 输入校验（zod）、请求编排、超时控制、错误映射、结果聚合、traceId 下发 | 承载业务规则、访问数据库 |
| | 出现 `entity/` / `repository/` —— 数据访问权只属于 Java 层（spec.md §3.1） |

## 接口

| 方法 | 路径 | 处理者 | 说明 |
|---|---|---|---|
| GET | `/healthz` | `controller/health.controller.ts` → `health` | 健康检查（spec.md §2.8） |
| GET | `/api/ping` | `controller/job.controller.ts` → `ping` | 全链连通性探针，聚合 job-service → analyzer |

## 目录结构

```
src/
├─ index.ts                              进程入口：建容器 → listen → 优雅退出
├─ app.ts                                组装 Koa app（不 listen，便于测试）
├─ container.ts                          ★ 组合根：唯一 new 具体实现的地方
├─ config/
│  ├─ env.ts                             zod 校验环境变量，失败即 exit(1)
│  ├─ constants.ts                       冻结常量：TRACE_ID_HEADER / API_PREFIX / TIMEOUT_MS
│  └─ index.ts                           统一出口
├─ controller/                           ① 控制层：只懂 HTTP
│  ├─ health.controller.ts
│  └─ job.controller.ts
├─ service/                              ② 业务层：只懂业务（不 import koa）
│  └─ job.service.ts
├─ client/                               ③ 下游适配器（**没有 repository / entity**）
│  ├─ http.ts                            undici + AbortSignal.timeout，唯一发请求的地方
│  └─ jobService.client.ts
├─ dto/                                  ④ 契约形状的唯一落点
│  ├─ request/analysis.request.ts        zod schema + 派生类型（spec.md §2.1）
│  └─ response/{analysis,error,health,ping}.response.ts
├─ middleware/                           横切关注点
│  ├─ errorHandler.middleware.ts         统一错误收口（必须最外层）
│  ├─ traceId.middleware.ts              X-Trace-Id 贯穿
│  ├─ requestLog.middleware.ts           结构化访问日志
│  ├─ validate.middleware.ts             zod 校验 → ctx.state.dto
│  └─ rateLimit.middleware.ts            ★ 预留，本期不挂载
├─ errors/
│  ├─ errorCode.ts                       spec.md §2.3 冻结错误码表
│  ├─ appError.ts                        客户端错误 + 两类下游故障
│  └─ mapUpstream.ts                     下游表现 → 错误码（plan.md §6.4）
├─ route/index.ts                        唯一的「路径 → controller」接线点
├─ type/koa.d.ts                         ctx.state 类型增强
└─ util/
   ├─ logger.ts                          pino 结构化日志
   └─ response.ts                        统一**错误**响应封装

tests/
├─ setup.ts                              测试前置（压日志到 silent）
├─ support/container.ts                  用 stub 适配器拼容器
├─ unit/                                 纯单测：Service / 错误映射
└─ e2e/                                  supertest 喂 app.callback()，不起端口
```

## 依赖方向（唯一不可违反的架构律）

```
Controller  →  Service  →  Client(HTTP)
（懂 HTTP）    （懂业务）    （懂网络）
```

三条硬规则（指南 §1.1）：

1. **只向内依赖**，反向依赖一律禁止
2. **禁止跨层**：Controller 不得直接注入 Client
3. **DTO 是跨边界的唯一语言**，Entity / ORM 对象绝不出现（本项目根本没有）

自检方式：`service/` 下任何文件出现 `import ... from 'koa'` 就是违规。

---

## ★ 溯源地图：出问题了先看哪个文件

按「你观察到的现象」直接定位，不用从 `index.ts` 一路读下来。

| 现象 | 第一个该看的文件 | 再看 | 说明 |
|---|---|---|---|
| 前端收到 5xx / 4xx，但不知道谁报的 | `errors/mapUpstream.ts` | `errors/appError.ts` | 下游故障 → 对外错误码的唯一映射表 |
| 前端看到的错误文案不对 | `errors/appError.ts` | `spec.md` §2.3 | `message` 是预置文案，改这里；状态码 + code 组合必须落在 §2.3 表内 |
| 想加/改一个错误码 | `errors/errorCode.ts` | `spec.md` §6 变更记录 | 冻结清单，**不擅自新增** |
| 某条 URL 由谁处理 | `route/index.ts` | `controller/*.controller.ts` | 唯一的接线点，一个文件看全 |
| 某个接口返回的字段不对 | `dto/response/*.response.ts` | `spec.md` §2.2 | 契约形状归 DTO 管；值来自下游 |
| 请求参数没被校验住 / 校验报错文案 | `middleware/validate.middleware.ts` | `dto/request/analysis.request.ts` | schema 在 DTO 层，不在 controller |
| 调下游超时了 / 超时时间想调整 | `config/constants.ts`（`TIMEOUT_MS`） | `plan.md` §6.1 | 超时矩阵的单一来源；env 可覆盖 |
| 下游请求本身失败（连不上、返回非 JSON） | `client/http.ts` | `client/*.client.ts` | 唯一发 HTTP 请求的地方 |
| 下游 URL 拼错 / 端口不对 | `client/*.client.ts` | `config/env.ts` | baseUrl 只在适配器里拼接 |
| 日志里 traceId 断了 | `middleware/traceId.middleware.ts` | `client/http.ts`（是否透传 header） | 断点通常是忘了带 `X-Trace-Id` |
| 日志格式不对 / 有敏感信息 | `util/logger.ts` | — | pino 配置 + redact 规则 |
| 业务编排顺序不对（先调谁后调谁） | `service/*.service.ts` | `plan.md` §1.1 时序 | 业务层是编排的唯一归属 |
| 响应体套了一层壳 / 多字段 | `util/response.ts` | `spec.md` §2.2 | 成功响应不套壳，错误才用统一体 |
| 中间件没生效 / 顺序不对 | `app.ts` | — | 洋葱顺序：errorHandler → traceId → 日志 → bodyParser → 路由 |
| 启动就崩，日志说环境变量校验失败 | `config/env.ts` | `workspace/.env.example` | 配置错误**故意**快速失败，不带病启动 |
| 想替换某层做测试 | `container.ts` | `tests/support/container.ts` | 组合根是唯一的装配点 |

## 改一个东西要动哪些文件（变更路径）

| 要改什么 | 动哪些文件 | 千万别动 |
|---|---|---|
| 加一个接口 | `dto/`（形状）→ `service/`（编排）→ `controller/`（HTTP）→ `route/index.ts`（接线）→ `container.ts`（装配） | `errors/`（除非要新错误码） |
| 加一个下游服务 | `config/env.ts` + `config/constants.ts` + `client/<name>.client.ts` + `container.ts` | `controller/` |
| 改超时 | `config/constants.ts`（改完同步 `plan.md` §6.1） | 各 client 里硬编码 |
| 改错误表现 | `errors/mapUpstream.ts` + `tests/unit/errors.test.ts` | controller |
| 换掉日志实现 | `util/logger.ts` | 各处 `console.log` |

## 未接线清单（P1 引入，T3 才接线）

P1 是纯结构重构，不引入新功能。以下文件当前**没有调用方**，是刻意保留的骨架：

| 文件 | 作用 | 接线点 |
|---|---|---|
| `dto/request/analysis.request.ts` | `POST /api/analysis` 入参 schema（spec.md §2.1 冻结） | T3：`route/index.ts` 里 `validateBody(analyzeRequestSchema)` |
| `dto/response/analysis.response.ts` | 四块响应契约（spec.md §2.2 冻结） | T3：`service/analysis.service.ts` 的返回类型 |
| `middleware/validate.middleware.ts` | zod 校验中间件 | T3：同上 |
| `middleware/rateLimit.middleware.ts` | 令牌桶限流 | 本期**不启用**（spec.md §1.4 Out of Scope） |
| `config/env.ts` 的 `analyzer.*` | analyzer 地址与超时 | T3：`client/analyzer.client.ts` |

> 判断标准：**契约形状**（DTO）与**横切中间件**可以先行；**调用链**（client / service / controller）必须跟着功能一起进，避免死代码。

## 已知缺口

- `POST /api/analysis` 编排未实现（T3）；`GET /api/jobs` 未实现（T4）
- **未匹配路由返回 Koa 默认的 `text/plain` 404**，不是 `{code,message,traceId}`。
  原因：`spec.md` §2.3 错误码表内没有"路由不存在"对应的 code，不擅自新增。
  处理方式：T3 若需要，先在 `spec.md` 补一个 code，再在 `route/index.ts` 加 fallback。
- 未引入 eslint（T8 的 CI 阶段统一加）
- 限流未启用（见上表）

## 本地运行

```bash
npm install
npm run dev          # http://localhost:3000
```

配置见仓库根 `../.env.example`（`BFF_PORT` / `JOB_SERVICE_URL` / `JOB_SERVICE_TIMEOUT_MS` /
`ANALYZER_URL` / `ANALYZER_TIMEOUT_MS` / `LOG_LEVEL`）。

## 测试

```bash
npm test             # jest + supertest，下游一律用 stub，不依赖外部服务
npm run type-check
```

分层测试矩阵（指南 §2.5）：

| 层级 | 位置 | 测什么 | 不测什么 |
|---|---|---|---|
| Service 单测 | `tests/unit/` | 编排顺序、不变量、DTO 裁剪 | HTTP 状态码 |
| 错误映射单测 | `tests/unit/errors.test.ts` | 映射表逐条 | 真实下游行为 |
| Controller/e2e | `tests/e2e/` | 状态码、响应体形状、traceId 贯穿 | 下游真实行为（用 stub） |
| 全链冒烟 | `../scripts/smoke.sh` | 四服务连通 + traceId 贯穿 | 业务精度 |
