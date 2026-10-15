r"""分析响应 —— 与 spec.md §2.2 / part2 spec §2.3 的**冻结契约**逐字对应。

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
