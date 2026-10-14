# 分层架构实现指南 —— Controller / Service / DTO

> **CareerLens · part1 工程细化文档**
> 版本 v1.0 · 2026-10-14
> 定位：`plan.md` §7「目录结构」在**包内分层**层面的细化实现指南。
> 来源：① 你提供的三框架初步方案 ② `spec.md` §2 稳定面 / §3 禁止 ③ `plan.md` §1 职责边界 / §2 选型 / ADR-001 ~ ADR-007。
> 效力：**本指南不修改 spec.md / plan.md / tasks.md 的任何冻结内容。** 若本文与 spec.md 或 plan.md 冲突，**一律以 spec.md / plan.md 为准**。

---

## 0. 如何使用本指南

### 0.1 阅读顺序

| 你的目的 | 直接看 |
|---|---|
| 先搞清"哪条规则不能违反" | §0.2 红线清单 → §1 总览 |
| 动手写 BFF | §2 Koa |
| 动手写 job-service | §3 Spring Boot |
| 动手写 analyzer | §4 FastAPI |
| 面试 / 答辩要横向讲 | §5 跨框架对比 |
| 写代码时随手查规范 | §6 工程最佳实践 |
| 准备改造现有骨架 | §7 迁移路线图 → 附录 A 速查 |

### 0.2 红线清单：通用模板里"必须改掉"的东西 ⚠️

这是本指南与你那份初步方案**差异最大、也最容易踩雷**的地方。通用三层模板是"技术中立"的，而 CareerLens 的层职责边界是**冻结**的（spec.md §2.6 / §3.1）。照抄模板会直接违反冻结条款。

| 通用模板里的东西 | 在 CareerLens 必须怎么处理 | 依据 |
|---|---|---|
| BFF 的 `entity/`（数据库模型） | **删除**。BFF 禁止访问数据库，它的"第三层"是 `client/`（下游 HTTP 适配器） | spec §2.6 / §3.1 |
| BFF 的 `repository/` | **删除**，同上 | spec §3.1 |
| BFF 里写业务规则（打分、归一化） | **删除**。BFF 只做校验/编排/超时/错误映射/聚合 | spec §2.6 / ADR-005 |
| FastAPI 的 `model/`（数据库实体） | **删除**。Python 禁止岗位数据 CRUD、禁止直连数据库 | spec §2.6 / §3.1 |
| FastAPI 的 `repository/` | **删除**，同上 | spec §3.1 |
| FastAPI 的鉴权 / 登录模块 | **删除**。Python 层禁止做鉴权 | spec §2.6 |
| FastAPI 的 `SQLAlchemy` / `Alembic` | **不引入**。analyzer 无自有数据库，schema 归 Java 层 `db/` 目录 | plan §4 / spec §2.9 |
| 成功响应套 `{ code: 0, data: {...} }` | **不要**。spec §2.2 已冻结字段层级；`{code,message,traceId}` **只用于错误** | spec §2.2 / §2.3 |
| 全站加 `/api/v1` | **暂不加**。契约已冻结、只有单一客户端；加版本号会让三份 OpenAPI 与 spec §2.1 不一致 | spec §2.1 / plan §3 |
| 三个领域接口加分页 | **不加**。只有几十行数据，plan.md §4.2 连索引都刻意没建 | plan §4.2 |
| `RATE_LIMITED` 限流落地 | **只预留骨架**。错误码在 spec §2.3 里，但本期不实现 | spec §1.4 / §2.3 |
| 用户体系 / 密码 / JWT | **不实现**（Out of Scope）。只在指南里给"将来怎么接"的设计 | spec §1.4 |
| `Mock 数据放在 BFF 或 Python` | **禁止**。降级种子数据只允许存在于 Java 层 | spec §3.1 |

> **一句话总结**：同一套三层骨架，在三个服务里"第三层"的内容**完全不同** —— 因为 spec §2.6 决定了谁能碰数据。这就是本指南与通用模板的根本区别。

### 0.3 术语

| 缩写 | 含义 | 本项目实例 |
|---|---|---|
| DTO | Data Transfer Object，跨边界的纯数据载体 | `AnalyzeRequest`、`JobResponse` |
| PO / Entity | Persistent Object，与库表一一对应 | `JobEntity` ↔ 表 `job` |
| VO | View Object，为"渲染"裁剪/加工的模型 | 前端 `PingResult`、`AnalyzeResultView` |
| BO | Business Object，领域中间产物，不跨进程 | Python `ScoredSkill`、`JobRequirementSet` |
| 组合根 | Composition Root，唯一装配依赖的地方 | BFF `container.ts`、Spring 容器、FastAPI `dependencies.py` |

---

## 1. 总览：一个骨架，三种内容

### 1.1 依赖方向规则（唯一不可违反的架构律）

```
                    ┌──────────────────────────────┐
   HTTP 请求 ──────▶│  Controller  （只懂 HTTP）    │
                    └───────────────┬──────────────┘
                                    │ DTO（请求）
                                    ▼
                    ┌──────────────────────────────┐
                    │  Service     （只懂业务）     │
                    └───────────────┬──────────────┘
                                    │ 领域接口
                        ┌───────────┴───────────┐
                        ▼                       ▼
                 Repository/Client        纯计算模块
                 （懂存储 / 网络）        （懂算法）
```

**三条硬规则**

1. **只向内依赖**：`Controller → Service → Repository/Client`。反向依赖（Service 引用 Controller）一律禁止。
2. **禁止跨层**：Controller 不得直接注入 Repository / Client / 纯计算模块。
3. **DTO 是边界的唯一语言**：跨层传递的只有 DTO 与领域对象，**Entity / ORM 对象绝不离开 Repository**。

> 这三条对应 `plan.md` §1.2 的判断法：*"这段逻辑换个 UI 框架还要吗？要 → 不该放 Controller。"*

### 1.2 三服务分层映射总表

| 概念 | Koa BFF | Spring Boot job-service | FastAPI analyzer |
|---|---|---|---|
| ① 控制层 | `src/controller/*.controller.ts` | `controller/<domain>/*Controller.java` | `app/api/v1/*.py` |
| ② 业务层 | `src/service/*.service.ts` | `service/<X>Service.java` + `impl/` | `app/service/*_service.py` |
| ③ 数据/计算层 | `src/client/*.client.ts`（**HTTP 适配器**） | `repository/` + `entity/`（**JPA**） | `app/service/{cleaner,normalizer,matcher,rules}.py`（**纯计算**） |
| ④ DTO | `src/dto/{request,response}/` | `dto/{request,response}/` | `app/schema/{request,response}/` |
| 映射层 | Service 内手工映射（对象字面量） | `mapper/`（手工 → 可选 MapStruct） | Pydantic `model_validate` |
| 是否碰数据库 | **绝对不碰** | 唯一有权访问 | **绝对不碰** |

**第 4 个服务（web）的同构映射**（不是三层，但对应关系要一致，避免命名混乱）

| 概念 | web 目录 | 说明 |
|---|---|---|
| 控制层 | `src/api/client.ts` | 只负责"发请求 / 解析响应 / 抛 `ApiRequestError`" |
| 业务层 | `src/stores/*.ts`（Pinia） | 页面状态与编排，**不做业务判断** |
| DTO | `src/api/types.ts` | 与 `contracts/frontend-bff.yaml` 对齐的类型 |
| 视图 | `src/components/*.vue` | 只负责渲染 |

---

## 2. Koa BFF 分层（apps/bff）

> 定位复述（spec §2.6）：**输入校验、请求编排、超时、错误映射、结果聚合、traceId 下发**。
> 禁止：业务规则、访问数据库。

### 2.1 完整目录结构（目标态）

```
apps/bff/
├─ package.json
├─ tsconfig.json
├─ tsconfig.test.json
├─ jest.config.js
├─ .eslintrc.cjs
├─ README.md
├─ src/
│  ├─ index.ts                          # 进程入口：建容器 → listen → 优雅退出
│  ├─ app.ts                            # 组装 Koa 实例（不 listen，便于测试）
│  ├─ container.ts                      # ★ 组合根：唯一装配依赖的地方
│  ├─ config/
│  │  ├─ env.ts                         # zod 校验环境变量（原 config.ts）
│  │  ├─ constants.ts                   # 超时矩阵 / header 名 / 路由前缀
│  │  └─ index.ts
│  ├─ controller/                       # ① 控制层
│  │  ├─ health.controller.ts
│  │  ├─ job.controller.ts
│  │  └─ analysis.controller.ts
│  ├─ service/                          # ② 业务层（编排，无 HTTP 概念）
│  │  ├─ analysis.service.ts
│  │  └─ job.service.ts
│  ├─ dto/                              # ④ 数据传输对象（契约唯一落点）
│  │  ├─ request/
│  │  │  └─ analysis.request.ts         # zod schema + 派生类型
│  │  └─ response/
│  │     ├─ analysis.response.ts        # 四块结构（spec §2.2）
│  │     ├─ job.response.ts
│  │     ├─ error.response.ts           # { code, message, traceId }
│  │     └─ health.response.ts
│  ├─ client/                           # ③ 下游适配器（**没有 repository / entity**）
│  │  ├─ http.ts                        # undici + AbortSignal.timeout
│  │  ├─ jobService.client.ts
│  │  └─ analyzer.client.ts
│  ├─ middleware/
│  │  ├─ traceId.middleware.ts          # X-Trace-Id 贯穿（spec §2.8）
│  │  ├─ requestLog.middleware.ts       # 结构化访问日志
│  │  ├─ errorHandler.middleware.ts     # 统一错误收口（最外层）
│  │  ├─ validate.middleware.ts         # zod 校验 → ctx.state.dto
│  │  └─ rateLimit.middleware.ts        # ★ 预留：429 RATE_LIMITED（本期不启用）
│  ├─ errors/
│  │  ├─ errorCode.ts                   # spec §2.3 冻结错误码
│  │  ├─ appError.ts                    # AppError / UpstreamStatusError / UpstreamTransportError
│  │  └─ mapUpstream.ts                 # plan §6.4 映射表
│  ├─ route/
│  │  └─ index.ts                       # 只做「路径 → controller」接线
│  ├─ type/
│  │  ├─ koa.d.ts                       # ctx.state 类型增强
│  │  └─ result.ts                      # Result<T> / Page<T> 泛型
│  └─ util/
│     ├─ response.ts                    # 统一**错误**响应封装
│     └─ logger.ts                      # pino 实例 + child
└─ tests/
   ├─ setup.ts
   ├─ unit/
   │  ├─ analysis.service.test.ts       # 纯单测（注入 stub client）
   │  └─ errors.test.ts                 # 映射表逐条验证
   └─ e2e/
      ├─ health.test.ts
      ├─ ping.test.ts
      └─ analysis.test.ts
```

**相对当前骨架的变化**：`routes/` → `controller/` + `route/index.ts`；`clients/` → `client/`；新增 `container.ts` / `dto/` / `service/` / `config/constants.ts` / `type/`；`errors.ts` 拆成 `errors/` 三文件。

### 2.2 各层职责与反模式

| 层 | 必须做 | 禁止做 | 常见反模式 |
|---|---|---|---|
| Controller | 取 `ctx.state.dto`、调 Service、写 `ctx.body` / `ctx.status` | 校验之外的业务判断、拼 SQL、调下游、try/catch 业务异常 | ❌ Controller 里 `if (score > 80)`；❌ Controller 里 `fetch(analyzerUrl)` |
| Service | 编排（先取 JD 再调分析）、裁剪为前端 DTO、决定降级顺序 | 读 `ctx`（拿不到 `ctx` 才是对的）、抛 HTTP 状态码、拼 JSON | ❌ Service 参数里传 `ctx`；❌ Service 里 `ctx.throw(400)` |
| Client | 一次下游调用 + 超时 + traceId 透传 + 错误归一 | 业务字段解读、重试策略散落各处、无超时调用 | ❌ `client` 里判断"这是不是有效岗位" |
| DTO | 定义并**只定义**契约形状 | 混入 Entity、混入 ORM、混入 `ctx` | ❌ DTO 里放 `id: ObjectId`；❌ 同一个类型既做入参又做出参 |
| Middleware | 横切关注点（traceId / 日志 / 错误 / 校验） | 单个业务分支 | ❌ 在中间件里写 `/api/analysis` 专属逻辑 |

### 2.3 代码示例

#### (1) DTO：请求校验 + 类型（spec §2.1 逐字对应）

```ts
// src/dto/request/analysis.request.ts
import { z } from 'zod';

/**
 * spec.md §2.1 请求契约（冻结）：
 *  - resumeText 必填 1~20000
 *  - jobId / jdText 二选一；同时提供以 jobId 为准
 * 校验属于 BFF 职责（spec §2.6），所以 zod schema 落在这里，而不是 controller。
 */
export const analyzeRequestSchema = z
  .object({
    resumeText: z.string().min(1, '简历文本不能为空'),
    jobId: z.string().min(1).optional(),
    jdText: z.string().min(1).max(8000, 'JD 文本不能超过 8000 字符').optional(),
  })
  .superRefine((value, ctx) => {
    // 二选一：至少提供一个，否则 400 INVALID_INPUT
    if (!value.jobId && !value.jdText) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['jobId'],
        message: 'jobId 与 jdText 至少提供一个',
      });
    }
  });

export type AnalyzeRequest = z.infer<typeof analyzeRequestSchema>;

/** 超长是独立错误码（spec §2.3：400 RESUME_TOO_LONG），所以单独判断 */
export const RESUME_MAX_LENGTH = 20_000;
```

```ts
// src/dto/response/analysis.response.ts
/**
 * spec.md §2.2 响应契约（冻结）：字段名 / 层级 / 类型不可改。
 * 这里只声明形状 —— BFF 不做业务计算，值全部来自 analyzer（ADR-005）。
 */
export interface NormalizedSkill { raw: string; canonical: string; category?: string | null }
export interface ResumeView { sections: Record<'education' | 'experience' | 'projects' | 'skills', string[]>; skills: NormalizedSkill[] }
export interface Issue { type: string; severity: 'high' | 'medium' | 'low'; evidence: string; suggestion: string }
export interface MatchedItem {
  skill: string; importance: 'required' | 'preferred'; weight: number;
  jdEvidence: string; resumeEvidence: string;
  jdOffset?: number | null; resumeOffset?: number | null;
}
export interface MissingItem { skill: string; importance: 'required' | 'preferred'; suggestion: string }
export interface MatchResult { score: number; matched: MatchedItem[]; missing: MissingItem[] }
export interface Meta { traceId: string; llmUsed: boolean; degraded: boolean; elapsedMs: number }

export interface AnalysisResponse {
  resume: ResumeView;
  issues: Issue[];
  match: MatchResult;
  meta: Meta;
}
```

```ts
// src/dto/response/error.response.ts
/** spec.md §2.3 统一**错误**响应体。成功响应不使用它（见 §6.7）。 */
export interface ErrorResponse {
  code: string;
  message: string;
  traceId: string;
}
```

#### (2) errors：错误码 + 业务异常 + 下游映射

```ts
// src/errors/errorCode.ts
/** spec.md §2.3 错误码表（冻结）。新增错误码必须走 spec 变更记录。 */
export const ERROR_CODES = [
  'INVALID_INPUT', 'RESUME_TOO_LONG', 'JOB_NOT_FOUND', 'ANALYSIS_FAILED',
  'RATE_LIMITED', 'SERVICE_UNAVAILABLE', 'UPSTREAM_TIMEOUT', 'INTERNAL_ERROR',
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];
```

```ts
// src/errors/appError.ts
import type { ErrorCode } from './errorCode';

/** 面向客户端的业务错误：status + code 的组合必须在 spec §2.3 表内。 */
export class AppError extends Error {
  constructor(readonly status: number, readonly code: ErrorCode, message: string) {
    super(message);
    this.name = 'AppError';
  }
  static invalidInput(message = '请求参数校验失败') { return new AppError(400, 'INVALID_INPUT', message); }
  static resumeTooLong(max = 20000) { return new AppError(400, 'RESUME_TOO_LONG', `简历文本不能超过 ${max} 字符`); }
  static jobNotFound(id: string) { return new AppError(404, 'JOB_NOT_FOUND', `岗位不存在：${id}`); }
  static analysisFailed() { return new AppError(422, 'ANALYSIS_FAILED', '分析失败，请稍后重试'); }
  static upstreamTimeout(service: string) { return new AppError(504, 'UPSTREAM_TIMEOUT', `下游服务 ${service} 响应超时`); }
  static serviceUnavailable(service: string) { return new AppError(503, 'SERVICE_UNAVAILABLE', `下游服务 ${service} 暂时不可用`); }
  static internal() { return new AppError(500, 'INTERNAL_ERROR', '服务内部错误'); }
}

/** 传输层故障（连不上 / 超时 / 响应不可解析） */
export class UpstreamTransportError extends Error {
  constructor(readonly service: string, readonly reason: 'timeout' | 'network' | 'malformed', cause?: unknown) {
    super(`upstream ${service} transport failure: ${reason}`, { cause });
    this.name = 'UpstreamTransportError';
  }
}

/** 下游返回非 2xx */
export class UpstreamStatusError extends Error {
  constructor(readonly service: string, readonly status: number) {
    super(`upstream ${service} responded ${status}`);
    this.name = 'UpstreamStatusError';
  }
}
```

```ts
// src/errors/mapUpstream.ts
import { AppError, UpstreamStatusError, UpstreamTransportError } from './appError';

/**
 * plan.md §6.4 下游表现 → 错误码。
 * 注意：**数据库不可用不会出现在这里** —— 存储降级在 Java 层内部消化（spec §2.9）。
 */
export function mapUpstreamError(error: unknown): AppError {
  if (error instanceof AppError) return error;

  if (error instanceof UpstreamTransportError) {
    return error.reason === 'timeout'
      ? AppError.upstreamTimeout(error.service)
      : AppError.serviceUnavailable(error.service);
  }

  if (error instanceof UpstreamStatusError) {
    // Java 404 → JOB_NOT_FOUND；Java 5xx / Python 5xx → 503；Python 4xx → 422
    if (error.service === 'job-service' && error.status === 404) return AppError.jobNotFound('(unknown)');
    if (error.service === 'analyzer' && error.status >= 400 && error.status < 500) return AppError.analysisFailed();
    return AppError.serviceUnavailable(error.service);
  }

  return AppError.internal();
}
```

#### (3) Client：下游适配器（BFF 的"第三层"）

```ts
// src/client/http.ts
import { UpstreamStatusError, UpstreamTransportError } from '../errors/appError';

export interface RequestOptions {
  service: string; url: string; timeoutMs: number; traceId: string;
  method?: 'GET' | 'POST'; body?: unknown;
}

/**
 * 下游 HTTP 调用封装。
 * - 用 Node 内置 undici（全局 fetch），不引第三方 HTTP 库（plan §2 选型）
 * - **禁止无超时的外部调用**（spec §3.3）→ 一律 AbortSignal.timeout
 * - 透传 X-Trace-Id，保证全链可 grep（spec §2.8）
 */
export async function requestJson<T>(o: RequestOptions): Promise<T> {
  let res: Response;
  try {
    res = await fetch(o.url, {
      method: o.method ?? 'GET',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Trace-Id': o.traceId },
      body: o.body === undefined ? undefined : JSON.stringify(o.body),
      signal: AbortSignal.timeout(o.timeoutMs),
    });
  } catch (e) {
    throw new UpstreamTransportError(o.service, isTimeout(e) ? 'timeout' : 'network', e);
  }
  if (!res.ok) throw new UpstreamStatusError(o.service, res.status);
  try { return (await res.json()) as T; }
  catch (e) { throw new UpstreamTransportError(o.service, 'malformed', e); }
}

const isTimeout = (e: unknown) =>
  e instanceof Error && (e.name === 'TimeoutError' || e.name === 'AbortError');
```

```ts
// src/client/analyzer.client.ts
import { config } from '../config';
import type { AnalysisResponse } from '../dto/response/analysis.response';
import { requestJson } from './http';

/** analyzer 适配器。入参出参只谈契约，不谈业务。 */
export interface AnalyzerClient {
  analyze(input: { resumeText: string; jdText: string; traceId: string }): Promise<AnalysisResponse>;
}

export function createAnalyzerClient(): AnalyzerClient {
  return {
    analyze: ({ resumeText, jdText, traceId }) =>
      requestJson<AnalysisResponse>({
        service: 'analyzer',
        url: `${config.analyzer.baseUrl}/internal/analyze`,
        timeoutMs: config.analyzer.timeoutMs, // 45s，对齐 plan §6.1
        method: 'POST',
        body: { resumeText, jdText, traceId },
        traceId,
      }),
  };
}
```

```ts
// src/client/jobService.client.ts
import { config } from '../config';
import type { JobResponse } from '../dto/response/job.response';
import { requestJson } from './http';

export interface JobServiceClient {
  listJobs(traceId: string): Promise<JobResponse[]>;
  getJob(id: string, traceId: string): Promise<JobResponse>;
}

export function createJobServiceClient(): JobServiceClient {
  const base = config.jobService.baseUrl;
  return {
    listJobs: (traceId) =>
      requestJson<JobResponse[]>({ service: 'job-service', url: `${base}/api/jobs`, timeoutMs: config.jobService.timeoutMs, traceId }),
    getJob: (id, traceId) =>
      requestJson<JobResponse>({ service: 'job-service', url: `${base}/api/jobs/${encodeURIComponent(id)}`, timeoutMs: config.jobService.timeoutMs, traceId }),
  };
}
```

#### (4) Service：编排，不知道 HTTP 存在

```ts
// src/service/analysis.service.ts
import { AppError } from '../errors/appError';
import type { AnalyzeRequest } from '../dto/request/analysis.request';
import type { AnalysisResponse } from '../dto/response/analysis.response';
import type { AnalyzerClient } from '../client/analyzer.client';
import type { JobServiceClient } from '../client/jobService.client';
import { RESUME_MAX_LENGTH } from '../dto/request/analysis.request';

export interface AnalysisService {
  analyze(dto: AnalyzeRequest, traceId: string): Promise<AnalysisResponse>;
}

/**
 * 编排顺序严格按 plan.md §1.1 时序：
 *   jobId 场景 → 先向 Java 取 jdText → 再调 analyzer
 * 不做任何业务计算（ADR-005）。
 * 注意：本文件不 import koa —— 这是"Service 不依赖框架"的自检方式。
 */
export function createAnalysisService(deps: {
  jobService: JobServiceClient;
  analyzer: AnalyzerClient;
}): AnalysisService {
  return {
    async analyze(dto, traceId) {
      // 领域前置校验：入口校验之外，Service 仍守住不变量
      if (dto.resumeText.length > RESUME_MAX_LENGTH) {
        throw AppError.resumeTooLong(RESUME_MAX_LENGTH);
      }

      // jobId 优先（spec §2.1）；取不到即 404
      let jdText = dto.jdText ?? '';
      if (dto.jobId) {
        try {
          jdText = (await deps.jobService.getJob(dto.jobId, traceId)).jdText;
        } catch (e) {
          throw e; // 由 errorHandler 统一映射为 404 / 503
        }
      }

      const result = await deps.analyzer.analyze({ resumeText: dto.resumeText, jdText, traceId });

      // 裁剪为前端 DTO：前端只拿到契约字段，多余的实现细节不外泄
      return {
        resume: result.resume,
        issues: result.issues,
        match: result.match,
        meta: { ...result.meta, traceId }, // 以本层 traceId 为准，保证全链一致
      };
    },
  };
}
```

#### (5) Controller：只做 HTTP

```ts
// src/controller/analysis.controller.ts
import type { Context } from 'koa';
import type { AnalyzeRequest } from '../dto/request/analysis.request';
import type { AnalysisService } from '../service/analysis.service';

/**
 * 控制层职责：取校验后的 DTO → 调 Service → 写 body。
 * 没有 if/else 业务分支，没有 try/catch（异常交给 errorHandler）。
 */
export class AnalysisController {
  constructor(private readonly service: AnalysisService) {}

  analyze = async (ctx: Context): Promise<void> => {
    const dto = ctx.state.dto as AnalyzeRequest;   // 由 validate 中间件写入
    ctx.body = await this.service.analyze(dto, ctx.state.traceId);
  };
}
```

#### (6) Middleware：校验 / traceId / 日志 / 错误

```ts
// src/middleware/validate.middleware.ts
import type { Context, Next } from 'koa';
import type { ZodTypeAny } from 'zod';
import { AppError } from '../errors/appError';

/** 校验通过才进 controller；失败即抛 AppError(400 INVALID_INPUT)。 */
export function validateBody(schema: ZodTypeAny) {
  return async (ctx: Context, next: Next): Promise<void> => {
    const parsed = schema.safeParse(ctx.request.body);
    if (!parsed.success) {
      const detail = parsed.error.issues
        .map((i) => `${i.path.join('.') || 'body'}: ${i.message}`)
        .join('; ');
      throw AppError.invalidInput(detail);
    }
    ctx.state.dto = parsed.data;
    await next();
  };
}
```

```ts
// src/middleware/traceId.middleware.ts
import { randomUUID } from 'node:crypto';
import type { Context, Next } from 'koa';
import { TRACE_ID_HEADER } from '../config/constants';   // header 名单点定义在 constants
import { logger } from '../util/logger';

/**
 * traceId 贯穿（spec §2.8）。
 * 前端生成 → BFF 兜底生成 → 写入 ctx.state → 回写响应头 → 透传给下游。
 */
export async function traceIdMiddleware(ctx: Context, next: Next): Promise<void> {
  const incoming = ctx.get(TRACE_ID_HEADER).trim();
  const traceId = incoming === '' ? randomUUID() : incoming;

  ctx.state.traceId = traceId;
  ctx.state.log = logger.child({ traceId });   // 日志与 traceId 绑定
  ctx.set(TRACE_ID_HEADER, traceId);
  await next();
}
```

```ts
// src/middleware/errorHandler.middleware.ts
import type { Context, Next } from 'koa';
import { AppError } from '../errors/appError';
import { mapUpstreamError } from '../errors/mapUpstream';
import { logger } from '../util/logger';
import { TRACE_ID_HEADER } from '../config/constants';
import { toErrorResponse } from '../util/response';

/**
 * 统一错误收口（spec §2.3）。必须是**最外层**中间件。
 * 不透传下游原始错误栈（spec §3.3）。
 */
export async function errorHandlerMiddleware(ctx: Context, next: Next): Promise<void> {
  try {
    await next();
  } catch (error) {
    const appError = error instanceof AppError ? error : mapUpstreamError(error);
    const traceId = ctx.state.traceId ?? ctx.get(TRACE_ID_HEADER);
    const log = ctx.state.log ?? logger;

    if (appError.status >= 500) log.error({ err: error, code: appError.code }, 'request failed');
    else log.warn({ err: error, code: appError.code }, 'request rejected');

    ctx.status = appError.status;
    ctx.body = toErrorResponse(appError, traceId);
  }
}
```

```ts
// src/middleware/rateLimit.middleware.ts
import type { Context, Next } from 'koa';
import { AppError } from '../errors/appError';

/**
 * ★ 预留骨架 —— 本期**不启用**（spec §1.4 Out of Scope；429 RATE_LIMITED 仅作为错误码存在）。
 * 启用条件：需要保护 BFF 入口不被刷时（例如公开部署）。
 * 生产实现请换成 Redis 令牌桶，进程内 Map 只在单实例下有效。
 */
export function createRateLimitMiddleware(opts: { capacity: number; refillPerSec: number }) {
  const buckets = new Map<string, { tokens: number; updatedAt: number }>();
  return async (ctx: Context, next: Next): Promise<void> => {
    const key = ctx.ip;
    const now = Date.now();
    const bucket = buckets.get(key) ?? { tokens: opts.capacity, updatedAt: now };
    bucket.tokens = Math.min(opts.capacity, bucket.tokens + ((now - bucket.updatedAt) / 1000) * opts.refillPerSec);
    bucket.updatedAt = now;

    if (bucket.tokens < 1) {
      buckets.set(key, bucket);
      ctx.set('Retry-After', '1');
      throw new AppError(429, 'RATE_LIMITED', '请求过于频繁，请稍后重试');
    }
    bucket.tokens -= 1;
    buckets.set(key, bucket);
    await next();
  };
}
```

#### (7) route / container / app：接线与装配

```ts
// src/route/index.ts
import Router from '@koa/router';
import type { AnalysisController } from '../controller/analysis.controller';
import type { JobController } from '../controller/job.controller';
import { analyzeRequestSchema } from '../dto/request/analysis.request';
import { validateBody } from '../middleware/validate.middleware';

/** 路由层只做「路径 → controller」接线，不出现业务判断。 */
export function createApiRouter(deps: {
  analysis: AnalysisController;
  job: JobController;
}): Router {
  const router = new Router();

  router.get('/healthz', (ctx) => { ctx.body = { status: 'ok', service: 'bff' }; });
  router.get('/api/jobs', deps.job.list);
  router.post('/api/analysis', validateBody(analyzeRequestSchema), deps.analysis.analyze);

  return router;
}
```

```ts
// src/container.ts
import { createAnalyzerClient } from './client/analyzer.client';
import { createJobServiceClient } from './client/jobService.client';
import { AnalysisController } from './controller/analysis.controller';
import { JobController } from './controller/job.controller';
import { createAnalysisService } from './service/analysis.service';
import { createJobService } from './service/job.service';

/**
 * ★ 组合根：全项目**唯一** new 具体实现的地方（ADR-006：Koa2 没有 DI 容器，靠这一层补偿）。
 * 依赖从外向内手工装配，测试时替换任意一层即可。
 */
export function buildContainer() {
  const jobServiceClient = createJobServiceClient();
  const analyzerClient = createAnalyzerClient();

  const jobService = createJobService({ jobService: jobServiceClient });
  const analysisService = createAnalysisService({ jobService: jobServiceClient, analyzer: analyzerClient });

  return {
    jobServiceClient,
    analyzerClient,
    controllers: {
      job: new JobController(jobService),
      analysis: new AnalysisController(analysisService),
    },
  };
}
```

```ts
// src/app.ts
import Koa from 'koa';
import bodyParser from 'koa-bodyparser';
import { buildContainer } from './container';
import { errorHandlerMiddleware } from './middleware/errorHandler.middleware';
import { requestLogMiddleware } from './middleware/requestLog.middleware';
import { traceIdMiddleware } from './middleware/traceId.middleware';
import { createApiRouter } from './route';

/**
 * 组装 Koa app（不 listen，测试可直接喂 app.callback()）。
 * 中间件顺序（洋葱模型）：errorHandler（最外）→ traceId → 访问日志 → bodyParser → 路由
 */
export function createApp(container = buildContainer()): Koa {
  const app = new Koa();
  app.silent = true; // 关掉 Koa 自带错误输出，统一走 errorHandler

  app.use(errorHandlerMiddleware);
  app.use(traceIdMiddleware);
  app.use(requestLogMiddleware);
  app.use(bodyParser());

  const router = createApiRouter(container.controllers);
  app.use(router.routes()).use(router.allowedMethods());

  return app;
}
```

#### (8) config / constants / util

```ts
// src/config/constants.ts
/** 集中常量，避免魔法值散落（也便于单测引用）。 */
export const TRACE_ID_HEADER = 'X-Trace-Id';
export const API_PREFIX = '/api';

/** 超时矩阵 —— 对齐 plan.md §6.1，改这里必须同步改 plan.md */
export const TIMEOUT_MS = {
  jobService: 5_000,
  analyzer: 45_000,
} as const;
```

```ts
// src/util/response.ts
import type { AppError } from '../errors/appError';
import type { ErrorResponse } from '../dto/response/error.response';

/** 统一**错误**响应封装。成功响应直接返回业务对象，不套壳（见 §6.7）。 */
export function toErrorResponse(error: AppError, traceId: string): ErrorResponse {
  return { code: error.code, message: error.message, traceId };
}
```

### 2.4 依赖注入：手写容器是刻意的

`ADR-006` 已明确：**3 小时预算下熟悉度优先**，Koa2 的代价就是"没有 DI 与装饰器"。补偿手段是**目录约定 + 单一组合根**：

| 需求 | 不引 inversify 的做法 |
|---|---|
| 全局单例 | `container.ts` 里 new 一次并复用 |
| 测试替换 | 工厂函数参数注入（`createApp(container)`） |
| 生命周期 | 无（BFF 全部无状态，不需要） |
| 循环依赖 | 工厂函数由外向内传入，结构上无法成环 |

> **选型对照**：`inversify` / `tsyringe` 能给你 `@injectable()` 与自动解析，但在 4 个 controller 的规模下，收益 < 配置成本，且会引入 `reflect-metadata` 与 `experimentalDecorators` 两处编译配置。**引入条件**：controller 超过 ~10 个，或出现跨 service 的共享状态。

### 2.5 测试策略

```ts
// tests/unit/analysis.service.test.ts
import { AppError } from '../../src/errors/appError';
import { createAnalysisService } from '../../src/service/analysis.service';

/** 纯单测：注入 stub，不启 HTTP，不起下游。 */
describe('AnalysisService.analyze', () => {
  const analyzerStub = {
    analyze: async ({ traceId }: { traceId: string }) => ({
      resume: { sections: { education: [], experience: [], projects: [], skills: [] }, skills: [] },
      issues: [], match: { score: 0, matched: [], missing: [] },
      meta: { traceId, llmUsed: false, degraded: true, elapsedMs: 1 },
    }),
  };
  const jobServiceStub = {
    listJobs: async () => [],
    getJob: async () => ({ id: 'job-java-01', title: 'Java', company: 'X', level: '校招', jdText: 'JD-原文' }),
  };

  it('jobId 场景：先取 jdText 再调 analyzer（plan §1.1 时序）', async () => {
    const seen: string[] = [];
    const svc = createAnalysisService({
      jobService: jobServiceStub,
      analyzer: { analyze: async (i) => { seen.push(i.jdText); return analyzerStub.analyze(i); } },
    });
    await svc.analyze({ resumeText: '简历', jobId: 'job-java-01' }, 't-1');
    expect(seen).toEqual(['JD-原文']);
  });

  it('简历超长 → 400 RESUME_TOO_LONG（spec §2.3）', async () => {
    const svc = createAnalysisService({ jobService: jobServiceStub, analyzer: analyzerStub });
    await expect(svc.analyze({ resumeText: 'x'.repeat(20_001), jdText: 'j' }, 't-1'))
      .rejects.toMatchObject({ status: 400, code: 'RESUME_TOO_LONG' });
  });

  it('meta.traceId 以本层为准，保证全链一致', async () => {
    const svc = createAnalysisService({ jobService: jobServiceStub, analyzer: analyzerStub });
    const r = await svc.analyze({ resumeText: '简历', jdText: 'jd' }, 'trace-x');
    expect(r.meta.traceId).toBe('trace-x');
  });
});
```

```ts
// tests/e2e/analysis.test.ts
import request from 'supertest';
import { createApp } from '../../src/app';
import { AppError } from '../../src/errors/appError';

/** e2e：喂 app.callback()，验证「校验 → 编排 → 响应」与错误映射。 */
describe('POST /api/analysis', () => {
  const container = {
    jobServiceClient: {} as never, analyzerClient: {} as never,
    controllers: {
      job: { list: async () => undefined } as never,
      analysis: { analyze: async (ctx: any) => { ctx.body = { resume: {}, issues: [], match: {}, meta: {} }; } } as never,
    },
  };

  it('空 resumeText → 400 INVALID_INPUT（AC2）', async () => {
    const res = await request(createApp(container as never).callback())
      .post('/api/analysis').send({ resumeText: '', jobId: 'job-java-01' });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe('INVALID_INPUT');
  });

  it('错误响应体固定为 { code, message, traceId }（spec §2.3）', async () => {
    const res = await request(createApp(container as never).callback())
      .post('/api/analysis').send({ resumeText: 'a' });
    expect(Object.keys(res.body).sort()).toEqual(['code', 'message', 'traceId']);
    expect(res.body.traceId).toBe(res.headers['x-trace-id']);
  });
});
```

**分层测试矩阵**

| 层级 | 工具 | 测什么 | 不测什么 |
|---|---|---|---|
| Service 单测 | Jest | 编排顺序、不变量、DTO 裁剪 | HTTP 状态码 |
| Middleware 单测 | Jest | 校验失败、traceId 生成/透传 | 业务分支 |
| Controller/e2e | Jest + supertest | 状态码、响应体形状、错误映射表 | 下游真实行为（用 stub） |
| 全链冒烟 | `scripts/smoke.sh` | 四服务连通 + traceId 贯穿 | 业务精度 |

### 2.6 安全与性能要点（BFF 视角）

| 项 | 做法 | 依据 |
|---|---|---|
| 无超时调用 | `AbortSignal.timeout` 强制；code review 检查 `fetch(` 是否带 signal | spec §3.3 |
| 错误栈外泄 | 只返回 `{code,message,traceId}`，`message` 是**预置文案**而非 `err.message` | spec §3.3 |
| 请求体大小 | `koa-bodyparser({ jsonLimit: '512kb' })`；`resumeText` 另有 20000 字符上限 | 防御性 |
| CORS | 开发走 Vite 代理（同源）；生产由 Nginx 同域反代。**不开 `*`** | plan §1 |
| 限流 | 见 `rateLimit.middleware.ts`（预留，429） | spec §2.3 |
| 密钥 | 只读环境变量，`config/env.ts` 校验失败即 `exit(1)`，不带病启动 | spec §3.3 |
| 下游裁剪 | 只把契约字段返回给前端，不透传下游的额外字段 | ADR-005 |

### 2.7 推荐依赖与版本

| 用途 | 已选（plan §2 冻结） | 版本 | 说明 |
|---|---|---|---|
| Web 框架 | `koa` + `@koa/router` | 2.15.x / 13.1.x | ADR-006：3h 预算下熟悉度优先 |
| 请求体解析 | `koa-bodyparser` | 4.4.x | **P1 新增**：`validateBody` 中间件依赖它 |
| 校验 | `zod` | 3.23.x | 与 TS 类型同源（`z.infer`），比 `class-validator` 少一层装饰器配置 |
| HTTP 客户端 | **Node 内置 undici**（全局 `fetch`） | 内置 | 不引第三方库；超时用 `AbortSignal.timeout` |
| 日志 | `pino` | 8.21.x | 结构化 JSON，`logger.child({traceId})` 天然支持请求级上下文 |
| 配置 | `dotenv` | 16.4.x | 只读环境变量，不写默认凭据 |
| 开发运行 | `tsx` | 4.19.x | `tsx watch` 免编译热重载 |
| 类型 / 构建 | `typescript` | 5.6.x | `tsc -p tsconfig.json` 做 build 与 type-check |
| 测试 | `jest` + `ts-jest` + `supertest` | 29.7 / 29.2 / 7.0 | `supertest(app.callback())` 不用起端口 |
| Lint | `eslint` + `@typescript-eslint/*` | 9.x / 8.x | plan §9.2 的 lint 项 |

**选型对照：为什么不用这些**

| 候选 | 不用的理由 | 引入条件 |
|---|---|---|
| **class-validator + class-transformer** | 需要 `experimentalDecorators` + `emitDecoratorMetadata` 两处编译配置，且"类 + 装饰器"与 `zod` 的"schema 即类型"重复；zod 还能直接产出 TS 类型（`z.infer`），少维护一份 interface | DTO 数量 > 20 且需要大量继承时 |
| **inversify / tsyringe** | 4 个 controller 的规模下，配置成本 > 收益；且引入 `reflect-metadata` 增加启动开销。`container.ts` 已覆盖"单例 + 可替换"两个核心需求（§2.4） | controller > 10 个，或出现跨 service 共享状态 |
| **winston** | `pino` 性能更好且默认输出 JSON；winston 的 transport 体系在本项目是纯负担 | 需要多路输出（文件 + 云日志 + 告警）时 |
| **axios** | 全局 `fetch` 已能满足；axios 额外带来拦截器抽象，而本项目的超时/透传逻辑需要显式可见（便于 code review 检查"有没有漏超时"） | 需要请求重试 / 代理 / 取消令牌编排时 |
| **NestJS** | plan §2 列为**备选**，ADR-006 已决策用 Koa2 | 项目周期从 3h 变成 3 周时，NestJS 的 Pipe/Guard/Interceptor 天然对口分层 |
| **@koa/cors** | 开发走 Vite 代理（同源），生产同域反代，**不需要开 CORS** | 前后端分域部署时（注意：只放行白名单 origin，禁止 `*`） |

---

## 3. Spring Boot job-service 分层（apps/job-service）

> 定位复述（spec §2.6）：**岗位 JD 与技能词典领域 API、DTO 契约、服务编排、持久化**。
> 禁止：文本算法、直接调用 LLM。

### 3.1 完整目录结构（目标态）

```
apps/job-service/
├─ pom.xml
├─ README.md
├─ src/main/java/com/careerlens/jobservice/
│  ├─ JobServiceApplication.java
│  ├─ config/
│  │  ├─ properties/
│  │  │  ├─ AppProperties.java              # careerlens.*
│  │  │  └─ StorageProperties.java          # app.storage.*
│  │  ├─ StorageModeEnvironmentPostProcessor.java  # ★ auto 探测（装配期决策，ADR-007）
│  │  ├─ WebConfig.java                     # 拦截器注册（鉴权预留位）
│  │  ├─ RestClientConfig.java              # 下游 analyzer 客户端
│  │  └─ OpenApiConfig.java                 # springdoc 分组与信息
│  ├─ controller/                           # ① 控制层（按业务划分子包）
│  │  ├─ health/HealthController.java       # GET /healthz（含 storage 字段）
│  │  ├─ job/JobController.java             # GET /api/jobs, /api/jobs/{id}
│  │  ├─ skill/SkillController.java         # GET /api/skills
│  │  └─ internal/InternalController.java   # GET /internal/ping（非契约探针）
│  ├─ service/                              # ② 业务层
│  │  ├─ JobService.java                    # 接口
│  │  ├─ SkillService.java
│  │  └─ impl/{JobServiceImpl.java, SkillServiceImpl.java}
│  ├─ dto/                                  # ④ 数据传输对象
│  │  ├─ request/                           # 本期无写接口 → 仅预留
│  │  └─ response/
│  │     ├─ JobResponse.java                # { id, title, company, level, jdText }
│  │     ├─ SkillResponse.java              # { canonical, aliases[], category }
│  │     ├─ HealthResponse.java             # { status, storage }
│  │     └─ ApiErrorResponse.java           # { code, message, traceId }
│  ├─ mapper/                               # DTO ↔ Entity
│  │  ├─ JobMapper.java
│  │  └─ SkillMapper.java
│  ├─ entity/                               # PO（与库表一一对应）
│  │  ├─ JobEntity.java
│  │  └─ SkillEntity.java
│  ├─ repository/                           # ③ 数据访问层（ADR-007 抽象）
│  │  ├─ JobRepository.java                 # 领域接口（Service 只认它）
│  │  ├─ SkillRepository.java
│  │  ├─ jpa/                               # mysql + local 共用
│  │  │  ├─ JpaJobRepository.java
│  │  │  ├─ JpaSkillRepository.java
│  │  │  ├─ JobJpaRepository.java           # extends JpaRepository<JobEntity,String>
│  │  │  └─ SkillJpaRepository.java
│  │  └─ memory/                            # mock 兜底
│  │     ├─ InMemoryJobRepository.java
│  │     └─ InMemorySkillRepository.java
│  ├─ exception/
│  │  ├─ ErrorCode.java                     # 与 spec §2.3 对齐的枚举
│  │  ├─ BusinessException.java
│  │  └─ GlobalExceptionHandler.java
│  ├─ client/AnalyzerClient.java
│  └─ web/filter/TraceIdFilter.java         # MDC traceId
├─ src/main/resources/
│  ├─ application.yml
│  ├─ application-mysql.yml / application-local.yml / application-mock.yml
│  ├─ logback-spring.xml                    # logstash-encoder 结构化 JSON
│  ├─ META-INF/spring.factories             # 注册 EnvironmentPostProcessor
│  └─ db/
│     ├─ mysql/schema.sql                   # 主路径
│     ├─ h2/schema.sql                      # 降级
│     └─ seed.sql                           # 两模式共用（幂等）
└─ src/test/java/com/careerlens/jobservice/
   ├─ unit/
   │  ├─ service/JobServiceImplTest.java     # Mockito 注入内存 Repository
   │  └─ mapper/JobMapperTest.java
   ├─ web/HealthControllerTest.java          # @WebMvcTest 切片
   ├─ web/JobControllerTest.java             # @WebMvcTest + @MockBean
   ├─ repository/JpaJobRepositoryTest.java   # @DataJpaTest（local/H2）
   ├─ storage/StorageFallbackTest.java       # ★ AC9 / AC10 双模式
   └─ JobServiceApplicationTests.java
```

**与 plan.md §7 的关系**：`db/{mysql,h2,seed}.sql` 的位置与 `plan.md` §7 完全一致；本指南只细化 `src/main/java` 下的包结构。

### 3.2 各层职责与反模式

| 层 | 必须做 | 禁止做 | 常见反模式 |
|---|---|---|---|
| Controller | `@Valid` 接收、调 Service、返回 DTO | 写业务、注入 Repository、`try/catch` 业务异常 | ❌ Controller 返回 `JobEntity`；❌ Controller 里 `jobRepository.findAll()` |
| Service | 业务规则、编排、事务边界、Entity→DTO | 依赖 `HttpServletRequest`、返回 Entity、拼 JSON | ❌ Service 返回 `JobEntity`（懒加载炸 + 泄漏表结构） |
| Repository | 只做数据访问，返回 Entity / Optional | 业务判断、DTO 转换 | ❌ Repository 里 `if (job.level.equals("校招"))` |
| Mapper | 纯函数式转换，无副作用 | 查库、调下游 | ❌ Mapper 里注入 Repository 补字段 |
| Entity | 与表一一对应 | 加展示字段（`scoreText`）、加业务方法 | ❌ Entity 里塞 `@JsonProperty("jd_text")` 只为省一次映射 |
| Exception | 领域抛 `BusinessException`，边界收口 | 在 Service 里 `ResponseEntity` | ❌ Service 抛 `HttpStatus.NOT_FOUND` 相关类型 |

### 3.3 代码示例

#### (1) Entity（PO，与 `db/mysql/schema.sql` 逐列对应）

```java
package com.careerlens.jobservice.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * PO：与 db/mysql/schema.sql 的 job 表一一对应（plan §4.2）。
 * 字段名用 camelCase，列名用 snake_case，靠 @Column 显式绑定 —— 不依赖命名策略猜测。
 */
@Entity
@Table(name = "job")
public class JobEntity {

    @Id
    @Column(name = "id", length = 32, nullable = false)
    private String id;

    @Column(name = "title", length = 128, nullable = false)
    private String title;

    @Column(name = "company", length = 128)
    private String company;

    @Column(name = "level", length = 32)
    private String level;

    /** 对应 TEXT；JD 原文用于双向证据定位（spec §2.4 AC5）。 */
    @Column(name = "jd_text", nullable = false, columnDefinition = "TEXT")
    private String jdText;

    protected JobEntity() { }   // JPA 需要无参构造，声明 protected 防止被业务代码 new

    public JobEntity(String id, String title, String company, String level, String jdText) {
        this.id = id; this.title = title; this.company = company; this.level = level; this.jdText = jdText;
    }

    public String getId() { return id; }
    public String getTitle() { return title; }
    public String getCompany() { return company; }
    public String getLevel() { return level; }
    public String getJdText() { return jdText; }
    // 本期只读预置数据（spec §2.9），因此不提供 setter —— 从类型层面阻止写路径
}
```

#### (2) Repository 抽象：接口 + 两实现 + 装配期决策（ADR-007）

```java
package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.entity.JobEntity;
import java.util.List;
import java.util.Optional;

/**
 * 领域接口 —— Service 只依赖它（ADR-007）。
 * 方法刻意只有**只读**操作（spec §2.9：岗位与技能词典为只读预置数据）。
 */
public interface JobRepository {
    List<JobEntity> findAllJobs();
    Optional<JobEntity> findJobById(String id);
}
```

```java
package com.careerlens.jobservice.repository.jpa;

import com.careerlens.jobservice.entity.JobEntity;
import org.springframework.data.jpa.repository.JpaRepository;

/** Spring Data JPA 派生接口，不对外暴露（只有 JpaJobRepository 会用到它）。 */
public interface JobJpaRepository extends JpaRepository<JobEntity, String> { }
```

```java
package com.careerlens.jobservice.repository.jpa;

import com.careerlens.jobservice.entity.JobEntity;
import com.careerlens.jobservice.repository.JobRepository;
import java.util.List;
import java.util.Optional;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

/**
 * mysql 与 local 模式共用本实现 —— 两者只差 DataSource URL，Repository 层无需区分。
 * mock 模式不装配本 Bean（见 InMemoryJobRepository）。
 */
@Repository
@ConditionalOnProperty(name = "app.storage.mode", havingValue = "mock", matchIfMissing = true)
public class JpaJobRepository implements JobRepository {

    private final JobJpaRepository jpa;

    public JpaJobRepository(JobJpaRepository jpa) { this.jpa = jpa; }

    @Override
    public List<JobEntity> findAllJobs() { return jpa.findAll(); }

    @Override
    public Optional<JobEntity> findJobById(String id) { return jpa.findById(id); }
}
```

> ⚠️ 上面 `havingValue = "mock", matchIfMissing = true` 的语义是"**除 mock 之外都装配**"。写成反向条件更易读的做法是自定义 `@ConditionalOnStorageMode` 注解（`@ConditionalOnProperty` 不支持"不等于"）。落地时二选一：
> - **方案 A（推荐，零额外代码）**：`JpaJobRepository` 用 `@ConditionalOnProperty(name = "app.storage.mode", havingValue = "mysql")` + 再复制一份给 `local`（两个 Bean 名不同，实现体共用同一个 `JpaJobRepository` 父类）。
> - **方案 B（更干净）**：自定义 `@ConditionalOnStorageMode({"mysql","local"})`，内部用 `Condition` 实现"在集合内则匹配"。

```java
package com.careerlens.jobservice.repository.memory;

import com.careerlens.jobservice.entity.JobEntity;
import com.careerlens.jobservice.repository.JobRepository;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Repository;

/**
 * mock 兜底（plan §4.4）：MySQL 与 H2 同时不可用时，演示链路依然完整（AC10）。
 * Mock 数据**只允许存在于 Java 层**（spec §3.1）。
 */
@Repository
@ConditionalOnProperty(name = "app.storage.mode", havingValue = "mock")
public class InMemoryJobRepository implements JobRepository {

    private static final List<JobEntity> MOCK_JOBS = List.of(
        new JobEntity("job-java-01", "Java 后端开发", "示例科技", "校招",
            "岗位职责：负责后端服务开发。任职要求：熟悉 Java、Spring Boot、MySQL、Redis，了解 Docker。"),
        new JobEntity("job-frontend-01", "前端开发工程师", "示例科技", "校招",
            "任职要求：熟悉 JavaScript、TypeScript、Vue 3，了解 Vite 与前端工程化。")
    );

    private final Map<String, JobEntity> byId = MOCK_JOBS.stream()
        .collect(Collectors.toMap(JobEntity::getId, Function.identity()));

    @Override
    public List<JobEntity> findAllJobs() { return new ArrayList<>(MOCK_JOBS); }

    @Override
    public Optional<JobEntity> findJobById(String id) { return Optional.ofNullable(byId.get(id)); }
}
```

#### (3) 存储模式探测：装配期决策（`plan.md` §6.3 / ADR-007）

```java
package com.careerlens.jobservice.config;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

/**
 * app.storage.mode=auto 时的启动探测（plan §6.3）：
 *   mysql（重试 3×2s）→ local（H2）→ mock
 * 把探测结果写回 Environment，让后续的 DataSource / Repository 装配**基于已定模式**，
 * 从而做到「降级是装配期决策，而不是运行期 if/else」（ADR-007）。
 *
 * 注册方式：src/main/resources/META-INF/spring.factories
 *   org.springframework.boot.env.EnvironmentPostProcessor=com.careerlens.jobservice.config.StorageModeEnvironmentPostProcessor
 */
public class StorageModeEnvironmentPostProcessor implements EnvironmentPostProcessor, Ordered {

    private static final Logger log = LoggerFactory.getLogger(StorageModeEnvironmentPostProcessor.class);

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment env, SpringApplication application) {
        String requested = env.getProperty("app.storage.mode", "auto");
        if (!"auto".equalsIgnoreCase(requested)) {
            // 显式指定（演示 / 测试）：跳过探测，失败即启动失败，绝不静默降级（plan §6.3）
            log.info("storage mode explicitly set to '{}', skip probing", requested);
            return;
        }

        String resolved = probe(env);
        Map<String, Object> overrides = new LinkedHashMap<>();
        overrides.put("app.storage.mode", resolved);
        overrides.put("app.storage.effective", resolved);

        if ("mock".equals(resolved)) {
            // mock 模式不需要 DataSource，排除 JPA 自动装配，避免启动时去找数据库
            overrides.put("spring.autoconfigure.exclude",
                "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,"
              + "org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration");
        } else if ("local".equals(resolved)) {
            overrides.put("spring.datasource.url",
                "jdbc:h2:mem:careerlens;MODE=MySQL;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE");
            overrides.put("spring.sql.init.schema-locations", "classpath:db/h2/schema.sql");
        } else {
            overrides.put("spring.sql.init.schema-locations", "classpath:db/mysql/schema.sql");
        }

        // addFirst：必须优先于 application.yml 中的默认值
        env.getPropertySources().addFirst(new MapPropertySource("careerlensStorageProbe", overrides));
        log.warn("storage mode auto-resolved to '{}'", resolved);
    }

    private String probe(ConfigurableEnvironment env) {
        String url = "jdbc:mysql://%s:%s/%s?createDatabaseIfNotExist=true&useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true"
            .formatted(env.getProperty("MYSQL_HOST", "localhost"),
                       env.getProperty("MYSQL_PORT", "3306"),
                       env.getProperty("MYSQL_DATABASE", "careerlens"));
        for (int attempt = 1; attempt <= 3; attempt++) {
            try (Connection ignored = DriverManager.getConnection(
                    url, env.getProperty("MYSQL_USER", "root"), env.getProperty("MYSQL_PASSWORD", ""))) {
                env.getPropertySources().addFirst(new MapPropertySource("careerlensDatasource",
                    Map.of("spring.datasource.url", url)));
                return "mysql";
            } catch (Exception e) {
                log.warn("mysql probe attempt {}/3 failed: {}", attempt, e.getMessage());
                sleep();
            }
        }
        return "local";   // H2 是本地依赖，几乎不会失败；真失败则由 spring.sql.init 抛错 → 手工切 mock
    }

    private void sleep() {
        try { Thread.sleep(2_000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    @Override
    public int getOrder() { return Ordered.LOWEST_PRECEDENCE; }
}
```

```java
package com.careerlens.jobservice.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * app.storage.* —— 对应 spec §2.9 的三档降级与 .env 的 STORAGE_MODE。
 *
 * @param mode      auto | mysql | local | mock（默认 auto）
 * @param effective 实际生效模式，由 StorageModeEnvironmentPostProcessor 写入，/healthz 读它
 */
@ConfigurationProperties(prefix = "app.storage")
public record StorageProperties(String mode, String effective) { }
```

```yaml
# src/main/resources/application.yml（关键片段）
server:
  port: ${JOB_SERVICE_PORT:8080}
  shutdown: graceful

spring:
  application:
    name: job-service
  sql:
    init:
      mode: always                     # 幂等 schema + seed（plan §4.2）
      schema-locations: classpath:db/mysql/schema.sql   # 被探测器按模式覆盖
      data-locations: classpath:db/seed.sql
      continue-on-error: false
  jpa:
    hibernate:
      ddl-auto: validate               # 校验实体与 schema.sql 是否一致（plan §9.2）
    open-in-view: false                # ★ 关闭 OSIV：强制在 Service 内完成 Entity→DTO 映射
    properties:
      hibernate.jdbc.batch_size: 30

app:
  storage:
    mode: ${STORAGE_MODE:auto}

careerlens:
  version: 0.1.0
  analyzer:
    base-url: ${ANALYZER_URL:http://localhost:8000}
    timeout-ms: ${ANALYZER_TIMEOUT_MS:45000}

logging:
  level:
    root: ${LOG_LEVEL:INFO}
```

#### (4) DTO：request / response 严格分离

```java
package com.careerlens.jobservice.dto.response;

/**
 * GET /api/jobs 的响应元素 —— 与 contracts/bff-java.yaml 逐字一致（plan §3.2）。
 * 用 record：不可变 + 自动 getter/equals，天然适合 DTO。
 */
public record JobResponse(String id, String title, String company, String level, String jdText) { }
```

```java
package com.careerlens.jobservice.dto.response;

import java.util.List;

/** GET /api/skills 的响应元素：{ canonical, aliases[], category }（plan §3.2）。 */
public record SkillResponse(String canonical, List<String> aliases, String category) { }
```

```java
package com.careerlens.jobservice.dto.response;

/** GET /healthz（spec §2.8）：storage 是存储降级的唯一可观测证据，**不进业务响应**。 */
public record HealthResponse(String status, String storage) { }
```

```java
package com.careerlens.jobservice.dto.response;

/** 统一**错误**响应体（spec §2.3）。成功响应直接返回业务 DTO，不套壳（见 §6.7）。 */
public record ApiErrorResponse(String code, String message, String traceId) { }
```

#### (5) Mapper：Entity → DTO 的唯一通道

```java
package com.careerlens.jobservice.mapper;

import com.careerlens.jobservice.dto.response.JobResponse;
import com.careerlens.jobservice.entity.JobEntity;

/**
 * Entity ↔ DTO 转换。
 * 本期字段少（5 个），手写即可 —— 引入 MapStruct 的成本高于收益（见 §3.11 选型对照）。
 * 铁律：Entity 永不离开 Repository，DTO 永不出现在 Repository。
 */
public final class JobMapper {

    private JobMapper() { }

    public static JobResponse toResponse(JobEntity entity) {
        return new JobResponse(
            entity.getId(), entity.getTitle(), entity.getCompany(), entity.getLevel(), entity.getJdText());
    }
}
```

#### (6) Service：接口 + 实现 + 事务边界

```java
package com.careerlens.jobservice.service;

import com.careerlens.jobservice.dto.response.JobResponse;
import java.util.List;

/** Service 只返回 DTO，不返回 Entity —— 否则 OSIV 一关就会炸，且会泄漏表结构。 */
public interface JobService {
    List<JobResponse> listJobs();
    JobResponse getJob(String id);
}
```

```java
package com.careerlens.jobservice.service.impl;

import com.careerlens.jobservice.dto.response.JobResponse;
import com.careerlens.jobservice.exception.BusinessException;
import com.careerlens.jobservice.exception.ErrorCode;
import com.careerlens.jobservice.mapper.JobMapper;
import com.careerlens.jobservice.repository.JobRepository;
import com.careerlens.jobservice.service.JobService;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JobServiceImpl implements JobService {

    private final JobRepository jobRepository;

    public JobServiceImpl(JobRepository jobRepository) {   // ★ 构造器注入，字段 final
        this.jobRepository = jobRepository;
    }

    /**
     * readOnly = true：本期全是只读查询（spec §2.9），显式声明能让 Hibernate 跳过脏检查，
     * 也让"这里不该写库"成为代码事实。
     */
    @Override
    @Transactional(readOnly = true)
    public List<JobResponse> listJobs() {
        return jobRepository.findAllJobs().stream().map(JobMapper::toResponse).toList();
    }

    @Override
    @Transactional(readOnly = true)
    public JobResponse getJob(String id) {
        return jobRepository.findJobById(id)
            .map(JobMapper::toResponse)
            .orElseThrow(() -> new BusinessException(ErrorCode.JOB_NOT_FOUND, "岗位不存在：" + id));
    }
}
```

#### (7) Controller：`@Valid` + 只调 Service

```java
package com.careerlens.jobservice.controller.job;

import com.careerlens.jobservice.dto.response.JobResponse;
import com.careerlens.jobservice.service.JobService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 控制层：只做 HTTP ↔ DTO 的转换，无业务判断、无 try/catch。
 * 路径与 contracts/bff-java.yaml 一致（plan §3.2）。
 */
@RestController
@RequestMapping("/api/jobs")
public class JobController {

    private final JobService jobService;

    public JobController(JobService jobService) { this.jobService = jobService; }

    @GetMapping
    public List<JobResponse> list() { return jobService.listJobs(); }

    @GetMapping("/{id}")
    public JobResponse detail(@PathVariable String id) { return jobService.getJob(id); }
}
```

```java
package com.careerlens.jobservice.controller.health;

import com.careerlens.jobservice.config.properties.StorageProperties;
import com.careerlens.jobservice.dto.response.HealthResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** spec §2.8：/healthz 必须额外暴露 storage，作为存储降级的唯一可观测证据。 */
@RestController
public class HealthController {

    private final StorageProperties storageProperties;

    public HealthController(StorageProperties storageProperties) { this.storageProperties = storageProperties; }

    @GetMapping("/healthz")
    public HealthResponse healthz() {
        return new HealthResponse("ok", storageProperties.effective());
    }
}
```

#### (8) 异常：错误码枚举 + 业务异常 + 全局收口

```java
package com.careerlens.jobservice.exception;

/**
 * 与 spec §2.3 对齐的错误码（冻结）。
 * 命名规则见 §6.2；**不得**新增"数据库不可用"类错误码 —— 存储降级在 Java 层内部消化（plan §6.4）。
 */
public enum ErrorCode {
    INVALID_INPUT(400),
    RESUME_TOO_LONG(400),
    JOB_NOT_FOUND(404),
    ANALYSIS_FAILED(422),
    RATE_LIMITED(429),
    SERVICE_UNAVAILABLE(503),
    UPSTREAM_TIMEOUT(504),
    INTERNAL_ERROR(500);

    private final int httpStatus;

    ErrorCode(int httpStatus) { this.httpStatus = httpStatus; }

    public int httpStatus() { return httpStatus; }
}
```

```java
package com.careerlens.jobservice.exception;

/** 领域业务异常：Service 只抛它，不抛任何 HTTP 相关类型。 */
public class BusinessException extends RuntimeException {

    private final ErrorCode errorCode;

    public BusinessException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public ErrorCode errorCode() { return errorCode; }
}
```

```java
package com.careerlens.jobservice.exception;

import com.careerlens.jobservice.dto.response.ApiErrorResponse;
import com.careerlens.jobservice.web.filter.TraceIdFilter;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.NoHandlerFoundException;

/**
 * 统一错误收口（spec §2.3）。响应体固定 { code, message, traceId }。
 * 禁止向前端透传原始错误栈（spec §3.3）。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiErrorResponse> handleBusiness(BusinessException ex) {
        log.warn("business exception: code={}, message={}", ex.errorCode(), ex.getMessage());
        return build(ex.errorCode(), ex.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        String detail = ex.getBindingResult().getFieldErrors().stream()
            .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
            .collect(Collectors.joining("; "));
        log.warn("validation failed: {}", detail);
        return build(ErrorCode.INVALID_INPUT, detail.isEmpty() ? "请求参数校验失败" : detail);
    }

    @ExceptionHandler(NoHandlerFoundException.class)
    public ResponseEntity<ApiErrorResponse> handleNotFound(NoHandlerFoundException ex) {
        return build(ErrorCode.JOB_NOT_FOUND, "资源不存在");
    }

    /** 兜底：任何未预期异常都收口为 500，且只回固定文案（不透传 ex.getMessage()）。 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiErrorResponse> handleUnexpected(Exception ex) {
        log.error("unexpected error", ex);
        return build(ErrorCode.INTERNAL_ERROR, "服务内部错误");
    }

    private ResponseEntity<ApiErrorResponse> build(ErrorCode code, String message) {
        ApiErrorResponse body = new ApiErrorResponse(code.name(), message, MDC.get(TraceIdFilter.MDC_KEY));
        return ResponseEntity.status(code.httpStatus()).body(body);
    }
}
```

#### (9) Filter / Interceptor：traceId 与鉴权预留位

```java
// src/main/java/com/careerlens/jobservice/web/filter/TraceIdFilter.java
// （现有实现已符合要求，保持不动）读取 X-Trace-Id → MDC → 回写响应头 → finally 清理 MDC
```

```java
package com.careerlens.jobservice.config;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * ★ 鉴权拦截器 —— 本期**不启用**（spec §1.4：用户注册 / 登录 / 鉴权为 Out of Scope）。
 * 保留骨架是为了让"将来往哪儿加"有明确答案：
 *   - 校验只发生在**最外层**（BFF 或本服务入口），Python 层永不做鉴权（spec §2.6）
 *   - 密钥（jwt_key）只存在于服务端环境变量，**绝不下发到前端、绝不硬编码**
 *   - 无状态 token 认不出冒用 / 踢不掉人 → 需要时引入白名单或 jti 版本号
 * 启用步骤：实现 preHandle → 在 WebConfig 里 addInterceptors 注册 → 加 .env 的 JWT_SECRET。
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // TODO(auth)：解析 Authorization: Bearer <token>，校验签名与过期，写入请求上下文。
        // 未启用时直接放行。
        return true;
    }
}
```

```java
package com.careerlens.jobservice.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** Web 层装配：拦截器注册、CORS 策略（生产同域反代，不开 *）。 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final AuthInterceptor authInterceptor;

    public WebConfig(AuthInterceptor authInterceptor) { this.authInterceptor = authInterceptor; }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 本期不注册（authInterceptor 恒返回 true）；启用时取消注释即可
        // registry.addInterceptor(authInterceptor).addPathPatterns("/api/**");
    }
}
```

#### (10) 分页模板（本期**不启用**）

```java
package com.careerlens.jobservice.dto.response;

import java.util.List;

/**
 * ★ 通用分页响应模板 —— 本期三个领域接口**刻意不分页**（plan §4.2：表只有几十行，连索引都没建）。
 * 引入判据（满足任一即应分页）：
 *   1. 单表行数 > 1000，或接口返回数组长度不可预估
 *   2. 出现"列表页 + 滚动加载"这类真实 UI 需求
 *   3. 单次响应体 > 100KB
 * 引入方式：Controller 增加 @RequestParam(defaultValue="0") int page 等，Service 接收 Pageable。
 */
public record PageResponse<T>(List<T> items, int page, int size, long total, int totalPages) {

    public static <T> PageResponse<T> of(org.springframework.data.domain.Page<T> page) {
        return new PageResponse<>(page.getContent(), page.getNumber(), page.getSize(),
            page.getTotalElements(), page.getTotalPages());
    }
}
```

### 3.4 依赖注入与装配

| 机制 | 用途 | 本项目实例 |
|---|---|---|
| 构造器注入 | **唯一推荐**方式（字段 `final`，缺失即启动失败） | `JobServiceImpl(JobRepository)` |
| `@ConfigurationProperties` | 类型安全配置 | `AppProperties`、`StorageProperties` |
| `@ConditionalOnProperty` | 按存储模式选实现（ADR-007） | `JpaJobRepository` / `InMemoryJobRepository` |
| `EnvironmentPostProcessor` | 装配**之前**决定模式 | `StorageModeEnvironmentPostProcessor` |
| `@Profile` | 环境差异（可选，本项目用 mode 而非 profile 表达存储差异） | `application-mysql.yml` 等 |
| `@MockBean`（测试） | 替换下游 | `JobControllerTest` 里替换 `JobService` |

**反模式**：字段注入（`@Autowired` 直接标字段）→ 无法 final、测试要反射、掩盖循环依赖。**禁止**。

### 3.5 事务管理（本期只读，但规则要钉死）

```java
// ✅ 正确：事务边界在 Service
@Service
public class JobServiceImpl implements JobService {
    @Transactional(readOnly = true)          // 只读：跳过脏检查
    public List<JobResponse> listJobs() { ... }
}
```

| 规则 | 说明 |
|---|---|
| 事务边界在 **Service 方法** | Controller 上加 `@Transactional` 会让"一个 HTTP 请求 = 一个事务"，含序列化与网络时间，事务被无限拉长 |
| 只读查询加 `readOnly = true` | 明确语义 + Hibernate 跳过脏检查 + 便于将来切只读从库 |
| Repository 不加事务 | 交给上层，避免事务嵌套语义混乱 |
| `@Transactional` **自调用失效** | `this.otherMethod()` 不走代理 → 事务不生效。解法：拆到另一个 Bean，或注入自身代理 |
| 默认只对 `RuntimeException` 回滚 | 受检异常需显式 `rollbackFor = Exception.class` |
| 长事务是事故 | 事务内**禁止**调下游 HTTP（本项目 Java→Python 调用不在事务内） |

> **本期特殊性**：只有只读路径（spec §2.9），所以事务的实际价值是"语义声明 + 防止未来误加写操作"。唯一可能涉及写入的是 `seed.sql` 导入，那属于启动初始化，不走 Service 事务。

### 3.6 日志与 traceId

```xml
<!-- src/main/resources/logback-spring.xml 关键片段（现有文件已具备） -->
<encoder class="net.logstash.logback.encoder.LogstashEncoder">
  <includeMdcKeyName>traceId</includeMdcKeyName>   <!-- 每条日志自动带上 traceId -->
</encoder>
```

**关联方式**：`TraceIdFilter` 写入 MDC → LogstashEncoder 自动输出 → `grep '"traceId":"xxx"'` 即可捞出一次请求在**四个服务**里的全部日志（因为 header 一路透传）。

### 3.7 测试策略

```java
// src/test/java/com/careerlens/jobservice/unit/service/JobServiceImplTest.java
@ExtendWith(MockitoExtension.class)
class JobServiceImplTest {

    @Mock private JobRepository jobRepository;     // 接口 mock —— 不需要数据库（ADR-007 的收益）
    @InjectMocks private JobServiceImpl jobService;

    @Test
    void getJob_不存在时抛 JOB_NOT_FOUND() {
        given(jobRepository.findJobById("nope")).willReturn(Optional.empty());

        BusinessException ex = assertThrows(BusinessException.class, () -> jobService.getJob("nope"));
        assertThat(ex.errorCode()).isEqualTo(ErrorCode.JOB_NOT_FOUND);
    }

    @Test
    void listJobs_返回 DTO 而非 Entity() {
        given(jobRepository.findAllJobs()).willReturn(List.of(
            new JobEntity("job-java-01", "Java 后端开发", "示例科技", "校招", "JD 原文")));

        assertThat(jobService.listJobs()).singleElement()
            .extracting(JobResponse::id, JobResponse::jdText)
            .containsExactly("job-java-01", "JD 原文");
    }
}
```

```java
// src/test/java/com/careerlens/jobservice/web/JobControllerTest.java
@WebMvcTest(controllers = {JobController.class, HealthController.class, GlobalExceptionHandler.class})
@Import(TraceIdFilter.class)
class JobControllerTest {

    @Autowired private MockMvc mockMvc;
    @MockBean private JobService jobService;
    @MockBean private StorageProperties storageProperties;

    @Test
    void list_返回契约字段() throws Exception {
        given(jobService.listJobs()).willReturn(List.of(
            new JobResponse("job-java-01", "Java 后端开发", "示例科技", "校招", "JD")));

        mockMvc.perform(get("/api/jobs"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].id").value("job-java-01"))
            .andExpect(jsonPath("$[0].jdText").value("JD"));
    }

    @Test
    void detail_岗位不存在时返回 404 JOB_NOT_FOUND() throws Exception {
        given(jobService.getJob("nope")).willThrow(new BusinessException(ErrorCode.JOB_NOT_FOUND, "岗位不存在"));

        mockMvc.perform(get("/api/jobs/nope"))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("JOB_NOT_FOUND"))
            .andExpect(jsonPath("$.traceId").exists());
    }
}
```

```java
// src/test/java/com/careerlens/jobservice/repository/JpaJobRepositoryTest.java
@DataJpaTest   // 默认走嵌入式 H2；用 db/h2/schema.sql + db/seed.sql 初始化
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class JpaJobRepositoryTest {
    @Autowired private JobJpaRepository jpa;

    @Test
    void seed 数据已导入且实体映射与 schema 一致() {
        assertThat(jpa.findAll()).hasSize(3);
    }
}
```

**分层测试矩阵**

| 层 | 注解 / 工具 | 覆盖 | 依赖 |
|---|---|---|---|
| Service | `@ExtendWith(MockitoExtension.class)` | 业务规则、异常分支 | 无（Mock Repository） |
| Mapper | 纯 JUnit | 字段一一对应 | 无 |
| Controller | `@WebMvcTest` | 路由、状态码、错误体 | Mock Service |
| Repository | `@DataJpaTest` | 实体↔schema 一致性、seed | H2 |
| 装配 | `@SpringBootTest` + 三种 `STORAGE_MODE` | AC9 / AC10 双模式 | MySQL（CI 里用 `services:`） |

> `plan.md` §9.2 要求 job-service 跑**两组**测试（mysql 模式 + local/mock 模式），否则降级路径一定会烂掉。

### 3.8 安全与性能要点（Java 视角）

| 项 | 做法 |
|---|---|
| SQL 注入 | 一律 JPA / 参数化；禁止字符串拼 SQL。原生 SQL 必须用 `?` 占位 |
| 凭据 | 连接串只来自环境变量；日志**不打印** url/密码（spec §3.3）；`spring.jpa.show-sql` 生产关闭 |
| 敏感字段 | 本期无用户数据；将来加用户表时，密码只存 bcrypt/argon2 哈希（**绝不 MD5**），DTO 不含密码字段 |
| 参数校验 | `@Valid` + Bean Validation；`@PathVariable` 用 `@Pattern` 限定 id 格式，避免无意义查库 |
| N+1 | 本期无关联查询；将来加关联时用 `@EntityGraph` 或 `join fetch` |
| 连接池 | HikariCP（默认）；`maximum-pool-size` 与 DB `max_connections` 对齐；mock 模式下无池 |
| 缓存 | **本期不做**。岗位词典变化频率极低，但只有几十行，缓存的收益 < 一致性成本。引入判据：单接口 P99 > 50ms 且 QPS > 100 |
| OSIV | 关闭（`spring.jpa.open-in-view: false`）—— 强制在 Service 内完成 Entity→DTO，避免"视图层触发懒加载查询" |
| 索引 | 刻意不建（plan §4.2），答辩用 `EXPLAIN` 说明判断依据 |

### 3.9 推荐依赖与版本

| 用途 | 已选（plan §2 冻结） | 版本 | 说明 |
|---|---|---|---|
| Web / 校验 / 测试 | `spring-boot-starter-web`、`-validation`、`-test` | Boot 3.2.5 | — |
| 持久化 | `spring-boot-starter-data-jpa` + `mysql-connector-j` + `h2`（runtime） | 随 Boot | h2 用 `runtime` scope，仅降级用 |
| 结构化日志 | `logstash-logback-encoder` | 7.4 | 现有 pom 已有 |
| API 文档 | `springdoc-openapi-starter-webmvc-ui` | 2.5.x | plan §2 已选，答辩现场展示 |

**选型对照：为什么不用这些**

| 候选 | 不用的理由 | 引入条件 |
|---|---|---|
| **Lombok** | Java 17 的 `record` 已覆盖 DTO 场景；Entity 需要无参构造 + 受控 setter，Lombok 的 `@Data` 反而会生成 setter 破坏"只读"语义；且 Lombok 与 IDE/编译期插件的耦合是隐性成本 | Entity 字段 > 20 个时再考虑 `@Getter` |
| **MapStruct** | 5 个字段的映射，手写 Mapper 共 6 行；MapStruct 需要注解处理器配置 + 生成代码进构建产物 | 映射字段 > 10 个，或映射器 > 5 个 |
| **MyBatis** | plan §2 已定 JPA；JPA 的 `ddl-auto: validate` 能自动校验实体与 `schema.sql` 是否漂移 | 出现复杂多表动态查询 |
| **Spring Security** | spec §1.4 明确 Out of Scope；引入会强制打开一套 filter chain 与默认登录页，纯消耗 | 出现真实鉴权需求时（见 §3.3-(9) 的预留设计） |
| **Redis 缓存** | 数据量 3 行、变化频率≈0 | 见 §3.8 缓存引入判据 |

---

## 4. FastAPI analyzer 分层（apps/analyzer）

> 定位复述（spec §2.6）：**清洗、归一化、匹配打分、LLM 编排与降级**。
> 禁止：鉴权、岗位数据 CRUD、直连数据库。

### 4.1 完整目录结构（目标态）

```
apps/analyzer/
├─ requirements.txt
├─ pytest.ini
├─ pyproject.toml                    # ruff / pytest 配置（可选）
├─ README.md
├─ app/
│  ├─ main.py                        # FastAPI 实例 + 路由注册 + 异常处理器 + lifespan
│  ├─ core/
│  │  ├─ config.py                   # Settings（pydantic-settings）
│  │  ├─ constants.py                # 长度上限 / 权重 / 枚举（与 spec §2.4 对齐）
│  │  ├─ exceptions.py               # AppException + ErrorCode
│  │  ├─ exception_handlers.py       # 统一错误收口
│  │  ├─ logging.py                  # 结构化 JSON 日志 + traceId 注入
│  │  ├─ trace.py                    # contextvar + TraceIdMiddleware
│  │  ├─ dependencies.py             # ★ Depends 工厂（单例装配）
│  │  └─ resources.py                # skills.yaml 加载（lru_cache）
│  ├─ api/                           # ① 控制层
│  │  └─ v1/
│  │     ├─ health.py                # GET /healthz
│  │     └─ internal.py              # POST /internal/analyze, GET /internal/ping
│  ├─ schema/                        # ④ DTO
│  │  ├─ request/analyze_request.py
│  │  └─ response/
│  │     ├─ analyze_response.py      # 四块结构（spec §2.2，冻结）
│  │     ├─ error_response.py
│  │     └─ health_response.py
│  ├─ service/                       # ② 业务层 + ③ 纯计算模块
│  │  ├─ analysis_service.py         # 编排：清洗 → 归一化 → 匹配 → LLM
│  │  ├─ cleaner.py                  # 切分 教育/工作/项目/技能
│  │  ├─ normalizer.py               # raw → canonical
│  │  ├─ matcher.py                  # 加权覆盖率打分 + 双向证据
│  │  └─ rules.py                    # 5 类简历问题规则
│  ├─ llm/                           # LLM 接入与降级（ADR-004）
│  │  ├─ client.py
│  │  └─ prompts.py
│  ├─ data/skills.yaml               # 技能词典（canonical + aliases + category）
│  └─ util/response.py
└─ tests/
   ├─ conftest.py
   ├─ unit/
   │  ├─ test_cleaner.py
   │  ├─ test_normalizer.py          # 覆盖 AC6
   │  ├─ test_matcher.py             # 覆盖 AC4 / AC7
   │  └─ test_rules.py               # 覆盖 AC8
   └─ api/
      ├─ test_health.py
      ├─ test_internal.py            # 覆盖 AC3（LLM 降级）
      └─ test_contract_shape.py      # 契约形状快照
```

**相对当前骨架的变化**：`routers/` → `api/v1/`；`models.py` 拆到 `schema/{request,response}/`；`logging_setup.py` → `core/logging.py`；新增 `core/{constants,exceptions,exception_handlers,trace,dependencies,resources}.py`、`service/`、`llm/`、`data/`。

> ⚠️ **注意这里没有 `model/` 与 `repository/`**。analyzer 不拥有任何数据库（spec §2.6 / §3.1），技能词典是**随代码分发的只读 YAML 资源**，由 `core/resources.py` 加载，不属于持久层。同理没有 `auth/`。

### 4.2 各层职责与反模式

| 层 | 必须做 | 禁止做 | 常见反模式 |
|---|---|---|---|
| api (router) | 声明路径/入参/出参、`Depends` 取依赖、调 Service | 写算法、读文件、拼 SQL | ❌ router 里 `re.findall(...)` |
| service | 编排三步链、组装 DTO、决定降级 | 依赖 `Request` 对象、返回裸 dict | ❌ Service 直接 `raise HTTPException` |
| 纯计算模块 | 单一职责的纯函数（输入→输出，可确定性复现） | 读环境变量、发网络请求、写日志之外有副作用 | ❌ `matcher.py` 里 `os.environ` |
| schema | 定义并校验契约形状 | 混入业务逻辑、混入 ORM | ❌ `@field_validator` 里做打分 |
| core | 横切（配置/日志/异常/依赖） | 依赖 `service` 层 | ❌ `core/config.py` import `service.matcher` |

**关键反模式：Service 直接抛 `HTTPException`**。这会把 HTTP 语义渗进业务层，导致：① 算法单测要造 HTTP 上下文；② 换传输层（例如改成 CLI/队列消费者）就要改业务代码。正确做法是抛 `AppException`，由 `exception_handlers.py` 翻译成 HTTP。

### 4.3 代码示例

#### (1) schema：请求 / 响应分离（Pydantic v2）

```python
# app/schema/request/analyze_request.py
from typing import Optional
from pydantic import BaseModel, Field

from app.core.constants import JD_MAX_LENGTH, RESUME_MAX_LENGTH


class AnalyzeRequest(BaseModel):
    """BFF → analyzer 的内部请求（plan §3.3）。

    内部接口只收**已解析好的 jdText** —— analyzer 不认 jobId，也就不可能去查岗位数据（spec §2.6）。
    """

    resumeText: str = Field(min_length=1, max_length=RESUME_MAX_LENGTH)
    jdText: str = Field(min_length=1, max_length=JD_MAX_LENGTH)
    traceId: Optional[str] = None
```

```python
# app/schema/response/analyze_response.py
from typing import Literal, Optional
from pydantic import BaseModel, Field

IssueType = Literal["NO_QUANTIFY", "NO_STAR", "SKILL_STUFFING", "TIMELINE_GAP", "MISSING_CONTACT"]
Severity = Literal["high", "medium", "low"]
Importance = Literal["required", "preferred"]


class NormalizedSkill(BaseModel):
    raw: str
    canonical: str
    category: Optional[str] = None


class ResumeView(BaseModel):
    sections: dict[str, list[str]] = Field(
        default_factory=lambda: {"education": [], "experience": [], "projects": [], "skills": []}
    )
    skills: list[NormalizedSkill] = Field(default_factory=list)


class Issue(BaseModel):
    """对简历**本身**的诊断，与 JD 无关（spec §2.10 术语表）。"""

    type: IssueType
    severity: Severity
    evidence: str
    suggestion: str


class MatchedItem(BaseModel):
    """命中项必须带双向原文证据，否则不算「可解释」（AC5）。"""

    skill: str
    importance: Importance
    weight: float
    jdEvidence: str
    resumeEvidence: str
    jdOffset: Optional[int] = None
    resumeOffset: Optional[int] = None


class MissingItem(BaseModel):
    skill: str
    importance: Importance
    suggestion: str


class MatchResult(BaseModel):
    score: int
    matched: list[MatchedItem] = Field(default_factory=list)
    missing: list[MissingItem] = Field(default_factory=list)


class Meta(BaseModel):
    """llmUsed / degraded 必须保留 —— 是降级能力的唯一证据（spec §2.2）。"""

    traceId: str
    llmUsed: bool = False
    degraded: bool = True
    elapsedMs: int = 0


class AnalyzeResponse(BaseModel):
    """spec §2.2 响应契约（冻结）：字段名 / 层级 / 类型不可改。"""

    resume: ResumeView
    issues: list[Issue] = Field(default_factory=list)
    match: MatchResult
    meta: Meta
```

```python
# app/schema/response/error_response.py
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """统一**错误**响应体（spec §2.3）。成功响应不使用它（见 §6.7）。"""

    code: str
    message: str
    traceId: str
```

#### (2) core：常量 / 异常 / 异常处理器 / 追踪

```python
# app/core/constants.py
"""与 spec §2.4 对齐的常量。改这里必须同步 spec 与三份契约。"""

RESUME_MAX_LENGTH = 20_000      # spec §2.1
JD_MAX_LENGTH = 8_000           # spec §2.1

WEIGHT_REQUIRED = 1.0           # ADR-002：加权覆盖率
WEIGHT_PREFERRED = 0.5

SCORE_MIN, SCORE_MAX = 0, 100
```

```python
# app/core/exceptions.py
from enum import Enum


class ErrorCode(str, Enum):
    """与 spec §2.3 对齐（冻结）。BFF 按 HTTP 状态码二次映射（plan §6.4）。"""

    INVALID_INPUT = "INVALID_INPUT"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppException(Exception):
    """领域异常：业务层只抛它，由 exception_handlers 翻译成 HTTP。"""

    def __init__(self, code: ErrorCode, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
```

```python
# app/core/exception_handlers.py
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException, ErrorCode
from app.core.trace import get_trace_id

logger = logging.getLogger(__name__)


def _body(code: str, message: str) -> dict:
    return {"code": code, "message": message, "traceId": get_trace_id()}


def register_exception_handlers(app: FastAPI) -> None:
    """统一错误收口（spec §2.3）。不透传原始错误栈（spec §3.3）。"""

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        logger.warning("app exception: code=%s message=%s", exc.code.value, exc.message)
        return JSONResponse(status_code=exc.http_status, content=_body(exc.code.value, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic 校验失败 → 400 INVALID_INPUT（长度超限也算这一类）
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors()
        )
        logger.warning("validation failed: %s", detail)
        return JSONResponse(status_code=400, content=_body(ErrorCode.INVALID_INPUT.value, detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected error", exc_info=exc)
        return JSONResponse(status_code=500, content=_body(ErrorCode.INTERNAL_ERROR.value, "分析服务内部错误"))
```

```python
# app/core/trace.py
from contextvars import ContextVar
from typing import Optional
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

TRACE_ID_HEADER = "X-Trace-Id"

# contextvar 而非全局变量：async 并发下每个请求有独立上下文
_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def get_trace_id() -> str:
    return _trace_id.get() or str(uuid.uuid4())


class TraceIdMiddleware(BaseHTTPMiddleware):
    """读取上游 X-Trace-Id，缺失则生成；写入 contextvar 并回写响应头（spec §2.8）。"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())
        token = _trace_id.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            _trace_id.reset(token)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
```

```python
# app/core/logging.py
import json
import logging
import sys

from app.core.trace import _trace_id


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志（spec §2.8），每条自动带上 traceId。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "service": "analyzer",
            "message": record.getMessage(),
            "logger": record.name,
            "traceId": _trace_id.get(),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
```

#### (3) core：依赖注入（`Depends` 工厂）

```python
# app/core/resources.py
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import settings

SKILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "skills.yaml"


@lru_cache
def get_skill_dictionary() -> dict:
    """技能词典随代码分发、进程内只读一次（analyzer 无数据库，spec §2.6）。

    lru_cache = 进程级单例；测试里可用 get_skill_dictionary.cache_clear() 重置。
    """
    with SKILLS_PATH.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp)
```

```python
# app/core/dependencies.py
from functools import lru_cache

from app.core.config import settings
from app.core.resources import get_skill_dictionary
from app.llm.client import LlmClient, create_llm_client
from app.service.analysis_service import AnalysisService, create_analysis_service


@lru_cache
def get_llm_client() -> LlmClient:
    """LLM 客户端单例。未配置时返回一个"永不启用"的客户端，由 Service 决定降级（ADR-004）。"""
    return create_llm_client(settings)


@lru_cache
def get_analysis_service() -> AnalysisService:
    """
    ★ 组合根：全项目唯一装配具体实现的地方。
    FastAPI 的 Depends 没有自动装配，靠这里显式组装 —— 与 BFF 的 container.ts 是同一个思路。
    """
    return create_analysis_service(
        dictionary=get_skill_dictionary(),
        llm=get_llm_client(),
    )
```

#### (4) service：编排 + 纯计算模块

```python
# app/service/analysis_service.py
import time
from typing import Protocol

from app.core.constants import WEIGHT_PREFERRED, WEIGHT_REQUIRED
from app.llm.client import LlmClient
from app.schema.request.analyze_request import AnalyzeRequest
from app.schema.response.analyze_response import (
    AnalyzeResponse, MatchResult, Meta, ResumeView,
)
from app.service import cleaner, matcher, normalizer, rules


class AnalysisService(Protocol):
    def analyze(self, request: AnalyzeRequest, trace_id: str) -> AnalyzeResponse: ...


def create_analysis_service(*, dictionary: dict, llm: LlmClient) -> AnalysisService:
    """组合根注入依赖；本函数是唯一把各模块接起来的地方。"""

    class _AnalysisService:
        def analyze(self, request: AnalyzeRequest, trace_id: str) -> AnalyzeResponse:
            started = time.perf_counter()

            # spec §2.5 处理链顺序（冻结）：清洗 → 归一化 → 匹配，严格串行
            cleaned = cleaner.clean(request.resumeText)
            skills = normalizer.normalize(cleaned.skills_raw, dictionary)
            resume = ResumeView(sections=cleaned.sections, skills=skills)

            # 简历问题：纯规则，与 JD 无关
            issues = rules.detect(request.resumeText, cleaned)

            # 匹配：加权覆盖率 + 双向证据（ADR-002）
            jd_skills = normalizer.normalize(matcher.extract_jd_skills(request.jdText, dictionary), dictionary)
            match: MatchResult = matcher.match(jd_skills, skills, weights=(WEIGHT_REQUIRED, WEIGHT_PREFERRED))

            # LLM 只做两件事：① 技能抽取兜底 ② suggestion 措辞（ADR-004）
            llm_used, degraded = False, False
            try:
                if llm.enabled:
                    match = llm.enrich_suggestions(match)
                    llm_used = True
                else:
                    degraded = True   # 未配置 = 主动降级，不是错误
            except Exception:          # 超时 / 报错 / 非法 JSON（Pydantic 校验失败）→ 全部降级
                degraded = True            # AC3：仍返回完整四块结果

            return AnalyzeResponse(
                resume=resume,
                issues=issues,
                match=match,
                meta=Meta(
                    traceId=trace_id,
                    llmUsed=llm_used,
                    degraded=degraded,
                    elapsedMs=int((time.perf_counter() - started) * 1000),
                ),
            )

    return _AnalysisService()
```

```python
# app/service/normalizer.py
"""技能归一化：raw → canonical（AC6）。纯函数，无副作用，无 IO。"""


def normalize(raw_skills: list[str], dictionary: dict) -> list[dict]:
    """把自由文本技能映射到标准词表；未登录词保留 raw 并标 category=None（不阻断，plan §10）。"""
    alias_index: dict[str, dict] = {}
    for entry in dictionary.get("skills", []):
        canonical = entry["canonical"]
        for alias in [canonical, *entry.get("aliases", [])]:
            alias_index[alias.strip().lower()] = entry

    result: list[dict] = []
    for raw in raw_skills:
        hit = alias_index.get(raw.strip().lower())
        result.append({
            "raw": raw,
            "canonical": hit["canonical"] if hit else raw,
            "category": hit.get("category") if hit else None,
        })
    return result
```

#### (5) api：router + Depends

```python
# app/api/v1/internal.py
import logging

from fastapi import APIRouter, Depends, Header
from typing import Optional

from app.core.dependencies import get_analysis_service
from app.core.trace import get_trace_id
from app.schema.request.analyze_request import AnalyzeRequest
from app.schema.response.analyze_response import AnalyzeResponse

router = APIRouter(tags=["internal"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    service=Depends(get_analysis_service),          # ★ 依赖注入：不 new，不从全局拿
    x_trace_id: Optional[str] = Header(default=None, alias="X-Trace-Id"),
) -> AnalyzeResponse:
    """分析入口（plan §3.3）。

    控制层只做三件事：声明契约、取依赖、把结果交给序列化。
    没有算法、没有 try/except（异常交给 exception_handlers）。
    """
    trace_id = x_trace_id or payload.traceId or get_trace_id()
    logger.info("analyze requested (resume=%d, jd=%d)", len(payload.resumeText), len(payload.jdText))
    return service.analyze(payload, trace_id)
```

```python
# app/api/v1/health.py
from fastapi import APIRouter

from app.core.config import settings
from app.schema.response.health_response import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """spec §2.8：每个服务暴露 GET /healthz。"""
    return HealthResponse(service=settings.service_name)
```

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import health, internal
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.trace import TraceIdMiddleware

setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    import logging
    logging.getLogger(__name__).info("analyzer starting (llm_enabled=%s)", settings.llm_enabled)
    yield
    logging.getLogger(__name__).info("analyzer stopped")


app = FastAPI(title="CareerLens Analyzer", version=settings.version, lifespan=lifespan)

app.add_middleware(TraceIdMiddleware)      # traceId 必须最外层
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(internal.router, prefix="/internal")   # 内部接口统一前缀（plan §3.3）
```

#### (6) llm：接入与降级包装（ADR-004）

```python
# app/llm/client.py
from typing import Protocol

from app.core.config import Settings
from app.schema.response.analyze_response import MatchResult


class LlmClient(Protocol):
    enabled: bool
    def enrich_suggestions(self, match: MatchResult) -> MatchResult: ...


class _DisabledLlm:
    """未配置 LLM 时的空实现：enabled=False，Service 会直接走规则分支。"""

    enabled = False

    def enrich_suggestions(self, match: MatchResult) -> MatchResult:  # pragma: no cover
        return match


class _OpenAiLlm:
    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI
        self.enabled = True
        # 密钥只来自环境变量（spec §3.3）；base_url 可配（plan §2 选型）
        self._client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,   # 禁止无超时的外部调用（spec §3.3）
        )
        self._model = settings.llm_model

    def enrich_suggestions(self, match: MatchResult) -> MatchResult:
        # 让 LLM 生成更自然的建议措辞；解析失败/超时由 Service 捕获并降级
        ...
        return match


def create_llm_client(settings: Settings) -> LlmClient:
    return _OpenAiLlm(settings) if settings.llm_enabled else _DisabledLlm()
```

### 4.4 依赖注入：`Depends` + `lru_cache`

| 需求 | 做法 |
|---|---|
| 请求级依赖 | `Depends(get_analysis_service)` —— 每个请求解析一次，可被 `app.dependency_overrides` 替换 |
| 进程级单例 | `@lru_cache` 装饰工厂（词典、LLM 客户端） |
| 测试替换 | `app.dependency_overrides[get_analysis_service] = lambda: fake` |
| 生命周期资源 | `lifespan` 里初始化 / 释放（本期无长连接，留空） |

```python
# tests/conftest.py
import pytest
from app.core.dependencies import get_analysis_service
from app.main import app


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def override_service(fake_service):
    """用依赖覆盖替换真实 Service —— 测试不碰词典文件、不碰 LLM。"""
    app.dependency_overrides[get_analysis_service] = lambda: fake_service
    yield
    app.dependency_overrides.clear()
```

> **选型对照**：`dependency-injector` 等容器库能做 wiring 与作用域，但 FastAPI 的 `Depends` 已经覆盖"请求级 + 可覆盖"两个核心需求，且**零配置**。引入容器会在 3h 预算里净亏损。

### 4.5 测试策略

```python
# tests/unit/test_matcher.py
from app.schema.response.analyze_response import MatchedItem, MissingItem
from app.service import matcher


def _skill(canonical: str, category: str = "framework") -> dict:
    return {"raw": canonical, "canonical": canonical, "category": category}


def test_score_等于加权覆盖率():
    """AC1/AC4：required=1.0，preferred=0.5（ADR-002）。"""
    jd = [_skill("Java"), _skill("Redis"), _skill("Vue")]
    resume = [_skill("Java"), _skill("Vue")]
    result = matcher.match(jd, resume, weights=(1.0, 0.5))

    # 命中 1.0(Java) + 1.0(Vue) = 2.0；全量 3.0 → 66.67 → 67
    assert result.score == 67
    assert {m.skill for m in result.matched} == {"Java", "Vue"}
    assert {m.skill for m in result.missing} == {"Redis"}


def test_集合自洽_AC7():
    """AC7：matched ∩ missing = ∅ 且 matched ∪ missing = JD 技能全集。"""
    jd = [_skill("Java"), _skill("Redis")]
    result = matcher.match(jd, [_skill("Java")], weights=(1.0, 0.5))

    matched = {m.skill for m in result.matched}
    missing = {m.skill for m in result.missing}
    assert matched & missing == set()
    assert matched | missing == {"Java", "Redis"}


def test_同输入两次结果一致_AC4():
    jd, resume = [_skill("Java"), _skill("Redis")], [_skill("Java")]
    a = matcher.match(jd, resume, weights=(1.0, 0.5))
    b = matcher.match(jd, resume, weights=(1.0, 0.5))
    assert a.score == b.score
    assert [m.skill for m in a.matched] == [m.skill for m in b.matched]
```

```python
# tests/api/test_internal.py
def test_llm_不可用时仍返回完整四块且_degraded_为_true(client):
    """AC3：LLM 不可用（未配置 / 超时 / 非法输出）仍返回完整结果。"""
    resp = client.post("/internal/analyze", json={
        "resumeText": "张三，3 年 Java 后端，负责订单中心。",
        "jdText": "熟悉 Java、Spring Boot、MySQL、Redis。",
        "traceId": "trace-ac3",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"resume", "issues", "match", "meta"}
    assert body["meta"]["degraded"] is True
    assert body["meta"]["traceId"] == "trace-ac3"


def test_超长简历返回_400_INVALID_INPUT(client):
    resp = client.post("/internal/analyze", json={"resumeText": "x" * 20_001, "jdText": "jd"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


def test_错误响应体形状固定(client):
    resp = client.post("/internal/analyze", json={"resumeText": "", "jdText": "jd"})
    assert set(resp.json()) == {"code", "message", "traceId"}
```

```python
# tests/api/test_contract_shape.py
def test_契约形状快照(client):
    """契约被改坏时这条用例会红 —— spec §2.2 的守卫。"""
    body = client.post("/internal/analyze", json={"resumeText": "简历", "jdText": "JD"}).json()
    assert set(body["resume"]["sections"]) == {"education", "experience", "projects", "skills"}
    assert set(body["match"]) == {"score", "matched", "missing"}
    assert set(body["meta"]) == {"traceId", "llmUsed", "degraded", "elapsedMs"}
```

**分层测试矩阵**

| 层 | 工具 | 覆盖 | 要点 |
|---|---|---|---|
| 纯计算模块 | 纯 pytest | AC4 / AC6 / AC7 / AC8 | 纯函数 → 无 mock、极快、可穷举边界 |
| Service | pytest + 假词典/假 LLM | 编排顺序、降级分支 | 用 `dependency_overrides` 或直接构造 |
| api | `TestClient` | 状态码、错误体、契约形状 | 覆盖 AC3 |
| 并发 | `httpx.AsyncClient` + `ASGITransport` | traceId 在并发下不串号 | contextvar 的关键验证 |

> **选型对照**：`pytest-asyncio` 用于异步用例；若全用 `TestClient`（同步封装），可不引入。

### 4.6 安全与性能要点（Python 视角）

| 项 | 做法 | 依据 |
|---|---|---|
| LLM 密钥 | 只来自环境变量；`Settings` 里 `llm_api_key` 绝不进日志；报错信息不含 key | spec §3.3 |
| 无超时调用 | `OpenAI(timeout=...)` 必填；降级分支兜底 | spec §3.3 |
| 输入上限 | Pydantic `max_length` 拦截 20000 / 8000，**在进入算法前**挡住 | spec §2.1 |
| 正则灾难性回溯 | 用户可控文本上的正则避免嵌套量词；先截断长度再匹配 | 性能 |
| 事件循环阻塞 | 纯 CPU 的正则/循环在毫秒级，直接 `async def` 内同步执行可接受；若单次 > 100ms，改 `def`（FastAPI 自动丢线程池） | 性能 |
| LLM 成本 | LLM 只做措辞与兜底抽取，核心链路走规则（ADR-004）→ 单次调用可控 | 成本 |
| 确定性 | 算法不用随机数、不依赖字典遍历顺序（排序后再比对）→ 满足 AC4 | spec §2.4 |
| 依赖安全 | 锁定 `requirements.txt` 版本；不引入重型 NLP（spec §3.2） | plan §2 |

### 4.7 推荐依赖与版本

| 用途 | 已选（plan §2 冻结） | 版本 | 说明 |
|---|---|---|---|
| Web | `fastapi` + `uvicorn[standard]` | 0.115.6 / 0.34.0 | 自带 OpenAPI，与契约体系对齐 |
| 校验 / 配置 | `pydantic` v2 + `pydantic-settings` | 2.10.4 / 2.7.0 | Pydantic v2 的校验失败即触发降级（ADR-004） |
| HTTP 客户端 | `httpx` | 0.28.1 | 测试用；LLM 走 `openai` SDK |
| LLM | `openai` | 1.x | `base_url` 可配（plan §2 选型） |
| 词典 | `PyYAML` | 6.x | `skills.yaml` 加载 |
| 测试 | `pytest`（+ 可选 `pytest-asyncio`） | 8.3.4 | — |
| Lint | `ruff` | latest | plan §9.2 的 lint 项 |

**选型对照：为什么不用这些**

| 候选 | 不用的理由 | 依据 |
|---|---|---|
| **SQLAlchemy 2.0** | analyzer **没有数据库**；岗位与技能数据由 Java 层提供，本层只收 `jdText` | spec §2.6 / §3.1 |
| **Alembic** | 无自有 schema 需要迁移；schema 归 Java 层 `db/` 目录管理 | plan §4 |
| **spaCy / 重型 NLP** | 题目明确禁止；镜像体积与安装时间都是净损失 | spec §3.2 |
| **Celery / 队列** | 本期无异步任务；超时与降级已覆盖可用性需求 | spec §1.4 |
| **JWT / 鉴权库** | Python 层禁止做鉴权 | spec §2.6 |

---

## 5. 跨框架对比

### 5.1 十二维度对比

| 维度 | Koa BFF | Spring Boot job-service | FastAPI analyzer |
|---|---|---|---|
| **控制层** | `controller/*.controller.ts`（class + 方法） | `@RestController` + `@RequestMapping` | `APIRouter` + 路径装饰器 |
| **业务层** | `service/*.service.ts`（工厂函数返回对象） | `Service` 接口 + `impl/` | `service/*_service.py`（工厂 + Protocol） |
| **DTO** | `dto/{request,response}`（zod schema + `z.infer`） | `dto/{request,response}`（record + Bean Validation） | `schema/{request,response}`（Pydantic v2） |
| **DTO↔Entity 映射** | Service 内对象字面量（无 Entity 概念） | `mapper/` 静态方法（或 MapStruct） | Pydantic `model_validate` |
| **依赖注入** | **手写组合根** `container.ts`（ADR-006 的代价） | 容器自动装配 + 构造器注入 + `@ConditionalOnProperty` | `Depends` + `lru_cache` + `dependency_overrides` |
| **参数校验** | zod（运行时）+ TS 类型（编译期），同源 | Bean Validation（`@Valid` + `@NotBlank` 等） | Pydantic v2（声明即校验） |
| **异常收口** | `errorHandler.middleware.ts`（最外层中间件） | `@RestControllerAdvice` + `@ExceptionHandler` | `app.exception_handler(...)` |
| **业务异常类型** | `AppError`（含 status + code） | `BusinessException`（含 `ErrorCode`） | `AppException`（含 `ErrorCode` + http_status） |
| **统一响应** | 成功=业务对象；错误=`{code,message,traceId}` | 同左 | 同左（三服务一致，§6.7） |
| **日志 & traceId** | pino + `logger.child({traceId})` | Logback + LogstashEncoder + MDC | `logging` + JSON Formatter + contextvar |
| **事务** | 无（无状态） | `@Transactional` 在 Service 方法上 | 无（无写入） |
| **测试** | Jest + supertest（`app.callback()`） | JUnit 5 + MockMvc 切片 + `@DataJpaTest` | pytest + TestClient |
| **API 文档** | 无（内部适配层，前端契约在 `contracts/`） | springdoc-openapi | FastAPI 自带 OpenAPI |

### 5.2 各框架最"别扭"的一点与补偿

| 框架 | 别扭之处 | 补偿手段 |
|---|---|---|
| Koa2 | **没有 DI、没有装饰器**，分层只能靠目录约定 | 单一组合根 `container.ts` + 工厂函数参数注入；测试用 `createApp(stubContainer)` |
| Koa2 | **没有内建校验**，`ctx.request.body` 是 `any` | zod schema + `validateBody` 中间件，把 `unknown` 收敛成 `ctx.state.dto` |
| Spring Boot | **默认 OSIV 打开**，Entity 会被悄悄带到视图层 | `spring.jpa.open-in-view: false` + Service 只返回 DTO |
| Spring Boot | **`@ConditionalOnProperty` 不支持"不等于"** | 自定义 `@ConditionalOnStorageMode({...})`，或按模式拆两个 Bean 名 |
| Spring Boot | **`@Transactional` 自调用失效** | 拆 Bean；或在测试里断言"代理确实生效" |
| FastAPI | **没有编译期类型检查**，`Depends` 返回类型靠注解 | `mypy` / `ruff` 可选；Service 用 `Protocol` 显式声明契约 |
| FastAPI | **`async def` 里写 CPU 密集会阻塞事件循环** | 单次 > 100ms 的计算改成 `def`（自动走线程池）；本期正则在毫秒级，保持 `async` |
| FastAPI | **Pydantic 模型易被当"业务模型"滥用** | schema 只描述形状，规则放 `service/rules.py`；`@field_validator` 里不写业务逻辑 |

### 5.3 统一设计原则（10 条，可执行判据）

| # | 原则 | 判据 / 自检问题 |
|---|---|---|
| 1 | **依赖单向向内** | Service 里能否 `import` Controller？不能 —— 能就是设计错了 |
| 2 | **Controller 只做 HTTP** | 把 HTTP 换掉（改成 CLI），这个函数还需要吗？不需要 → 它就该在 Controller |
| 3 | **Service 不认识框架** | Service 文件里能否 import `koa` / `HttpServletRequest` / `Request`？不能 |
| 4 | **Entity 不出 Repository** | 方法签名里有没有出现 `Entity` 类型？有 → 违规 |
| 5 | **DTO 是边界唯一语言** | 跨层传参是 DTO / 领域对象，还是裸 `dict` / `Map<String,Object>`？后者违规 |
| 6 | **依赖注入代替 new** | 业务代码里能否出现 `new XxxService()`？不能（只有组合根可以） |
| 7 | **异常分层**：领域抛业务异常，边界统一收口 | Service 里是否出现 HTTP 状态码？出现即违规 |
| 8 | **校验前置 + 不变量兜底** | 入口校验过了，Service 内是否仍守住关键不变量？（长度、二选一） |
| 9 | **无超时的外部调用 = bug** | 每处 `fetch` / `RestClient` / LLM 调用是否都有显式 timeout？ |
| 10 | **契约冻结 > 重构洁癖** | 这次重构会不会改动 spec §2.1 / §2.2 的字段？会 → 停，先走变更流程 |

---

## 6. 工程最佳实践

### 6.1 DTO / VO / BO / PO：区别与使用场景

| 类型 | 回答的问题 | 生命周期 | CareerLens 实例 | 存放位置 |
|---|---|---|---|---|
| **PO / Entity** | 数据在库里长什么样 | 持久层内部 | `JobEntity`（↔ 表 `job`） | Java `entity/` |
| **DTO** | 跨边界的字段约定是什么 | 一次调用 | `AnalyzeRequest`、`JobResponse`、`AnalyzeResponse` | 三服务的 `dto/` 或 `schema/` |
| **BO** | 领域计算过程中间态 | 一次算法 | Python `ScoredSkill`、`JobRequirementSet`；Java `WeightedSkill` | Service 内部，**不跨进程** |
| **VO** | 界面要渲染什么 | 一次渲染 | 前端 `PingResult`、`AnalyzeResultView`（含 `scoreText`、排序后的列表） | web `api/types.ts` 或组件内 |

**判定口诀**

```
要落库吗？        → PO
要过网络吗？      → DTO
只在算法里活着？  → BO
只为渲染服务？    → VO
```

**最容易犯的错**：把 VO 的需求（`scoreText: "78 分"`、`matchedSorted`）塞进 DTO。一旦塞进去，后端就被前端展示细节绑架了。正确做法是前端在 `utils/` 里算。

### 6.2 错误码规范设计

**命名规则**：`<领域/动作>_<失败原因>`，全大写下划线，**面向调用方的语义**而非实现细节。

| 规则 | 好例子 | 坏例子 | 原因 |
|---|---|---|---|
| 描述"发生了什么"，不描述"哪段代码出错" | `JOB_NOT_FOUND` | `JOB_REPOSITORY_RETURN_EMPTY` | 后者是实现细节，一重构就得改错误码 |
| 稳定，不随 HTTP 状态码变 | `INVALID_INPUT` 恒为 `INVALID_INPUT` | `ERROR_400` | 状态码可能调整，错误码是客户端契约 |
| 不出现基础设施细节 | （无） | `DB_UNAVAILABLE` | 存储降级在 Java 层内部消化（plan §6.4） |
| 不在错误码里带动态值 | `JOB_NOT_FOUND` + `message` 里带 id | `JOB_java_01_NOT_FOUND` | 会导致错误码爆炸 |

**本项目的错误码（spec §2.3 冻结）**

| HTTP | code | 抛出位置 | 客户端该做什么 |
|---|---|---|---|
| 400 | `INVALID_INPUT` | BFF（zod）/ Java（`@Valid`）/ Python（Pydantic） | 修正输入 |
| 400 | `RESUME_TOO_LONG` | BFF（Service 不变量） | 截断简历 |
| 404 | `JOB_NOT_FOUND` | Java（Service）→ BFF 映射 | 换岗位 |
| 422 | `ANALYSIS_FAILED` | Python → BFF 映射 | 重试 |
| 429 | `RATE_LIMITED` | BFF（预留） | 退避重试 |
| 503 | `SERVICE_UNAVAILABLE` | BFF（下游 5xx） | 重试 |
| 504 | `UPSTREAM_TIMEOUT` | BFF（下游超时） | 重试 |
| 500 | `INTERNAL_ERROR` | 任意层兜底 | 上报 traceId |

**两条降级链必须分清**（这是本项目最容易讲错的地方）

| 降级链 | 观测字段 | 触发 | 谁消化 |
|---|---|---|---|
| **LLM 降级** | `meta.degraded` / `meta.llmUsed` | LLM 超时 / 报错 / 输出非法 | Python 内部 |
| **存储降级** | Java `/healthz` 的 `storage` | MySQL 连不上 | Java 内部 |

> 两条链都**不产生错误码**，也**不改变响应结构**。区别只在观测字段：一个在业务响应里，一个只在 `/healthz` 里。

### 6.3 请求追踪 ID 与日志关联

**责任链**：前端生成（`crypto.randomUUID()`）→ BFF 兜底生成 → Java 兜底生成 → Python 兜底生成。**每一跳都读上游的、只在缺失时生成**，因此全链唯一。

| 环节 | 载体 | 代码位置 |
|---|---|---|
| HTTP header | `X-Trace-Id`（spec §2.8 冻结） | 所有服务 |
| Koa | `ctx.state.traceId` + `logger.child({traceId})` | `middleware/traceId.middleware.ts` |
| Java | `MDC.put("traceId", ...)` | `web/filter/TraceIdFilter.java` |
| Python | `ContextVar` | `core/trace.py` |
| 响应回写 | 每个服务都 `set(header)` | 三处 |
| 错误响应体 | `{ code, message, traceId }` | `errorHandler` / `@RestControllerAdvice` / `exception_handlers` |

**排障示例**：一次请求失败，前端拿到 `traceId = 3f9c...`，然后

```bash
docker compose logs | grep '3f9c'      # 一条命令捞出四个服务的全部相关日志
```

> **关键点**：traceId 必须**同时**出现在 ① 响应头 ② 错误响应体 ③ 每一行日志。少任何一个，排障链路就断了。

### 6.4 事务在 Service 层的正确使用

| 规则 | 说明 |
|---|---|
| 边界在 Service **public 方法**上 | Controller 上加 → 事务包含序列化 + 网络 IO，被无限拉长 |
| 查询加 `readOnly = true` | 语义声明 + 跳过脏检查 + 可切只读从库 |
| 事务内**禁止**调下游 | Java→Python 的 45s 调用绝不能在事务内（本项目天然满足：`InternalController` 无事务） |
| 自调用失效 | `this.a()` 不走代理 → 无事务。拆 Bean 或注入自身 |
| 默认只回滚 `RuntimeException` | 受检异常需 `rollbackFor = Exception.class` |
| 事务粒度尽量小 | 事务内只放必要的库操作 |
| 本期无写路径 | 唯一"写入"是启动时 `seed.sql` 导入，不走 Service 事务 |

```java
// ❌ 反例
public void bad() {
    this.doWrite();          // 自调用：@Transactional 失效，事务根本没开
}

// ✅ 正例
@Service
public class A {
    private final B b;
    public void good() { b.doWrite(); }   // 跨 Bean 调用，代理生效
}
```

### 6.5 循环依赖的避免

| 框架 | 表现 | 检测 | 解法 |
|---|---|---|---|
| Spring Boot | 启动报 `BeanCurrentlyInCreationException` | 启动即暴露（好事） | ① 抽公共 Service ② `@Lazy`（临时）③ 事件解耦（`ApplicationEventPublisher`）④ 重新审视职责划分 |
| Koa | 运行时 `undefined` / 部分初始化对象 | 单测里 stub 注入会立刻暴露 | 工厂函数由外向内传参，**结构上无法成环**；`container.ts` 是唯一装配点 |
| FastAPI | `Depends` 互相引用 → 请求时异常 | `dependency_overrides` 测试暴露 | 抽 `core/` 公共依赖；Service 之间不互相注入，改为编排在 `analysis_service` 里 |

**根治原则**：**依赖成环 = 职责划分错了**。环上一定存在一个"既属于 A 又属于 B"的职责，把它抽出来成为 C，环就断了。`@Lazy` 只是让报错延后，不是解法。

### 6.6 接口版本管理

**本项目的现状（刻意不做版本号）**

| 维度 | 现状 | 理由 |
|---|---|---|
| 对外契约 | `POST /api/analysis`（**无 v1**） | spec §2.1 已冻结路径；加 `/api/v1` 会让三份 OpenAPI 与 spec 不一致 |
| 消费者 | 只有自家前端一个 | 没有多版本并存的必要 |
| 内部契约 | `/internal/*` 前缀 | 语义上标明"不对外"（plan §3.3），比版本号更有用 |

**引入判据（满足任一即应引入）**

1. 出现**外部**消费者（第三方接入、App 与 Web 不同发布节奏）
2. 同一路径需要**不兼容**的两种响应结构并存
3. 客户端无法与后端同步发布（如已上架的小程序）

**引入方式（不破坏现有客户端）**

```
Phase 1  新逻辑挂在 /api/v2/*，/api/v1/* 保留旧实现（或旧实现内部转调 v2 做适配）
Phase 2  前端切 v2，观察一个发布周期
Phase 3  删除 v1，同步更新 contracts/frontend-bff.yaml 与 spec.md §2.1
```

**实现要点**

- 版本号只在**对外边界**（BFF）出现。Java / Python 的内部接口**不加版本号** —— 它们与 BFF 同步发布。
- 版本切换靠**目录**（`controller/v1/`、`controller/v2/`）而非 `if (version === 2)`。
- BFF 的 v1→v2 适配必须显式写成一个 `dto/response/v1.adapter.ts`，让"两版差异"集中可见。

### 6.7 统一响应格式（本项目是"半个"统一）

很多团队会统一成 `{ code: 0, data: {...}, msg: "" }`。**本项目刻意不这么做**，因为 spec §2.2 已冻结字段层级（`resume` / `issues` / `match` / `meta` 直接在顶层）。

| 场景 | 形态 | 依据 |
|---|---|---|
| 业务成功 | **业务对象本身**（`AnalyzeResponse` / `JobResponse[]`） | spec §2.1 / §2.2 冻结字段层级 |
| 业务失败 | `{ code, message, traceId }` | spec §2.3 |
| 健康检查 | `{ status: "ok" }`；Java 额外带 `storage` | spec §2.8 |

**为什么不套壳**

| 套壳的理由 | 本项目的判断 |
|---|---|
| 便于统一处理 `code !== 0` | 用 HTTP 状态码 + `{code,message,traceId}` 已达成同样目的 |
| 便于加 traceId | traceId 已在**响应头** + 错误体里，成功响应不必再包一层 |
| "大家都这么做" | ❌ 契约已冻结，套壳会直接违反 spec §2.2 |

> 这是一条**有意识地偏离通用惯例**的决策：当契约冻结与"统一风格"冲突时，**契约赢**。要在答辩里讲清这个取舍。

### 6.8 校验分层：谁校验什么

| 层 | 校验内容 | 失败表现 | 为什么在这一层 |
|---|---|---|---|
| 前端 | 必填、长度提示、格式 | 行内红字 | 体验：即时反馈，减少无效请求 |
| BFF | 契约校验（zod）：类型、长度、二选一 | `400 INVALID_INPUT` / `400 RESUME_TOO_LONG` | spec §2.6 明确 BFF 负责输入校验 |
| Java | 路径参数格式、领域不变量（岗位存在） | `400 INVALID_INPUT` / `404 JOB_NOT_FOUND` | 领域规则归领域层 |
| Python | 输入长度上限（Pydantic）、算法前置条件 | `400 INVALID_INPUT` | 防御性：不假设调用方已校验 |

**原则**：**每层都校验，但校验的内容不同**。BFF 校验"契约合规"，Java 校验"领域存在性"，Python 校验"算法前置条件"。重复的不是规则，是**不信任上游的边界**。

---

## 7. 迁移路线图（从当前骨架到目标分层）

> **本步只交付指南，不动代码。** 下面是可执行的改造计划，每一步独立提交、可回滚，且**任何时刻仓库都可运行**（spec §3.5）。

### 7.1 现状盘点

| 服务 | 当前 | 目标 | 差距 |
|---|---|---|---|
| bff | `routes/` + `clients/` + `errors.ts` 单文件 | `controller/` + `service/` + `dto/` + `client/` + `errors/` | 缺 Service 层与 DTO 层 |
| job-service | `web/`（含 controller 与 filter）+ `dto/` 单文件 + `client/` | `controller/<domain>/` + `service/` + `repository/` + `entity/` + `mapper/` + `exception/` + `web/filter/` | 缺 Service / Repository / Entity / Mapper / 领域 API |
| analyzer | `routers/` + `models.py` 单文件 | `api/v1/` + `service/` + `schema/{request,response}/` + `core/` + `llm/` | 缺 Service 层、模块拆分、异常与依赖注入 |
| web | `api/` + `components/` + `utils/` | 同左（+ `stores/`） | 基本达标 |

### 7.2 逐文件映射（改造清单）

**bff**

| 当前 | 目标 | 动作 |
|---|---|---|
| `src/config.ts` | `src/config/env.ts` + `src/config/constants.ts` | 拆分（超时常量入 constants） |
| `src/logger.ts` | `src/util/logger.ts` | 移动 |
| `src/errors.ts` | `src/errors/{errorCode,appError,mapUpstream}.ts` | 拆分 |
| `src/clients/http.ts` | `src/client/http.ts` | 移动（`clients/` → `client/`） |
| `src/clients/jobServiceClient.ts` | `src/client/jobService.client.ts` | 移动 + 改名 |
| `src/routes/health.ts` | `src/controller/health.controller.ts` | 改造为 class |
| `src/routes/ping.ts` | `src/controller/job.controller.ts`（T3 起改为业务路由） | 改造 |
| `src/middleware/*` | 同名 + `.middleware.ts` 后缀 | 改名 |
| `src/koa.d.ts` | `src/type/koa.d.ts` | 移动 |
| — | `src/container.ts` / `src/service/` / `src/dto/` / `src/route/index.ts` / `src/util/response.ts` | 新增 |

**job-service**

| 当前 | 目标 | 动作 |
|---|---|---|
| `web/HealthController.java` | `controller/health/HealthController.java` | 移动 + 补 `storage` 字段 |
| `web/InternalController.java` | `controller/internal/InternalController.java` | 移动 |
| `web/GlobalExceptionHandler.java` | `exception/GlobalExceptionHandler.java` | 移动 + 补 `BusinessException` / `ErrorCode` |
| `web/TraceIdFilter.java` | `web/filter/TraceIdFilter.java` | 移动 |
| `dto/PingResponse.java` | `dto/response/PingResponse.java` | 移动 |
| `config/AppProperties.java` | `config/properties/AppProperties.java` | 移动 |
| — | `service/` + `impl/` + `repository/` + `entity/` + `mapper/` + `controller/{job,skill}/` | 新增（T4） |

**analyzer**

| 当前 | 目标 | 动作 |
|---|---|---|
| `app/routers/health.py` | `app/api/v1/health.py` | 移动 |
| `app/routers/internal.py` | `app/api/v1/internal.py` | 移动 + 拆出 Service |
| `app/models.py` | `app/schema/{request,response}/` | 拆分 |
| `app/logging_setup.py` | `app/core/logging.py` | 移动 + JSON formatter |
| `app/config.py` | `app/core/config.py` | 移动 |
| — | `app/service/` + `app/llm/` + `app/core/{constants,exceptions,exception_handlers,trace,dependencies,resources}.py` + `app/data/skills.yaml` | 新增（T5） |

### 7.3 分阶段步骤

| 阶段 | 内容 | 验收 | 提交信息 |
|---|---|---|---|
| **P0** | 落地本指南 + 冻结目录约定（不动代码） | `docs/architecture/layered-architecture-guide.md` 存在且被团队确认 | `docs: layered architecture guide (controller/service/dto)` |
| **P1** | **BFF 分层**：拆 `errors/`、移 `client/`、把 `routes/` 改 `controller/`、新增 `service/` + `dto/` + `container.ts` + `route/index.ts` | `npm run type-check` + `npm test` 全绿；`bash scripts/smoke.sh` 通过 | `refactor(bff): adopt controller/service/dto layering` |
| **P2** | **job-service 分层**：`web/` → `controller/` + `web/filter/`；`dto/` 拆 request/response；补 `exception/`（`ErrorCode` + `BusinessException`）；建 `service/` 骨架 | `mvn test` 通过；`/healthz` 与 `/internal/ping` 行为不变 | `refactor(job-service): layered packages & unified error codes` |
| **P3** | **analyzer 分层**：`routers/` → `api/v1/`；`models.py` → `schema/`；新增 `service/` 占位 + `core/{exceptions,exception_handlers,trace}.py` + `dependencies.py` | `pytest` 通过；契约形状测试仍绿 | `refactor(analyzer): adopt api/service/schema layering` |
| **P4** | **接业务与存储**（回到 `tasks.md` 主线）：T3 竖切 → T4 领域 API + 存储降级 → T5 真实算法与 LLM | 按 `tasks.md` 各任务验收 | 见 `tasks.md` 附录 C |

**每阶段 DoD**（对齐 `tasks.md` 附录 B）

1. 代码已提交，commit message 符合 Conventional Commits
2. 该层 lint / test 通过
3. `bash scripts/smoke.sh` 全链仍通过（不破坏已有功能）
4. 新增依赖或环境变量已同步 `.env.example` 与 `README.md`
5. 若涉及存储层：`mysql` 与 `local`（或 `mock`）两种模式都跑通

### 7.4 风险与回滚

| 风险 | 缓解 |
|---|---|
| 重构改动面大导致链路断 | **一步一提交**，每步独立可 `git revert`；提交前必跑 `smoke.sh` |
| 重构顺手动契约 | **铁律**：任何阶段都不得修改 `spec.md` §2.1 / §2.2 的字段与路径（§5.3 原则 10） |
| 目录改名导致 CI / Dockerfile 路径失效 | P1–P3 阶段同步检查 `.dockerignore`、`Dockerfile` 的 `COPY` 路径与 `package.json` 的入口 |
| 时间不够做完 P4 | P1–P3 是**纯重构、无功能增量**，可整体砍掉；`tasks.md` 主线不依赖它们 |
| 改动引入循环依赖 | P1 后跑一次 `npm run type-check`（TS 会报循环 import）；Java 启动即暴露；Python 用 `dependency_overrides` 测试暴露 |

### 7.5 与 `tasks.md` 的衔接

```
P0（本文档）  ──▶ 无依赖，可立即做
P1  BFF 分层  ──▶ 建议在 T3（竖切贯通）之前完成 —— 竖切是"加代码"，分层是"摆位置"，先摆好位置更省事
P2  Java 分层 ──▶ 建议在 T4 之前完成
P3  Py 分层   ──▶ 建议在 T5 之前完成（T5 要新增 service/llm 多个模块）
P4  业务主线  ──▶ 完全按 tasks.md T3 → T4 → T5 执行
```

> **重要**：P1–P3 属于**工程整理**，`tasks.md` 里没有对应任务。若 3 小时预算紧张，**优先级低于 T3（竖切贯通）** —— 因为 T3 是"全链贯通"的里程碑，而分层是"更好维护"，不是"能跑起来"。

---

## 附录 A · 速查清单

### A.1 写代码时的自检问题

| # | 自检 | 违规信号 |
|---|---|---|
| 1 | 这个文件的 import 里出现了框架类型吗？（Service 层） | `import koa` / `HttpServletRequest` / `Request` |
| 2 | 方法签名里出现 Entity 了吗？ | `JobEntity getJob(String id)` |
| 3 | Controller 里有 `if` 业务分支吗？ | `if (score > 80)` |
| 4 | 业务代码里 `new` 了服务吗？ | `new JobServiceImpl()` |
| 5 | 每处外部调用都有 timeout 吗？ | `fetch(url)` 无 signal |
| 6 | 错误响应是 `{code,message,traceId}` 吗？ | 返回了 `ex.getMessage()` 原始栈 |
| 7 | 成功响应套壳了吗？ | `{ code: 0, data: {...} }` ← **本项目禁止** |
| 8 | 日志里有密钥 / 连接串吗？ | `log.info(dbUrl)` |

### A.2 目录约定速查

```
apps/bff/src/          controller/  service/  dto/{request,response}/  client/  middleware/  errors/  route/  config/  type/  util/
apps/job-service/.../  controller/  service/impl/  dto/{request,response}/  mapper/  entity/  repository/{jpa,memory}/  exception/  client/  web/filter/  config/properties/
apps/analyzer/app/     api/v1/  service/  schema/{request,response}/  llm/  core/  util/  data/
apps/web/src/          api/  stores/  components/  utils/  styles/
```

### A.3 一句话记忆

> **Controller 只懂 HTTP，Service 只懂业务，第三层各干各的**（BFF 是 `client`，Java 是 `repository`，Python 是纯计算）。
> **Entity 不出 Repository，DTO 才跨边界；成功响应不套壳，错误才用统一体。**
> **降级不改契约：LLM 看 `meta.degraded`，存储看 `/healthz` 的 `storage`。**

---

## 附录 B · 与 spec.md / plan.md 的条款对照

| 本指南内容 | 依据 |
|---|---|
| §0.2 BFF / Python 无 `entity` `repository` | spec §2.6、§3.1 |
| §0.2 成功响应不套壳 | spec §2.2 |
| §0.2 不加 `/api/v1`、不分页 | spec §2.1、plan §3、plan §4.2 |
| §1.1 依赖方向 | plan §1.2 |
| §2.3 DTO 字段与错误码 | spec §2.1 / §2.2 / §2.3 |
| §2.3 超时与错误映射 | plan §6.1 / §6.4 |
| §2.3 限流预留 | spec §1.4（Out of Scope）、§2.3（429 存在） |
| §3.3 Repository 抽象与装配期决策 | ADR-007 |
| §3.3 存储模式探测与三档降级 | spec §2.9、plan §6.3、ADR-003 |
| §3.3 `/healthz` 的 `storage` 字段 | spec §2.8 |
| §3.5 事务规则 | 通用工程实践（本项目只读，规则为将来预留） |
| §3.6 结构化日志 + traceId | spec §2.8 |
| §3.7 双模式测试进 CI | plan §9.2、AC9 / AC10 |
| §4.3 处理链顺序 | spec §2.5 |
| §4.3 打分与集合自洽 | spec §2.4、ADR-002 |
| §4.3 LLM 降级 | ADR-004、AC3 |
| §4.6 不引 spaCy / 无数据库 | spec §3.2、§2.6 |
| §6.2 两条降级链 | spec §2.2、§2.9 |
| §6.4 事务不在 Controller / 不在事务内调下游 | 通用工程实践 |
| §6.6 版本管理判据 | spec §2.1（冻结）、plan §3 |
| §6.7 统一响应取舍 | spec §2.2、§2.3 |
| §7 迁移阶段与 DoD | tasks.md 附录 B / 附录 C |
| §7.5 优先级低于 T3 | tasks.md 进度总览（T3 为里程碑） |
