# tasks.md — CareerLens part2：任务拆解

> SDD 产物 **3/3** · v0.3（补数据模型）· 依赖 `sdd/part2/{spec,plan}.md`
> 只列 part2 **增量任务**；**提交门禁、DoD、审核清单沿用 `sdd/part1/tasks.md`**。
> 时间基准：增量 150 分钟（plan §11），按实际等比缩放。

> ### ⛔ 提交门禁（逐字沿用 part1）
>
> AI / 脚本**不得自动提交**。铁律：完成改动 → **人工通读 diff** → 人工回复"通过" → 才 `git commit`。
> 禁 `--no-verify`、禁批量补提交；审核不过 → 先改代码不提交。
> **part1 门禁违规（11 个提交未经审核）未裁决前，本文件所有"提交 xxx"仅为"准备好一次提交"。**

---

## 进度总览

| 阶段                       | 时间          | 里程碑                         |
| -------------------------- | ------------- | ------------------------------ |
| M0 准备与目录              | 0:00–0:05     | 目录与词典地基就位             |
| M1 契约增量冻结 ★          | 0:05–0:15     | **契约冻结**                   |
| **M1.5 DB Schema 与种子**  | **0:15–0:25** | **6 张表就位 + seed 幂等导入** |
| M2 Python 解析与清洗       | 0:25–0:38     | 真实 PDF 抽出干净文本          |
| M3 Python 归一化·匹配·推荐 | 0:38–0:58     | 手算样例对照通过               |
| M4 Python 流式与 LLM       | 0:58–1:12     | `curl -N` 拿到完整事件序列     |
| M5 Java 承接与透传         | 1:12–1:32     | 经 Java 拿到同样序列           |
| M6 BFF 校验与透传          | 1:32–1:52     | 经 BFF 拿到同样序列            |
| M7 前端 analyzer 页        | 1:52–2:20     | 浏览器可演示                   |
| M8 联调·降级·交付          | 2:20–2:35     | 交付完成                       |

**关键路径** M1→**M1.5**→M2→M3→M4→M5→M6→M7 ｜ **可压缩** 岗位数(5→3)、动效、LLM 真实接入(可先用假流) ｜ **可降级** M5 流式透传（40 分钟不通 → BFF 直连 Python，记偏差）

> 总 **155** 分钟（原 150 + M1.5 的 10 分钟，从 M7 动效让出 5 分钟）。

**实际进度（2026-10-14 21:10 核对文件后更新，不是凭印象）**

| 阶段 | 状态 | 说明 |
|---|---|---|
| M0 / M1 / M1.5 / M2 | ✅ 完成 | 目录、契约冻结、6 表 schema + seed、PDF 解析清洗 |
| M3 | ✅ 完成 | `normalizer` / `matcher` / `recommender` + 81 个新测试 |
| **M4** | ✅ 完成 | `sse_event` / `util/sse` / `analysis_stream_service` / `llm/*` / `rules` / `api/v1/stream` + 43 个新测试，全量 **260 passed** |
| M5 → M8 | ⏳ 未开始 | M5 Java 承接·候选集·透传 → M6 BFF 校验透传 → M7 前端 analyzer 页 → M8 联调降级交付 |

> **所有 `提交 xxx` 条目全部未执行** —— part1 门禁违规（11 个提交未经审核）尚未裁决，
> 按铁律一律只算「准备好一次提交」。当前 HEAD 仍是 **21** 个提交。
>
> **M3 的一处种子数据变更**：`db/seed/jobs/job-operation-01.json` 增加 `"_zeroRequirements": true`。
> 原文件的 `requirements: []` 是**有意的**（运营岗无技术技能要求，同时是 M3.3「岗位 0 技能」
> 边界的真实样本），但「有意为空」和「忘配了」在数据上长得一样。加这个标记后，
> `test_seed_consistency.py` 能区分两者。`gen-seed.sh` 忽略 `_` 前缀键，`db/seed.sql` 内容不变（已复跑核对）。
>
> **M4 的新增依赖**：`python-multipart==0.0.20`（`api/v1/stream.py` 的 `Form(...)` + `UploadFile`
> 入参需要它，否则 FastAPI 连路由都注册不上）。

---

## M0 · 准备与目录（0:00–0:05）

- [x] M0.1 建 `sdd/part2/`，放入三件套
- [x] M0.2 建 `web/src/pages/{analyzer,connectivity}/`（analyzer 下预留 `components/`、`composables/`）
- [x] M0.3 建 `analyzer/app/data/`
- [x] M0.4 `.gitignore` 覆盖运行期 `*.pdf`、`workspace/.logs/` → `git status` 无残留

## M1 · 契约增量冻结（0:05–0:15）★

> 不冻结不许写业务代码。

- [x] M1.1 `frontend-bff.yaml`：+ `POST /api/analysis/stream`，保留同步 `POST /api/analysis`
- [x] M1.2 `bff-java.yaml`：+ `POST /api/analysis/stream`
- [x] M1.3 `bff-python.yaml`：+ `POST /internal/analyze/stream`（含 `jobCandidates`，**不含 `jdText`**）
- [x] M1.4 三份契约补齐 SSE 事件 schema（6 类事件 + 7 个 stage，与 spec §2.4 逐字一致）
- [ ] M1.6 提交 `docs(part2): freeze streaming contracts` —— 门禁：`git diff` 无 `-` 行

## M1.5 · 数据库 Schema 与种子（0:15–0:25）

> 前置 = spec §2.9（D1–D3 冻结约束）；设计细节 = plan §4。**先建表再写 Java**，否则 M5 的 `ddl-auto=validate` 起不来。

- [x] M1.5.1 `db/mysql/schema.sql` + `db/h2/schema.sql`：**6 张表** —— `job_category` / `job` / `job_requirement` / `job_tag` / `skill` / `skill_alias`；含全部 `uk_*` 唯一键与索引（H2 版 `MODE=MySQL` 同构）
- [x] M1.5.2 `db/seed/jobs/*.json`：5–8 个岗位源（一岗一文件，含 `category` / `tags` / `jdRaw` / `requirements`）；**至少 1 个用真实 JD**（直播 / 视频全栈）
- [x] M1.5.3 `scripts/gen-seed.sh`：`skills.yaml` + `jobs/*.json` → `db/seed.sql`（分节 + 转义）；**禁止手改 seed.sql**
- [x] M1.5.4 幂等：全部 `INSERT ... ON DUPLICATE KEY UPDATE`（MySQL）→ 连续导入两次行数不变（AC23）
- [x] M1.5.5 `job_category` 种子：技术 8 子类 + 产品 / 运营 / 财务 / 市场 / 设计 5 大类（树形，`parent_id` 自关联）
- [x] M1.5.6 扩展位两表（`analysis_record` / `job_revision`）**只写注释不建**，记入 `DELIVERY.md`
- [ ] M1.5.7 提交 `feat(db): job schema, taxonomy seed & idempotent import`

## M2 · Python：解析与清洗（0:25–0:38）

- [x] M2.1 `requirements.txt` + `pypdf`（阿里云镜像装包成功）
- [x] M2.2 `service/pdf_parser.py`：**唯一**用 pypdf；输入 bytes → `PdfParseResult(text,pageCount,encrypted,hasTextLayer)`；处理损坏 / 加密 / 页数 / 无文本层
- [x] M2.3 无文本层判定：非空白字符 <100 → `has_textLayer=False`
- [x] M2.4 `service/cleaner.py`：去隐形字符(`\u200b`/`\xa0`/`\xad`)、全半角统一、合并断行、按章节切块、阅读顺序自检(WARN)、>20000 截断标记
- [x] M2.5 单测 `test_pdf_parser.py` + `test_cleaner.py`（正常/损坏/加密/无文本层/超长/隐形字符）
- [ ] M2.6 提交 `feat(analyzer): pdf parsing and resume cleaning` —— 门禁：PDF 未复制进 `apps/`

## M3 · Python：归一化·匹配·推荐（0:38–0:58）

- [x] M3.1 `app/data/skills.yaml`（≥60 条；语言 / 框架 / DB / 中间件 / 前端 / 测试 / DevOps / 工具）—— 83 条
- [x] M3.2 `service/normalizer.py`：① 查别名 ② 规范化后再查 ③ 编辑距离 ≥0.90 且长度 ≥4 兜底 ④ 否则 `unknown` 不阻断；**`Java ≠ JavaScript` 必须不误判**
- [x] M3.3 `service/matcher.py`：**唯一**打分公式 `score = Σ命中权重 / Σ岗位权重 × 100`；交集 →matched（双向证据 + offset），差集 →missing（带 suggestion）；边界：岗位 0 技能 / 简历 0 技能 / 全命中 / 同技能取最高权重
- [x] M3.4 `service/recommender.py`：全部候选各跑 matcher → score 降序、同分 jobId 升序 → Top-3；`reason` 用规则模板，**不调 LLM**
- [x] M3.5 **seed 一致性校验**：`db/seed.sql` 中每个 `job_requirement.skill` 必须命中 `skills.yaml` 的 canonical（未登录词先补词典再落库）；校验脚本进 CI
      → 落成 `tests/unit/test_seed_consistency.py`（pytest 即 CI 入口，M8.4 接进 workflow）
- [x] M3.6 单测 `test_{normalizer,matcher,recommender}.py`（AC16 / AC17 / AC18 + 边界四例）+ 真实样本门禁 `tests/integration/test_m3_real_samples.py`
- [ ] M3.7 提交 `feat(analyzer): taxonomy, weighted matching & top-n`

## M4 · Python：流式与 LLM（0:58–1:12）

- [x] M4.1 `schema/response/sse_event.py`：6 类事件 + 7 个 stage 枚举
- [x] M4.2 `util/sse.py`：`(event,data)` → `event: X\ndata: {...}\n\n`；`ping()`（data 为单行 JSON）
      → 另加 `parse_frames()`：**服务端与测试/前端共用同一套分帧规则**，避免两边各写一遍对不上
- [x] M4.3 `service/analysis_stream_service.py`（async generator）：按序 yield；`try/except/finally` 包裹 —— 致命失败 `yield error → yield done`，LLM 失败 `status=fail` 但继续
- [x] M4.4 `llm/{client.py,prompts.py}`：Prompt-2；流式 yield thinking；累积后 JSON 解析，失败 / 超时 → `rules.py` + `degraded=true`
- [x] M4.5 `service/rules.py`：5 类 issues 规则兜底（枚举与 part1 §2.4 一致）
- [x] M4.6 `api/v1/stream.py`：`StreamingResponse` + 头 `Cache-Control: no-cache`、`X-Accel-Buffering: no`；`curl -N` 逐行输出
- [x] M4.7 单测 `test_stream.py` + `test_rules_llm.py`（meta 首 / done 尾 / stage 齐全 / error 与 result 互斥）
      → 新增 **43** 个用例，全量 **260 passed**
- [ ] M4.8 提交 `feat(analyzer): sse streaming analysis with llm fallback`

### M4 实施中定位并修掉的三个真问题

| # | 问题 | 为什么是问题 | 修法 |
|---|---|---|---|
| 1 | `SseEvent.to_frame()` 只认 `to_dict()`，而 `result` 的 data 是 pydantic 模型 | `result` 事件抛 `AttributeError` 被兜底成 `error → done`，外面只看得到「没有 result」 | 加 `_payload_of()`：dataclass 走 `to_dict()`，pydantic 走 `model_dump(mode="json")`（`mode="json"` 是必须的，否则 Enum 输出 repr） |
| 2 | LLM 阶段抛异常时**整条流失败** | 违反 spec §2.4 硬性规则 3「只有 `parsed` 失败才发 `error`」—— 一个 LLM 抖动会让用户连 `recommendations` 都拿不到 | 编排层给 LLM 循环单独包 try/except → 降级。客户端本该自己转 `LlmFinished(issues=None)`，但那是约定不是保证，这里补最后一道防线 |
| 3 | `TIMELINE_GAP` 把「项目区间 ⊂ 任职区间」判成重叠 | 真实样本一跑就现形：项目本来就发生在任职期间，那是最正常的简历结构 | 倒挂全文查，**重叠只在 `experience` 章节内查** |

另有两处协议不一致（文本入口少发 `parsed.start`、跳过 matched 时只发一帧）也一并统一成
start+ok 一对 —— 消费方不该为「文本入口」「没选岗位」写特殊分支。

### M4 端到端跑出来的第四个 bug（单测抓不到，`curl -N` 才现形）

**`resume.sections` 的值是逐字符列表**：`_resume_view()` 用了 `list(sections[key])`，
而 `cleaner.split_sections()` 返回的是 `dict[str, str]`（章节名 → 整段文本），
于是 `"2019.09-2023.06 某大学"` 被拆成 `["2","0","1","9",...]`。
**Pydantic 的 `list[str]` 不报错**，它老老实实接受这个字符列表 ——
所以单测里 `assert isinstance(lines, list)` 一直是过的。

修法：`_section_lines()` 按 `\n` 拆分并去空行。回归测试
`test_sections_are_lines_not_characters` 断言「每行至少 2 个字符」。

> **教训**：契约形状的断言不能只验类型，要验**值的形态**。
> 这次的直接触发因素是真实 PDF 的章节文本，构造数据里反而碰不到。

## M5 · Java：承接·候选集·透传（1:12–1:32）

> ⚠️ 1:32 仍不通 → 按 ADR-101 临时允许 BFF 直连 Python，记 `DELIVERY.md` 偏差。

- [ ] M5.1 entity/{Job,JobCategory,Skill,Requirement}Entity.java（4 张读表；`job_tag` / `skill_alias` 本期 Java 不读 → 不建 entity）；`ddl-auto=validate` 通过
- [ ] M5.2 `repository/{Job,Requirement}Repository.java`（**只读方法**）
- [ ] M5.3 `repository/impl/` 双实现（JPA + InMemory）+ `@ConditionalOnProperty`（沿用 part1 ADR-007）
- [ ] M5.4 `dto/{JobCandidate,Requirement}Dto.java`（字段名与 plan §3 逐字一致）
- [ ] M5.5 `service/AnalysisOrchestrationService.java`：**唯一**给 Python 数据的地方 —— 装配候选集（全部岗位 + requirements）；带 `jobId` 时附 `jdText`；`grep -rn "pdf" src/main/java` 只在校验 / 转发两处
- [ ] M5.6 `client/AnalyzerStreamClient.java` + `controller/analysis/AnalysisController.java`：`SseEmitter(timeout=130_000)` + `RestClient` 流式读；**收到 Python 首事件后才转发**；独立 `TaskExecutor`
- [ ] M5.7 JUnit：`RequirementRepositoryTest`（mysql + local）+ `uk_job_skill` 唯一约束测试
- [ ] M5.8 提交 `feat(job-service): file relay, candidate assembly & sse passthrough`

## M6 · BFF：校验与透传（1:32–1:52）

- [ ] M6.1 加 `@koa/multer`（memoryStorage）+ `.env.example` 增 `MAX_UPLOAD_MB=10`
- [ ] M6.2 `middleware/upload.middleware.ts`：**唯一**校验点 —— ≤10MB(413) / MIME(415) / magic number ≠ `%PDF-`(415)
- [ ] M6.3 `util/sse.ts`：帧写 + **按 `\n\n` 分帧 + 行缓冲**解析（单测用分包流）
- [ ] M6.4 `service/analysis.service.ts` + `controller/analysis.controller.ts`：前置校验 → 建头 → 发 meta → 转发 Java → 逐块透传；断连捕获 `res.on('close')` → 取消上游 → `STREAM_ABORTED`；`EPIPE` 不抛全局
- [ ] M6.5 `errors/mapUpstream.ts`：Java 413 / 415 原样透传；Python `error` 事件**原样透传不二次包装**
- [ ] M6.6 e2e `stream.e2e.test.ts`（事件序列断言）
- [ ] M6.7 提交 `feat(bff): multipart validation and sse proxy`

## M7 · 前端：analyzer 页（1:52–2:20）

> 规避"纯 AI UI"：主题定制 / 组合式布局 / 改造留痕（ADR-107）。

- [ ] M7.1 接入 `element-plus` + `vue-router` + `echarts`；`styles/element-theme.scss` 覆盖 `--el-color-primary`（**不用默认蓝**）
- [ ] M7.2 `router/index.ts`：`/` → `/analyzer`；`/connectivity` 承载 part1 连通页（**功能不丢**）
- [ ] M7.3 `composables/useAnalysisStream.ts`：`fetch` + `ReadableStream`，按 `\n\n` 分帧；暴露 `stages/thinking/result/error/isStreaming`；单测覆盖跨 chunk 截断
- [ ] M7.4 `UploadPanel.vue`：`el-upload` 拖拽 + 本地预校验（不过则**不发请求**）
- [ ] M7.5 `StageProgress.vue`（el-steps 7 阶段）+ `ThinkingConsole.vue`（打字机追加 delta）
- [ ] M7.6 `{ResultPanel,ScoreRing,MatchList,IssueList}.vue`：ECharts 分数环；`el-tag` + `el-collapse` 展示证据；**`match` 为 null 时不报错**
- [ ] M7.7 `RecommendList.vue`：Top-N 卡片（分数 + reason + 命中 / 缺口摘要）
- [ ] M7.8 `index.vue` 组装（左上传 / 右流式 + 结果 两栏）
- [ ] M7.9 `AI_LOG.md` 记录改造留痕（≥3 条：改了哪个组件什么属性、为什么）
- [ ] M7.10 提交 `feat(web): analyzer page with upload, stream console & recommendations`

## M8 · 联调·降级·交付（2:20–2:35）

- [ ] M8.1 `smoke-stream.sh`：断言 meta 首 / done 尾 / stage 齐全 / recommendations 非空
- [ ] M8.2 `gen-seed.sh` 复跑：`skills.yaml` + `jobs/*.json` → `db/seed.sql`；MySQL / H2 各导入一次，行数一致（AC23）
- [ ] M8.3 **降级演练（逐条实测留档）**：断 LLM→degraded(AC15) ｜ 改名 docx→415(AC12) ｜ 扫描件 →PDF_NO_TEXT_LAYER(AC14) ｜ 停 MySQL→ 推荐正常 ｜ 20 次连断 → 健康(AC19) ｜ 无 `text/event-stream`→ 同步 JSON(AC21)
- [ ] M8.4 CI 增量：analyzer(`test_pdf_parser`/`test_matcher`/`test_stream`) · bff(`stream.e2e`) · job-service(`RequirementRepositoryTest`) · web(`useAnalysisStream`)
- [ ] M8.5 `DELIVERY.md` 增补：流式协议 · PDF 已知缺口(排版/扫描件/无 OCR) · 超长行为不一致取舍(ADR-109) · 线性链取舍(C3) · 六条降级验证方法
- [ ] M8.6 `AI_LOG.md` 增补 part2（密钥脱敏、正文不入档）
- [ ] M8.7 最终提交 `docs(part2): streaming delivery notes & ci`

---

## 附录 A · 需求 → 任务追溯

| 需求                     | 任务                 | 验收                  |
| ------------------------ | -------------------- | --------------------- |
| G5 PDF 真实进入系统      | M2.\*                | AC11 / AC14           |
| G6 等待过程可见          | M4.2–M4.6, M7.5      | AC20                  |
| G7 推荐一组岗位          | M3.4, M7.7           | AC17                  |
| G8 推荐可解释            | M3.3–M3.4            | AC18                  |
| 文件校验（大小 / 类型）  | M6.2                 | AC12 / AC13           |
| 技能词典 taxonomy        | M3.1–M3.2, M8.2      | part1 AC6             |
| 岗位技能结构化           | M3.5, M5.1–M5.4      | seed 校验脚本         |
| 岗位分类可扩展（D1）     | M1.5.1, M1.5.5, M5.1 | AC22                  |
| 离线幂等 + 软删（D2/D3） | M1.5.2–M1.5.4        | AC23                  |
| 流式协议完整性           | M4.1–M4.6, M6.3–M6.6 | AC11 / AC15 / AC19    |
| 推荐确定性               | M3.4                 | AC16                  |
| 流式降级为同步           | M6.5, M8.3           | AC21                  |
| 前端页面与体验           | M7.\*                | AC20                  |
| 规避"纯 AI UI"           | M7.1, M7.9           | AI_LOG 改造留痕 ≥3 条 |

## 附录 B · DoD（增补 part1 的 6 条）

7. 改流式协议（事件 / stage / 顺序）→ **同步 spec §2.4 + 三份 OpenAPI + 前端解析器三处**
8. 改 `skills.yaml` → **重新生成 `seed.sql` 的 `skill` 表**，否则归一化率静默下降
9. 改 PDF 解析 → **必须用 `脱敏资料/` 真实样本验证**，不得只用构造的假 PDF
10. 改岗位分类 / 标签 → **只插字典表行**，禁止改 Java `enum`；改 `db/seed/jobs/*.json` → **必须复跑 `gen-seed.sh`**，否则库与源不一致

## 附录 C · 提交审核增补（在 part1 附录 C.2 基础上）

- [ ] 未落盘上传文件：`git status` 无新增 `*.pdf`
- [ ] 未把简历正文写进日志 / `AI_LOG`
- [ ] Java 无 PDF 解析 API：`grep -rn "PDFTextStripper\|PDDocument\|pdfbox" workspace/apps/job-service/` 为空
- [ ] BFF 无直连 Python：`grep -rn "analyzer\|8000" workspace/apps/bff/src/client/` 无命中
- [ ] 契约纯增量：三份 yaml `git diff` 无 `-` 行
- [ ] SSE 顺序未破：`meta` 首 / `done` 尾 / `error` 与 `result` 互斥
- [ ] 岗位分类无硬编码：`grep -rn "enum JobCategory\|class JobCategory" workspace/apps/job-service/` 只应有 entity，无 enum 常量
- [ ] `db/seed.sql` 未被手改：改动只能来自复跑 `gen-seed.sh`
- [ ] 岗位无物理删除：`grep -rn "delete.*from job\b" workspace/apps/job-service/` 为空

## 附录 D · 一页纸速查

```
契约先行 → 先让 Python 单独能流 → 逐层往外套（Java → BFF → 前端）
每层都用 curl -N 单独验证，过了再上一层
流式穿三层最脆，40 分钟不通就回退 BFF 直连 Python（记偏差）
不落盘 · Java 不解析 PDF · Python 不连库 · LLM 不打分
提交门禁不变：完成改动 → 人工审核 diff → 提交
```
