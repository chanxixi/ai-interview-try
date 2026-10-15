# plan.md — CareerLens 最小纵向闭环（part1）

> SDD 阶段产物 **2 / 3** · 版本 v0.3 · 依赖 `spec.md` 已评审
> 本文档回答 **「怎么做」**：架构、选型、契约、数据模型、关键决策、风险与降级。
>
> **v0.3 变更**：§9.1 增加**人工审核门禁** —— 取消自动提交，`git commit` 必须由人工审核代码后发起（同步 `spec.md` §3.5、`tasks.md` 附录 C）。
> **v0.2 变更**：持久化由「H2 内存库」改为「**MySQL 8.0 为主 + H2 本地 / Mock 兜底**」，同步更新 §1 请求链、§2 选型、§3.2 契约、§4 数据模型、ADR-003 / ADR-007、§6.3 存储降级、§7 目录、§8 本地运行、§9.2 CI、§10 风险、§11 时间预算。

---

## 1. 架构总览

### 1.1 请求链

```
Vue 3 SPA  →  Node.js BFF  →  Java / Spring Boot  →  Python + FastAPI  →  LLM
                        ↘______________________↗
                          （BFF 同时编排两个下游）

                              Java / Spring Boot
                                    │  Spring Data JPA
                                    ▼
                          MySQL 8  ──(连不上)──▶  H2 ──(亦不可用)──▶  Mock 内置数据
                          storage=mysql        storage=local        storage=mock
```

**存储降级与请求链的关系**：存储只在 Java 层内部切换，**BFF 与前端完全不感知**——三个领域接口的响应结构在三种模式下逐字一致（spec.md §2.9）。

**一次分析的完整时序**

```
1. 前端 POST /api/analysis  { resumeText, jobId | jdText }   + X-Trace-Id
2. BFF  校验参数（zod）→ 生成/透传 traceId
3. BFF  → Java   GET /api/jobs/{id}                取岗位 JD 原文（jobId 场景）
        └ Java 从 MySQL 读取；MySQL 不可用时自动走 H2 / Mock，响应结构不变
4. BFF  → Python POST /internal/analyze            传 { resumeText, jdText }
5. Python 清洗 → 归一化 → 匹配 → （可选）LLM 增强 → 汇总四块结果
6. BFF  聚合 Java + Python 结果，裁剪为前端 DTO
7. 前端渲染：匹配度环形图 + 命中/缺口列表 + 简历问题清单
```

### 1.2 职责边界（复述 spec.md §2.6，实现时的判据）

| 层 | 一句话定位 | 判断"该不该放这层"的问题 |
|---|---|---|
| Vue | 只负责呈现与交互 | 这段逻辑换个 UI 框架还要吗？要 → 不该放这层 |
| BFF | 面向客户端的**适配层** | 这是"客户端要什么形状"还是"业务是什么"？前者留这层 |
| Java | 面向领域的**稳定层** | 这个模型会因前端改版而变吗？会 → 不该放这层 |
| Python | 计算与算法 | 是"算"还是"管"？算留这层 |

---

## 2. 技术选型与理由

| 层 | 选型 | 版本 | 理由 | 已知代价 |
|---|---|---|---|---|
| 前端 | Vue 3 + TS + Vite | 3.4 / 5.x | 题目强制 | — |
| 状态 | Pinia | 2.x | 轻量够用 | — |
| 组件库 | **shadcn-vue**（Radix Vue 底座） | latest | 组件源码进仓，改样式即"经 vibcoding 改造"，规避"纯 AI UI"判负 | 部分样式需手写 |
| 图表 | ECharts | 5.x | 匹配度环形图 + 命中/缺口对比 | 体积大，按需引入 |
| BFF | **Koa2 + TS** | 2.15 | 已熟悉，3h 内最稳 | 需手写超时/错误映射中间件 |
| BFF 备选 | NestJS | 10 | Interceptor / Pipe / Filter 天然对口本题，简历加分 | 学习成本会吃掉时间 |
| 校验 | zod | 3.x | 与 TS 类型同源 | — |
| HTTP 客户端 | undici（原生 AbortSignal） | 内置 | 超时控制不引重库 | — |
| 日志 | pino | 8.x | 结构化 JSON，便于 grep traceId | — |
| Java | Spring Boot + Java 17 | 3.2 | LTS 最稳 | 团队最弱一环 |
| 持久化（主） | **MySQL 8.0** + Spring Data JPA + `schema.sql` / `seed.sql` | 8.0 | 贴合团队既有栈（Node + MySQL），答辩可现场展示真实 DDL / 索引 / EXPLAIN；`docker compose` 一个 db 服务即可 | 多一个容器，需处理启动顺序与连接重试 |
| 持久化（降级） | H2（文件 / 内存）+ 同一份种子数据 | 2.2 | MySQL 不可用时零配置启动，**对外契约不变** | 只读快照，无写入路径 |
| 持久化（兜底） | 代码内置 Mock 数据集 | — | 连 H2 都不可用时的最后一道保险，保证演示不挂 | 数据集最小化（1–3 条岗位） |
| 契约 | springdoc-openapi | 2.x | 自动生成，答辩可现场展示 | — |
| 构建 | Maven | 3.9 | 上手快 | — |
| Python | FastAPI + uvicorn | 0.110 / 0.29 | 自带 OpenAPI，与契约体系对齐 | — |
| 文本处理 | 正则 + YAML 技能词典 | — | 装包快、镜像小、可解释 | 词典覆盖度靠手工 |
| LLM | `openai` SDK，`base_url` 可配 | 1.x | OpenAI-compatible 为题目指定接入方式，换网关只改 base_url | 需自建降级 |
| 测试 | pytest + httpx ｜ Jest + supertest ｜ JUnit5 + MockMvc ｜ Vitest | — | 各层原生方案 | — |
| 基础设施 | Docker 多阶段构建 + Compose | — | 每层独立 Dockerfile | 注意 `.dockerignore` |
| CI/CD | GitHub Actions | — | matrix 跑 4 层 | — |

---

## 3. 契约设计（契约先行）

三份 OpenAPI 放在 `contracts/`，**先冻结再写代码**。

### 3.1 `frontend-bff.yaml`

```
POST /api/analysis        分析入口（spec.md §2.1 / §2.2）
GET  /api/jobs            岗位列表（供前端下拉）
GET  /healthz
```

### 3.2 `bff-java.yaml`

```
GET /api/jobs             → [{ id, title, company, level, jdText }]
GET /api/jobs/{id}        → { id, title, company, level, jdText }
GET /api/skills           → [{ canonical, aliases[], category }]
GET /healthz              → { status: "ok", storage: "mysql" | "local" | "mock" }
```

> 三个领域接口的响应结构**与存储模式无关**（AC9 / AC10 要求逐字一致）；
> `storage` 字段只出现在 `/healthz`，作为降级的可观测证据，**不进入业务响应**。

### 3.3 `bff-python.yaml`

```
POST /internal/analyze
  req  { resumeText, jdText, traceId }
  resp { resume, issues, match, meta }
GET /healthz
```

> 内部接口统一带 `/internal` 前缀，语义上标明"不对外"。

---

## 4. 数据模型

### 4.1 存储策略总览

| 模式 | 触发 | 实现 | 初始化脚本 | 读写 |
|---|---|---|---|---|
| `mysql`（主） | MySQL 连接成功 | MySQL 8.0 + Spring Data JPA | `db/mysql/schema.sql` + `db/seed.sql` | 只读 |
| `local`（降级） | 连接失败 / 未配置 | H2（`MODE=MySQL`，默认内存，可切文件） | `db/h2/schema.sql` + `db/seed.sql` | 只读 |
| `mock`（兜底） | H2 初始化失败 | 代码内置 `InMemoryJobRepository` | 无 | 只读 |

- 由 `app.storage.mode`（`auto` \| `mysql` \| `local` \| `mock`）控制，默认 `auto`：启动时按 `mysql → local → mock` 顺序探测，**第一个成功即停**。
- 三模式共用同一套 **Repository 接口**（`JobRepository` / `SkillRepository`），JPA 实现与内存实现并存，靠 `@ConditionalOnProperty` 装配。
- 三种模式的接口响应**逐字一致**——这是 AC9 / AC10 的判定依据。

### 4.2 MySQL 建表（主路径）

```sql
-- db/mysql/schema.sql
CREATE DATABASE IF NOT EXISTS careerlens
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS job (
  id      VARCHAR(32)  NOT NULL COMMENT '岗位 ID，如 job-java-01',
  title   VARCHAR(128) NOT NULL COMMENT '岗位名，如 Java 后端开发',
  company VARCHAR(128)          COMMENT '公司名',
  level   VARCHAR(32)           COMMENT '校招 / 社招 / 实习',
  jd_text TEXT         NOT NULL COMMENT 'JD 原文，用于双向证据定位',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='预置岗位';

CREATE TABLE IF NOT EXISTS skill (
  canonical VARCHAR(64)  NOT NULL COMMENT '标准名，如 Spring Boot',
  category  VARCHAR(32)           COMMENT 'language / framework / db / devops …',
  aliases   VARCHAR(512)          COMMENT '逗号分隔，如 SpringBoot,spring boot',
  PRIMARY KEY (canonical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技能词典';
```

**要点**

- `jd_text` 用 `TEXT`（64KB）而非 `LONGTEXT`：单条 JD 上限 8000 字符（spec.md §2.1），TEXT 足够；MySQL 的 `TEXT` 恰好对应原 H2 方案的 `CLOB` 语义。
- 字符集统一 `utf8mb4`：简历 / JD 里中文与 emoji 都不会乱码。
- 不建额外索引：表只有几十行、访问模式是主键点查，加了反而拖慢导入。**答辩时可现场用 `EXPLAIN` 说明这一点**，比无脑加索引更能体现判断力。
- `db/seed.sql` 用 `INSERT ... ON DUPLICATE KEY UPDATE` 保证**幂等**，容器重复启动不会报错。

### 4.3 H2 降级建表（`local` 模式）

```sql
-- db/h2/schema.sql：去掉 ENGINE / COMMENT 等 MySQL 专有子句，其余保持一致
CREATE TABLE IF NOT EXISTS job (
  id      VARCHAR(32)  PRIMARY KEY,
  title   VARCHAR(128) NOT NULL,
  company VARCHAR(128),
  level   VARCHAR(32),
  jd_text CLOB         NOT NULL
);

CREATE TABLE IF NOT EXISTS skill (
  canonical VARCHAR(64) PRIMARY KEY,
  category  VARCHAR(32),
  aliases   VARCHAR(512)
);
```

- 连接串：`jdbc:h2:mem:careerlens;MODE=MySQL;DB_CLOSE_DELAY=-1`
- `db/seed.sql` **两份共用**（纯 `INSERT` 语句，MySQL 与 H2 语法兼容）。
- 落到容器里建议把 H2 切文件模式（`jdbc:h2:file:/app/data/careerlens`）并挂 volume，便于答辩时展示"降级后数据仍在"。

### 4.4 Mock 兜底（`mock` 模式）

```java
// 仅 1–3 条岗位 + 最小技能词典，硬编码在 Java 层
// 目的：MySQL 与 H2 同时不可用时，演示链路依然完整（AC10）
@Component
@ConditionalOnProperty(name = "app.storage.mode", havingValue = "mock")
class InMemoryJobRepository implements JobRepository { ... }
```

> Mock 数据**只允许存在于 Java 层**（spec.md §3.1），BFF 与 Python 不得内置业务数据。

### 4.5 Python 侧（无持久化，纯计算）

```python
class NormalizedSkill(BaseModel):
    raw: str
    canonical: str
    category: str | None

class Issue(BaseModel):
    type: Literal["NO_QUANTIFY","NO_STAR","SKILL_STUFFING","TIMELINE_GAP","MISSING_CONTACT"]
    severity: Literal["high","medium","low"]
    evidence: str
    suggestion: str

class MatchedItem(BaseModel):
    skill: str
    importance: Literal["required","preferred"]
    weight: float
    jdEvidence: str
    resumeEvidence: str
    jdOffset: int | None
    resumeOffset: int | None

class MatchResult(BaseModel):
    score: int
    matched: list[MatchedItem]
    missing: list[MissingItem]

class AnalyzeResult(BaseModel):
    resume: ResumeView
    issues: list[Issue]
    match: MatchResult
    meta: Meta
```

用 Pydantic 校验 LLM 的结构化输出——**校验失败即触发降级**。

---

## 5. 关键设计决策（ADR）

### ADR-001 岗位输入支持「预置 + 自定义粘贴」

- **背景**：题干写"选择岗位"，资料 JD 却是"从招聘网站复制"。
- **决策**：两种都支持，前端切换；BFF 按 `jobId` / `jdText` 分支。
- **理由**：同时解释"Java 层为何存在"与"资料为何是复制的 JD"，增量成本极小（BFF 多一个分支，Python 只收 `jdText`）。

### ADR-002 匹配度用加权覆盖率，不用向量相似度

- **决策**：`score = Σ(命中权重) / Σ(JD 全部权重) × 100`，required = 1.0，preferred = 0.5。
- **理由**：spec.md 要求**可解释**（AC5）。向量相似度给不出"为什么命中"，无法产出双向原文证据。
- **代价**：对语义相近但字面不同的技能（如"分布式缓存"vs"Redis"）覆盖不足，靠词典 alias 缓解。

### ADR-003 Java 层持久化以 MySQL 为主，不可用时降级为本地 / Mock 存储

- **背景**：团队既有栈是 Node + MySQL（前端转全栈的既有资产），而本期数据是**只读预置数据**（岗位 JD + 技能词典），理论上 H2 内存库更省事。
- **决策**：
  - **主路径用 MySQL 8.0**（Compose 内一个 `mysql` 服务），Spring Data JPA + `schema.sql` / `seed.sql` 初始化。
  - **降级路径必须实现**：MySQL 连不上 → H2（`MODE=MySQL`）；H2 也不可用 → Java 层内置 Mock 数据。
  - 三模式共用同一套 Repository 接口，切换靠 `app.storage.mode`，**对 BFF 与前端完全透明**。
- **理由**：
  1. **技术栈一致性**：与团队既有 Node + MySQL 经验对齐，答辩时能讲真实 DDL / 索引判断，而不是"用内存库糊过去了"。
  2. **可演示性**：现场 `docker compose up` 能看到真实的库表与数据，比 H2 更有说服力。
  3. **风险可控**：题目给的是 3 小时预算，MySQL 的编排成本确实存在——所以**降级不是可选项而是硬性要求**，任何时刻都不能因为数据库问题导致演示失败。
- **代价**：
  1. 多一个容器 + 启动顺序（`depends_on: service_healthy`）与连接重试，约 20–30 分钟成本。
  2. 需要维护两份 schema（MySQL 与 H2 各一份），靠共用 `seed.sql` 降低重复。
- **回退条件**：若 2:05 时 MySQL 仍未跑通，**立即**把 `app.storage.mode` 固定为 `local` 继续推进关键路径，MySQL 编排挪到 T7 收尾阶段补——**不允许为了数据库阻塞主线**。

### ADR-004 LLM 必须可降级

- **决策**：LLM 只做两件事 —— ① 技能抽取兜底 ② 生成 `suggestion` 措辞。核心链路（清洗、归一化、打分、集合计算）全部由规则完成。
- **理由**：AC3 要求 LLM 不可用时仍返回完整四块结果。
- **实现**：`llm_client` 包一层，异常/超时/解析失败 → 捕获 → 走规则分支 → `meta.degraded = true`。

### ADR-005 BFF 不承载业务规则

- **决策**：BFF 只做校验、编排、超时、错误映射、聚合。
- **理由**：业务规则若落在 BFF，Java 与 Python 的领域边界会被侵蚀，且规则无法被测试覆盖。
- **代价**：字段映射代码会有一点重复，接受。

### ADR-006 用 Koa2 而非 NestJS

- **决策**：Koa2 + TS。
- **理由**：3 小时预算下，熟悉度 > 架构优雅度。超时/错误映射用两个中间件即可手写。
- **代价**：缺少 DI 与装饰器带来的结构约束，靠目录约定弥补。

### ADR-007 存储抽象：Repository 接口 + 多实现，而非 if/else 散落

- **决策**：定义 `JobRepository` / `SkillRepository` 两个接口，`mysql` 模式装配 Spring Data JPA 实现，`local` / `mock` 模式装配内存实现（`@ConditionalOnProperty`）。
- **理由**：降级逻辑若写成 Service 里的 `if (dbDown) { ... } else { ... }`，会污染业务代码且难以测试；用接口 + 条件装配，降级是**装配期决策**而非**运行期分支**。
- **代价**：多一层接口与两个实现类，约 40 行样板代码。
- **验证**：单元测试直接注入内存实现，无需起数据库即可跑通领域逻辑（对应 AC10）。

---

## 6. 降级与容错设计

### 6.1 超时矩阵

| 链路 | 超时 | 超时后行为 |
|---|---|---|
| BFF → Java | 5s | 返回 `504 UPSTREAM_TIMEOUT` |
| BFF → Python | 45s | 返回 `504 UPSTREAM_TIMEOUT` |
| Python → LLM | 20s | **降级**，`degraded = true`，继续走规则 |
| 整链（前端视角） | 60s | 前端中止并提示 |

### 6.2 降级路径

```
LLM 可用 → 结构化抽取 + 理由生成 → llmUsed = true,  degraded = false
LLM 超时 → 规则抽取（词典匹配）+ 模板化理由 → llmUsed = false, degraded = true
LLM 报错 → 同超时分支
LLM 返回非法 JSON → Pydantic 校验失败 → 同超时分支
```

### 6.3 存储降级（Java 层内部，对应 AC9 / AC10）

```
启动
 └─ app.storage.mode = auto（默认）
      ├─ 探测 MySQL（JDBC 连接，重试 3 次 × 2s）
      │    ├─ 成功 → 跑 schema.sql + seed.sql（幂等）→ storage = mysql
      │    └─ 失败 ↓
      ├─ 装配 H2（MODE=MySQL，同一份 seed.sql）
      │    ├─ 成功 → storage = local
      │    └─ 失败 ↓
      └─ 装配内置 Mock 数据 → storage = mock
```

| 场景 | 行为 |
|---|---|
| MySQL 未启动 / 端口占用 / 凭据错 | 启动日志 WARN + `/healthz` → `storage = local`；**不返回 5xx** |
| 运行中 MySQL 掉线 | 本层为**只读预置数据**，启动时已加载；连接失效只影响后续查询 → 捕获异常后回退内存实现并告警 |
| `app.storage.mode` 显式指定 | 跳过探测，按指定模式装配（演示 / 测试用，失败则启动失败，不静默降级） |
| 降级发生 | 三个领域接口响应结构与 `mysql` 模式**逐字一致**（AC10 判定依据） |

**可观测性**：降级状态只通过两个渠道暴露——① 启动日志（含失败原因）② `/healthz` 的 `storage` 字段。**不得**把降级细节透传给前端。

### 6.4 错误映射（BFF 统一收口）

| 下游表现 | 映射为 |
|---|---|
| Java 404 | `404 JOB_NOT_FOUND` |
| Java 5xx | `503 SERVICE_UNAVAILABLE` |
| Python 4xx | `422 ANALYSIS_FAILED` |
| Python 5xx | `503 SERVICE_UNAVAILABLE` |
| 任意超时 | `504 UPSTREAM_TIMEOUT` |

> **注意**：数据库不可用**不会**出现在这张表里——存储降级在 Java 层内部消化，BFF 感知不到（这正是降级设计的意义）。

---

## 7. 目录结构

```
careerlens/
├─ sdd/part1/{spec.md, plan.md, tasks.md}
├─ contracts/{frontend-bff.yaml, bff-java.yaml, bff-python.yaml}
├─ apps/
│  ├─ web/           Vue 3
│  ├─ bff/           Node.js + Koa2
│  ├─ job-service/   Java + Spring Boot
│  │  └─ src/main/resources/db/
│  │     ├─ mysql/schema.sql    MySQL 建表（主路径）
│  │     ├─ h2/schema.sql       H2 建表（降级）
│  │     └─ seed.sql            种子数据（两模式共用，幂等）
│  └─ analyzer/      Python + FastAPI
├─ docker-compose.yml          含 mysql 服务（healthcheck + volume）
├─ .env.example                含 MYSQL_* / STORAGE_MODE
├─ .github/workflows/{ci.yml, docker.yml}
├─ AI_LOG.md
├─ DELIVERY.md
└─ README.md
```

**`docker-compose.yml` 服务清单**

| 服务 | 镜像 | 端口 | 说明 |
|---|---|---|---|
| `mysql` | `mysql:8.0` | 3306 | `healthcheck: mysqladmin ping`，`volumes: mysql-data`，首次启动挂 `db/mysql/schema.sql` + `db/seed.sql` |
| `job-service` | 本地构建 | 8080 | `depends_on: mysql: condition: service_healthy` |
| `analyzer` | 本地构建 | 8000 | — |
| `bff` | 本地构建 | 3000 | `depends_on: job-service, analyzer` |
| `web` | 本地构建 | 5173 | — |

---

## 8. 本地运行

```bash
# 全量（含 MySQL）
docker compose up --build

# 前端     http://localhost:5173
# BFF      http://localhost:3000/healthz
# Java     http://localhost:8080/healthz   → {"status":"ok","storage":"mysql"}
# Python   http://localhost:8000/healthz
# MySQL    localhost:3306  (careerlens / careerlens)

# 端到端冒烟
curl -X POST http://localhost:3000/api/analysis \
  -H 'Content-Type: application/json' \
  -d '{"resumeText":"...","jobId":"job-java-01"}'
```

**只起业务服务、不起数据库（验证降级）**

```bash
# 方式 A：只起 Java，让它自动下沉到 H2
docker compose up --build job-service
curl http://localhost:8080/healthz        # → {"status":"ok","storage":"local"}
curl http://localhost:8080/api/jobs       # 数据完整，结构与 mysql 模式一致

# 方式 B：显式指定模式（跳过探测）
STORAGE_MODE=local docker compose up --build job-service
STORAGE_MODE=mock  docker compose up --build job-service
```

**连本地已有 MySQL（不用容器）**

```bash
# 先手工建库并灌数据
mysql -h 127.0.0.1 -u root -p < apps/job-service/src/main/resources/db/mysql/schema.sql
mysql -h 127.0.0.1 -u root -p careerlens < apps/job-service/src/main/resources/db/seed.sql

# 用 .env 覆盖连接信息后本地起 Java
MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_USER=root MYSQL_PASSWORD=*** \
MYSQL_DATABASE=careerlens mvn -f apps/job-service/pom.xml spring-boot:run
```

> **环境变量命名**（统一写进 `.env.example`）：
> `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DATABASE` / `MYSQL_USER` / `MYSQL_PASSWORD` / `STORAGE_MODE`
> 真实密码只进 `.env`（已 gitignore），仓库里只留 `.env.example` 占位。

---

## 9. CI/CD 设计

### 9.1 分支与工作流

```
main         ← 受保护，仅接受 PR，CI 必须绿灯
 └ develop   ← 集成分支
    └ feature/*  ← 功能分支
```

- 提交规范：Conventional Commits（`feat:` / `fix:` / `chore:` / `docs:`）
- 合并方式：Squash merge
- **提交门禁（人工审核）**：`git commit` **不由 AI / 脚本自动发起**。每次提交前必须由人工通读 diff 并按 `tasks.md` 附录 C.2 清单确认，通过后才提交。
  - 门禁顺序：**完成改动 → 人工审核 → 提交**，不可颠倒
  - 审核不通过 → 改代码，**不提交**（不允许"先提交再修"）
  - 人工审核暂时不可用 → 继续开发但**不提交**，恢复后按任务边界拆开补提交
  - 依据：`spec.md` §3.5「禁止未经人工审核即提交」

### 9.2 `ci.yml`（PR 与 push 触发）

matrix 并行跑四层：

| 层 | lint | test | build | 备注 |
|---|---|---|---|---|
| web | eslint | vitest | vite build | — |
| bff | eslint | jest + supertest | tsc | — |
| job-service | checkstyle（可选） | JUnit 5 | mvn package | **用 `services: mysql:8.0` 跑一组真实库测试；另一组用 `local` 模式跑降级测试** |
| analyzer | ruff | pytest | — | — |

> job-service 的两组测试分别覆盖 AC9（`mysql` 模式）与 AC10（`local` / `mock` 模式）——**降级路径必须进 CI**，否则它一定会烂掉。
> 数据库测试用 `spring.jpa.hibernate.ddl-auto=validate` 校验实体与 `schema.sql` 是否一致，避免"代码能跑但建表语句已经过期"。

### 9.3 `docker.yml`（main 分支触发）

构建四个镜像，打 `latest` + `sha` 双标签，推送 GHCR。

---

## 10. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| 1 | Java/Spring 为团队最弱一环 | 进度阻塞 | 只做 3 个 endpoint，不做鉴权/分页；实体与 Repository 直接照 `schema.sql` 生成 |
| 2 | **MySQL 编排吃掉时间**（容器启动慢、端口占用、初始化失败） | 阻塞关键路径 | ① `app.storage.mode=auto` 自动降级，**数据库问题不阻塞主线**（ADR-003 回退条件）② 本地已有 MySQL 时直接复用，不起容器 |
| 3 | **MySQL 凭据泄漏** | 事故级 | 连接串全走环境变量；`.env` 进 `.gitignore`；仓库只留 `.env.example`；日志不打印连接串（spec.md §3.3） |
| 4 | **降级路径从未被验证过**（"写了但跑不通"） | 答辩现场翻车 | 降级测试进 CI（§9.2）；AC10 作为独立验收项；演示环节强制跑一次（spec.md §4.3-5） |
| 5 | LLM Key 泄漏 | 事故级 | 环境变量 + `.env.example`；`.env` 进 `.gitignore`；AI_LOG 打码 |
| 6 | LLM 不可用/不稳定 | 主流程失败 | 规则兜底 + `degraded` 标记（ADR-004） |
| 7 | 被判"纯 AI UI" | 直接扣分 | shadcn-vue 组件改造留痕，AI_LOG 记录改动点 |
| 8 | 3 小时做 4 个服务 + 1 个数据库失控 | 交付不完整 | 竖切策略：先假数据打通全链，再逐层替换实现；MySQL 排在竖切之后 |
| 9 | 技能词典覆盖不足 | 归一化率低 | 先覆盖常见 60 条，未登录词标 `unknown` 不阻断 |

---

## 11. 时间预算（3 小时）

| 时段 | 动作 | 里程碑 |
|---|---|---|
| 0:00–0:15 | 定契约、建仓、首次 commit | 契约冻结 |
| 0:15–0:45 | Python analyzer：先返回**硬编码 JSON** | `/internal/analyze` 可独立调通 |
| 0:45–1:15 | **竖切联调**：BFF 转发 → Vue 显示 | ★ **全链贯通，安全垫到手** |
| 1:15–1:45 | Java job-service：3 个 endpoint + **H2 降级模式先跑通** | 可独立调通（`storage=local`） |
| 1:45–2:05 | **接入 MySQL**：`schema.sql` / `seed.sql` + Compose `mysql` 服务 | `storage=mysql`，AC9 通过 |
| 2:05–2:25 | 补真实算法：清洗 / 归一化 / 打分 + LLM 接入与降级 | 业务闭环真通 |
| 2:25–2:45 | 前端打磨：组件改造、结果可视化、错误态 | UI 可演示 |
| 2:45–3:00 | Compose 联调 + 健康检查 + 降级演练 + CI + 三份文档 + 提交 | 交付完成 |

> **核心原则：任何时刻仓库都是可运行的。** 1:15 里程碑之后，每一层都是"替换实现"，而不是"从零搭"。
>
> **MySQL 排序理由**：先让 H2 模式跑通（1:15–1:45），再切 MySQL（1:45–2:05）。这样即使 MySQL 那段超时，仓库里也已经有一个**功能等价、契约一致**的可运行版本——降级路径反而是先被验证的那条。
