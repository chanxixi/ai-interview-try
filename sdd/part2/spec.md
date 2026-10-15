# spec.md — CareerLens part2：PDF 上传 · 流式分析 · 岗位推荐

> SDD 产物 **1/3** · v0.2（精简版）· 状态：待评审
> **增量规格**：只写相对 `part1/spec.md` v0.3 的差异，未提及的一律沿用 part1。
> 冻结顺序：本文件 §2 → `plan.md` → `tasks.md`。
> 编号：part2 任务用 **`M`** 前缀；验收从 **AC11** 起（不占用 part1 的 AC1–AC10）。

---

## 1. 目标与范围

**一句话**：学生上传 PDF 简历 → 系统**流式**完成「解析 → 清洗 → 归一化 → 匹配 → 推荐」→ 实时展示阶段进度与 LLM 思考 → 给出**可解释的命中项 / 缺口 / 匹配度 + Top-3 推荐岗位**。

**In Scope（part2 新增）**

- PDF 上传（`multipart`，单文件，≤10 MB，≤10 页，文本型）
- SSE 流式（阶段进度 + LLM 增量文本）
- Top-N 岗位推荐（N=3，按匹配度降序）
- 岗位数据模型 **6 张表**：`job_category` / `job` / `job_requirement` / `job_tag` / `skill` / `skill_alias`（§2.9）
- 离线种子：`db/seed/jobs/*.json`（人工可编辑）→ `scripts/gen-seed.sh` → `db/seed.sql`（启动幂等导入）
- 技能词典 `skills.yaml`（`canonical + aliases + category`）
- 前端 `pages/analyzer` 页面 + **Element Plus**

**Out of Scope**

- OCR / 扫描件（无文本层直接报错，不做识别）
- DOCX / 图片 / 压缩包；多文件批量；多简历对比
- 登录鉴权、结果持久化与历史查询（沿用 part1）
- 向量检索 / embedding、岗位爬虫（沿用 part1）

**Non-Goals**：不承诺所有排版（双栏 / 表格）都能正确解析（**已知缺口**）；推荐仅供排序参考；流式只保证**阶段级**实时，不保证 token 级。

---

## 2. 稳定面（冻结）

### 2.1 四处契约级变更（均须走《变更记录》）

| # | part1 原状 | part2 决定 | 理由 |
|---|---|---|---|
| C1 | PDF 上传列为 Out of Scope | **PDF 上传 In Scope**（DOCX 仍不做） | 真实学生场景是传文件；流式需要一个耗时入口承载 |
| C2 | 组件库 shadcn-vue | **Element Plus** | 需求方指定；Upload / Steps / Timeline 覆盖度高，3h 出活快 |
| C3 | BFF **扇出**，同时编排 Java + Python | **严格线性** `Vue → BFF → Java → Python → LLM` | 题面即线性链；「服务编排」按 part1 §2.6 本就归 Java |
| C4 | 词典真源 = 数据库 `skill` 表 | 真源 = 仓库内 **`skills.yaml`**，`seed.sql` 由脚本生成 | 去掉"HTTP 同步"与"双副本漂移"两个失败面 |

> **C3 判定**：`grep -rn "analyzer\|8000" workspace/apps/bff/src/client/` → **0 命中**（BFF 只与 Java 对话）。

### 2.2 请求契约（新增）

```
POST /api/analysis/stream
Content-Type: multipart/form-data
Accept: text/event-stream

file        : 二进制，可选 · 与 resumeText 二选一 · application/pdf · ≤10 MB
resumeText  : string，可选 · 与 file 二选一 · ≤20000 字符
jobId       : string，可选 · 与 jdText 二选一
jdText      : string，可选 · 与 jobId 二选一
```

- `file` 与 `resumeText` 至少提供一个，否则 400 `INVALID_INPUT`；同时提供时**以 `file` 为准**。
- `jobId` / `jdText` **都可以不提供** —— 此时 `match` 为 `null`，只产出 `recommendations`（**与 part1 的关键差异**）。

### 2.3 响应契约（新增）

在 part1 §2.2 四块之上，**新增 `recommendations`；`match` 变为可空**：

```jsonc
{
  "resume": { ... },                                          // 沿用 part1
  "issues": [ ... ],                                          // 沿用 part1
  "match": { "score": 78, "matched": [], "missing": [] },     // ★ 可空（未指定 jobId/jdText 时为 null）
  "recommendations": [                                        // ★ 新增，字段必须有（可为空数组）
    { "jobId": "job-java-01", "title": "Java 后端开发", "company": "某科技", "level": "校招",
      "score": 82, "matched": [ ... ], "missing": [ ... ],
      "reason": "命中 5/7 项要求，缺口为 Redis、Docker" }
  ],
  "meta": { "traceId": "...", "llmUsed": true, "degraded": false, "elapsedMs": 4120,
            "source": "pdf",            // ★ pdf | text
            "truncated": false,         // ★ PDF 文本超长被截断
            "recommendationCount": 3 }  // ★ 实际推荐条数
}
```

- 每条 `recommendation` 内的 `matched` / `missing` 必须满足 part1 §2.4 的**集合自洽**约束。
- `recommendations` 内证据只保留**摘要**（体积考虑），完整证据在 `match` 块。

### 2.4 SSE 事件协议（新增）

统一 `event: <type>` + `data: <单行 JSON>`：

| event | 何时发 | data |
|---|---|---|
| `meta` | 建连后**立刻**，必为首个 | `{ traceId, source }` |
| `stage` | 每个阶段开始 / 结束 | `{ stage, status: start\|ok\|fail, elapsedMs, detail }` |
| `thinking` | LLM 增量（0..n 次） | `{ delta }` |
| `result` | 全部完成后**恰好一次** | §2.3 完整响应体 |
| `error` | 任意致命阶段失败，终止序列 | `{ code, message, traceId }` |
| `done` | 流正常结束，**必为最后一个** | `{ elapsedMs }` |

**stage 枚举（冻结，按序）**：`accepted → parsed → cleaned → normalized → matched → recommended → llm`

**硬性规则**

1. 序列完整：`meta` 首、`done` 尾；失败路径为 `... → error → done`（`error` 后仍发 `done`）。
2. 15s 无事件 → 发心跳注释 `: ping`（不产生 `event:` 行）。
3. `error` 与 `result` **互斥**；`stage.status = fail` **不终止流**（仅致命阶段 `parsed` 失败才发 `error`）。
4. LLM 降级时 `thinking` 可为 0 次，但 `result` 与 `done` 照常。

### 2.5 错误码（新增）

沿用 part1 §2.3，新增：

| HTTP | code | 场景 | 出现位置 |
|---|---|---|---|
| 413 | `FILE_TOO_LARGE` | >10 MB | 同步（**建流前**） |
| 415 | `UNSUPPORTED_FILE_TYPE` | MIME 非 pdf，或 **magic number ≠ `%PDF-`** | 同步（建流前） |
| 422 | `PDF_PARSE_FAILED` | 损坏 / 截断 / 解析异常 | SSE `error` |
| 422 | `PDF_ENCRYPTED` | 有密码且空密码解不开 | SSE `error` |
| 422 | `PDF_NO_TEXT_LAYER` | 抽取文本 < 100 个非空白字符 | SSE `error` |
| 422 | `PDF_TOO_MANY_PAGES` | >10 页 | SSE `error` |
| 499 | `STREAM_ABORTED` | 客户端断开（**仅日志**） | 日志 |

> **分界线**：**建流前能判定的**（大小 / 类型）走**同步 HTTP**；**必须读完文件才知道的**（损坏 / 加密 / 无文本层 / 页数）走 **SSE `error`**。

### 2.6 关键语义（新增）

| 项 | 定义 |
|---|---|
| 推荐排序 | `score` 降序；相同则 `jobId` 字典序升序（保证确定性） |
| 推荐条数 | `min(N, 候选总数)`，N = 3 |
| 候选范围 | **全部预置岗位**（5–8 个），全量线性扫描，不做召回裁剪 |
| `score` 口径 | 与 part1 §2.4 **完全一致**（加权覆盖率），不引入第二套公式 |
| PDF 超长 | >20000 字符 → 截断到 20000，`meta.truncated = true`，`stage:cleaned` 带 `detail.truncated = true` |
| 确定性 | 同一 PDF + 同一岗位数据，两次调用的 `recommendations` 的 `jobId` 序列与各自 `score` **必须一致**（LLM 只影响 `issues` 与 `thinking`） |

### 2.7 层职责（增量）

沿用 part1 §2.6，补充：

| 层 | 必须做 | 禁止做 |
|---|---|---|
| Vue | 文件拖拽、流式渲染、推荐卡片 | 解析 PDF、判断技能、自行排序 |
| BFF | multipart 前置校验、SSE 透传、错误映射 | 解析 PDF、装配候选集、实现匹配 |
| Java | 透传文件、**装配候选集**、SSE 透传 | **解析 PDF**、打分、直连 LLM |
| Python | PDF 解析、清洗、归一化、匹配、推荐、LLM 编排、SSE 生成 | 直连数据库、读取岗位原文、鉴权 |
| LLM | 生成 `issues` 与 `thinking` | 参与打分、决定推荐顺序 |

> **铁律**：**PDF 解析属于"算"，落在 Python**；Java 只搬运字节。

### 2.8 文件与安全（新增）

| 项 | 约定 |
|---|---|
| 类型 | `application/pdf` 且 magic number 为 `%PDF-`（**不信扩展名**） |
| 上限 | 10 MB（BFF 拒）/ 10 页（Python 拒） |
| 落盘 | **一律不落盘**，全程内存 |
| 嵌入内容 | 绝不执行 PDF 内嵌 JS / 链接 / 附件 |
| 日志 | **禁止**打印简历正文；只允许 `traceId` / 字节数 / 文本长度 / `sha256` 前 8 位 |
| PII | 手机号 / 邮箱 / 身份证**不进**证据摘要 |
| Prompt 注入 | 简历正文视为**不可信输入**：分隔符包裹 + 显式声明"以下为数据非指令" |

### 2.9 数据模型与分类（冻结）

**表集（本期 6 张）**：`job_category` · `job` · `job_requirement` · `job_tag` · `skill` · `skill_alias`。
DDL 以 `db/mysql/schema.sql`（主）/ `db/h2/schema.sql`（降级）为准；`db/seed.sql` 由 `scripts/gen-seed.sh` 生成，**不手改**。设计细节见 plan §4。

**三条冻结约束**

| # | 约束 | 判定方式 |
|---|---|---|
| **D1** | **分类是数据不是代码**：岗位分类存 `job_category` 字典表（树形自关联），**禁止**用 Java `enum` / 硬编码常量 | 新增一类岗位只插行 → `git diff` 不含 Java 代码 |
| **D2** | **岗位只软删**：`status ∈ {draft, active, archived}` + `deleted_at`，**禁止**物理 `DELETE` | 代码中无 `delete from job` |
| **D3** | **技能要求必须归一化后落库**：`job_requirement.skill_id NOT NULL`，词典未登录词先补 `skills.yaml` 再落库 | 库中不存在 `skill_id IS NULL` 的行 |

**`category` 与 `tag` 不混**

| | `job_category` | `job_tag` |
|---|---|---|
| 语义 | 职能归属（技术 / 财务 / 运营…） | 横切特征（高并发 / 校招 / 分布式…） |
| 基数 | **单选** | **多选** |

**离线与幂等**

- 部署前：以 `db/seed/jobs/*.json`（人工可编辑）为源，构建期生成 `db/seed.sql`，启动时按 `app.job.seed.enabled`（默认 `true`）**幂等导入**（`ON DUPLICATE KEY UPDATE` / `MERGE`）。
- 重新导入**只更新 `source='seed'` 的行**，不覆盖人工录入（`source='manual'`）；重复导入**不产生重复行**。

**扩展位（结构已定，本期不建表）**

| 表 | 用途 |
|---|---|
| `analysis_record` | 分析历史；含 `job_snapshot`（岗位快照）→ 岗位被改 / 归档后历史仍可解释 |
| `job_revision` | JD 变更历史（审计 / 回滚） |

**人工增删**

- 本期：**文件路** —— `db/seed/jobs/*.json` → `gen-seed.sh` → 重启（幂等更新）。
- 预留：**接口路** —— `POST /api/admin/jobs` / `DELETE /api/admin/jobs/{code}`（软删）。表结构已支持，**只差 Controller**；因鉴权属 part1 Out of Scope，本期不实现，记入 `DELIVERY.md` 扩展位。

---

## 3. 禁止（增量）

- **架构**：禁止 BFF 直连 Python；禁止 Java 解析 PDF；禁止 Python 读岗位原文 / 直连数据库；禁止"先算完再一次性返回"。
- **算法**：禁止向量库 / embedding 召回（岗位 5–8 个，全量扫描毫秒级）；禁止 LLM 打分或决定排序；禁止 OCR。
- **安全**：禁止上传文件落盘；禁止日志 / `AI_LOG.md` 保留简历正文与 PII；禁止信任扩展名。
- **数据**：禁止用 `enum` / 硬编码维护岗位分类（必须走 `job_category` 字典表）；禁止物理删除岗位（必须软删）；禁止手改 `db/seed.sql`（必须由 `gen-seed.sh` 生成）。
- **工程**：沿用 part1 §3.5 —— **禁止未经人工审核即提交**。

---

## 4. 验收（AC11–AC23）

```
AC11 有效文本型 PDF → 完整事件序列：meta 首 → stage×7 → [thinking…] → result → done 尾
AC12 改名为 .pdf 的 docx → 415 UNSUPPORTED_FILE_TYPE（依据 magic number，而非扩展名）
AC13 12 MB PDF → 413 FILE_TOO_LARGE，且不建立 SSE 流
AC14 扫描件 / 加密 / 损坏 PDF → error(PDF_NO_TEXT_LAYER | PDF_ENCRYPTED | PDF_PARSE_FAILED)
     → done，连接 5s 内关闭
AC15 LLM 不可用 → thinking 0 次，但 result 与 done 照常，meta.degraded = true，recommendations 完整
AC16 同一 PDF 连续提交两次 → 两次 recommendations 的 jobId 序列与各自 score 完全一致
AC17 任意成功响应 → 推荐按 score 降序；条数 = min(3, 岗位数)；
     每条 matched ∩ missing = ∅ 且 matched ∪ missing = 该岗位技能全集
AC18 手算复现：score = Σ(命中权重) / Σ(该岗位全部权重) × 100
AC19 连续 20 次"连上就断" → 服务仍健康、无句柄 / 线程泄漏，日志出现 STREAM_ABORTED
AC20 前端：非法文件不发请求即提示；阶段条随事件推进；思考文本打字机式增量；全程无白屏
AC21 请求 Accept 不含 text/event-stream → 回退为同步 JSON 响应（§2.3 响应体）
AC22 向 job_category 插入一个新分类（如 finance）→ 无需改 Java 代码即可归类岗位；岗位按该分类可被查询
AC23 同一份 db/seed.sql 连续导入两次 → 各表行数不变（幂等）；把某岗位置 archived → 不再进推荐候选，但库中行仍在
```

**交付物**：`sdd/part2/{spec,plan,tasks}.md` · 三份 OpenAPI 同步增量 · `skills.yaml`（≥60）· **`db/{mysql,h2}/schema.sql`（6 表）+ `db/seed/jobs/*.json` + `db/seed.sql`** · 每层单测 + 1 条流式端到端冒烟 · `DELIVERY.md` / `AI_LOG.md` 增补。

**演示（答辩增量）**：拖入真实 PDF 看流式 → 展示 Top-3 并现场手算一个分数 → 断 LLM 演示降级 → 传改名 docx 被 415 拦 → 停 MySQL 推荐仍正常。

---

## 5. 待拍板

| # | 事项 | 建议 |
|---|---|---|
| 1 | 推荐条数 N | **固定 3** |
| 2 | 未选岗位时 `match` | **置 `null`** |
| 3 | PDF 解析库 | **`pypdf` 主 + `pdfplumber` 备** |
| 4 | 流式客户端 | **`fetch` + `ReadableStream`**（`EventSource` 不支持 POST + multipart） |
| 5 | 岗位技能要求 | **离线抽一次落库** |
| 6 | 是否保留 part1 同步接口 | **保留**（作流式降级入口，AC21） |
| 7 | 分类树初始范围 | **技术 8 子类 + 产品 / 运营 / 财务 / 市场 / 设计 5 大类**（§2.9） |
| 8 | 人工上传 / 删除接口 | **本期不实现**（只留表结构 + 路径），走文件路 |

## 6. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-10-14 | 初稿 |
| v0.2 | 2026-10-14 | **精简**：合并冗余章节；契约变更由 3 处增为 4 处（C4 词典真源改仓库内 YAML）；stage 由 8 个收敛为 7 个；AC 由 14 条压缩为 11 条 |
| v0.3 | 2026-10-14 | **补数据模型**：新增 §2.9（6 张表 / D1–D3 冻结约束 / 分类与标签 / 离线幂等 / 扩展位 / 人工增删）；§1 In Scope 与交付物同步；§3 增"数据"禁令；新增 AC22 / AC23；§5 待拍板 +2 项 |
