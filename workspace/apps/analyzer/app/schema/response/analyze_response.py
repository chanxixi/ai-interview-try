"""分析响应 —— 与 spec.md §2.2 / part2 spec §2.3 的**冻结契约**逐字对应。

字段名、层级、类型不可改；变更须走 spec.md 的《变更记录》并同步 OpenAPI 契约。

## part2 增量（v0.3）

| 变化 | 原来 | 现在 |
|---|---|---|
| `recommendations` | 无 | **新增**，字段必须有（可为空数组） |
| `match` | 必填 | **可空**（未指定 `jobId`/`jdText` 时为 `null`） |
| `meta.source` | 无 | `pdf` \| `text` |
| `meta.truncated` | 无 | PDF 文本 >20000 被截断（ADR-109） |
| `meta.recommendationCount` | 无 | 实际推荐条数 = `min(3, 候选总数)` |

`meta.llmUsed` / `meta.degraded` **继续保留** —— 它们是降级能力的唯一证据（spec §2.2）。

## part3 增量（v0.4，**纯增量**）

新增四个块与 `AnalysisDepth` / `VerdictKind` 等枚举，**既有字段名、层级、类型零改动**。

⚠️ **关键设计：为什么是「另开两个模型」而不是给 `AnalyzeResponse` 加可选字段**

AC25 要求 `analysisDepth=standard`（缺省）时响应与 part2 **逐字节一致**。
如果在 `AnalyzeResponse` 上加 4 个 `Optional` 字段，`model_dump()` 会把它们输出成
`"verdicts": null` —— **键还是出现了**，只是值为 null，AC25 立刻不成立
（而且同步端点 `/internal/analyze` 的响应形状也会跟着变，`test_contract_shape.py` 会红）。

所以：

| 模型 | 何时用 | 形状 |
|---|---|---|
| `AnalyzeResponse` | 永远（part2 的 5 块） | **一行未改** |
| `DeepAnalysisResult` | 仅 `deep` | 5 块 + 4 块 |

两个模型在 OpenAPI 里都映射到同一个 `AnalysisResult`（它的 4 个新属性非 `required`），
这正是「键可以不存在」的标准表达方式。
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class IssueType(str, Enum):
    """`issues[].type` 枚举（part1 §2.4 冻结，不许增删改名）。

    用 `str, Enum` 而不是 `Literal[...]`：两者在 JSON 上输出同样的字符串，
    但 Enum 能被 `rules.py` / `llm/client.py` 当常量用（`IssueType.NO_STAR`），
    拼错名字在 import 期就炸，而不是等到某次断言静默不匹配。
    """

    NO_QUANTIFY = "NO_QUANTIFY"
    NO_STAR = "NO_STAR"
    SKILL_STUFFING = "SKILL_STUFFING"
    TIMELINE_GAP = "TIMELINE_GAP"
    MISSING_CONTACT = "MISSING_CONTACT"


class Severity(str, Enum):
    """严重程度（part1 §2.4 冻结枚举）。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Importance(str, Enum):
    """技能要求的重要程度（part1 §2.4 冻结枚举；权重见 `core/constants.py`）。"""

    REQUIRED = "required"
    PREFERRED = "preferred"


class Source(str, Enum):
    """入参来源（part2 spec §2.3 的 `meta.source`）。"""

    PDF = "pdf"
    TEXT = "text"


class NormalizedSkill(BaseModel):
    """归一化后的技能：`raw` 保留原文，`canonical` 是标准词（AC6）。"""

    raw: str
    canonical: str
    category: Optional[str] = None


class ResumeSections(BaseModel):
    """四类小节。键名与 part1 §2.2 一致（冻结）。"""

    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class ResumeView(BaseModel):
    """简历视图 —— 四类小节 + 归一化技能列表。"""

    sections: ResumeSections = Field(default_factory=ResumeSections)
    skills: list[NormalizedSkill] = Field(default_factory=list)


class Issue(BaseModel):
    """对简历**本身**的诊断，与 JD 无关（spec.md §2.10）。"""

    type: IssueType
    severity: Severity
    evidence: str
    suggestion: str


class MatchedItem(BaseModel):
    """命中项必须带**双向原文证据**，否则不算「可解释」（AC5）。"""

    skill: str
    importance: Importance
    weight: float
    jdEvidence: str
    resumeEvidence: str
    jdOffset: Optional[int] = None
    resumeOffset: Optional[int] = None


class MissingItem(BaseModel):
    """缺口项 —— 必须给出可执行建议，不能只列技能名（AC7）。"""

    skill: str
    importance: Importance
    suggestion: str


class MatchResult(BaseModel):
    """匹配结果：`matched ∩ missing = ∅` 且并集 = JD 技能全集（spec.md §2.4）。

    part2 起**可空** —— 未指定 `jobId` / `jdText` 时为 `null`（spec §2.2）。
    """

    score: int
    matched: list[MatchedItem] = Field(default_factory=list)
    missing: list[MissingItem] = Field(default_factory=list)


class RecommendationMatchedItem(BaseModel):
    """命中**摘要**（不含双向证据，完整证据在 `match` 块）—— part2 spec §2.3。"""

    skill: str
    importance: Importance


class RecommendationMissingItem(BaseModel):
    skill: str
    importance: Importance
    suggestion: str


class Recommendation(BaseModel):
    """一条推荐。`reason` 由**规则模板**生成（M3.4），**不调 LLM**。

    排序：`score` 降序，同分按 `jobId` 字典序升序（保证确定性，AC16）。
    """

    jobId: str
    title: str
    company: Optional[str] = None
    level: Optional[str] = None
    score: int
    matched: list[RecommendationMatchedItem] = Field(default_factory=list)
    missing: list[RecommendationMissingItem] = Field(default_factory=list)
    reason: str


class Meta(BaseModel):
    """`llmUsed` / `degraded` 必须保留 —— 是降级能力的唯一证据（spec.md §2.2）。"""

    traceId: str
    llmUsed: bool = False
    degraded: bool = True
    elapsedMs: int = 0
    # 默认值必须是枚举成员而不是裸字符串：Pydantic 对 `str` 默认值会告警
    # （"Expected enum but got str"），且 `model_dump()` 出来的形状可能不一致。
    source: Source = Source.TEXT
    truncated: bool = False
    recommendationCount: int = 0


class AnalyzeResponse(BaseModel):
    """spec.md §2.2 + part2 spec §2.3 响应契约（冻结）：字段名 / 层级 / 类型不可改。"""

    resume: ResumeView
    issues: list[Issue] = Field(default_factory=list)
    match: Optional[MatchResult] = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    meta: Meta


# ------------------------------------------------------------------ part3 增量


class AnalysisDepth(str, Enum):
    """分析深度（part3 spec §2.2）。**缺省 `standard`** —— 老前端行为一字不变（AC25）。"""

    STANDARD = "standard"
    DEEP = "deep"


class VerdictKind(str, Enum):
    """逐条判定档位（part3 spec §2.3 **冻结三档**）。

    与 `core/constants.VERDICT_KINDS` 是**同一份契约的两种表达**（Enum 给类型检查、
    tuple 给解析器当白名单），由 `test_contract_shape.py` 断言两者一致，防漂移。
    """

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    MISSING = "missing"


class Verdict(BaseModel):
    """对**一条岗位要求**的判定（part3 spec §2.3）。

    与 `match` 的关系：`match` 是集合级事实（命中 / 未命中），`verdict` 是在其**骨架之上**
    的判档与理由 —— LLM **不得新增 / 删除条目**（plan §8 风险 1）。
    """

    skill: str
    importance: Importance
    verdict: VerdictKind
    reason: str
    jdEvidence: Optional[str] = None
    resumeEvidence: Optional[str] = None


class Improvement(BaseModel):
    """优化点 —— **怎么改简历**（part3 spec §2.3）。"""

    area: str
    action: str
    evidence: str
    targets: list[str] = Field(default_factory=list)


class GrowthDirection(BaseModel):
    """提升方向 —— **该补什么能力**。

    顺序由**代码**按 `priority` 升序定，**LLM 不排序**（spec §2.7 禁 LLM 决定任何排序）。
    """

    direction: str
    why: str
    firstStep: str
    priority: int


class AbilityDimension(BaseModel):
    """一个能力维度的分数。

    **分数由代码算**（档位 → 分数，见 `service/ability_profile.py`），
    LLM 只给档位与证据（spec §2.5②）。

    `score = None` 表示**该维算不出** —— 前端必须显示「无依据」，**不得画成 0 分**
    （spec §2.5.2 ①）。
    """

    name: str
    score: Optional[int] = None
    rubricRef: str
    evidence: str = ""


class AbilityProfile(BaseModel):
    """六维能力画像（part3 spec §2.5①）。维度集合**冻结**。

    `overall = Σ(维度分×权重)/Σ(权重)`，**由代码算**，四舍五入口径与 `matcher.score_of`
    一致（AC28）。某维算不出时 `overall` 按**已有维度**重新归一；算不出就留空，**不编分**。
    """

    dimensions: list[AbilityDimension] = Field(default_factory=list)
    overall: Optional[int] = None


class DeepMeta(Meta):
    """`deep` 模式下的 `meta`：在 part2 的 7 个字段后**追加** 3 个（顺序即契约顺序）。

    用继承而不是给 `Meta` 加可选字段：`standard` 模式下这 3 个键必须**不存在**
    （AC25），而 `Optional` 字段会输出成 `null` —— 键仍在。
    """

    analysisDepth: AnalysisDepth = AnalysisDepth.DEEP
    verdictCount: int = 0
    directionCount: int = 0


class DeepAnalysisResult(AnalyzeResponse):
    """`deep` 模式的完整响应：part2 的 5 块 + part3 的 4 块（part3 spec §2.3）。

    ⚠️ `meta` **必须显式重声明成 `DeepMeta`**。pydantic 不会因为「传进来的是子类实例」
    就按子类序列化：字段的注解决定 `model_dump()` 用哪张 schema，
    留着 `meta: Meta` 会让那 3 个 part3 键在输出里**静默消失**
    （`verdictCount` 明明传了，响应里却没有 —— 这类 bug 单测只断言「字段存在」是抓不到的）。

    ⚠️ 四个新块的位置在 `meta` **之后**（pydantic 的派生类字段追加在基类之后）。
    契约把它们列在 `meta` 之前，但 JSON 对象的键序无语义，AC24 只要求「四块存在」；
    为换这个顺序去重写整个模型不值当，也与「既有字段零改动」相冲突。
    """

    meta: DeepMeta  # 见 docstring：不重声明，3 个新键会被丢掉
    verdicts: list[Verdict] = Field(default_factory=list)
    improvements: list[Improvement] = Field(default_factory=list)
    growthDirections: list[GrowthDirection] = Field(default_factory=list)
    abilityProfile: Optional[AbilityProfile] = None
