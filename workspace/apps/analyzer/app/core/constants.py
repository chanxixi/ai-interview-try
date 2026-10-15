"""与 spec.md §2.1 / §2.4 对齐的**编译期常量**。

改这里等于改契约：必须同步 spec.md 与三份 OpenAPI 契约（contracts/*.yaml）。

**为什么与 `config.py` 分开**（指南 §4.1）：

- `constants.py` 放**永不随环境变化**的值（长度上限、权重、枚举）—— 它们是契约的一部分；
- `config.py` 放**可被环境覆盖**的值（端口、日志级别、LLM 密钥）—— 它们是部署的一部分。

混在一起会导致「改个端口要翻契约文件」这类误判。
"""

# ---------------------------------------------------------------- 长度上限（spec.md §2.1 冻结）

RESUME_MAX_LENGTH = 20_000
JD_MAX_LENGTH = 8_000

# ---------------------------------------------------------------- part2：文件入口（spec.md §2.5 / §2.8）

#: PDF 页数上限。超了直接拒（`PDF_TOO_MANY_PAGES`），不是抽完再判 ——
#: 一份 200 页的文件抽完要几十秒，白烧 CPU，内存占用也被放大好几倍。
PDF_MAX_PAGES = 10

#: 「有文本层」的判定阈值：抽出的**非空白**字符数低于它 → `has_text_layer=False`（M2.3）。
#: 取 100 而不是 0：扫描件往往还能抽出页码 / 页眉几个字符，按 0 判会把扫描件当有效简历放行，
#: 之后所有阶段都在处理垃圾输入。100 是「少到不可能是正文」的量级。
PDF_MIN_TEXT_LAYER_CHARS = 100

#: 上传大小上限（10 MB）。**校验点是 BFF**（M6.2，建流前同步拒绝）；
#: analyzer 侧不重复判 —— 同一个规则两处实现，迟早会不一致。
FILE_MAX_BYTES = 10 * 1024 * 1024

# ---------------------------------------------------------------- part2：清洗（M2.4）

#: 阅读顺序自检：非空行里「短行」（长度 < 6）占比超过它就记 WARN。
#: 依据：排版被按列拼串时，抽出的行会大量退化成几个字的碎片，而正常简历的行长普遍 ≥ 10 字。
#: **只 WARN 不报错**（spec §3：不承诺所有排版都能正确解析，这是已知缺口）。
READING_ORDER_SHORT_LINE_RATIO = 0.35

#: 行数太少时上面的比例没有统计意义（3 行里 2 行短 = 0.67），所以再加一个样本量下限。
READING_ORDER_MIN_LINES = 12

# ---------------------------------------------------------------- 打分权重（ADR-002 冻结）

#: 加权覆盖率：score = Σ(命中权重) / Σ(JD 全部权重) × 100
WEIGHT_REQUIRED = 1.0
WEIGHT_PREFERRED = 0.5

SCORE_MIN = 0
SCORE_MAX = 100

# ---------------------------------------------------------------- part2：归一化（M3.2）

#: 编辑距离兜底的相似度阈值：`1 - 编辑距离 / max(len(a, len(b))`。
#: 0.90 的含义是「10 个字符允许 1 个编辑失误」—— 能救 `TypeScript`→`Typescrpt` 这类手滑，
#: 又不会把 `java`(0.40) 误判成 `javascript`。
FUZZY_MATCH_THRESHOLD = 0.90

#: 兜底只对**足够长**的词生效。短词在编辑距离下极易互撞（`go`↔`golang` 只有 0.33 的差距看似安全，
#: 但 `es`↔`ec`、`pg`↔`gg` 这类 2 字母组合稍一改就过线），且短词本身歧义就大。
#: **认不出只是少认一个，认错会直接把打分带偏** —— 所以宁可不兜底。
FUZZY_MIN_LENGTH = 4

#: 参与**全文扫描**的别名最短长度（折叠后）。
#: 为什么单字母词必须排除：边界检查只挡「前后是 ASCII 字母数字」，而 `C++` 里的 `C`
#: 后面跟的是 `+`（不是字母数字）—— 边界检查救不了它，会把 `C++` 同时判成 `C` 和 `C++`。
#: 这些词仍能被 `normalize()` 单独归一化，只是不做全文扫描。
MIN_SCAN_ALIAS_LENGTH = 2

#: 推荐条数 N（part2 spec §5 待拍板 #1 定稿 = 3；§2.6「条数 = min(N, 候选总数)」）
RECOMMEND_TOP_N = 3

#: 自定义 JD 的「加分项」判定词：命中这些词的句子里的技能一律记 `preferred`。
#: 与 `db/seed/jobs/*.json` 里人工标注的口径一致（JD 的「加分项」小节），
#: 这样运行期抽取的结果才能和离线落库的结果对得上。
JD_PREFERRED_HINTS = ("加分", "优先", "plus", "preferred", "nice to have", "bonus")

# ---------------------------------------------------------------- part2：SSE 流式（M4）

#: 心跳间隔（秒）。**15s 无事件就发 `: ping` 注释行**（spec §2.4 硬性规则 2）。
#: 取 15 而不是 5：心跳的作用只是防止代理/浏览器把空闲连接掐掉，
#: 5 秒一条会在慢网络下把日志刷爆，而连接超时通常是 30–60s 量级。
SSE_HEARTBEAT_SECONDS = 15

#: LLM 产出的 issues 上限（Prompt-2 规则 4）。规则兜底也用同一个数，
#: 保证降级前后 `issues` 的规模量级一致，不会「降级后突然多出一倍」。
MAX_ISSUES = 8

#: `suggestion` 字数上限（Prompt-2 规则 3，part1 §2.4 同源）。
SUGGESTION_MAX_CHARS = 20

#: 规则兜底判定「技能堆砌」的阈值：技能章节条目数超过它即记 SKILL_STUFFING。
#: 依据：真实简历的技能章节普遍在 10–20 条；超过 25 条更像「把词典抄了一遍」。
SKILL_STUFFING_THRESHOLD = 25

#: 规则兜底判定「缺乏量化」的最小动作动词命中数：低于它说明样本太少，不下结论。
MIN_ACTION_VERBS_FOR_NO_QUANTIFY = 1

# ---------------------------------------------------------------- 全链追踪（spec.md §2.8 冻结）

#: 全链 traceId 的 header 名。**唯一来源**：trace.py / logging.py / 测试都从这里 import，
#: 不各自写字面量 —— 否则「某处改了 header 名、别处没改」会让全链 traceId 静默断裂。
TRACE_ID_HEADER = "X-Trace-Id"

# ---------------------------------------------------------------- part3：LLM 深度匹配分析（spec §2.2 / §2.5）

#: 六个能力维度 —— **冻结集合**（spec §2.5①）。元组顺序 = 雷达图渲染顺序 = `abilityProfile.dimensions` 的稳定顺序。
#:
#: **真源是 `app/data/rubric.yaml`**，这里是**编译期镜像**：
#: `test_rubric_consistency.py` 断言两处**逐字一致**，防「改了 YAML 忘了改常量」这种两处漂移
#: （与 `skills.yaml` ↔ `skill` 表同一个思路）。因此**改维度集合要改三处**：spec §2.5 + rubric.yaml + 这里。
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("tech_depth", "技术深度"),
    ("engineering", "工程能力"),
    ("business", "业务理解"),
    ("impact", "项目影响力"),
    ("collaboration", "协作沟通"),
    ("growth", "成长性"),
)

#: 逐条判定档位（spec §2.3 **冻结三档**，不许增删改名）。
#: 用元组而不是 `Enum`：它同时被 `llm/client.py` 的解析器当**白名单**用（不在里面就丢该条），
#: 与 `IssueType` 用 `Enum` 的场景不同 —— 这里要的是「可迭代的合法取值集合」。
VERDICT_KINDS: tuple[str, ...] = ("satisfied", "partial", "missing")

#: 分析深度（spec §2.2）。缺省 `standard` ⇒ 响应与 part2 **逐字节一致**（AC25，可一键回退）。
ANALYSIS_DEPTHS: tuple[str, ...] = ("standard", "deep")
DEFAULT_ANALYSIS_DEPTH = "standard"

#: 推荐条数上限（C7）。**默认仍是 3**（= `RECOMMEND_TOP_N`），所以 AC17 不被破坏；
#: 只有显式传 `topN` 时才变。
MAX_TOP_N = 10
DEFAULT_TOP_N = RECOMMEND_TOP_N

#: `growthDirections` 条数上限（spec §2.3）。取 5 而不是 10：
#: 「提升方向」要的是**聚焦**，给十个方向等于没给方向；而且方向越少，每条越可能被真的执行。
MAX_GROWTH_DIRECTIONS = 5
