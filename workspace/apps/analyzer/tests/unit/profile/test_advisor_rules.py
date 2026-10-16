"""逐条判定与六维判档的规则兜底（part3 N1.2 / N2.2 的判据基础）。

两批用例守的同一件事：**断 LLM 之后结论仍然存在、且仍然可复现**。

| 守什么 | 用例 |
|---|---|
| 判定条数 = `match` 条数、每条 `reason` 非空 | `test_verdicts_*` |
| 六维**全有档位**（最差 `L0`，不是缺失的键） | `test_grade_dimensions_returns_all_six` |
| `项目影响力` / `成长性` **与 LLM 无关、独立可算** | `test_code_only_dimensions_*` |
| 判据**同源**（与 `rules.py` 的 NO_QUANTIFY / TIMELINE_GAP 看同一批句子） | `test_impact_shares_evidence_with_no_quantify` |
| 确定性 | `test_grading_is_deterministic` |
| 空简历不编分（全 `L0`） | `test_blank_resume_gets_l0_everywhere` |
"""

from __future__ import annotations
from app.core.constants import DIMENSIONS, MAX_GROWTH_DIRECTIONS
from app.schema.response.analyze_response import IssueType
from app.service.profile.advisor_rules import (
    CODE_ONLY_DIMENSIONS,
    ResumeFacts,
    directions_fallback,
    grade_dimensions,
    improvements_fallback,
    verdicts_from_match,
)
from app.service.match.matcher import Requirement, ResumeSkills, match
from app.service.skill.normalizer import get_dictionary
from app.service.profile.rubric import load_rubric
from app.service.advice.rules import detect_issues

SKILLS_LINE = "专业技能\nJava、Spring Boot、MySQL、Redis、Vue\n"

QUANTIFIED_RESUME = (
    "个人信息\n张三，电话 13800138000\n\n"
    "专业技能\nJava、Spring Boot、MySQL、Redis\n\n"
    "项目经历\n负责订单系统重构，接口耗时从 800ms 降到 120ms，日均 5 万次调用\n\n"
    "工作经历\n2023.07-2024.06 某公司 后端开发工程师\n2024.07-2025.06 另一公司 高级工程师\n"
)


def _report(resume_text: str):
    """构造一个真实的 `MatchReport`（走 `matcher.match()`，不手搓 dataclass）。"""
    dictionary = get_dictionary()
    requirements = (
        Requirement(skill="Java", importance="required", evidence="熟悉 Java", jd_offset=0),
        Requirement(skill="Redis", importance="required", evidence="熟悉 Redis 与缓存", jd_offset=12),
        Requirement(skill="Kafka", importance="preferred", evidence="Kafka 加分", jd_offset=30),
    )
    return match(requirements, ResumeSkills(tuple(dictionary.extract_unique(resume_text))))


# ------------------------------------------------------------------ 判定兜底


def test_verdicts_count_equals_match_count() -> None:
    """N1.2 的完成标准：断 LLM 时 `verdicts` 条数 **= `match` 条数**。

    `match` 是集合级事实的**骨架**，判定只能在这副骨架上判档 ——
    少一条或多一条都说明骨架被穿透了（plan §8 风险 1）。
    """
    report = _report(QUANTIFIED_RESUME)
    verdicts = verdicts_from_match(report)

    assert len(verdicts) == report.total_count
    assert [v.skill for v in verdicts] == [m.skill for m in report.matched] + [
        m.skill for m in report.missing
    ]


def test_every_fallback_verdict_has_nonempty_reason() -> None:
    """每条 `reason` 必须非空 —— 只给结论不给理由等于没判（AC26）。"""
    for verdict in verdicts_from_match(_report(QUANTIFIED_RESUME)):
        assert verdict.reason.strip(), f"{verdict.skill} 的 reason 为空"


def test_fallback_verdicts_follow_match_facts() -> None:
    """判档必须与集合级事实一致：`matched` → `satisfied`，`missing` → `missing`。"""
    report = _report(SKILLS_LINE)                       # 只命中 Java / Redis，缺 Kafka
    by_skill = {v.skill: v for v in verdicts_from_match(report)}

    assert by_skill["Java"].verdict == "satisfied"
    assert by_skill["Redis"].verdict == "satisfied"
    assert by_skill["Kafka"].verdict == "missing"


def test_fallback_verdicts_are_empty_without_match() -> None:
    """没指定岗位（`match` 为 `null`）→ 没有要求可判，返回空列表而不是抛错。"""
    assert verdicts_from_match(None) == []


def test_verdicts_are_deterministic() -> None:
    first = verdicts_from_match(_report(QUANTIFIED_RESUME))
    second = verdicts_from_match(_report(QUANTIFIED_RESUME))

    assert [(v.skill, v.verdict, v.reason) for v in first] == [
        (v.skill, v.verdict, v.reason) for v in second
    ]


# ------------------------------------------------------------------ 六维判档兜底


def test_grade_dimensions_returns_all_six() -> None:
    """**六条一条不少** —— 判不出来的是 `L0`（无证据），不是一个缺失的键。

    少一条会让前端雷达图缺角；而 `L0` 是「诚实地说没证据」，两者含义完全不同。
    """
    rubric = load_rubric()
    facts = ResumeFacts(text=QUANTIFIED_RESUME, skill_count=4)
    grades = grade_dimensions(facts, rubric)

    assert [g.key for g in grades] == [key for key, _ in DIMENSIONS]


def test_grade_level_keys_always_exist_in_rubric() -> None:
    """兜底产出的档位 key 必须**能在 rubric 里查到**，否则 `score` 会变成 `null`。"""
    rubric = load_rubric()
    facts = ResumeFacts(text=QUANTIFIED_RESUME, skill_count=4)

    for grade in grade_dimensions(facts, rubric):
        dimension = rubric.dimension(grade.key)
        assert dimension is not None
        assert grade.level_key in dimension.level_keys
        assert rubric.score_of(grade.key, grade.level_key) is not None


def test_code_only_dimensions_are_computable_without_llm() -> None:
    """`项目影响力` / `成长性` **纯代码可算** —— 断 LLM 也不会六维全 `L0`（spec §2.5①）。

    这正是「降级质量高一档」的落点：没有这两维，断 LLM 后雷达图会是一片空白。
    """
    rubric = load_rubric()
    facts = ResumeFacts(text=QUANTIFIED_RESUME, skill_count=4)
    by_key = {g.key: g for g in grade_dimensions(facts, rubric)}

    for key in CODE_ONLY_DIMENSIONS:
        grade = by_key[key]
        assert grade.level_key != "L0", f"{key} 在量化简历上不应落 L0"
        assert grade.evidence.strip(), f"{key} 有档位却没有证据（AC27）"


def test_impact_shares_evidence_with_no_quantify() -> None:
    """**同源守卫**（spec §2.5.1）：`项目影响力` 与 `NO_QUANTIFY` 必须看**同一批句子**。

    两者是同一件事的两个粒度（issue 定位到句、维度是整体水位）。
    各写一套正则就会漂移 —— 比如这里判「有量化」而那边判「缺量化」。
    """
    rubric = load_rubric()
    text = "项目经历\n负责订单系统重构，配合团队完成交付\n"     # 有动作、无数字
    facts = ResumeFacts(text=text, sections={"projects": "负责订单系统重构，配合团队完成交付"})

    impact = next(g for g in grade_dimensions(facts, rubric) if g.key == "impact")
    issues = detect_issues(text, {"projects": "负责订单系统重构，配合团队完成交付"})

    # 维度说「只有动作」；issue 说「缺量化」—— 同一判断的两个粒度，必须同时成立
    assert impact.level_key == "L1"
    assert any(i.type == IssueType.NO_QUANTIFY for i in issues)
    assert impact.evidence in "负责订单系统重构，配合团队完成交付"


def test_blank_resume_gets_l0_everywhere() -> None:
    """**不编分**（spec §2.5.2 ①）：空简历六维全 `L0`、证据为空。

    宁可整片留空，也不给一个「看起来合理」的分数 —— 编分比留空危险得多。
    """
    rubric = load_rubric()
    grades = grade_dimensions(ResumeFacts(text="", sections={}), rubric)

    assert all(g.level_key == "L0" for g in grades)
    assert all(g.evidence == "" for g in grades)


def test_grading_is_deterministic() -> None:
    """AC30 的前置条件：**同一输入两次判档完全一致**（不抽样、不调模型）。"""
    rubric = load_rubric()
    facts = ResumeFacts(text=QUANTIFIED_RESUME, skill_count=4)

    first = [(g.key, g.level_key, g.evidence) for g in grade_dimensions(facts, rubric)]
    second = [(g.key, g.level_key, g.evidence) for g in grade_dimensions(facts, rubric)]

    assert first == second


# ------------------------------------------------------------------ N3.2 优化点 / 提升方向兜底

GAP_RESUME = (
    "个人信息\n张三，电话 13800138000\n\n"
    "专业技能\nJava、Spring Boot、Redis\n\n"
    "项目经历\n负责订单系统重构，配合团队完成交付\n\n"
    "工作经历\n2023.07-2024.06 某公司 后端开发工程师\n"
)


def _facts() -> ResumeFacts:
    return ResumeFacts(
        text=GAP_RESUME,
        sections={
            "projects": "负责订单系统重构，配合团队完成交付",
            "experience": "2023.07-2024.06 某公司 后端开发工程师",
        },
        skill_count=3,
    )


def _verdicts():
    """简历命中 Java/Redis，缺 Kafka（硬性）与 Docker（加分）。"""
    dictionary = get_dictionary()
    requirements = (
        Requirement(skill="Java", importance="required", evidence="熟悉 Java"),
        Requirement(skill="Redis", importance="required", evidence="熟悉 Redis"),
        Requirement(skill="Kafka", importance="required", evidence="熟悉 Kafka"),
        Requirement(skill="Docker", importance="preferred", evidence="Docker 加分"),
    )
    report = match(requirements, ResumeSkills(tuple(dictionary.extract_unique(GAP_RESUME))))
    return verdicts_from_match(report)


def test_improvements_fallback_is_nonempty_and_every_item_is_actionable() -> None:
    """N3.2：断 LLM 时优化点**非空**，且每条都带 `targets` 与**逐字原文** `evidence`。

    `targets` 是契约硬要求（`required: [area, action, evidence, targets]`）；
    `evidence` 为空等于「让你改，但不告诉你在哪」。
    """
    facts = _facts()
    improvements = improvements_fallback(
        _verdicts(), detect_issues(GAP_RESUME, dict(facts.sections)), facts=facts
    )

    assert improvements, "断 LLM 时优化点不该为空"
    for item in improvements:
        assert item.targets, f"{item.area} 没有 targets"
        assert item.evidence.strip(), f"{item.area} 没有落点"
        assert item.action.strip()
        # 证据必须是简历里真实存在的一行（逐字复制，不是模板拼的）
        assert item.evidence in GAP_RESUME


def test_fallback_advice_contains_no_course_links_or_institutions() -> None:
    """spec §3 禁止项：只给方向与关键词，**不给课程链接、不给机构名**。

    兜底文案全是模板，结构上不可能出现链接 —— 这条断言是为了防「以后有人为了
    『建议更具体』往模板里塞一个 URL」。
    """
    facts = _facts()
    improvements = improvements_fallback(_verdicts(), (), facts=facts)
    directions = directions_fallback(_verdicts())

    blob = " ".join(
        [f"{i.area}{i.action}" for i in improvements] + [f"{d.direction}{d.why}{d.first_step}" for d in directions]
    )
    for token in ("http", "www.", ".com", "课程", "网课", "培训", "机构"):
        assert token not in blob, f"兜底文案里出现了 {token!r}"


def test_directions_are_sorted_by_priority_and_capped() -> None:
    """AC32：按 `priority` 升序、条数 ≤ 5；且**硬性要求排在加分项前面**。"""
    directions = directions_fallback(_verdicts())

    assert directions
    assert [d.priority for d in directions] == list(range(1, len(directions) + 1))
    assert len(directions) <= MAX_GROWTH_DIRECTIONS
    # 排序键是「先硬性后加分、同档按技能名」——Docker 是加分项，必须排在 Kafka 后面
    assert [d.direction.split(" ")[0] for d in directions] == ["Kafka", "Docker"]


def test_directions_respect_max_cap() -> None:
    """条数上限由参数决定，但**不得超过 `MAX_GROWTH_DIRECTIONS`** 这条契约约束时也一样。"""
    assert len(directions_fallback(_verdicts(), max_directions=1)) == 1
    assert directions_fallback(_verdicts(), max_directions=0) == []


def test_issue_area_and_action_maps_cover_every_issue_type() -> None:
    """两个映射必须覆盖 `IssueType` 全集：漏一个不会报错，只会让那类问题在降级时
    没有对应建议（静默丢内容）。**
    """
    from app.schema.response.analyze_response import IssueType
    from app.service.profile.advisor_rules import _ISSUE_ACTION, _ISSUE_AREA

    for issue_type in IssueType:
        assert issue_type.value in _ISSUE_AREA, f"{issue_type.value} 缺 area 文案"
        assert issue_type.value in _ISSUE_ACTION, f"{issue_type.value} 缺 action 文案"


def test_improvements_are_deterministic() -> None:
    facts = _facts()
    issues = detect_issues(GAP_RESUME, dict(facts.sections))

    first = improvements_fallback(_verdicts(), issues, facts=facts)
    second = improvements_fallback(_verdicts(), issues, facts=facts)

    assert [(i.area, i.action, i.evidence, i.targets) for i in first] == [
        (i.area, i.action, i.evidence, i.targets) for i in second
    ]


# ------------------------------------------------------------------ N3.3 rubric 片段裁剪


def test_rubric_slice_is_smaller_than_the_full_rubric() -> None:
    """N3.3：按岗位裁剪后注入的片段**必须比全量小** —— 否则「裁剪」没发生，
    只是白白多了一层代码（plan §8 风险 5：整套 rubric 塞 prompt 会留出更多自由发挥空间）。
    """
    import json

    rubric = load_rubric()
    all_keys = [key for key, _ in DIMENSIONS]
    sliced = rubric.slice_for(["tech_depth", "engineering", "business"])

    assert len(sliced) == 3
    assert len(json.dumps(sliced, ensure_ascii=False)) < len(
        json.dumps(rubric.slice_for(all_keys), ensure_ascii=False)
    )


def test_slice_only_returns_requested_dimensions_in_order() -> None:
    rubric = load_rubric()

    sliced = rubric.slice_for(["business", "tech_depth", "business"])

    assert [item["key"] for item in sliced] == ["business", "tech_depth"]


def test_code_only_dimensions_are_not_injected_into_the_prompt() -> None:
    """`项目影响力` / `成长性` 是**纯代码算**的（spec §2.5①），不占 prompt 预算。"""
    from app.service.profile.rubric import dimension_keys_for_requirements

    keys = dimension_keys_for_requirements([Requirement(skill="Java", importance="required")])

    assert keys
    assert "impact" not in keys and "growth" not in keys
    assert "tech_depth" in keys


def test_no_requirements_means_no_rubric_slice() -> None:
    """没选岗位 → 没有要求 → 不需要给模型看 rubric（省一次无效注入）。"""
    from app.service.profile.rubric import dimension_keys_for_requirements

    assert dimension_keys_for_requirements([]) == []
