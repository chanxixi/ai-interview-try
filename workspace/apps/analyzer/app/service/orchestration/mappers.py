"""内部领域对象 → 契约 DTO（从 orchestration/stream.py 拆出）。

**唯一**做字段名转换的地方：内部用 `skill` / `report.hits` 这类顺手的命名，
契约要的是 `jobId` / `matched` 这种小写驼峰。两边各自演化，
转换只在这里发生**一次** —— 分散到各处就是「改了契约忘了改映射」的经典事故。

part3 的四块（`verdicts` / `improvements` / `growthDirections` / `abilityProfile`）
映射也在这里：它们和 part2 的五块是同一件事，不另开文件。
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from app.schema.response.analyze_response import (
    AbilityDimension,
    AbilityProfile,
    GrowthDirection,
    Improvement,
    MatchResult,
    NormalizedSkill,
    Recommendation,
    ResumeSections,
    ResumeView,
    Verdict,
    VerdictKind,
)
from app.service.match.matcher import MatchReport
from app.service.skill.normalizer import SkillDictionary, SkillMention


def _sha256_8(data: bytes) -> str:
    """字节指纹前 8 位。**只记指纹不记内容**（spec §2.8：禁止日志打印简历正文）。"""
    return hashlib.sha256(data).hexdigest()[:8]


def _section_lines(section_text: str) -> list[str]:
    """章节文本 → 行列表。

    **为什么不能直接 `list(section_text)`**：`cleaner.split_sections()` 返回的是
    `dict[str, str]`（章节名 → 整段文本），而契约要求 `list[str]`。
    `list("2019.09-2023.06 某大学")` 会把它拆成**一个个字符** ——
    而且 Pydantic 的 `list[str]` 不会报错，它老老实实接受这个字符列表，
    于是响应体里出现 `"education": ["2","0","1","9",...]`。
    端到端 curl 一次才能看出来，单测里只断言 `isinstance(list)` 是抓不到的。
    """
    return [line.strip() for line in section_text.split("\n") if line.strip()]


def _resume_view(
    sections: dict[str, str],
    mentions: Sequence[SkillMention],
    dictionary: SkillDictionary,
) -> ResumeView:
    """把内部类型映射成契约形状。**这是唯一做字段名转换的地方**。"""
    return ResumeView(
        sections=ResumeSections(**{key: _section_lines(sections.get(key, "")) for key in
                                   ("education", "experience", "projects", "skills")}),
        skills=[
            NormalizedSkill(raw=m.raw, canonical=m.canonical, category=dictionary.category_of(m.canonical))
            for m in mentions
        ],
    )


def _match_report_to_contract(report: MatchReport) -> MatchResult:
    """`matcher.MatchReport` → 契约 `MatchResult`。**唯一的字段名转换点**。"""
    from app.schema.response.analyze_response import MatchedItem, MissingItem

    return MatchResult(
        score=report.score,
        matched=[
            MatchedItem(
                skill=item.skill,
                importance=item.importance,
                weight=item.weight,
                jdEvidence=item.jd_evidence,
                resumeEvidence=item.resume_evidence,
                jdOffset=item.jd_offset,
                resumeOffset=item.resume_offset,
            )
            for item in report.matched
        ],
        missing=[
            MissingItem(skill=item.skill, importance=item.importance, suggestion=item.suggestion)
            for item in report.missing
        ],
    )


def _recommendation_to_contract(item) -> Recommendation:
    from app.schema.response.analyze_response import (
        RecommendationMatchedItem,
        RecommendationMissingItem,
    )

    return Recommendation(
        jobId=item.jobId,
        title=item.title,
        company=item.company,
        level=item.level,
        score=item.score,
        matched=[
            RecommendationMatchedItem(skill=m.skill, importance=m.importance) for m in item.matched
        ],
        missing=[
            RecommendationMissingItem(skill=m.skill, importance=m.importance, suggestion=m.suggestion)
            for m in item.missing
        ],
        reason=item.reason,
    )


# ---------------------------------------------------------------- part3：四块的字段名转换


def _verdict_to_contract(fact) -> Verdict:
    return Verdict(
        skill=fact.skill,
        importance=fact.importance,
        verdict=VerdictKind(fact.verdict),
        reason=fact.reason,
        jdEvidence=fact.jd_evidence,
        resumeEvidence=fact.resume_evidence or None,
    )


def _improvement_to_contract(fact) -> Improvement:
    return Improvement(
        area=fact.area, action=fact.action, evidence=fact.evidence, targets=list(fact.targets)
    )


def _direction_to_contract(fact) -> GrowthDirection:
    return GrowthDirection(
        direction=fact.direction, why=fact.why, firstStep=fact.first_step, priority=fact.priority
    )


def _profile_to_contract(profile) -> AbilityProfile:
    """`ability_profile.ProfileResult` → 契约 `AbilityProfile`。

    注意 `score=None` 的维度**照样进列表**（带 `evidence=""`）：前端要靠这一条显示
    「无依据」，把它删掉只会让雷达图少一个顶点，用户不知道是缺了还是没测。
    """
    return AbilityProfile(
        dimensions=[
            AbilityDimension(
                name=item.name,
                score=item.score,
                rubricRef=item.rubric_ref,
                evidence=item.evidence,
            )
            for item in profile.dimensions
        ],
        overall=profile.overall,
    )


def _advice_brief(verdicts: Sequence[Verdict], dimensions: Sequence[AbilityDimension]) -> str:
    """喂给 Prompt-4 的**结构化摘要**（ADR-205）。

    只喂 `verdicts`（skill + verdict + reason + 逐字证据）与 `dimensions`（key + level），
    不喂原始累积文本 —— 后者含模型的啰嗦过程，既长又乱。摘要里已经带了原文片段，
    模型要引用证据时直接从这里取，不必再读一遍简历。
    """
    payload = {
        "verdicts": [
            {
                "skill": item.skill,
                "importance": item.importance.value
                if hasattr(item.importance, "value")
                else item.importance,
                "verdict": item.verdict.value if hasattr(item.verdict, "value") else item.verdict,
                "reason": item.reason,
                "resumeEvidence": item.resumeEvidence or "",
            }
            for item in verdicts
        ],
        "dimensions": [{"name": item.name, "level": _level_of_ref(item.rubricRef)} for item in dimensions],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _level_of_ref(rubric_ref: str) -> str:
    """`tech_depth.L3` → `L3`。摘要里只需要档位，不需要维度 key 的前缀。"""
    return rubric_ref.rsplit(".", 1)[-1]
