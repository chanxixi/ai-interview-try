# spec.md — CareerLens 最小纵向闭环（part1）

> SDD（Spec-Driven Development）阶段产物 **1 / 3**
> 版本：v0.2 · 状态：**待评审**
> 对应需求编号：R1–R11
> 下一步：确认「稳定面」后冻结，再进入 plan.md

---

## 0. 文档约定

本文档只回答 **「要什么」**，不回答「怎么做」。

| 问题 | 文档 |
|---|---|
| 要什么 | `spec.md`（本文） |
| 怎么做 | `plan.md` |
| 谁、什么时候做 | `tasks.md` |

**「稳定面」章节一经确认即冻结**，任何变更必须走文末的《变更记录》。

---

## 1. 目标

### 1.1 一句话目标

学生提交**简历文本**并**选择岗位**，系统完成**简历数据清洗、技能归一化、岗位匹配分析**，返回**简历结构化问题、可解释的命中项、能力缺口与岗位匹配度**。

### 1.2 业务目标

| 编号 | 目标 | 衡量方式 |
|---|---|---|
| G1 | 把自由文本的简历变成可分析的结构化数据 | 一份真实脱敏简历能被切成 教育 / 工作 / 项目 / 技能 四类区块 |
| G2 | 把「技能」从自由文本收敛到标准词表 | 常见别名（JS、ES6、SpringBoot…）全部归一成功 |
| G3 | 给出**可解释**的匹配结论，而非黑盒分数 | 每条命中项都带 JD 与简历的**双向原文证据** |
| G4 | 指出简历**本身**的结构性问题 | 覆盖 5 类：无量化 / 缺 STAR / 技能堆砌 / 时间线断档 / 缺联系方式 |

### 1.3 用户故事

- **US1** 作为学生，我想粘贴简历并选一个岗位，以便知道我与该岗位的匹配程度。
- **US2** 作为学生，我想看到「为什么匹配」的原文证据，以便判断结论是否可信。
- **US3** 作为学生，我想看到我缺哪些技能，以便知道下一步补什么。
- **US4** 作为学生，我想看到简历本身有哪些结构性问题，以便在投递前改进。

### 1.4 范围

**In Scope（本期做）**

- 简历**纯文本**输入 + 岗位选择（预置岗位库 **或** 自定义粘贴 JD）
- 三步处理链：数据清洗 → 技能归一化 → 匹配分析
- 四块输出：简历结构化问题 / 可解释命中项 / 能力缺口 / 岗位匹配度
- 四层请求链：Vue 3 → Node BFF → Java/Spring Boot → Python（+ LLM）
- **领域数据持久化**：岗位 JD 与技能词典落 **MySQL**；MySQL 不可用时自动降级为**本地存储**（H2 文件/内存）或**内置 Mock 数据**，对外契约不变
- Docker Compose 一键启动 + CI/CD + 测试 + 交付文档

**Out of Scope（本期明确不做）**

- 用户注册、登录、鉴权
- 历史记录、分析结果持久化查询（**注意**：MySQL 本期只承载岗位 / 技能词典这类**只读预置领域数据**，不落分析结果）
- PDF / DOCX 文件上传与解析
- 管理后台、岗位维护界面
- 多轮对话、Agent 编排、模拟面试、简历生成
- 向量检索、模型微调、embedding 相似度

### 1.5 非目标（Non-Goals）

- 本系统**不是**权威简历评分工具，匹配度仅供学生参考。
- 本系统**不追求**算法精度，追求的是**可解释性**与**链路完整性**。
- 本系统**不承诺**对任意排版格式的简历文本都能正确解析。

---

## 2. 稳定面

> **稳定面 = 一旦冻结就不允许单方面变更的对外承诺。**
> 变更需：① 修改本文档 → ② 同步三份 OpenAPI 契约 → ③ 追加《变更记录》。

### 2.1 请求契约（冻结）

```
POST /api/analysis
Content-Type: application/json

{
  "resumeText": "string 必填 · 1 ~ 20000 字符 · 纯文本",
  "jobId":      "string 可选 · 与 jdText 二选一",
  "jdText":     "string 可选 · 1 ~ 8000 字符 · 与 jobId 二选一"
}
```

- `jobId` 与 `jdText` **至少提供一个**，否则 400。
- 两者同时提供时，**以 `jobId` 为准**。

### 2.2 响应契约（冻结）

```json
{
  "resume": {
    "sections": { "education": [], "experience": [], "projects": [], "skills": [] },
    "skills": [{ "raw": "SpringBoot", "canonical": "Spring Boot", "category": "framework" }]
  },
  "issues": [
    { "type": "NO_QUANTIFY", "severity": "high",
      "evidence": "优化了系统性能", "suggestion": "补充 QPS / 延迟 / 提升幅度等量化指标" }
  ],
  "match": {
    "score": 78,
    "matched": [
      { "skill": "Spring Boot", "importance": "required", "weight": 1.0,
        "jdEvidence": "熟悉 Spring Boot 微服务开发",
        "resumeEvidence": "使用 SpringBoot 开发订单中心",
        "jdOffset": 12, "resumeOffset": 340 }
    ],
    "missing": [
      { "skill": "Redis", "importance": "required", "suggestion": "补充缓存 / 分布式锁相关项目经验" }
    ]
  },
  "meta": { "traceId": "uuid", "llmUsed": true, "degraded": false, "elapsedMs": 2140 }
}
```

- 字段名、层级、类型**不可改**。
- `meta.llmUsed` / `meta.degraded` **必须保留**，是降级能力的唯一证据。

### 2.3 错误码表（冻结）

| HTTP | code | 场景 |
|---|---|---|
| 400 | `INVALID_INPUT` | 参数校验失败 |
| 400 | `RESUME_TOO_LONG` | 简历超过 20000 字符 |
| 404 | `JOB_NOT_FOUND` | `jobId` 不存在 |
| 422 | `ANALYSIS_FAILED` | Python 分析失败 |
| 429 | `RATE_LIMITED` | 触发限流 |
| 503 | `SERVICE_UNAVAILABLE` | 下游不可用 |
| 504 | `UPSTREAM_TIMEOUT` | 下游超时 |
| 500 | `INTERNAL_ERROR` | 未预期错误 |

统一响应体：`{ "code": "...", "message": "...", "traceId": "..." }`

### 2.4 语义定义（冻结）

| 项 | 定义 |
|---|---|
| `score` | 0–100 整数；全命中 = 100，全缺失 = 0 |
| 集合自洽 | `matched ∩ missing = ∅` 且 `matched ∪ missing = JD 技能全集` |
| `importance` | 枚举：`required` \| `preferred` |
| `severity` | 枚举：`high` \| `medium` \| `low` |
| `issues[].type` | 枚举：`NO_QUANTIFY` \| `NO_STAR` \| `SKILL_STUFFING` \| `TIMELINE_GAP` \| `MISSING_CONTACT` |
| 打分公式 | `score = Σ(命中技能权重) / Σ(JD 全部技能权重) × 100`，required = 1.0，preferred = 0.5 |
| 确定性 | 同一输入两次调用，`score` 与 `matched` 集合必须一致 |

### 2.5 处理链顺序（冻结）

**数据清洗 → 技能归一化 → 匹配分析**，严格串行，不可调换、不可并行。

### 2.6 层职责边界（冻结）

| 层 | 必须做 | 禁止做 |
|---|---|---|
| Vue 3 | 表单、loading、结果可视化、错误提示 | 业务判断、直连 Java/Python |
| Node BFF | 输入校验、请求编排、超时、错误映射、结果聚合、traceId 下发 | 业务规则、访问数据库（含 MySQL） |
| Java / Spring Boot | 岗位 JD 与技能词典领域 API、DTO 契约、服务编排、**持久化（MySQL 优先，不可用时降级为本地 / Mock 存储）** | 文本算法、直接调用 LLM |
| Python | 清洗、归一化、匹配打分、LLM 编排与降级 | 鉴权、岗位数据 CRUD、直连数据库 |
| LLM | 结构化抽取、生成可解释理由 | 成为唯一执行路径 |

> 数据访问权**只属于 Java 层**：BFF 与 Python 一律通过 HTTP 契约取数据，不得直连 MySQL。

### 2.7 技术栈（冻结）

Vue 3 + TypeScript + Vite ｜ Node.js（Koa2 或 NestJS）+ TypeScript ｜ Java 17 + Spring Boot 3.2 ｜ Python 3.11+ + FastAPI ｜ **MySQL 8.x（主存储）+ Spring Data JPA；H2 / 内存实现（降级）** ｜ Docker + Docker Compose ｜ GitHub Actions

### 2.8 可观测性约定（冻结）

- 所有服务日志为**结构化 JSON**。
- 全链 **traceId** 贯穿，HTTP header 名固定为 `X-Trace-Id`。
- 每个服务暴露 `GET /healthz`，返回 `{ "status": "ok" }`。
- Java 的 `/healthz` **额外**返回存储状态：`{ "status": "ok", "storage": "mysql" | "local" | "mock" }`，作为存储降级的唯一可观测证据。

### 2.9 存储与降级约定（冻结）

> 本节回答"数据存哪儿、存不了怎么办"，是对 **R2 / R4**（岗位与技能词典）的存储承诺。

**主路径**

- 主存储：**MySQL 8.x**，由 `docker-compose.yml` 中的 `mysql` 服务提供。
- 访问方：**仅 Java 层**（Spring Data JPA）。BFF 与 Python 不得直连数据库。
- 表结构以 `db/mysql/schema.sql`（主）/ `db/h2/schema.sql`（降级）为准，种子数据以 `db/seed.sql`（两模式共用）为准。
- 岗位与技能词典为**只读预置数据**，本期不提供写入 / 修改 API。

**降级路径（必须实现）**

| 优先级 | 模式 | 触发条件 | 数据来源 | 行为 |
|---|---|---|---|---|
| 1 | `mysql` | 连接成功 | MySQL 实例 | 只读查询 |
| 2 | `local` | MySQL 连不上 / 未配置 | H2（内存或文件，`MODE=MySQL`）+ 同一份 `seed.sql` | 只读，进程内生效 |
| 3 | `mock` | H2 亦不可用 | 代码内置的静态岗位 / 词典对象 | 只读，返回最小可用数据集 |

- 降级**对上游透明**：`GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills` 的**响应结构完全不变**，仅数据来源不同。
- 降级由 `app.storage.mode`（`auto` \| `mysql` \| `local` \| `mock`）控制，默认 `auto`（探测失败自动下沉一级）。
- 降级发生时**不得**返回 5xx；启动日志与 `/healthz` 必须显式暴露当前模式。
- 判定方法（答辩可现场演示）：**停掉 MySQL 容器后重启 Java 服务，三个领域接口仍返回完整数据。**

### 2.10 术语表

| 术语 | 含义 |
|---|---|
| canonical | 技能的标准名，如 `Spring Boot` |
| alias | 标准名的别名，如 `SpringBoot`、`spring boot` |
| 归一化 | 把 raw 技能文本映射到 canonical 的过程 |
| 命中（matched） | JD 要求且简历具备的技能 |
| 缺口（missing） | JD 要求但简历不具备的技能 |
| 简历结构化问题（issues） | 对简历**本身**的诊断，与 JD 无关 |
| 存储模式（storage mode） | Java 层实际生效的数据来源：`mysql` / `local` / `mock` |
| 存储降级 | MySQL 不可用时自动下沉到 `local` 或 `mock`，且对外契约不变 |

---

## 3. 禁止

### 3.1 架构禁止

- 禁止跳过任何一层（Vue 不得直连 Java / Python）。
- 禁止 BFF 承载业务规则或访问数据库（含 MySQL）。
- 禁止 Java 层做文本算法或直接调用 LLM。
- 禁止 Python 层管理岗位数据、做鉴权或直连数据库。
- 禁止绕过 Java 层把岗位 / 技能词典数据写死在 BFF 或 Python 中（降级种子数据只允许存在于 Java 层）。

### 3.2 算法禁止（对应「轻度算法」）

- 禁止微调模型。
- 禁止引入 spaCy 等重型 NLP pipeline。
- 禁止让 LLM 成为唯一执行路径（必须可降级）。

### 3.3 安全禁止

- 禁止将 API Key 写入代码、镜像、仓库或文档。
- 禁止将数据库连接串 / 账号 / 密码硬编码进代码、镜像、仓库或文档，一律走环境变量。
- 禁止在日志中打印数据库连接串或密码。
- 禁止在 `AI_LOG.md` 中保留未脱敏的密钥。
- 禁止无超时的外部调用。
- 禁止向前端透传下游原始错误栈。

<!-- ### 3.4 范围禁止（对应「最小纵向闭环」）

- 禁止实现登录 / 注册 / 权限。
- 禁止实现历史记录与结果持久化查询。
- 禁止实现文件上传解析。
- 禁止实现管理后台。

> 判定方法：**删掉某个功能，这条链路还能跑通吗？能，那就该删。** -->

### 3.5 工程禁止

- 禁止提交无法运行的代码（每次 commit 后仓库必须可运行）。
- 禁止绕过 CI（如 `--no-verify`）。
- 禁止单次巨型提交。

---

## 4. 验收

### 4.1 功能验收（AC）

```
AC1  Given 一份有效简历 + 一个有效岗位
     When  提交
     Then  30s 内返回含 resume / issues / match / meta 四块的 JSON

AC2  Given 简历文本为空或全空白
     When  提交
     Then  返回 400，code = INVALID_INPUT

AC3  Given LLM 服务不可用（超时或报错）
     When  提交有效输入
     Then  仍返回完整四块结果，且 meta.degraded = true

AC4  Given 同一份简历 + 同一个岗位
     When  连续提交两次
     Then  score 数值与 matched 技能集合完全一致

AC5  Given 返回结果中任意一条 matched
     Then  其 jdEvidence 与 resumeEvidence 均能在对应输入原文中定位

AC6  Given skills.yaml 中任意一条 alias
     When  经归一化处理
     Then  输出的 canonical 与词典定义一致

AC7  Given 任意一次成功响应
     Then  matched ∩ missing = ∅ 且 matched ∪ missing = JD 技能全集

AC8  Given 一份含「无量化描述」的简历
     When  提交
     Then  issues 中至少出现一条 type = NO_QUANTIFY

AC9  Given MySQL 可用
     When  启动 Java 服务并调用 GET /api/jobs
     Then  返回数据库中的岗位数据，且 /healthz 的 storage = mysql

AC10 Given MySQL 不可用（容器未启动或连接失败）
     When  启动 Java 服务并调用 GET /api/jobs、GET /api/jobs/{id}、GET /api/skills
     Then  三个接口均返回完整数据（不返回 5xx），
           且 /healthz 的 storage ∈ { local, mock }，
           且与 AC9 的响应结构完全一致
```

### 4.2 交付物验收

- [ ] 可运行代码（4 个服务）
- [ ] 每层单元测试 + 1 条端到端冒烟测试
- [ ] `docker-compose.yml` + 4 个 Dockerfile
- [ ] `.github/workflows/`（CI 测试 + 镜像构建）
- [ ] `DELIVERY.md`：启动 / 测试 / 部署回滚 / 架构取舍 / 已知缺口
  - 必须含**存储降级说明**：三种模式如何触发、如何验证（对应 AC9 / AC10）
- [ ] `AI_LOG.md`：vibcoding 会话记录（密钥脱敏）
- [ ] 计时期间**连续**的 git 提交历史
- [ ] `sdd/part1/` 下 spec.md / plan.md / tasks.md

### 4.3 演示验收（15 分钟答辩）

1. 现场 `docker compose up` 起 4 个服务，健康检查全绿。
2. 现场提交一份简历 + 一个岗位，展示完整请求链（四块结果）。
3. 按层讲解职责边界与架构取舍。
4. **演示 LLM 降级**：断开 LLM 后重跑，仍返回完整结果且 `degraded = true`。
5. **演示存储降级**：停掉 MySQL 容器后重启 Java 服务，`/healthz` 显示 `storage = local`（或 `mock`），三个领域接口仍返回完整数据。

### 4.4 质量门禁

- 每层单测通过
- 端到端冒烟通过
- CI 绿灯
- 四个镜像均可构建

---

## 5. 待拍板事项

| # | 事项 | 备选 | 建议 |
|---|---|---|---|
| 1 | 岗位输入方式（R2） | A 只做预置岗位库 / B 预置 + 自定义粘贴 | **B** |
| 2 | 简历结构化问题是否含岗位相关建议（R6） | 含 / 不含 | **不含**（R6 保持纯简历诊断，岗位相关建议归入 missing.suggestion） |
| 3 | 匹配度是否分维度（R9） | 单维度技能 / 技能+经验+学历 | **单维度技能** |

---

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|---|---|---|---|
| v0.1 | 2026-10-14 | 初稿：目标 / 稳定面 / 禁止 / 验收 四板块 | — |
| v0.2 | 2026-10-14 | **存储策略变更**：MySQL 纳入 In Scope；新增 §2.9 存储与降级约定（mysql → local → mock）；§2.6 明确数据访问权归 Java 层；§2.8 `/healthz` 增加 `storage` 字段；§3.3 增加数据库凭据禁令；新增 AC9 / AC10 | — |
