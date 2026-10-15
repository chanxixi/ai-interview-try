# spec.md — CareerLens part3：LLM 深度匹配分析（优化点 · 缺失能力 · 提升方向）

> SDD 产物 **1/3** · v0.2 · 状态：**待评审**
> **增量规格**：只写相对 `part1/spec.md` v0.3 与 `part2/spec.md` v0.3 的**差异**，未提及的一律沿用。
> 冻结顺序：本文件 §2 → `plan.md` → `tasks.md`。
> 编号：part3 任务用 **`N`** 前缀（part1 = `T`，part2 = `M`）；验收从 **AC24** 起；契约变更从 **C5** 起；ADR 从 **201** 起。

---

## 1. 目标与范围

**一句话**：上传一份简历并选定目标岗位后，系统在 part2 既有的「**集合级**匹配」之上，把简历里的**能力证据**与招聘方的**逐条要求**对照，由 LLM 讲出**优化点 / 缺失能力 / 提升方向**，并由**代码**（不是模型）算出**六维能力画像**与**综合分**。

**一句话用户故事**：给我一份简历，告诉我它**强在哪、弱在哪**，对着我要投的那个岗位**具体缺什么、该往哪个方向补**。

### 1.1 客户与真痛点

- 用户说的：**改简历太费时间**。
- 真问题：**判断不可复用** —— 「该补什么」这个结论今天靠人肉读 JD + 读简历，换个人、换份简历就重来一次；没有结构化、可复现、可追溯的判定。
- 推论（本 part 的验收取向）：产出物必须是**结构化判定 + 出处**，而不是一段读完就忘的建议文本。

### 1.2 产品边界

- **不替代人**：系统给「该看哪几处、为什么」，最终改不改、怎么改**留给人**。
- 把人工约 40 分钟的判断压到 10 分钟以内。
- 不做：简历自动改写、投递代发、薪资谈判建议、公司内幕信息。

### 1.3 范围

**In Scope（part3 新增）**

- **逐条判定**：每条岗位要求给 `satisfied` / `partial` / `missing` + 理由 + 双向证据
- **优化点**清单：改哪里、怎么改、依据哪条要求
- **缺失能力**清单：缺什么、优先级、补齐的**最小动作**
- **提升方向**：≤5 个方向（为什么是它、第一步做什么）
- **六维能力画像**：每维 0–100 + `rubricRef` + 简历原文证据
- **综合分**：由**代码**加权求和（权重来自岗位侧）
- SSE 新增阶段 `reviewed`
- `Top-N` 上限放宽到 10（默认仍 3）

**Out of Scope**

- 简历自动重写 / 生成新简历
- 岗位爬虫、薪资数据、公司信息
- 具体课程 / 视频链接（只给方向与关键词）
- **分析历史持久化**（沿用 part2 §4.8 的 `analysis_record` 扩展位，本期不建表）
- 多份简历对比、批量分析

**Non-Goals**：不承诺 LLM 判定 100% 正确；不承诺维度分与人评一致；`growthDirections` 是启发式排序，不是职业规划结论。

---

## 2. 稳定面（冻结）

### 2.1 契约级变更（C5 起，均须走《变更记录》）

| # | part2 原状 | part3 决定 | 理由 |
|---|---|---|---|
| **C5** | SSE **7 阶段** | **+1 阶段 `reviewed`**（`llm` 之后、`result` 之前） | 「逐条判定」是独立的一段耗时，塞进 `llm` 会让进度条**说谎** |
| **C6** | 响应 4 块 + `recommendations` | **新增 4 个字段块**（§2.3） | 纯增量；已有字段名 / 层级 / 类型**不动** |
| **C7** | `Top-N = 3`（常量 `RECOMMEND_TOP_N`） | **Top-N 可配**（默认 3，上限 10） | 需要「十个岗位」；默认值不动，AC17 不被破坏 |

> **纯增量约束（沿用 part2 附录 C）**：三份 OpenAPI `git diff` **不得出现 `-` 行**。

### 2.2 请求契约（增量）

已有字段一律不动。新增两个字段，**均可缺省**：

```
analysisDepth : "standard" | "deep"   默认 standard
topN          : int, 1..10            默认 3（缺省即沿用常量）
```

- `standard`（默认）：只出既有 `match` / `recommendations` —— **与 part2 完全一致**。
- `deep`：额外产出 §2.3 的四个块。
- 缺省 = `standard` ⇒ **老前端行为一字不变**。这是本 part 的**可回退保证**（ADR-202）。

### 2.3 响应契约（增量）

```jsonc
{
  // ... 既有 resume / issues / match / recommendations / meta 全部不动 ...

  "verdicts": [                    // ★ 逐条判定（standard 时为空数组）
    { "skill": "Redis", "importance": "required",
      "verdict": "missing",        // ★ satisfied | partial | missing
      "reason": "简历提到缓存优化，但未给出 Redis 使用证据",
      "jdEvidence": "熟悉 Redis 缓存与分布式锁",
      "resumeEvidence": "优化了订单查询缓存" }
  ],

  "improvements": [                // ★ 优化点（怎么改简历）
    { "area": "项目描述",
      "action": "把「优化了缓存」补成「用 Redis 把 P99 从 800ms 降到 120ms」",
      "evidence": "优化了订单查询缓存",
      "targets": ["Redis"] }
  ],

  "growthDirections": [            // ★ 提升方向（补什么能力）
    { "direction": "分布式缓存",
      "why": "目标岗位 required 项，简历零证据",
      "firstStep": "在一个真实项目里把 Redis 用在读多写少的查询路径上",
      "priority": 1 }
  ],

  "abilityProfile": {              // ★ 六维画像（分数由代码算）
    "dimensions": [
      { "name": "技术深度", "score": 72,
        "rubricRef": "tech.depth.L3", "evidence": "用 Redis 把 P99 降到 120ms" }
    ],
    "overall": 68                  // ★ 加权求和；权重来自岗位侧
  },

  "meta": { "analysisDepth": "deep", "verdictCount": 7, "directionCount": 3 }
}
```

- 每个分数（含 `overall`）**必须**同时挂 `rubricRef` 与 `evidence` —— **无出处的分数不允许出现**（AC27）。
- `overall` **由代码算**：`Σ(维度分 × 维度权重) / Σ(权重)`，四舍五入口径与 `matcher.score_of` **一致**（`floor(x + 0.5)`，不用 Python 的银行家舍入）。
- LLM **不产出** `overall`，也**不排序** `growthDirections`（排序由 `priority` 规则定）。

### 2.4 SSE 事件协议（增量）

- 新增阶段 `reviewed`，位置：`llm` 之后、`result` 之前。
- **事件类型不新增**（仍是 6 类：meta / stage / thinking / result / error / done）。
- **`thinking` 只在文案阶段（Prompt-4）发**。判定阶段（Prompt-3）的输出是 JSON，逐字推给用户只会刷屏、还会把结构暴露在 UI 上 —— 该阶段只发 `stage.detail`（如 `{requirementCount: 7}`）。
- 阶段序列变为 9 个：

```
meta → stage(accepted) → stage(parsed) → stage(cleaned) → stage(normalized)
     → stage(matched) → stage(recommended) → stage(llm) → stage(reviewed)
     → [thinking × n] → result → done
```

- `reviewed` 阶段失败**不终止流**（`stage.status = fail`，沿用 part2 §2.4 硬性规则 3），四个新块退化为**规则兜底**（§2.6）。
- `standard` 模式下 `reviewed` 阶段**不发**（否则进度条多一格却没内容）。

### 2.5 两个产品决策（**定死**，后面所有节都受它约束）

**① 六个维度写死**

`技术深度 · 工程能力 · 业务理解 · 项目影响力 · 协作沟通 · 成长性`

- 每维 **0–100 整数**。
- 每个维度分**必须**同时挂 `rubricRef`（rubric 出处）与 `evidence`（**简历原文片段，逐字复制**）。
- 维度定义与分级标准放 `analyzer/app/data/rubric.yaml`（**真源在仓库**，与 `skills.yaml` 同思路）：改分级 = 改数据，**不改代码**。
- 维度**集合**属冻结面：增删维度 = 契约级变更（C 级，走 §2.1）。
- **每个维度必须同时写清三样**（只写一句抽象定义不算完成）：① **定义**（这一维在问什么）② **可读信号**（简历里出现哪些词/形态才算证据，给 LLM 当锚点）③ **代码兜底判据**（断 LLM 时用什么纯规则判档）。

| 维度 | 问什么 | 可读信号（锚点） | 兜底判据（纯代码） |
|---|---|---|---|
| **技术深度** | 对所用技术是「用过」还是「懂原理」 | strong：JVM 调优 / 索引优化 / 并发 / 锁 / 内存 / 选型权衡 / 故障定位<br>weak：熟悉、了解、使用过 | strong ≥2 → L3；=1 → L2；只有名词 → L1；无 → **L0** |
| **工程能力** | 有没有把工程做「能维护」的意识 | strong：CI/CD / 单测 / 集成测试 / 监控告警 / 日志 / 部署 / CR / 文档 | ≥2 → L3；1 → L2；只有工具名 → L1；无 → L0 |
| **业务理解** | 能不能说清「为谁解决什么、带来什么指标」 | strong：业务指标（GMV / 转化 / 留存 / DAU / P99）、业务域名词、上下游 | 指标 + 业务域 → L3；仅业务名词 → L2；纯技术描述 → L1；无 → L0 |
| **项目影响力** | 做的事有多大、有没有结果 | strong：量化结果（% / ms / QPS / 人数）、规模（用户数 / 数据量）、角色（主导 / owner） | 量化 + 规模 → L3；有量化 → L2；只有动作 → L1；无 → L0 |
| **协作沟通** | 有没有**可查的**「与人协作并交付」的证据 | strong：团队规模（带 N 人）、主导 / 推动 / 跨部门 / 对接 / 评审、开源贡献 | 角色词 + 团队规模 → L3；有角色词 → L2；仅「协作/团队」→ L1；无 → **L0** |
| **成长性** | 时间线上有没有「越做越难」的痕迹 | strong：职责递进、技术栈演进、职级上升、时间线连续 | 递进 + 演进 → L3；时间线连续 → L2；有经历无递进 → L1；无 → L0 |

- **其中两维可纯代码算**：`项目影响力`（数字 / 规模正则，与 `rules.py` 的 `_check_no_quantify` 同源）与 `成长性`（时间线递进，与 `_check_timeline_gap` 同源）。
  → 直接好处：**断 LLM 时这两维仍然可用**，不会六维全 `L0`，降级质量高一档。

**② 综合分由代码算，不由模型算**

- 模型只出**逐条判定**（`verdicts`）与**各维度的档位 `level`**，**不出任何分数**；文案也由模型出。
- **档位 → 分数**与**加权求和**都由代码完成（`service/ability_profile.py`，全项目**唯一**的维度分公式实现 —— 与 `matcher.py` 是唯一打分公式同源）。
- 三条硬要求：**可复现**（同输入两次结果一致）· **可审计**（每个分数有出处）· **可调权**（权重是**数据**不是代码）。

### 2.5.1 三个产物的分工（**不许重叠**）

| 产物 | 粒度 | 回答 | 谁产出 |
|---|---|---|---|
| `issues` | **逐句** | 这一句哪里要改 | LLM（Prompt-2）→ `rules.py` 兜底 |
| `verdicts` | **逐条要求** | 这个岗位这条要求满足了没 | LLM（Prompt-3）→ 集合事实兜底 |
| `abilityProfile` | **整体** | 这个人什么水平、往哪走 | LLM（Prompt-3）判档 → **代码算分** |

⚠️ **最需要警惕的一处重叠**：`abilityProfile.项目影响力` 与 `issue.NO_QUANTIFY` 讲的是**同一件事的两个粒度**，分工必须写死：

- `NO_QUANTIFY` = **定位到句**（「'负责订单系统'这行没数字」）→ **可执行**，喂给 `improvements`
- `项目影响力` = **整体水位**（「这个人影响力 L1」）→ **可比较**，喂给雷达图

**同源不同粒度：禁止合并，也禁止各算一套判据**（合并会让用户读两遍同一句话；各算一套就会漂移）。

### 2.5.2 两条硬性克制

1. **弱证据维度允许且必须留 `L0`**：`协作沟通` / `成长性` 在简历里常常**真的没有证据**。必须接受它们经常是 `L0`，**禁止为了让雷达图好看而编分**（与 §2.6「不编分」同源）。前端也必须把 `L0` 显示为「无依据」，**不得画成 0 分**。
2. **权重不得平均**：校招档要**压 `项目影响力`**（校招生本就没多少影响力可谈，权重高会让所有人分数难看）、抬 `成长性`；社招 / 高级档反向。三档权重都放 `rubric.yaml`，每档之和必须为 1.0。

### 2.6 降级（沿用 ADR-004 的形状）

| 触发 | 行为 |
|---|---|
| `llm_enabled == false` | 四块为空数组 / `abilityProfile = null`，`meta.degraded = true` |
| LLM 超时 / 非 200 | 同上 |
| LLM 返回非法 JSON | 同上；且**逐条判定退化为集合级事实**（`match.matched` → `satisfied`、`match.missing` → `missing`，`reason` 用规则模板） |
| 某维度算不出来 | 该维度 `score = null` + `evidence = ""`，**不编分**；`overall` 按**已有维度**重新归一 |

> **「不编分」是硬要求**：算不出来就留空、`overall` 少算一维，比编一个看起来合理的分数**更诚实**。
> 这条与 `rules.py` 的「宁可漏不可编」是同一个取向。

### 2.7 语言分工表（每行必须回答「为什么是它」）

| 层 | part3 新增什么 | 为什么是它 |
|---|---|---|
| **Python analyzer** | 逐条判定编排 · 优化点/方向解析 · 六维分**加权求和** · rubric 加载与校验 | 已有 `llm/`、`matcher`、`normalizer`；**「算」归 Python**（ADR-102 同源） |
| **Java job-service** | 装配岗位侧的**维度权重**与级别信息 | **岗位数据只有 Java 有**；Python 不连库（part1 §2.6） |
| **BFF（Node/TS）** | 只**透传**新字段 | **禁业务规则**（ADR-005） |
| **Vue** | 新面板（雷达图 + 判定列表 + 出处展开） | **只呈现不判断**（part1 §2.7） |
| **LLM** | 逐条语义判定 + 优化点/方向**文案** | 唯一能「读懂自然语言」的地方；也是它**唯一**的运行期判断职责 |

> **与参考施工单的差异（有意）**：参考里写「综合分由 **Java** 规则引擎算」。本项目**算分在 Python**
> （`matcher.py` 是唯一公式，Java 只装配数据）。照抄会出现**第二套公式** —— 正是 part2 反复防的
> 那个 bug（`match.score = 82` 而推荐里同一岗位 79，用户第一个问题就是「这俩数怎么不一样」）。
> 因此 part3 的加权求和**落在 `ability_profile.py`**。

### 2.8 稳定面清单（合同锁死）

- **HTTP**：请求 2 个新字段（§2.2）；响应 4 个新块（§2.3）
- **SSE**：**+1 阶段**，事件类型不变（§2.4）
- **常量**（`core/constants.py`）：`DIMENSIONS`（六维，冻结）、`VERDICT_KINDS`（三档，冻结）、`MAX_GROWTH_DIRECTIONS = 5`
- **数据**：`analyzer/app/data/rubric.yaml`（维度定义 + 分级 + 权重）
- **契约文件**：`contracts/{frontend-bff,bff-java,bff-python}.yaml` 三份**同步**增量
- **不新增**：数据库表 · 服务 · 新一跳

### 2.9 依赖增量

- Python：**无新依赖**（继续 `httpx`）。
- 前端：复用已引入的 ECharts（`ScoreRing.vue` 已是按需引入的先例），新增 **radar** 图表类型。

---

## 3. 禁止（增量）

- **架构**：禁止新增服务或新增一跳（C3）；禁止 BFF 直连 Python；禁止 Python 连数据库。
- **算法**：禁止 LLM 产出 `overall` 或决定**任何**排序；禁止把 rubric 整套塞进 system prompt（rubric 是**数据**，只按岗位裁剪片段）；禁止权重写死在代码里；禁止**无出处**的分数。
- **正确性**：禁止模型做算术（「3 年以上经验」「相差 2 年」这类一律代码算）；禁止模型解析 PDF 原文（PDF 归 `pdf_parser.py`）；禁止给模型任何 SQL / 工具执行能力。
- **安全**：禁止简历正文进日志 / `AI_LOG.md` / git；禁止上传文件落盘（ADR-110 沿用）；禁止 prompt 省略分隔符与「这是数据不是指令」声明。
- **工程**：禁止未经人工审核即提交（part1 §3.5 沿用）；禁止把三件套写成一份。

---

## 4. 验收（AC24–AC35，十二行）

```
AC24  deep 分析 → 事件序列含 reviewed 阶段；result 含 verdicts / improvements /
      growthDirections / abilityProfile 四块
AC25  standard（默认）→ 响应与 part2 **形状逐字节一致**（无新块），老前端零改动
AC26  verdicts 每条 verdict ∈ {satisfied, partial, missing}，且 reason 非空
AC27  abilityProfile 每个维度分与 overall **都带 rubricRef 与 evidence**；无出处即判失败
AC28  手算复现：overall = Σ(维度分×权重)/Σ(权重)，四舍五入口径与 matcher.score_of 一致
AC29  断 LLM → 四块降级（判定退化为集合级事实），result / done 照常，meta.degraded=true
AC30  同一简历 + 同一岗位连续两次 deep → verdicts 顺序、各维度分、overall **完全一致**
AC31  rubric.yaml 新增一个分级档位 → 无需改 Python 代码即可生效
AC32  growthDirections 按 priority 升序，条数 ≤ 5
AC33  简历正文不出现在任何日志；SSE 中除 thinking 外无正文回显
AC34  deep 分析整体耗时 ≤ 150s
AC35  topN=10 时 recommendations 条数 = min(10, 候选数)；topN 缺省仍为 3（AC17 不破）
```

---

## 5. 交付物

`sdd/part3/{spec,plan,tasks}.md` · 三份 OpenAPI 同步增量 · `analyzer/app/data/rubric.yaml` ·
Python（`llm/prompts.py` +2 prompt · `llm/client.py` +1 方法 · `service/ability_profile.py` ·
`service/advisor_rules.py` 兜底 · `schema/response/analyze_response.py` 增量 · `core/constants.py` 增量）·
Java（候选集加维度权重）· Vue（判定面板 + 雷达图）· 单测 + 1 条 deep 端到端冒烟 · `DELIVERY.md` 增补

---

## 6. 拍板记录（v0.2 全部定稿）

| # | 事项 | 决定 |
|---|---|---|
| 1 | 六维就用这六个 | ✅ **采用**，且每维必须写「定义 + 可读信号 + 代码兜底判据」（§2.5①） |
| 2 | 逐条判定几档 | ✅ **三档**（satisfied / partial / missing） |
| 3 | 新增块字段名 | ✅ `verdicts` / `improvements` / `growthDirections` / `abilityProfile` |
| 4 | 新阶段名 | ✅ `reviewed` |
| 5 | Top-N 上限 | ✅ **10**（默认仍 3） |
| 6 | 维度权重来源 | ✅ `rubric.yaml`，按岗位 level 分档，每档和 = 1.0 |
| 7 | 是否落分析历史 | ✅ **本期不落**（用 part2 §4.8 的 `analysis_record` 扩展位） |
| 8 | deep 用几个 prompt | ✅ **2 个，但按新的职责划分**：**Prompt-3 = 判定 + 六维档（同一次调用）**；**Prompt-4 = 文案**。理由见 `plan.md` §7.0 与 ADR-205 |

---

## 7. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-10-15 | 初稿：依据 part2 已交付的 `matcher` / `recommender` / `llm` / SSE 做增量设计；确立「六维写死 + 综合分代码算」两个产品决策 |
| v0.2 | 2026-10-15 | **六维定稿**：§2.5① 补「定义 + 可读信号 + 代码兜底判据」六维表，标明 `项目影响力` / `成长性` 两维可纯代码算；新增 **§2.5.1 三个产物分工**（含 `NO_QUANTIFY` 与 `项目影响力` 的同源不同粒度说明）与 **§2.5.2 两条硬性克制**（L0 不编分 / 权重不平均）；§2.4 明确 **`thinking` 只在文案阶段发**；§6 由「待拍板」改为「拍板记录」，8 项全部定稿（第 8 项改为 **Prompt-3 出判定+六维档 / Prompt-4 出文案**） |

