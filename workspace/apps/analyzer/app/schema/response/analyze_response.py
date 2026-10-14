"""分析响应 —— 与 spec.md §2.2 的**冻结契约**逐字对应。

字段名、层级、类型不可改；变更须走 spec.md 的《变更记录》并同步 OpenAPI 契约。
骨架阶段只定义形状，真实数据由 tasks.md T5 填充。
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

IssueType = Literal[
    "NO_QUANTIFY",
    "NO_STAR",
    "SKILL_STUFFING",
    "TIMELINE_GAP",
    "MISSING_CONTACT",
]
Severity = Literal["high", "medium", "low"]
Importance = Literal["required", "preferred"]


class NormalizedSkill(BaseModel):
    """归一化后的技能：`raw` 保留原文，`canonical` 是标准词（AC6）。"""

    raw: str
    canonical: str
    category: Optional[str] = None


class ResumeView(BaseModel):
    """简历视图 —— 四类小节 + 归一化技能列表。"""

    sections: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "education": [],
            "experience": [],
            "projects": [],
            "skills": [],
        }
    )
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
    """匹配结果：`matched ∩ missing = ∅` 且并集 = JD 技能全集（spec.md §2.4）。"""

    score: int
    matched: list[MatchedItem] = Field(default_factory=list)
    missing: list[MissingItem] = Field(default_factory=list)


class Meta(BaseModel):
    """llmUsed / degraded 必须保留 —— 是降级能力的唯一证据（spec.md §2.2）。"""

    traceId: str
    llmUsed: bool = False
    degraded: bool = True
    elapsedMs: int = 0


class AnalyzeResponse(BaseModel):
    """spec.md §2.2 响应契约（冻结）：字段名 / 层级 / 类型不可改。"""

    resume: ResumeView
    issues: list[Issue] = Field(default_factory=list)
    match: MatchResult
    meta: Meta
