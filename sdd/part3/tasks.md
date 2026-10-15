# tasks.md — CareerLens part3：任务拆解

> SDD 产物 **3/3** · v0.2 · 依赖 `sdd/part3/{spec,plan}.md` v0.2
> 只列 part3 **增量任务**；**提交门禁、DoD、审核清单沿用 `sdd/part1/tasks.md` 与 `sdd/part2/tasks.md`**。
> 任务前缀 **`N`**（part1 = `T`，part2 = `M`）；时间基准 155 分钟（plan §11），按实际等比缩放。

> ### ⛔ 提交门禁（逐字沿用 part1 / part2）
>
> AI / 脚本**不得自动提交**。铁律：完成改动 → **人工通读 diff** → 人工回复「通过」→ 才 `git commit`。
> 禁 `--no-verify`、禁批量补提交；审核不过 → 先改代码不提交。

---

## 进度总览

| 阶段 | 时间 | 里程碑 |
|---|---|---|
| N0 契约增量冻结 ★ | 0:00–0:15 | **契约冻结（C5–C7）** |
| N1 逐条判定 | 0:15–0:45 | 判定可复现（含兜底） |
| N2 六维分（代码算） | 0:45–1:05 | **手算对照通过（AC28）** |
| N3 优化点 · 提升方向 | 1:05–1:35 | 四块齐全 |
| N4 新阶段接线 · 契约同步 | 1:35–1:55 | `curl -N` 事件序列完整 |
| N5 前端面板 | 1:55–2:20 | 浏览器可演示 |
| N6 降级演练 · 交付 | 2:20–2:35 | 交付完成 |

**关键路径** N0→N1→N2→N3→N4→N5 ｜ **可压缩** 维度档位细化、雷达动效、`growthDirections` 条数（5→3） ｜ **可降级** 两次 LLM 串行改一次（记偏差）；**最坏可整块关掉**（`analysisDepth` 默认 standard，回到 part2 行为）

---

## 任务表

> 「完成标准」必须是**可当堂验证的事实**，不许写「完成 xxx 开发」这类无法验证的话。

| 任务 | 内容 | 完成标准（可当堂验证） |
|---|---|---|
| **N0.1** | 三份 OpenAPI 增量：请求 `analysisDepth` / `topN`；响应四块；SSE `reviewed` 阶段 | 三份 yaml 的 `stages` 与 `SseStageName.enum` 都含 `reviewed` 且位置一致；`AnalysisResult` 含 4 新块且**未加进 `required`**（保 AC25）；所有 `$ref` 可解析；`git diff` 的 `-` 行**只允许出现在「枚举/列表追加」的 5 类行**上（`stages` / `enum` / stage 序列 / events 计数 / detail 说明），**不得有任何字段或语义被删除** |
| **N0.2** | `analyzer/app/data/rubric.yaml`：六维**定义 + 可读信号** + 每维 ≥3 档 + 权重（按 level 分档） | 六维齐；**每维 `signals` 非空**；每维档位数 ≥3；**三档（校招 / 社招 / 高级）各自**权重和 = 1.0（±1e-9） |
| **N0.3** | `core/constants.py`：`DIMENSIONS` / `VERDICT_KINDS` / `MAX_GROWTH_DIRECTIONS` | `test_rubric_consistency.py` 通过（六维与常量**逐字一致**，防两处漂移） |
| **N1.1** | Prompt-3（**判定 + 六维档**）+ 解析器（严进：`verdict` / `level` 不认识就丢该条 / 该维） | 同一简历两次调用 `verdicts` 与 `dimensions` 档位完全一致；非法 JSON → 返回 `None` 而非抛错 |
| **N1.2** | `service/advisor_rules.py`：判定兜底（`match.matched`→satisfied、`missing`→missing）+ **六维判档兜底**（消费 `rubric.yaml` 的 `signals`） | 断 LLM 时 `verdicts` 条数 **= `match` 条数** 且每条 `reason` 非空；**六维也全有档位**（其中 `项目影响力` / `成长性` 与 LLM 无关，必须独立可算） |
| **N1.3** | `llm/client.py` +`stream_review(...)`，沿用三层降级 | 未配置 / 连接失败 / 非法 JSON 三种情况都返回 `LlmFinished(...)` 而**不抛异常**（与现有 `stream_issues` 同断言） |
| **N2.1** | `service/ability_profile.py`：维度分归一 + **加权求和**（`floor(x+0.5)`） | 手算一个用例：`Σ(分×权重)/Σ(权重)` 与 `overall` **相等**（AC28） |
| **N2.2** | 维度算不出 → `score=null` 且 `overall` 按已有维度归一 | 构造「缺一维」用例：该维 `score=null`、`overall` 等于其余维归一结果；**没有编分** |
| **N2.3** | Java 候选集装配加「维度权重 / level」 | `RequirementRepositoryTest` 之外新增断言：DTO 的权重字段非空且和为 1 |
| **N3.1** | Prompt-4（优化点 + 提升方向）+ 解析器 | `growthDirections` 条数 ≤5、按 `priority` 升序；`improvements[].targets` 非空 |
| **N3.2** | `advisor_rules.py` 的优化点 / 方向兜底 | 断 LLM 时两块**非空**（规则模板），且不含课程链接 / 机构名 |
| **N3.3** | rubric 片段**裁剪**注入（只喂与岗位相关的维度片段） | 构造一个 5 技能岗位：注入的 rubric 片段行数 < 全量 rubric 行数 |
| **N4.1** | `analysis_stream_service.py` +`reviewed` 阶段；`thinking` 只在文案阶段发 | `curl -N` 事件序列出现 `stage(reviewed)` 且**仍在 `result` 之前**（AC24）；**判定阶段无 `thinking` 行**，文案阶段才有 `thinking` 行 |
| **N4.2** | `standard` 模式不发 `reviewed`、不返回四块 | `standard` 响应与 part2 **形状逐字节一致**（AC25，写成快照断言） |
| **N4.3** | 四块模型进 `schema/response/analyze_response.py`（增量） | 既有字段名 / 层级 / 类型**零改动**；`api/test_contract_shape.py` 的快照仍通过 |
| **N5.1** | `VerdictList.vue`：逐条判定 + 出处展开 | 页面每条判定可展开看到 `rubricRef` / `jdEvidence` / `resumeEvidence` |
| **N5.2** | `AbilityRadar.vue`：六维雷达（ECharts 按需引入 radar） | 页面出现六个维度；某维 `score=null` 时**不画成 0**，标注「无依据」 |
| **N5.3** | `AdvicePanel.vue`：优化点 + 提升方向 | 面板显式标注「AI 判定，仅供参考」；`standard` 响应下**不渲染且不报错** |
| **N6.1** | 降级演练（4 条，逐一留档） | 断 LLM / 非法 JSON / 维度算不出 / `standard` 模式 —— 四条**result 与 done 均照常**（AC29） |
| **N6.2** | `DELIVERY.md` 增补 | 记录：六维口径 · 权重来源与档位 · 两次 LLM 取舍 · 已知缺口（判定准确率不承诺、`overall` 与全维不可比） |
| **N6.3** | 提交 `feat(part3): evidence-level verdicts, ability profile & growth directions` | 人工审核 diff 通过后才执行（门禁） |

---

## 收口验收（六条，最后一节当堂做）

1. `analysisDepth=standard` 的响应与 part2 **形状逐字节一致**（AC25）
2. deep 分析四块齐全，且**每个分数都有 `rubricRef` + `evidence`**（AC24 / AC27）
3. 手算 `overall` 与接口返回值**相等**（AC28）
4. 断 LLM 后四块降级，但 `result` 与 `done` **照常**（AC29）
5. 同一简历 + 同一岗位连续两次 deep，`verdicts` 顺序与所有分数**完全一致**（AC30）
6. `rubric.yaml` 加一个分级档位 → **不改 Python 代码**即生效（AC31）

---

## 附录 A · 需求 → 任务追溯

| 需求 | 任务 | 验收 |
|---|---|---|
| 逐条能力 vs 要求对比 | N1.1–N1.3, N4.1 | AC24 / AC26 |
| 优化点（怎么改简历） | N3.1–N3.2, N5.3 | AC32 |
| 缺失能力 + 提升方向 | N1.2, N3.1–N3.2, N5.3 | AC32 |
| 六维能力画像 + 综合分 | N1.1, N2.1–N2.3, N5.2 | AC27 / AC28 |
| 可复现 / 可审计 | N0.2, N2.1, N3.3 | AC30 / AC31 |
| 断 LLM 不塌 | N1.2, N1.3, N6.1 | AC29 |
| 老前端不受影响 | N4.2, N5.3 | AC25 |
| 十个岗位 | N0.1 | AC35 |

## 附录 B · DoD（增补 part2 的 10 条）

11. 改**维度集合** → 同步 `spec.md §2.5` + 三份契约 + `rubric.yaml` **三处**
12. 改**权重** → **只改 `rubric.yaml`**，禁止改代码（有测试守）
13. 改 **prompt** → 必须复跑「断 LLM 降级」用例，确认兜底仍非空
14. 改 **`reviewed` 阶段位置** → 同步 spec §2.4 + 三份 yaml + 前端阶段标签三处
15. 改**可读信号（`signals`）** → 同步 `rubric.yaml` + `advisor_rules.py` 判据 **两处**（兜底判据消费 signals，只改一处会静默失效）

## 附录 C · 提交审核增补

- [ ] 抽查 3 条 `verdicts` 与全部维度：**无分数无出处**
- [ ] `ability_profile.py` 之外**无第二处** `overall` 计算：`grep -rn "overall" workspace/apps/analyzer/app/`
- [ ] 简历正文未进日志 / `AI_LOG.md`：`grep -rn "resume_text\|resumeText" workspace/apps/analyzer/app/` 中无 logging 调用
- [ ] `git diff workspace/contracts/` **无 `-` 行**
- [ ] `standard` 模式响应快照未变（AC25）
- [ ] `rubric.yaml` 未含任何课程链接 / 机构名

## 附录 D · 一页纸速查

```
契约先行 → 判定先跑通（含兜底）→ 分数交给代码算 → 文案最后加 → 逐层 curl -N 验证
LLM 只判档与写文案；分数与排序永远归代码
Prompt-3 出「判定 + 六维档」（不发 thinking）；Prompt-4 出文案（发 thinking）
每个分数都要有出处：rubricRef + 原文 evidence
算不出来就留空，不编分
analysisDepth=standard 是永远可用的安全出口
提交门禁不变：完成改动 → 人工审核 diff → 提交
```
