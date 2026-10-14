# tasks.md — CareerLens 最小纵向闭环（part1）

> SDD 阶段产物 **3 / 3** · 版本 v0.2
> 依赖：`spec.md`（要什么）、`plan.md`（怎么做）
> 本文档回答 **「谁、什么时候做、怎么算做完」**
>
> **v0.2 变更**：T4 扩为 10 条（存储抽象 / H2 降级 / Mock 兜底 / MySQL 接入），T7 增 `mysql` 服务与降级演练，T8 增存储降级文档与 CI 双模式测试；附录 A 增存储追溯项，附录 B 增第 5 条 DoD。

**使用方式**：边做边勾。每条任务必须写清**验收方式**，否则不算一条任务。
**时间基准**：全程 3 小时（180 分钟），时间盒见每阶段标题。

---

## 0. 进度总览

| 阶段 | 时间盒 | 任务数 | 里程碑 | 状态 |
|---|---|---|---|---|
| T0 仓库与骨架 | 0:00–0:10 | 4 | 仓库可提交 | ☐ |
| T1 契约冻结 | 0:10–0:15 | 4 | **契约冻结** | ☐ |
| T2 Python 骨架 | 0:15–0:45 | 5 | analyzer 可独立调通 | ☐ |
| T3 竖切贯通 ★ | 0:45–1:15 | 6 | **全链贯通（安全垫）** | ☐ |
| T4 Java job-service | 1:15–2:05 | 10 | 领域接口可独立调通（local + mysql 双模式） | ☐ |
| T5 真实算法 + LLM | 2:05–2:25 | 9 | 业务闭环真通 | ☐ |
| T6 前端打磨 | 2:25–2:45 | 7 | UI 可演示 | ☐ |
| T7 基础设施 | 2:45–2:53 | 7 | `compose up` 全绿 + 降级可演示 | ☐ |
| T8 CI/CD 与文档 | 2:53–3:00 | 6 | **交付完成** | ☐ |

**关键路径（不可延误）**：T1 → T2 → T3 → T5 → T7 → T8
**可压缩项**：T4 的岗位数量、T6 的动效、T5.6 的 LLM 接入（可延后到 T6 之后）
**可降级项**：T4.8 的 MySQL 接入 —— **若 2:05 仍未跑通，直接把 `STORAGE_MODE` 固定为 `local` 继续推进**，MySQL 挪到 T7 补，绝不阻塞关键路径（plan.md ADR-003 回退条件）

---

## T0 · 仓库与骨架（0:00–0:10）

- [ ] **T0.1** 建立 monorepo 目录结构
  - 验收：`sdd/ contracts/ apps/{web,bff,job-service,analyzer}/` 均存在
- [ ] **T0.2** 写 `.gitignore`
  - 必含：`node_modules/`、`target/`、`__pycache__/`、`.venv/`、**`.env`**
  - 验收：`git status` 中看不到 `.env`
- [ ] **T0.3** 写 `.env.example`
  - 含 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`（值留空）
  - 含 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`、`STORAGE_MODE`
  - 验收：`.env.example` 中**无任何真实凭据**；`STORAGE_MODE` 默认值注释为 `auto`
- [ ] **T0.4** 首次提交
  - `chore: init monorepo skeleton`
  - 验收：`git log --oneline` 有第一条记录

---

## T1 · 契约冻结（0:10–0:15）★ 关键路径

- [ ] **T1.1** `contracts/frontend-bff.yaml`（OpenAPI 3.1）
  - 覆盖：`POST /api/analysis`、`GET /api/jobs`、`GET /healthz`
  - 验收：字段名与 `spec.md` §2.1 / §2.2 **逐字一致**
- [ ] **T1.2** `contracts/bff-java.yaml`
  - 覆盖：`GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills`
- [ ] **T1.3** `contracts/bff-python.yaml`
  - 覆盖：`POST /internal/analyze`、`GET /healthz`
- [ ] **T1.4** 提交 `docs: freeze api contracts`
  - 验收：三份契约的请求/响应字段全部确定，四层可并行开发

> ⚠️ **这一步不做完不许写业务代码。** 契约是四层不返工的唯一保障。

---

## T2 · Python analyzer 骨架（0:15–0:45）

> 策略：**先返回硬编码 JSON**，把服务跑起来，业务逻辑留到 T5。

- [ ] **T2.1** FastAPI 骨架 + `GET /healthz`
  - 验收：`curl localhost:8000/healthz` → `{"status":"ok"}`
- [ ] **T2.2** `POST /internal/analyze` 返回**硬编码**四块 JSON
  - 验收：`curl` 能拿到 `resume / issues / match / meta` 四个 key
- [ ] **T2.3** 定义 Pydantic 模型（`AnalyzeResult` / `MatchedItem` / `Issue` …）
  - 验收：与 `plan.md` §4.5 一致
- [ ] **T2.4** pytest 一条用例
  - 验收：`pytest` 通过
- [ ] **T2.5** 提交 `feat(analyzer): scaffold with stub response`

---

## T3 · 竖切贯通（0:45–1:15）★ 里程碑

> **这是全题最重要的一步**：哪怕数据是假的，也要先让 Vue 屏幕上有结果。

- [ ] **T3.1** BFF 骨架（Koa2 + TS）+ `/healthz` + pino + traceId 中间件
  - 验收：响应 header 含 `X-Trace-Id`，日志为 JSON
- [ ] **T3.2** `POST /api/analysis`：zod 校验 → 转发 Python
  - 验收：空 `resumeText` → 400 `INVALID_INPUT`（对应 AC2）
- [ ] **T3.3** 超时 + 错误映射中间件
  - 验收：手动让 Python 停掉 → 返回 `503 SERVICE_UNAVAILABLE`
- [ ] **T3.4** Vue 骨架 + 表单 + 结果渲染（数据可假）
  - 验收：页面能提交并显示四块结果
- [ ] **T3.5** 端到端 curl 打通
  - 验收：`curl -X POST localhost:3000/api/analysis ...` 返回四块 JSON
- [ ] **T3.6** 提交 `feat: vertical slice end-to-end (stub data)` ★

> 到这里，**你已经有了一份能跑的交付物**。后面每一步都是替换实现，而不是从零搭。

---

## T4 · Java job-service（1:15–2:05）

> **顺序原则**：先跑通 `local`（H2）模式，再切 `mysql`。这样即使 MySQL 那段超时，仓库里也已经有一个功能等价的可运行版本。
> **对应**：spec.md §2.9 存储与降级约定、plan.md §4 数据模型、ADR-003 / ADR-007。

- [ ] **T4.1** Spring Boot 骨架 + `/healthz`
  - 验收：`curl localhost:8080/healthz` 返回 `status = ok`
- [ ] **T4.2** 存储抽象层：`JobRepository` / `SkillRepository` 接口 + 领域 DTO
  - 依据：ADR-007（接口 + 多实现，降级是装配期决策而非运行期 if/else）
  - 验收：接口方法只有 `findAllJobs` / `findJobById` / `findAllSkills` 三类只读操作
- [ ] **T4.3** `db/h2/schema.sql` + `db/seed.sql`（3 个开发岗 JD + 约 60 条技能词典）
  - 验收：`seed.sql` 幂等，重复执行不报错
- [ ] **T4.4** 实现 `GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills`（`local` 模式先跑通）
  - 验收：与 `contracts/bff-java.yaml` 一致；`GET /api/jobs` 返回 3 条
- [ ] **T4.5** Mock 兜底实现 + `app.storage.mode` 探测与条件装配（`auto` → `mysql` → `local` → `mock`）
  - 验收：`STORAGE_MODE=mock` 启动时三个接口仍返回数据
- [ ] **T4.6** `/healthz` 暴露 `storage` 字段
  - 验收：三种模式启动分别返回 `mysql` / `local` / `mock`
- [ ] **T4.7** JUnit：`local` 与 `mock` 双模式用例（内存实现注入，不依赖数据库）
  - 验收：`mvn test` 通过；对应 **AC10**
- [ ] **T4.8** **接入 MySQL** ★ 可降级项
  - `db/mysql/schema.sql`（utf8mb4 / InnoDB）+ `docker-compose.yml` 加 `mysql` 服务（healthcheck + volume）+ 启动连接重试
  - 验收：**AC9 通过**（`GET /api/jobs` 数据来自库，`/healthz` 的 `storage = mysql`）
  - ⚠️ **超时处理**：若此时仍未跑通，把 `STORAGE_MODE` 固定为 `local` 继续 T5，MySQL 挪到 T7 补
- [ ] **T4.9** BFF 接入 Java：`jobId` 场景先取 `jdText` 再调 Python
  - 验收：传 `jobId` 与传对应 `jdText` 结果一致
- [ ] **T4.10** 提交 `feat(job-service): job & skill domain api with storage fallback`

---

## T5 · 真实算法 + LLM（2:05–2:25）

- [ ] **T5.1** `skills.yaml` 技能词典（canonical + aliases + category）
  - 验收：覆盖 JS / TS / Java / Spring Boot / Vue / MySQL / Redis / Docker 等常见项
- [ ] **T5.2** 清洗模块
  - 验收：一份真实脱敏简历能切出 教育/工作/项目/技能 四类区块（对应 G1）
- [ ] **T5.3** 归一化模块
  - 验收：AC6 通过（词典内 alias 全部正确映射）
- [ ] **T5.4** 匹配打分模块（加权覆盖率）
  - 验收：AC4 通过（同输入两次结果一致）、AC7 通过（集合自洽）
- [ ] **T5.5** 简历问题规则引擎（5 类：NO_QUANTIFY / NO_STAR / SKILL_STUFFING / TIMELINE_GAP / MISSING_CONTACT）
  - 验收：AC8 通过
- [ ] **T5.6** LLM 接入（`openai` SDK + `base_url` 可配）
  - 验收：`.env` 配好后能拿到结构化输出
- [ ] **T5.7** 降级包装：超时 / 报错 / Pydantic 校验失败 → 走规则分支 + `degraded = true`
  - 验收：**AC3 通过**（断开 LLM 仍返回完整四块）
- [ ] **T5.8** 单测补齐：覆盖 AC4 / AC6 / AC7 / AC8
  - 验收：`pytest` 全绿
- [ ] **T5.9** 提交 `feat(analyzer): real cleaning, normalization & matching`

---

## T6 · 前端打磨（2:25–2:45）

- [ ] **T6.1** 接入 shadcn-vue 并**改造**组件（改配色 / 间距 / 交互）
  - 验收：AI_LOG.md 记录"改了哪个组件、改了什么、为什么"
- [ ] **T6.2** 匹配度环形图（ECharts）
- [ ] **T6.3** 命中项 / 缺口列表 + **证据高亮**（用 `jdOffset` / `resumeOffset`）
  - 验收：对应 AC5 的可视化呈现
- [ ] **T6.4** 简历问题清单（按 severity 排序）
- [ ] **T6.5** 错误态与 loading 态
  - 验收：后端停掉时页面显示友好提示而非白屏
- [ ] **T6.6** 浅色 / 深色主题切换
- [ ] **T6.7** 提交 `feat(web): result visualization & themed ui`

---

## T7 · 基础设施（2:45–2:53）

- [ ] **T7.1** 四个 Dockerfile（**多阶段构建** + 非 root 用户）
- [ ] **T7.2** 四个 `.dockerignore`
  - 验收：`node_modules/`、`target/`、`.venv/` 不入镜像
- [ ] **T7.3** `docker-compose.yml`：网络 + `healthcheck` + `depends_on: condition: service_healthy`
- [ ] **T7.4** `mysql` 服务：`mysql:8.0` + `MYSQL_*` 环境变量 + `mysqladmin ping` healthcheck + `mysql-data` volume + 首次启动挂 `db/mysql/schema.sql` / `db/seed.sql`
  - 验收：`docker compose up mysql` 后库表与种子数据存在；`job-service` 等到 healthy 才启动
- [ ] **T7.5** `docker compose up --build` 全绿
  - 验收：四个 `/healthz` 均返回 ok，Java 的 `storage = mysql`
- [ ] **T7.6** **降级演练**：`docker compose up job-service`（不起 mysql）
  - 验收：**AC10 通过** —— `/healthz` 的 `storage = local`，三个领域接口数据完整
- [ ] **T7.7** 提交 `chore: dockerize all services`

---

## T8 · CI/CD 与文档（2:53–3:00）

- [ ] **T8.1** `.github/workflows/ci.yml`：matrix 跑 4 层 lint + test + build
  - job-service 需声明 `services: mysql:8.0`，并**分别**跑 `mysql` 模式与 `local` / `mock` 模式两组测试
  - 验收：降级路径被 CI 覆盖（对应 **AC9 / AC10**）
- [ ] **T8.2** `.github/workflows/docker.yml`：main 分支构建镜像并打 `latest` + `sha` 双标签
- [ ] **T8.3** `DELIVERY.md` —— **五块必须全**
  - [ ] 启动（实际验证过的命令）
  - [ ] 测试
  - [ ] 部署 / 回滚
  - [ ] 架构取舍（引用 ADR-001 ~ ADR-007）
  - [ ] 已知缺口
  - [ ] **存储降级说明**：三种模式如何触发、如何验证（AC9 / AC10），以及"MySQL 挂了怎么办"的现场操作步骤
- [ ] **T8.4** `AI_LOG.md` —— vibcoding 会话记录（**密钥必须脱敏**）
  - 建议表格：`时间 | 提问 | AI 给的方案 | 我的改动 | 原因`
- [ ] **T8.5** `README.md`（架构图 + 快速开始）
- [ ] **T8.6** 最终提交 `docs: delivery notes, ai log & ci/cd`

---

## 附录 A · 任务 → 需求追溯

| 需求 | 覆盖任务 | 验收标准 |
|---|---|---|
| R1 简历文本提交 | T3.2、T6.1 | AC2 |
| R2 岗位选择 | T1.2、T4.4、T4.8、T4.9 | AC9 |
| R3 数据清洗 | T5.2 | G1 |
| R4 技能归一化 | T5.1、T5.3 | AC6 |
| R5 匹配分析 | T5.4 | AC4、AC7 |
| R6 简历结构化问题 | T5.5、T6.4 | AC8 |
| R7 可解释命中项 | T5.4、T6.3 | AC5 |
| R8 能力缺口 | T5.4、T6.3 | AC7 |
| R9 岗位匹配度 | T5.4、T6.2 | AC1、AC4 |
| R10 最小纵向闭环 | T0、T3、T8.3 | 交付物验收 |
| R11 轻度算法 | T5.4、T5.7 | AC3 |
| 降级能力（LLM） | T5.7、T8.3 | **AC3** |
| **存储：MySQL 主路径** | T4.8、T7.4 | **AC9** |
| **存储：降级到本地 / Mock** | T4.2、T4.3、T4.5、T4.6、T4.7、T7.6 | **AC10** |
| 全链贯通 | T3.5 | AC1 |

## 附录 B · 完成定义（DoD）

一条任务只有同时满足以下 5 条才算「做完」：

1. 代码已提交，且 commit message 符合 Conventional Commits
2. 该层的 lint / test 通过
3. `docker compose up` 后链路仍然可跑通（不破坏已有功能）
4. 如果引入了新的外部依赖或环境变量，已同步更新 `.env.example` 与 `README.md`
5. **若改动涉及存储层：`mysql` 与 `local`（或 `mock`）两种模式都必须跑通，不得只验证其中一种**

## 附录 C · 提交节奏要求

- 每 **20–30 分钟**至少一次 commit
- 禁止单次巨型提交（题目明确要求"保留计时期间的提交历史"）
- 提交信息示例：
  - `chore: init monorepo skeleton`
  - `docs: freeze api contracts`
  - `feat(analyzer): scaffold with stub response`
  - `feat: vertical slice end-to-end (stub data)`
  - `feat(job-service): job & skill domain api with storage fallback`
  - `feat(job-service): mysql persistence with auto-degradation`
  - `feat(analyzer): real cleaning, normalization & matching`
  - `feat(web): result visualization & themed ui`
  - `chore: dockerize all services`
  - `docs: delivery notes, ai log & ci/cd`
