"""Top-N 岗位推荐（tasks.md M3.4）。

**只做三件事**：对每个候选跑一遍 `matcher.match()`、按分数排序、取前 N 条。
不自己算分、不调 LLM、不做召回裁剪。

## 为什么「不裁剪」值得写进注释

5–8 个候选全量线性扫描是**微秒级**的，任何「先粗筛再精排」的两段式设计都是在给
5 个元素加索引。spec §3 也明令禁止向量 / embedding 召回。
真正的风险是相反的那个：有人为了「性能」提前筛掉一批岗位，
于是推荐结果取决于筛选规则而不是匹配度 —— 那才是不可解释的。

## 确定性（AC16）

排序键 `(-score, jobId)`：分数降序，同分按 `jobId` 字典序升序。
`jobId` 是**稳定且全局唯一**的，所以同分时不会出现「两次调用顺序不同」。
注意不能用 `title` 兜底 —— 标题会改，改了之后同一份简历的推荐顺序就变了。

## `reason` 为什么是规则模板

它要解释「为什么把这条排第一」，属于**可解释性**的一部分。
交给 LLM 生成会出现两个问题：① 两次调用措辞不同，演示时没法复现；
② LLM 可能编造命中项。spec §2.7 把「决定推荐顺序」列为 LLM 的禁止事项，
`reason` 与顺序同源，所以一起钉死成规则。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
from app.core.constants import RECOMMEND_TOP_N
from app.service.match.matcher import (
    MatchReport,
    Requirement,
    ResumeSkills,
    match,
)

#: `reason` 模板（spec §2.3 的示例逐字对齐）：
#: `"命中 5/7 项要求，缺口为 Redis、Docker"`
_REASON_HITS = "命中 {hits}/{total} 项要求"
_REASON_GAPS = "，缺口为 {gaps}"
_REASON_NO_GAP = "，无缺口"
_REASON_NO_REQUIREMENT = "该岗位未设置技能要求"


# ---------------------------------------------------------------- 输入


@dataclass(frozen=True)
class JobCandidate:
    """一个候选岗位。字段名与契约 `bff-python.yaml` 的 `JobCandidate` 逐字一致。

    `category` 只是元数据回填，**不参与打分** —— 否则「按分类加权」会变成第二套公式
    （契约 R2 已明确标注这一点）。

    part3 N2.3 新增两个字段（**可选**）：`weight_level` 与 `dimension_weights` 由 Java
    从任务岗位的 `level` 装配而来，用于 `abilityProfile.overall` 的加权。
    ⚠️ 它们**只影响画像的权重**，不影响 `score`（匹配公式仍然唯一）。
    """

    jobId: str
    title: str
    requirements: tuple[Requirement, ...] = ()
    company: str | None = None
    level: str | None = None
    category: str | None = None
    weight_level: str | None = None
    dimension_weights: Mapping[str, float] | None = None


# ---------------------------------------------------------------- 输出（摘要，无双向证据）


@dataclass(frozen=True)
class RecommendationHit:
    """命中**摘要**。完整双向证据在 `match` 块里（spec §2.3：推荐内只保留摘要）。"""

    skill: str
    importance: str


@dataclass(frozen=True)
class RecommendationGap:
    skill: str
    importance: str
    suggestion: str


@dataclass(frozen=True)
class Recommendation:
    jobId: str
    title: str
    company: str | None
    level: str | None
    score: int
    matched: tuple[RecommendationHit, ...]
    missing: tuple[RecommendationGap, ...]
    reason: str


# ---------------------------------------------------------------- reason 模板


def build_reason(report: MatchReport) -> str:
    """从 `MatchReport` 生成一句人话。

    `hits/total` 用的是**去重后的技能条数**（不是权重）——
    「命中 5/7 项要求」是给人数的，写成「命中 5/6.5 项」没人看得懂。
    """
    total = report.total_count
    if total == 0:
        return _REASON_NO_REQUIREMENT
    reason = _REASON_HITS.format(hits=report.hit_count, total=total)
    if report.missing:
        return reason + _REASON_GAPS.format(gaps="、".join(item.skill for item in report.missing))
    return reason + _REASON_NO_GAP


# ---------------------------------------------------------------- 主流程


def recommend(
    candidates: Sequence[JobCandidate],
    resume: ResumeSkills | Iterable,
    *,
    top_n: int = RECOMMEND_TOP_N,
) -> list[Recommendation]:
    """全部候选各跑一次 `matcher.match()`，排序后取前 `top_n` 条。

    :param candidates: **全部** active 岗位（Java 装配）。archived 的岗位由 Java 过滤，
                       本层不再判一遍 —— 同一规则两处实现迟早不一致（AC23 的责任在 Java 侧）。
    :param top_n: 条数上限；实际返回 `min(top_n, len(candidates))`（spec §2.6）。
    """
    mentions = resume.mentions if isinstance(resume, ResumeSkills) else tuple(resume)
    resume_view = resume if isinstance(resume, ResumeSkills) else ResumeSkills(mentions)

    ranked: list[tuple[int, str, MatchReport, JobCandidate]] = []
    for candidate in candidates:
        report = match(candidate.requirements, resume_view)
        ranked.append((-report.score, candidate.jobId, report, candidate))

    # 分数降序 + jobId 升序。`jobId` 不进 key 的负数部分，避免「字符串取负」这种不存在的操作。
    ranked.sort(key=lambda item: (item[0], item[1]))

    recommendations: list[Recommendation] = []
    for _negative_score, _job_id, report, candidate in ranked[: max(top_n, 0)]:
        recommendations.append(
            Recommendation(
                jobId=candidate.jobId,
                title=candidate.title,
                company=candidate.company,
                level=candidate.level,
                score=report.score,
                matched=tuple(
                    RecommendationHit(skill=item.skill, importance=item.importance)
                    for item in report.matched
                ),
                missing=tuple(
                    RecommendationGap(
                        skill=item.skill,
                        importance=item.importance,
                        suggestion=item.suggestion,
                    )
                    for item in report.missing
                ),
                reason=build_reason(report),
            )
        )
    return recommendations
