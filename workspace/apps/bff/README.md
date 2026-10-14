# bff — Node.js 适配层

链路位置：`Vue → **BFF** → job-service → analyzer`

## 职责

- 输入校验（zod）、请求编排、超时控制、错误映射、结果聚合
- 全链 **traceId** 下发与回写（`X-Trace-Id`）
- 结构化 JSON 日志（pino）

## 禁止

- 承载业务规则、访问数据库（ADR-005 / spec.md §3.1）

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| GET | `/api/ping` | 全链连通性探针（聚合 job-service → analyzer 的结果） |

## 目录

```
src/
├─ index.ts               启动入口（监听 + 优雅退出）
├─ app.ts                 组装 Koa app（与监听分离，便于测试）
├─ config.ts              环境变量加载与校验（zod）
├─ logger.ts              pino 结构化日志
├─ errors.ts              错误码 + 下游故障 → 错误码映射（plan.md §6.4）
├─ koa.d.ts               ctx.state 类型扩展（traceId / log）
├─ clients/
│  ├─ http.ts             undici（全局 fetch）+ AbortSignal 超时
│  └─ jobServiceClient.ts job-service 领域 API 客户端
├─ middleware/
│  ├─ errorHandler.ts     统一错误收口（spec.md §2.3）
│  ├─ traceId.ts          traceId 贯穿（spec.md §2.8）
│  └─ requestLog.ts       访问日志
└─ routes/
   ├─ health.ts
   └─ ping.ts
```

## 本地运行

```bash
npm install
npm run dev          # http://localhost:3000
```

配置见仓库根 `../.env.example`（`BFF_PORT` / `JOB_SERVICE_URL` / `JOB_SERVICE_TIMEOUT_MS`）。

## 测试

```bash
npm test             # jest + supertest，下游一律用 stub，不依赖外部服务
npm run type-check
```

## 骨架阶段的已知缺口

- 只有 `/api/ping`，`POST /api/analysis` 编排见 `../../sdd/part1/tasks.md` T3
- 未引入 eslint（T8 的 CI 阶段统一加）
- 未做限流（`429 RATE_LIMITED` 已在错误码表内，待 T3 后按需接入）
