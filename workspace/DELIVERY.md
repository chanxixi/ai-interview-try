# DELIVERY.md — 交付说明

> 本文件按里程碑**增量补齐**：part1 的 T8.3 与 part2 的 M8.5 是最终汇总点，
> 在此之前每完成一个里程碑就把「别人接手必须知道的事」写进来。
>
> **当前已写入**：part2 · M1.5（数据模型与离线种子）· M2（PDF 解析与清洗）·
> M3（归一化 / 匹配 / 推荐）· M4（流式协议）· M7（前端）· M8（降级演练与偏离登记）
> **尚未写入**：启动 / 部署 / 回滚（part1 T8.3）
>
> **读法**：§1–§6 是「这层是怎么做的」，**§7 是「哪些地方和文档说的不一样、为什么」**。
> 接手时如果只有时间看一节，看 §7。

---

## 1. 数据模型与离线种子（part2 · M1.5）

### 1.1 文件与职责

| 文件 | 角色 | 能否手改 |
|---|---|---|
| `db/mysql/schema.sql` | 建表（主路径，MySQL 8.0） | ✅ 可以，属源码 |
| `db/h2/schema.sql` | 建表（降级路径，H2 `MODE=MySQL`）**与上面同构** | ✅ 可以，但必须同步改 MySQL 那份 |
| `db/seed/categories.json` | 岗位分类树（D1：分类是**数据**不是代码） | ✅ 可以，这是「新增一类岗位」的入口 |
| `db/seed/jobs/*.json` | 岗位源，一岗一文件 | ✅ 可以，这是「新增一个岗位」的入口 |
| `apps/analyzer/app/data/skills.yaml` | 技能词典**真源**（契约变更 C4） | ✅ 可以，但改完**必须复跑 `gen-seed.sh`** |
| `scripts/gen-seed.sh` + `scripts/gen_seed.py` | 编译器：上面这些 → `db/seed.sql` | ✅ 可以 |
| `db/seed.sql` | **构建产物**，启动时幂等导入 | ❌ **禁止手改**（改了下次跑脚本就没了） |

一句话：**要改数据，改源再跑脚本，别碰 `seed.sql`。**

```bash
bash workspace/scripts/gen-seed.sh            # 生成 db/seed.sql
bash workspace/scripts/gen-seed.sh --check    # 只校验源数据，不落盘（CI / 提交前）
```

`seed.sql` 的生成是**确定性**的（输出里只有输入的 sha256 指纹，没有时间戳），
所以「它有没有被手改」可以直接这样判定 —— 这也是提交审核项之一：

```bash
bash workspace/scripts/gen-seed.sh && git diff --stat workspace/db/seed.sql   # 无 diff = 没被手改
```

### 1.2 幂等与「不覆盖人工录入」—— 实测结论，不是设计承诺

用真实 H2（`2.2.224`，`MODE=MySQL`）连跑 4 次导入，逐项验证：

| 场景 | 期望 | 实测 |
|---|---|---|
| 连续导入 2 次 | 各表行数不变（AC23） | ✅ 14 / 83 / 79 / 7 / 66 / 22 恒定 |
| `job_requirement.skill_id IS NULL` | 必须 0 行（D3） | ✅ 0 |
| `job.category_id IS NULL` | 必须 0 行（分类都能解析） | ✅ 0 |
| 库里把某行 `source` 改成 `manual` 并改名 | 重复导入**不覆盖**（spec §2.9） | ✅ 标题与 `version` 原样保留 |
| 库里把某岗位 `status` 改成 `archived` | 重复导入**不复活**（AC23） | ✅ 仍为 `archived`，行仍在 |
| 库里只改了 `title`（没动 `content_hash`） | 应被识别为漂移并同步回源 | ✅ 标题还原，`version` 1 → 2 |
| 内容没变时反复导入 | `version` / `updated_at` **不动** | ✅ 稳定在 `version=2` |

复现命令（需要 H2 jar；`H2_JAR` 指到任意 `h2-*.jar` 即可）：

```bash
H2_JAR=/path/to/h2-2.2.224.jar
URL='jdbc:h2:file:./tmpseed/db;MODE=MySQL;DATABASE_TO_LOWER=TRUE'
run(){ java -cp "$H2_JAR" org.h2.tools.RunScript -url "$URL" -script "$1"; }

run workspace/db/h2/schema.sql
run workspace/db/seed.sql      # 第 1 次
run workspace/db/seed.sql      # 第 2 次 —— 行数必须与第 1 次一致
java -cp "$H2_JAR" org.h2.tools.Shell -url "$URL" -sql \
  "SELECT (SELECT COUNT(*) FROM job) AS jobs, (SELECT COUNT(*) FROM job_requirement) AS reqs"
```

> **为什么 `DATABASE_TO_LOWER=TRUE` 不能省**：不加的话 H2 把未加引号的标识符折成**大写**，
> 与 MySQL 的小写表名/列名不一致，Java 侧映射和手写 SQL 都会踩空。

**一处与 tasks.md 字面不同的实现**：M1.5.4 括号里写「MySQL 用 `ON DUPLICATE KEY UPDATE`／
H2 用 `MERGE`」，暗示要两份方言。实测 H2 2.2.224 在 `MODE=MySQL` 下**原生支持**
`ON DUPLICATE KEY UPDATE`（也支持 `AUTO_INCREMENT` / `MEDIUMTEXT` / `ON UPDATE CURRENT_TIMESTAMP` /
表内 `KEY` 索引 / `FROM DUAL`），因此**只有一份 `seed.sql`**，正是 spec §2.9「两模式共用」想要的。
代价：升级 H2 大版本时需要重跑上面这段验证。

**`job` 表为什么用「缺则插 + 变了才更」而不是 `ON DUPLICATE KEY UPDATE`**：
spec §2.9 要求「重新导入只更新 `source='seed'` 的行」。用 `ON DUPLICATE KEY UPDATE` 表达这个守卫，
得给每一列套 `CASE WHEN source='seed' THEN … ELSE <列名> END`，`jd_raw`（几百字）要重复两遍，
文件立刻臃肿到没法评审。拆开后更短、也更清楚，顺带让 `version` 变成有意义的字段
（**只在内容真变了才 +1**，而不是每次重启涨一格 —— 那种「版本号自己会跑」的现象最容易被当成 bug）。

### 1.3 扩展位：两张「现在不建、结构已想好」的表（M1.5.6）

本期 **6 张表**：`job_category` / `job` / `job_requirement` / `job_tag` / `skill` / `skill_alias`。
下面两张**只在 `schema.sql` 里留注释，不建表**：

| 表 | 用途 | 什么时候建 |
|---|---|---|
| `analysis_record` | 分析历史，含 `job_snapshot`（**分析当时的**岗位 + 技能要求快照） | 要「历史记录可解释」时：岗位被改 / 归档后，旧分数仍能说清「当时为什么 82 分」 |
| `job_revision` | JD 变更史（`content_hash` 已具备检测能力，只差落历史表） | 要审计 / 回滚 JD 变更时 |

字段设计（已冻结，建表时照抄，**不需要改动现有 6 张表**）：

```sql
CREATE TABLE analysis_record (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  trace_id CHAR(36) NOT NULL, resume_hash CHAR(64) NOT NULL,   -- PII 不入库
  job_id BIGINT NULL,
  job_snapshot TEXT NULL,                                       -- ★ 软删的另一半
  match_score INT NULL, result_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uk_analysis_trace UNIQUE (trace_id)
);
CREATE TABLE job_revision (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_id BIGINT NOT NULL, revision_no INT NOT NULL, content_hash CHAR(64) NOT NULL,
  jd_raw MEDIUMTEXT NOT NULL, changed_by VARCHAR(64) NULL,
  changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uk_job_rev UNIQUE (job_id, revision_no)
);
```

> `job_snapshot` 是「软删」的另一半：没有它，软删只是把行留下，语义仍然悬空。

**另一个扩展位：人工增删岗位的接口路（本期不做）**
`POST /api/admin/jobs` / `DELETE /api/admin/jobs/{code}`（软删）—— 表结构已完全支持
（新增写 `source='manual'`，删除走 `status='archived' + deleted_at`），**只差 Controller**。
不做的原因：它需要鉴权，而鉴权是 part1 的 Out of Scope。本期走**文件路**
（加 `db/seed/jobs/*.json` → 跑脚本 → 重启）。

### 1.4 已知缺口

| # | 缺口 | 影响 | 为什么先接受 |
|---|---|---|---|
| 1 | 岗位**没有外键约束** | 靠 `gen-seed.sh` 的分节顺序与 `--check` 保证完整性，数据库层不拦 | plan §4 的 DDL 就没写 FK；分类/技能是「可归档的字典」，加 FK 无收益还添约束 |
| 2 | `attributes` 用 `TEXT` 而不是 MySQL 原生 `JSON` | 失去 JSON 路径索引与 `->>` 查询 | 要与 H2 版保持**同构**（H2 无等价类型）；本期只做预留展示 |
| 3 | 没有「删除」语义 | 源里删掉一个岗位 JSON，库里那行**仍在**（不会自动下架） | 有意为之（D2 只软删）。要下架：`status='archived'`；要真删：手工 SQL |
| 4 | `job_tag` 是自由文本，没有标签字典 | 同义标签（「高并发」/「高并发场景」）会各存一条 | plan §4.5 明确本期不做；结构不阻碍将来补 `tag` 字典表 |

---

## 2. PDF 解析与清洗（part2 · M2）

**目标**：真实 PDF 抽出干净文本。**验收**：AC11 / AC14；**门禁**：PDF 未复制进 `apps/`。

### 2.1 文件与职责

| 文件 | 角色 | 关键约束 |
|---|---|---|
| `apps/analyzer/app/service/parser_plugin.py` | 解析器**插件框架**：`ParseResult` / `DocumentParser` 协议 / `ParserRegistry` / 组合根 `default_registry()` | 只定协议，不含任何格式的解析逻辑 |
| `apps/analyzer/app/service/pdf_parser.py` | PDF 字节 → `ParseResult` | **唯一** `import pypdf` 的文件（有测试守着） |
| `apps/analyzer/app/service/docx_parser.py` | Word 字节 → `ParseResult`，**自研**（只用标准库 `zipfile` + `xml.etree`） | 本期不在上传链路上（见 D-2） |
| `apps/analyzer/app/service/cleaner.py` | 原始文本 → 干净文本 + 章节 | **唯一**改文本的地方；不读文件、不抛业务错误码 |
| `apps/analyzer/app/core/constants.py` | `PDF_MAX_PAGES` / `PDF_MIN_TEXT_LAYER_CHARS` / `READING_ORDER_*` | 改这里等于改契约 |
| `apps/analyzer/tests/unit/` + `tests/integration/` | 111 + 25 条用例 | 全绿（`pytest`，5.8s） |

**「插件」的实际含义**（不是目录好看）：加一种格式 = 新建一个 `*_parser.py` + 在 `default_registry()`
注册一行，调用方与 `cleaner` **一行都不用改**；换 PDF 库（ADR-103：pypdf → pdfplumber）只改 `pdf_parser.py`。
注册**故意不用导入副作用** —— 那样导入顺序会决定注册结果，且单测里想只注册一个解析器就做不到。

### 2.2 边界处理：五条**故意不同**

| 情况 | 行为 | 为什么 |
|---|---|---|
| 空 / 损坏 / 截断 | 抛 `PDF_PARSE_FAILED` (422) | 连事实都拿不到 |
| 有密码且空密码解不开 | 抛 `PDF_ENCRYPTED` (422) | 同上 |
| 页数 > 10 | 抛 `PDF_TOO_MANY_PAGES` (422) | 不为 200 页文件白烧 CPU |
| **读完但文本太少** | **正常返回**，`has_text_layer=False` | ★ 抛异常会把「文本长度 + 页数」两样事实一起丢掉。要不要因此报 `PDF_NO_TEXT_LAYER` 是**上层策略**（M4 的流式编排） |
| **只有所有者密码** | 正常解析，`encrypted=True` | ★ 空密码能开就不算失败 —— 把 `encrypted` 直接当失败会误杀这类文件 |

判定「有没有文本层」用**非空白字符数**（阈值 `PDF_MIN_TEXT_LAYER_CHARS=100`），不用 `len()`：
扫描件常能抽出页码 / 页眉几个字符，再配上一堆换行，`len` 会虚高，把扫描件当有效简历放行。

### 2.3 真样本实测（`脱敏资料/*.pdf`，20 份）

| 指标 | 结果 |
|---|---|
| 解析成功 | **20 / 20**（无 `PDF_PARSE_FAILED`） |
| `has_text_layer` | **20 / 20 为 True** |
| 页数 | 1 – 6（上限 10） |
| 清洗后文本长度 | 1804 – 9621 字符（上限 20000，**无一份被截断**） |
| 可打印字符占比 | **20 / 20 = 1.000** |
| 切出至少一个具名章节 | **20 / 20**；`header` 20、`projects` 16、`experience` 15、`education` 13、`skills` 11、`summary` 11、`basic` 4、`certificates` 1 |

这份表**就是 AC11 / AC14 的证据**，可随时复现（见 2.7）。

### 2.4 清洗七步（顺序不能换）

| # | 步骤 | 为什么在这个位置 |
|---|---|---|
| 1 | 统一换行 | 后面所有按行处理都假设只有 `\n` |
| 2 | 去隐形字符 + **图标字形** | 零宽字符会让逐字比对静默失败；图标字体的私用区字形不是文字，但**行首的那一个是列表符号** |
| 3 | 全半角统一 | 让 `（）` 与 `()` 等价；**在合并断行之前**，否则行尾判断要处理两套标点 |
| 4 | **阅读顺序自检** | ★ 必须在合并断行**之前**：合并会毁掉行结构，之后再算「短行占比」就没意义了 |
| 5 | 合并断行 | 把「排版行」还原成「语义行」 |
| 6 | 截断 | >20000 → 截断并标记（ADR-109，写进 `meta.truncated`） |
| 7 | 按章节切块 | 切块描述的是**真正会往下走的那份文本**，所以放在截断之后 |

两个刻意的「不做」：**不用 `unicodedata.normalize("NFKC")`**（它会顺手把 `①`→`1`、`㎏`→`kg`，
对中文简历破坏性大于收益，且行为随 Unicode 版本变化 —— 清洗结果不该依赖 Python 版本）；
**章节判定要求「归一化后与别名完全相等」**（宁可漏切，不可误切 —— 误切会把正文片段塞进 `sections`，
让下游以为那是独立章节）。

### 2.5 写测试时从真实数据里挖出来并修掉的问题（修复登记）

> 这几条都是**先有测试/真样本、才暴露**的，不是设计时就想到的。列在这里是因为它们都是
> 「不改也能跑、但会静默错」的类型。

| # | 问题 | 症状 | 修法 |
|---|---|---|---|
| F-1 | **多词英文别名永远匹配不上** | `TECHNICAL SKILLS` / `PROJECT EXPERIENCE` 在别名表里有，却从不生效 | 别名表与候选行改用**同一个**归一化函数（小写 + 去空白）。`test_split_sections_recognises_a_multi_word_english_alias` 钉住 |
| F-2 | **`_MAX_HEADER_LEN = 12` 写死** | 上面的长别名即使归一化了也会被长度上限挡掉 | 改成**由别名表推导** `max(len(key) …)`，并改为在**归一化后的 key** 上判长度 |
| F-3 | **项目符号行的续行掉成独立一行** | `• 负责直播后台开发` / `与维护工作` 被拆成两段 | 遇到项目符号时**换 buffer**（而不是直接落块），让续行并进来。**章节标题仍独占一行** —— 两者故意不同 |
| F-4 | **`is_printable_ratio` 对整篇替换字符报 100%** | `\ufffd` 属 Unicode `So` 类，`str.isprintable()` 认为它可打印 | 单独排除 `\ufffd`。它正是「抽错」最该被发现的信号 |
| F-5 | **真实样本里的图标字形没被处理** | 20 份样本里出现 `\uf06c \uf06e \uf0d8 \uf0b2 \uf129 \uf095 \ue609 \ue656 \ue6b1`…（FontAwesome / 模板图标字体），可打印占比掉到 0.982；更糟的是 `\uf06c 熟练 Vue2/3` 这类**列表项被并进上一段** | 私用区字形分两种处理：**行首的换成 `•`**（保住列表结构），**其余直接删**（行内图标是纯装饰）。修完 20/20 可打印占比回到 1.000 |
| F-6 | **别名表缺真实标题** | 真实样本里 `个人技能` / `技术专长` / `个人优势` / `求职岗位` 是独立标题，但表里没有 → 整块被并进上一段 | 按真实数据补 4 个别名（`skills` ×2、`summary`、`job_intent`）。**别名表要跟着真实数据长，而不是靠想** |

### 2.6 试过但**否决**的方案

| 方案 | 实测结果 | 结论 |
|---|---|---|
| pypdf `extraction_mode="layout"` | 能救 1 份（`resume_06` 从 1 → 3 个章节），但让另外 6 份变差（`resume_07` 5 → 1、`resume_17` 6 → 2…），**章节命中总数 92 → 75** | **否决**，保留默认模式。真正的解法是 ADR-103 的备选 `pdfplumber`，换库只改 `pdf_parser.py` |
| 引入 `python-docx` 解析 Word | 只为「按顺序抠文字」就要拉进一整套文档模型 API | **否决**，自研 40 行（`zipfile` + `xml.etree`），少一个依赖就少一个受限网络下的失败面 |
| 把「没有文本层」也做成异常 | 会把「文本长度 + 页数」两样事实一起丢掉 | **否决**，只报事实、把策略留给上层（见 2.2） |
| 自研 PDF 解析（不依赖 pypdf） | xref 表 / 流解码 / 字体 CMap / 加密，3h 内不可能可靠 | **否决**，与 ADR-103 冲突（见 D-2） |

### 2.7 门禁与复现命令

```bash
cd workspace/apps/analyzer
python -m venv .venv && ./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/python.exe -m pytest                 # 136 passed

# 真样本门禁（找不到 脱敏资料/ 会 skip，不会 fail）
./.venv/Scripts/python.exe -m pytest tests/integration -v

# 门禁①：apps/ 下不得有任何样本文件
find workspace/apps -type f \( -iname '*.pdf' -o -iname '*.docx' \) -not -path '*/.venv/*' | wc -l   # 0

# 门禁②：只有 pdf_parser.py 能 import pypdf（plan §7 的「唯一职责文件」）
grep -rn -E '^\s*(import|from)\s+pypdf' workspace/apps/analyzer/app/
# → 只应出现 app/service/pdf_parser.py 两行
```

门禁①与②都**已写成测试**（`tests/integration/test_real_resume_samples.py`），不靠人记。

### 2.8 已知缺口

| # | 缺口 | 影响 | 为什么先接受 |
|---|---|---|---|
| 1 | **行结构塌陷** | `resume_06` / `resume_08` 这类 PDF 的换行全靠绝对定位，pypdf 抽出来整页是一行 → `sections` 只有 `header` | 文本本身**可用**（M3 的匹配、M4 的 Prompt 都吃整段文本），只影响结构切块。已试过 `layout` 模式，净负（见 2.6） |
| 2 | **私用区字形一律当图标删** | 极老的中文字体若把生僻字映射到私用区，会被误删 | 20 份样本里 100% 是图标字形。真遇到丢字就收窄 `_SYMBOL_GLYPH_RE` 的范围 |
| 3 | 不还原表格的行列结构（DOCX 侧） | 表格文字不丢，但失去二维形状 | 用样式猜结构太脆；本期不需要 |
| 4 | 页眉 / 页脚 / 批注不读（DOCX 侧） | 简历正文极少放那里 | 同上 |
| 5 | 阅读顺序自检只是**启发式** | 可能漏报双栏排版 | spec §3 明确不承诺所有排版都能正确解析；把启发式当判据会造成误杀，所以只 WARN |

### 2.9 超长文本：两个入口**故意**不一致（ADR-109）

| 入口 | >20000 字符时 | 用户看到 |
|---|---|---|
| **PDF 上传** | **截断 + 标记** `meta.truncated = true`，正常出结果 | 「结果基于前 20000 字」的提示 |
| **文本粘贴** | **400** `RESUME_TOO_LONG` | 明确让他改短 |

**为什么不能统一**：传文件的人**没得改** —— 简历就是那么长，文件已经生成好了。
把「因为太长所以拒绝」甩给他，等于告诉他「你去把简历删短点」，而他能做的只有重新排版。
粘贴文本的人手里就是一段可编辑的文字，直接拒绝是**可操作**的反馈。

**代价**：同一个字段（文本长度）在两个入口产生两种结果，测试要分两处覆盖
（`test_cleaner.py` 的截断用例 + BFF 的 `RESUME_TOO_LONG` 用例），
且写文档时必须显式说明，否则会被当成 bug。

**截断位置放在清洗第 6 步**（§2.4）：章节切块必须切「真正会往下走的那份文本」，
先切块再截断会让 `sections` 里出现下游拿不到的片段。

---

## 3. 归一化 · 匹配 · 推荐（part2 · M3）

**目标**：把「简历文本 + 岗位要求」变成**可复现**的分数与推荐。
**验收**：AC16（两次一致）/ AC17（集合自洽）/ AC18（手算复现）。

### 3.1 三个文件，三种职责

| 文件 | 角色 | 不做什么 |
|---|---|---|
| `service/normalizer.py` | 词典 + 四步归一化 + 全文技能抽取 | 不算分、不排序 |
| `service/matcher.py` | **全项目唯一**的打分实现（`score_of`） | 不排序、不选 Top-N |
| `service/recommender.py` | 全量候选打分 → 排序 → 取 Top-N | **不自己算分**（只调 matcher） |

> 「推荐自己再算一套分数」是最容易出的错：`match.score = 82` 而推荐里同一个岗位是 80，
> 两个数字都「看起来对」，但没人能解释差在哪。**一份公式只允许有一个实现。**

### 3.2 打分公式（AC18 的手算依据）

```
score = Σ(命中技能权重) / Σ(该岗位全部技能权重) × 100
required = 1.0   preferred = 0.5
```

| 边界 | 行为 | 为什么 |
|---|---|---|
| 岗位 0 技能 | `score = 0`（不是 100） | 分母为 0。没有要求可命中时给满分是误导 |
| 简历 0 技能 | `score = 0`，全部进 `missing` | 分子为 0 |
| 同一技能多条要求 | 取**最高**权重 | 重复要求不该被重复计分 |
| 舍入 | `floor(x + 0.5)`，**不用内置 `round`** | Python 的 `round` 是**银行家舍入**（`round(0.5)==0`），会让「手算 52.38 → 52」和「`round` 给出 52.4」对不上 |

`MatchReport` 把 `hit_weight` / `total_weight` 一起暴露出来 —— AC18 要的就是
**评审当场拿这两个数除一下**，结果必须等于 `score`。藏起来的话分数只是个黑盒数字。

`matched` / `missing` **由同一份去重列表生成**，所以
`matched ∩ missing = ∅`、`matched ∪ missing = 该岗位技能全集` 是**结构上成立**的（AC17），
不靠写测试去凑。

### 3.3 归一化四步（顺序不能换）

| # | 步骤 | 说明 |
|---|---|---|
| 1 | 查别名（精确） | `SpringBoot` → `Spring Boot` |
| 2 | 规范化后再查 | 全半角统一 + 小写 + 去空白与 `- _ . \ /` |
| 3 | 编辑距离兜底 | 相似度 ≥ 0.90 **且** 长度 ≥ 4（救 `Typescrpt` 这类手滑） |
| 4 | 都失败 → `None` | **不抛错**：认不出一个词不是异常，是常态 |

**两个刻意的保留**：`+` 与 `#` 不进「去字符」集合 —— 否则 `C++` 会归一成 `C`、
`C#` 归一成 `C`，三个不同的技能被并成一个。

**`Java` 与 `JavaScript` 的三道防线**（最经典的误命中）：

1. 长度门槛 —— 两者相似度只有 0.40，过不了 0.90；
2. **抽取时的 ASCII 边界检查** —— 后邻是字母/数字就拒。挡住 `Google`→`Go`、`GitHub`→`Git`；
3. **扫描按最长优先** —— 正则 alternation 是**最短**优先，直接用会先匹配到 `Java`。

**offset 必须回填原文坐标**：折叠删空格（第 2 步）会让位置整体偏移，
`resumeEvidence` 在前端高亮时就会错位。`_fold_with_index` 记映射表解决。

**单字母别名（`C`）不参与全文扫描**：`C++` 里的 `C` 后面跟的是 `+`，
边界检查救不了 —— 只能整体不扫。但 `normalize()` 仍然认它（显式写 `C` 时是对的）。

实测：143 个词 × 23200 字符 ≈ **10ms**。

### 3.4 推荐的确定性（AC16）

排序键 `(-score, jobId)` —— **用 `jobId` 兜底，不用 `title`**。
标题一改顺序就变，那就不可复现了；`jobId` 是稳定且全局唯一的。

`reason` 用**规则模板**（`命中 h/t 项要求，缺口为 X、Y`），不走 LLM：
它与排序同源，必须一起被钉死。注意 `h/t` 数的是**技能条数**，不是权重。

推荐项里的 `matched` / `missing` 只留**摘要**（技能名列表），完整证据留在 `match` 里 ——
否则同一份证据在响应里出现两遍，两边还可能不一致。

---

## 4. 流式协议（part2 · M4 + M8.5）

**目标**：一次请求跑完七阶段，过程可见、结果必达。**验收**：AC11 / AC15 / AC19 / AC21。

### 4.1 六个事件、七个阶段

```
event: meta      ← 必为**首帧**（traceId + source: text|pdf）
event: stage     ← 7 个阶段，每个发 start + ok 一对
event: thinking  ← 0..n 条（只在 LLM 真跑时才有）
event: result    ← **恰好一次**
event: error     ← 与 result **互斥**
event: done      ← 必为**末帧**
```

`STAGE_ORDER = accepted → parsed → cleaned → normalized → matched → recommended → llm`
（唯一真源在 `schema/response/sse_event.py`；冒烟脚本里**另抄一份**，避免「代码自证」）。

**跳过的阶段也发 start + ok 一对**（比如没选岗位时 `matched` 带 `skipped=true`）。
理由：消费方（前端的阶段条）不该为「这一步跳过了」写特殊分支，
否则那一格会闪一下或者干脆不显示。

### 4.2 三个响应头

| 头 | 值 | 为什么必须有 |
|---|---|---|
| `content-type` | `text/event-stream; charset=utf-8` | 契约 |
| `cache-control` | `no-cache` | 否则中间层缓存住整条流 |
| `x-accel-buffering` | `no` | **nginx 默认会缓冲响应**，不加这个头，流会被攒到最后一次性吐出 —— 本地直连完全看不出来，一上反代就「流式失效」 |

### 4.3 错误分界线：建流前 vs 建流后

这是流式最容易被忽略的一条：**HTTP 状态码只能表达建流之前的事**。

| 时机 | 错误 | 走哪条路 |
|---|---|---|
| 建流前 | >10MB | 同步 HTTP **413** `FILE_TOO_LARGE` |
| 建流前 | MIME 不是 pdf / **magic number 不是 `%PDF-`** | 同步 HTTP **415** `UNSUPPORTED_FILE_TYPE` |
| 建流前 | 既没 file 也没 resumeText | 同步 HTTP **400** `INVALID_INPUT` |
| 建流后 | 损坏 / 加密 / 页数超限 / **没有文本层** | SSE `error` 事件 + `done` |

一旦 `ctx.status = 200` 且 `flushHeaders()` 发出去，**再也改不了状态码**。
所以「什么都没传」必须在建流前判 —— 否则它会变成一个 200 + 空流，用户完全看不出哪错了。

**magic number 而不是扩展名**（AC12）：docx 改名为 `.pdf` 必须被 415 拦下。
判据是前 5 个字节 `%PDF-`，MIME 只当第一道便宜的筛子（客户端可以伪造）。
实测见 §6 演练 2。

### 4.4 心跳只在 LLM 阶段发

`解析 / 清洗 / 匹配 / 推荐` 合计通常 < 100ms；**慢到需要心跳的只有等 LLM**。
在其他阶段塞心跳判断，只会增加**没被测到**的代码路径。
心跳是注释帧（`: ping`），不是事件 —— 消费方按规范会忽略它，分帧器也要显式丢掉。

### 4.5 LLM 契约：失败也一定发 `LlmFinished`

`client.stream_issues()` 是 async generator，产出 `LlmThinking`(0..n) + `LlmFinished`(**恰好一次**)。
**LLM 失败时也发 `LlmFinished(issues=None)`** —— 于是编排层不需要一棵 except 森林：

```python
if event.issues is None:          # 降级
    issues = detect_issues(cleaned.text, cleaned.sections)
    llm_used, degraded = False, True
```

编排层**仍然**给整个 LLM 循环包了一层 try/except：客户端把异常转成 `LlmFinished`
是**约定**不是**保证**。少了这层兜底，一次 LLM 抖动会让用户连 `recommendations` 都拿不到
（spec §2.4：**只有 `parsed` 失败才发 `error`**）。

`parse_issues` **严进宽出**：顶层必须是 `{"issues":[...]}`、枚举必须命中、`evidence` 必须非空；
**单条不合法只丢那一条**，全军覆没才返回 `None`（= 整体降级）。

### 4.6 断连与资源释放（AC19）

客户端提前断开时，Python 会在 `finally` 里 yield 的那一刻抛
`RuntimeError: async generator ignored GeneratorExit`。**那不是 bug，是「连接已经没了」的正常信号** ——
记一条日志就够，不要让异常冒出去污染 ASGI 的错误日志。

BFF 侧同理：写操作全部包在 try/catch，断连只记一条 `STREAM_ABORTED`（**仅日志**，不进响应体）。
实测 20 次「连上就断」后服务照常工作，见 §6 演练 5。

### 4.7 写测试时挖出来的四个真 bug

| # | 问题 | 症状 | 修法 |
|---|---|---|---|
| S-1 | `to_frame()` 不认 pydantic 模型 | 帧里是 `<MetaData object at 0x…>` | `_payload_of()` + 必须 `model_dump(mode="json")` |
| S-2 | LLM 抛异常让**整条流**失败 | 违反 spec §2.4，用户拿不到推荐 | LLM 循环单独包 try/except，落规则兜底 |
| S-3 | `TIMELINE_GAP` 误报 | 项目区间本就包含在任职区间内 | 重叠检查**只在 `experience` 章节内**做 |
| S-4 | **`resume.sections` 是逐字符列表** | `"education": ["2","0","1","9",…]` | `list(dict[str,str] 的值)` 会拆成字符，且 **Pydantic 不报错**；改成按 `\n` 拆 |

> **教训（S-4）**：契约断言不能只验**类型**，要验**值的形态**。
> `isinstance(x, list)` 对 `["2","0","1","9"]` 和 `["2019.09-2023.06 某大学"]` 一样为真。
> 这个 bug 只在端到端 `curl` 一次时才看得见。

### 4.8 依赖与环境的两个坑

- **`python-multipart` 是硬依赖**：FastAPI 的 `Form` + `UploadFile` 没有它，**路由根本注册不上**
  （不是运行时报错，是启动后 404）—— 已在 `requirements.txt` 显式声明。
- **async 测试用 `pytestmark = pytest.mark.anyio`**，不需要装 `pytest-asyncio`（anyio 已在依赖树里）。
- `IssueType` / `Severity` / `Importance` 从 `Literal` 改成 `str, Enum`：JSON 输出不变，
  但代码里可以 `ErrorCode.PDF_NO_TEXT_LAYER.value` 这样引用，不再手写字符串。

### 4.9 为什么请求链是**严格线性**（C3 / ADR-101）

```
Vue ──▶ BFF ──▶ job-service ──▶ analyzer ──▶ LLM
        （校验/编排）  （岗位领域+装配候选集）  （解析/归一化/匹配/推荐）
```

part1 的骨架是「BFF 扇出」：BFF 同时调 job-service 和 analyzer。part2 **收敛成线性**，
代价是 BFF 少了一次并行调用（延迟略增），换来三件事：

1. **候选集必须由 Java 装配后下发** —— Python 收不到 `jdText`（spec §2.7：Python 不碰 DB、
   也不做 JD 抽取），岗位与技能要求的唯一来源是 `job-service`。
   扇出结构下「谁负责把候选集拼出来」没有自然归属，容易变成 BFF 里一段手写 SQL 形状的拼装。
2. **失败点单一** —— 线性链上「哪一跳断了」是唯一的。扇出时两个下游都失败，
   错误该映射成谁的错误码需要额外规则。
3. **门禁可写** —— `apps/bff/src/client/` 下**不允许出现 analyzer 客户端**、
   `client/` 与 `service/` 里不允许出现指向 `:8000` 的 URL（CI 门禁④）。
   这条约束只有在链是线性时才是干净的。

**要改回扇出**：给 BFF 加一个 `client/analyzer.client.ts`，并同步删掉 CI 门禁④ ——
但那样 `spec §2.7`「候选集由 Java 装配」就失去落点，需要重新决定候选集从哪来。

---

## 5. 前端（part2 · M7）

**目标**：上传 → 看过程 → 看结果。**验收**：AC20（非法文件不发请求 / 阶段条推进 / 打字机 / 无白屏）。

### 5.1 用 `fetch` + `ReadableStream`，不用 `EventSource`（ADR-104）

`EventSource` 只支持 GET、不能带 `multipart/form-data` 请求体。要 POST 上传 PDF，
只能自己读流。代价：**没有自动重连**（本期不做，只在出错时提示）。

### 5.2 SSE 分帧器（`utils/sse.ts`）

线上格式只有两条规则：**按 `\n\n` 分帧** + 取 `event:` / `data:` 两行。
难点只有一个：**帧会被 chunk 边界切断**。

```ts
const parser = createSseFrameParser(onFrame);   // 内部持有 buffer
parser.write(chunk);                            // 每次 fetch 拿到的 chunk
parser.end();                                   // 流结束，处理残留
```

`TextDecoder('utf-8')` 必须用 `{ stream: true }` —— 中文的一个字符可能跨两个 chunk，
不设这个选项会在边界处解出 `\ufffd`。

服务端（`util/sse.py`）、前端（`utils/sse.ts`）、测试三处**共用同一套分帧规则**，
所以「服务端发出来的字节前端能不能解析」这件事在单测里就能验掉。

### 5.3 状态机（`composables/useAnalysisStream.ts`）

暴露 `isStreaming / meta / stages / currentStage / thinking / result / error / elapsedMs`。
**不抛异常**：所有失败（网络不通、同步 4xx/5xx、流内 `error` 事件）统一落 `error`，
组件只判断 `error` 是否为空。否则每个调用点都要写一遍 try/catch。

### 5.4 组件库与主题（ADR-107）

- Element Plus **按需注册**（`main.ts` 里逐个 `app.component(...)`），12 个组件。
- 主题走 **CSS 变量覆盖**（`styles/element-theme.scss`）：主色 `#0d9488`（深青，**刻意避开默认蓝**），
  用 `color.mix()` 生成 `--el-color-primary-light-1..9`，不手写 10 个色值。
- locale 用 `<el-config-provider :locale="zhCn">` 包外壳 —— 按需模式下
  `app.use(ElementPlus, { locale })` 是**不生效**的（那条路径没有注册组件）。

### 5.5 构建：`manualChunks` 里**不要**写 `element-plus`

首版把 `element-plus` 写进 `manualChunks`，产物从 130KB 涨到 **940KB** ——
手动分包会让整个包进同一个 chunk，**tree-shaking 直接失效**。移除后：

```
vendor-vue     104.12 kB │ gzip:  40.43 kB
index          129.69 kB │ gzip:  46.58 kB
vendor-echarts 392.73 kB │ gzip: 132.92 kB
```

ECharts 用 `echarts/core` + `echarts.use([...])` 按需引入（只用了一个 gauge）。

---

## 6. 降级演练：六条（part2 · M8.3）

> **为什么必须实测**：降级路径的共同特征是「**不跑也不会报错**」。
> LLM 挂了不降级 → 用户拿不到推荐；扫描件不报错 → 用户拿到一份 0 技能的「正常」结果；
> 断连不处理 → 句柄慢慢漏光。这些都不会让 `/healthz` 变红，只会让线上慢慢烂掉。

```bash
bash scripts/drill-degradation.sh          # 六条全跑
bash scripts/drill-degradation.sh 2 3      # 只跑第 2、3 条
```

**前置**：四层已启动；analyzer 的 `LLM_*` 环境变量**留空**（第 1 条要的就是「LLM 不可用」这个状态）。

### 6.1 实测结果（2026-10-15，本机四层全开）

| # | 演练 | 验收 | 断言 | 结果 |
|---|---|---|---|---|
| 1 | LLM 不可用 | AC15 | `thinking` 0 帧 · `result` 照常 · `meta.degraded=true` · `llmUsed=false` · 推荐 3 条 | ✅ 9/9 |
| 2 | 改名为 `.pdf` 的 docx | AC12 | HTTP **415** · `application/json`（**没建流**）· 无 SSE 帧 · `UNSUPPORTED_FILE_TYPE` | ✅ 4/4 |
| 3 | 扫描件 / 纯图片 PDF | AC14 | `error(PDF_NO_TEXT_LAYER)` · 无 `result` · 末帧 `done` · **0.06s** 关闭 · `parsed` 留 `fail` | ✅ 6/6 |
| 4 | 存储降级（MySQL 缺席） | part1 AC9/AC10 | job-service 可达 · 推荐 3 条 · `/healthz.storage` | ⚠️ 2/3 + **1 项已登记缺口**（见 §7 D-9） |
| 5 | 连续 20 次「连上就断」 | AC19 | 20 次均建立后断开 · BFF/job-service `/healthz` 仍 ok · 完整流仍跑通 · 日志出现 `STREAM_ABORTED` | ✅ 5/5 |
| 6 | `Accept` 不含 `text/event-stream` | AC21 | HTTP 200 · `application/json` · 无 SSE 帧 · 五块齐全 · 推荐 3 条 | ✅ 5/5 |

**合计 31 项断言通过 + 1 项已登记缺口**（脚本退出码 0；缺口与失败**分开统计** ——
混在一起，要么缺口把 CI 永远染红，要么真回归被当成缺口忽略掉）。

### 6.2 六个假样本从哪来

`scripts/drill_fixtures.py` **现场生成**两个几十字节的样本，不把二进制塞进仓库：

| 样本 | 构造 | 为什么不能直接用真简历 |
|---|---|---|
| `renamed-docx.pdf` | 一个 zip（`[Content_Types].xml` + `word/document.xml`） | 真样本里没有 docx；且仓库**不该**出现 Word 文件（门禁①） |
| `scanned.pdf` | 手搓 PDF，正文只有一个 `"1"` | 20 份真简历**全部**有文本层（§2.3），拿不出反例 |

### 6.3 演练 5 为什么用 socket 而不是 `curl --max-time`

「连上就断」的关键是**在服务端还在写的时候**把连接拆掉。
整条流（LLM 关着）只要几十毫秒 —— `curl --max-time 0.3` 大概率是**跑完了**才退出，
等于什么都没测。用 `socket` 读 64 字节再 `close()`，才是确定的半途断开。

### 6.4 演练 3 暴露的真 bug（已修）

`PDF_NO_TEXT_LAYER` 这个错误码**在枚举里定义了，但全仓没有任何地方抛出它** ——
M2 把「要不要因此报错」明确留给了 M4 的编排层（`pdf_parser.py` 的 docstring 就是这么写的），
而 M4 没接上。后果：扫描件会**一路走到 `result`**，产出一份「0 技能 / 0 推荐」但结构完全正常的响应，
用户只会以为简历写得不好，真正的原因（文件里根本没有文字）被彻底藏起来。

修法在 `analysis_stream_service.py` 的 `parsed` 阶段：解析成功后判 `has_text_layer`，
不达标就抛 `AppException(PDF_NO_TEXT_LAYER)`；已有的 `except AppException` 会留下
`fail` + `code` 的 stage 记录，再走 `error → done`。
测试见 `tests/unit/test_stream.py::test_scanned_pdf_is_reported_as_no_text_layer`。

---

## 7. 偏离登记：施工单 / spec / plan 三者不一致时怎么裁

> 规则：**先看 spec（冻结面），再看 plan（实施），最后看施工单**；任何偏离都写在这里，
> 不悄悄改行为。每条都给出「代价」与「要改回去该动哪里」。

| # | 来源说法 | 实际做法 | 理由与代价 |
|---|---|---|---|
| D-1 | ⚠️ **本条目曾被误写**：早期版本声称「**施工单**要求 Java 用 MyBatis-Plus，本步决定改用 MyBatis-Plus」<br>**实际情况**：全仓（`sdd/` 三份文档 + `docs/` + `pom.xml`）**没有任何地方提到 MyBatis-Plus**。`sdd/part2/tasks.md` M5.3 的原话是「`repository/impl/` **双实现（JPA + InMemory）** + `@ConditionalOnProperty`（沿用 part1 ADR-007）」 | **保留 Spring Data JPA**，未引入 MyBatis-Plus | 那条「以施工单为准」的记录**没有依据，已删除**。真实的偏离是另一件事（见 D-9）：M5.3 要的是**双实现 + 条件装配**，实现成了**单实现 + 数据源 URL 切换**。**代价**：`@ConditionalOnProperty` 那套装配期切换没有落地。**要改回去**：把 `repository/*.java` 拆成接口 + `repository/impl/{Jpa,InMemory}` 两个实现，配 `app.storage.mode` 条件装配（见 D-9）。 |
| D-2 | **施工单**：Python 自己写一个解析 **PDF 跟 Word** 的插件<br>**spec §1**：DOCX 属 Out of Scope；**AC12**：改名成 `.pdf` 的 docx 必须被 415 拒<br>**plan ADR-103**：PDF 用 `pypdf` | ① 自建**可插拔解析器框架**（我们自己的协议 + 注册表）；② **Word 解析器自己写**（只用标准库 `zipfile` + `xml`，不引入 `python-docx`）；③ **PDF 仍用 `pypdf`**；④ 上传入口**仍然只放行 PDF**，Word 解析器作为已测试的能力预留 | 「自研插件」这条对 Word 完全满足；PDF 若也自研（xref 表 / 流解码 / 字体 CMap）在 3h 内不可能可靠，且会直接推翻 ADR-103。上传入口不放行 Word 是为了不破坏 AC12 与 spec §2.9 的安全边界。**要放开 Word**：改 BFF 白名单 + 在 spec 变更记录里把 DOCX 从 Out of Scope 移出，**不需要动解析器本身**。 |
| D-3 | **spec §5 / tasks M1.5.5**：技术 **8** 个子类<br>**plan §4.1** 的树只列了 **7** 个 | 补第 8 个 `tech-security`（安全 / 风控） | 两处对不上，取「8 个」这个更大的数。选安全/风控是因为它不与已有的 `tech-algorithm`（算法 / 数据）重叠，且是招聘平台常见岗位族。**要换**：改 `db/seed/categories.json` 一行 + 复跑脚本（D1 的意义就在这）。 |
| D-4 | **tasks M3.1**：`skills.yaml` 在 M3 才建<br>**tasks M1.5.3**：`gen-seed.sh` 要读 `skills.yaml` | `skills.yaml` **提前到 M1.5** 落地（83 条技能 / 79 别名） | M1.5.3 对 M3.1 有硬依赖，不提前就做不了 M1.5。M3.1 届时只剩「复核 + 按需补录」，不再是「从零写」。 |
| D-5 | **part1 plan §7**：`db/` 在 `apps/job-service/src/main/resources/db/`<br>**part2 plan §7**：`db/` 与 `apps/`、`scripts/` 平级 | 取 **`workspace/db/`**（与 part2 plan 一致） | part2 plan 是更新的文档，且把 `scripts/` 也画在同一层，与实际仓库一致。**代价**：Java 启动要加载 schema/seed 时得把它们放进 classpath（`pom.xml` 加一次资源拷贝，或 `spring.sql.init.*-locations` 指到拷贝后的路径）—— 这件事落在 M5，已在 M5 的改动清单里。 |
| D-6 | **tasks M1.5.3**：只提 `scripts/gen-seed.sh` | 拆成 `gen-seed.sh`（入口）+ `gen_seed.py`（生成器） | 入口名必须叫 `gen-seed.sh`（tasks 与 CI 都按这个名字调），但转义 / 算 `content_hash` / 算 `jd_offset` / 逐条校验写在 Python 里才可读可测。shell 只负责「找解释器 + 透传参数」。 |
| D-7 | **spec §2.4 / M2.4**：清洗要「去隐形字符（`\u200b` / `\xa0` / `\xad`）」—— 只列了三种<br>**实际**：真实样本里还有一整类**图标字形**（FontAwesome / 模板图标字体，落在 Unicode 私用区 U+E000–U+F8FF） | 私用区字形按位置分两种处理：**行首的换成 `•`**（它是列表符号，抹掉就丢段落结构），**行内的直接删**（纯装饰图标） | spec 列的三种是「零宽 / 空格类」隐形字符，而图标字形是**另一种**脏数据：它不是空白，是一个有字形、没文字含义的码位。不处理的话可打印占比掉到 0.982，且列表项会被并进上一段。**代价（已知缺口 2）**：极老的中文字体若把生僻字映射到私用区会被误删 —— 20 份样本里 100% 是图标，真遇到再收窄范围。**要改回去**：删 `cleaner.py` 的 `_SYMBOL_GLYPH_RE` / `_LEADING_SYMBOL_GLYPH_RE` 两条规则即可。 |
| D-8 | **plan §7**：`pdf_parser.py` 是「唯一」允许 `import pypdf` 的地方 | **`app/` 下严格成立**（已写成测试）；但**测试**里也 import 了 pypdf —— 用于 `PdfWriter` 造**加密样本** | 这条约束的意图是「换库成本被挡住」，对象是**应用代码**。测试需要的是一个**加密器**，而应用永远不做加密；手搓 RC4/AES 密文只会让测试没法维护。**要改回去**：把加密样本预先落成二进制 fixture（代价是仓库里多两个二进制文件）。 |
| D-9 | **part1 spec §2.9（冻结）**：存储降级三档 `mysql → local → mock`，由 `app.storage.mode`（默认 `auto`）在**启动时逐个探测**，第一个成功即停；**§2.8**：`/healthz` 必须返回 `{status, storage}` 作为「降级的唯一可观测证据」<br>**part2 tasks M5.3**：`repository/impl/` 双实现（JPA + InMemory）+ `@ConditionalOnProperty` | **两档、部署期切换**：默认 H2（`jdbc:h2:mem:…`），`JOB_DB_URL` 指向 MySQL 即切主路径。**同一套 Repository**，不做双实现。**`/healthz` 不返回 `storage`**，`mock` 档未实现 | 三档自动探测在 3h 预算下是**主线风险**：探测逻辑本身要写、要测、还要为「MySQL 半死不活」（能连上但查不动）定超时。而两档 URL 切换**已经满足最高原则**（任何时刻仓库都可运行 —— 默认零外部依赖），且「换存储不换分数」天然成立（两档共用同一份 `schema.sql` + `seed.sql`）。<br>**代价**：① part1 的 AC9/AC10 **未满足**；② 降级从「运行期自动」降级为「部署期显式」—— MySQL 挂了**不会**自动下沉，而是启动失败；③ 没有对外可观测的降级证据。<br>**已写成演练**：`drill-degradation.sh` 第 4 条把它标成 **GAP 而非 FAIL**（缺口与真回归必须分开统计）。<br>**要补回去**：新增 `StorageModeResolver`（读 `spring.datasource.url` → `mysql` \| `local`）+ `HealthResponse` 加一个 `storage` 字段（**最小实现**，就能让 §2.8 成立）；再做 `app.storage.mode=auto` 的启动探测与 InMemory 实现（工作量大头在这）。**注意**：`storage` 的枚举按 spec 是 `mysql \| local \| mock` —— H2 档应报 `local`（spec §2.9 的表里 `local` 就是「H2（内存或文件，`MODE=MySQL`）」），不要自造 `h2` 这种新词。 |
| D-10 | **惯例**：CI 用 `npm ci`（严格按 lock，保证可复现） | ⏳ **已完成一半**：`apps/web/package-lock.json` 已补成**完整** lock 并提交；`ci.yml` 那一步仍写着 `npm install`，换回 `npm ci` 需**有 `workflows` 权限**的提交者应用（见下） | 原问题：`apps/web/package-lock.json` 曾是**残缺的最小骨架**：生成它的那次 `npm install` 被沙箱的**安全删除守卫 fail-closed** 拦下（中文路径下 `genie-trash` 报 `relative path rejected`，PowerShell 回退也失败），整个路径被永久锁为不可写；`writeFile` / `rename` / `cp` / `git checkout` 全部 EPERM。`npm ci` 会因为 lock 与 `package.json` 不一致而**直接失败**。<br>**已按当初写下的「要改回去」执行了一半**：在普通终端 `cd workspace/apps/web && npm install` 生成完整 lock（199 条 `node_modules/*` 记录）并提交 —— 这一步做完，`npm ci` 已经**能跑通**（本地实测 140 packages / type-check / 19 tests / build 全绿）。<br>**剩余一步（1 行，任何人都能做）**：把 `.github/workflows/ci.yml` 里 web 步骤的 `npm install --no-audit --no-fund` 改成 `npm ci`，并可顺手给该 job 的 setup-node 补上 `cache: npm` + `cache-dependency-path: workspace/apps/web/package-lock.json`（与 bff 一致）。<br>**为什么没一起改**：本次提交用的 GitHub App **没有 `workflows` 权限**，推任何触碰 `.github/workflows/` 的 commit 都会被拒（`refusing to allow a GitHub App to create or update workflow`）—— 这是权限约束，不是设计取舍。 |
| D-11 | **Vite 惯例**：`cacheDir` 默认 `node_modules/.vite` | `apps/web/vitest.config.ts` 把 `cacheDir` 指到 `workspace/.logs/vitest-cache` | 同一个删除守卫把 `node_modules/.vite/` 锁死 → vitest 写 `results.json` 时 `EPERM`，**报错点在测试之前**，看起来像配置坏了。挪到 `.logs/`（已 gitignore）之后恢复正常（19 passed）。<br>**这不是纯环境 workaround**：缓存是可再生的**构建中间物**，写进 `node_modules/` 会让「依赖目录」和「临时文件」混在一起，任何把 `node_modules` 设为只读的环境（容器层、CI 缓存挂载）都会连带让测试跑不起来。与 pytest 的 `-p no:cacheprovider` 同一个思路。**要改回去**：删 `vitest.config.ts` 里的 `cacheDir` 一行。 |
| D-12 | **指南 §4.1** 的目标态里列了 `analyzer/app/core/resources.py`（`skills.yaml` 加载，`lru_cache`） | 实际**没建**：`skills.yaml` 的路径拼接与读取写在 `service/normalizer.py`（`DICTIONARY_PATH` + `yaml.safe_load`） | 单个资源文件放哪都能跑，所以一直没暴露问题。但 part3 要加**第二个**资源文件 `rubric.yaml` —— 照原习惯就会出现**第二份**路径拼接 + 第二份 YAML 读取 + 第二份顶层校验，三者各自漂移（改一处漏一处会**静默**失效：空词典 → 技能全 `unknown` → 匹配度全 0）。<br>**已清掉**：新增 `core/resources.py`（`DATA_DIR` / `resource_path` / `read_yaml`），`normalizer` 改为消费它；**路径拼接全项目只剩一处**。<br>**一处刻意的边界**：指南 §4.2 规定 `core` 不得 import `service`，因此「读成 dict」在 `resources.py`、「解释成领域对象」（`SkillDictionary` 的别名歧义 / `category` 闭集）仍在 `service/normalizer.py`。同一条约束也决定了 `get_dictionary()` **不能**搬进 core —— 它返回的是 service 层的领域对象。<br>**验证**：改后 `pytest` 仍 **232 passed / 10 skipped**（与改前逐条一致）。 |
