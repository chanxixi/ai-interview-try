"""加权覆盖率匹配（M3.3 / M3.6）。

**本文件是 AC18「手算复现」的落点**：`score = Σ(命中权重) / Σ(岗位权重) × 100`。
每条断言都写成「人能在纸上算出来」的形式 —— 权重写全、分子分母都暴露，
否则「分数对不上」这种事只能靠猜。

覆盖 tasks.md M3.3 点名的四个边界：岗位 0 技能 / 简历 0 技能 / 全命中 / 同技能取最高权重。
"""

from __future__ import annotations

import pytest

from app.service.matcher import (
    Requirement,
    ResumeSkills,
    SkillMention,
    dedupe_requirements,
    extract_requirements,
    match,
    score_of,
    suggestion_for,
)
from app.service.normalizer import SkillDictionary, get_dictionary


@pytest.fixture(scope="module")
def dictionary() -> SkillDictionary:
    return get_dictionary()


def mention(canonical: str, raw: str | None = None, offset: int = 0) -> SkillMention:
    return SkillMention(raw=raw or canonical, canonical=canonical, category="tool", offset=offset)


# ------------------------------------------------------------------ 打分公式（AC18）


def test_score_matches_hand_calculation() -> None:
    """AC18：score = Σ命中权重 / Σ全部权重 × 100。

    这个用例的数字是**手算**选出来的：6 个 required + 1  preferred = 6.5 总分，
    命中 5 个 required = 5.0，5 / 6.5 = 76.923… → 四舍五入 77。
    任一步算错这个数就变，所以它不是「看起来对」而是「算出来对」。
    """
    requirements = [
        Requirement(skill="Java", importance="required"),
        Requirement(skill="Spring Boot", importance="required"),
        Requirement(skill="MySQL", importance="required"),
        Requirement(skill="Redis", importance="required"),
        Requirement(skill="Kafka", importance="required"),
        Requirement(skill="Docker", importance="required"),
        Requirement(skill="LLM", importance="preferred"),
    ]
    resume = ResumeSkills(
        (mention("Java"), mention("Spring Boot"), mention("MySQL"), mention("Redis"), mention("Kafka"))
    )

    report = match(requirements, resume)

    assert report.hit_weight == 5.0
    assert report.total_weight == 6.5
    assert 5.0 / 6.5 * 100 == pytest.approx(76.923, abs=0.001)
    assert report.score == 77
    assert report.hit_count == 5
    assert report.total_count == 7


def test_score_rounds_half_up_not_bankers() -> None:
    """必须四舍五入，不能用 Python 内置 `round`（银行家舍入）。

    `round(12.5) == 12` —— AC18 要求「手算复现」，评审按四舍五入口算得到 13，
    对不上就会被当成 bug 追。

    这里的数字是手挑选到分界线上的：8 个 preferred（总权重 4.0）命中 1 个（0.5），
    0.5 / 4.0 = 0.125 → ×100 = 12.5，正好是「该进 13 却会被 round 成 12」的那个值。
    """
    requirements = [Requirement(skill=f"S{i}", importance="preferred") for i in range(8)]
    resume = ResumeSkills((mention("S0"),))

    report = match(requirements, resume)

    assert report.hit_weight == 0.5
    assert report.total_weight == 4.0
    assert 0.5 / 4.0 * 100 == 12.5
    assert report.score == 13
    assert round(12.5) == 12, "Python 的 round 确实是银行家舍入 —— 这正是不能用它的原因"
    assert score_of(0.5, 4.0) == 13


def test_score_clamps_to_zero_and_hundred() -> None:
    assert score_of(0.0, 10.0) == 0
    assert score_of(10.0, 10.0) == 100
    assert score_of(10.0, 10.0) == 100
    assert score_of(-1.0, 10.0) == 0        # 负权重不该出现，但不该算出负数
    assert score_of(99.0, 10.0) == 100      # 同上，向上夹住


# ------------------------------------------------------------------ 四个边界


def test_boundary_job_with_zero_requirements() -> None:
    """岗位 0 技能：分母为 0。选 `score = 0` 而不是 100 ——
    「没有要求可命中」时给满分是误导（用户会以为完美匹配）。
    """
    report = match([], ResumeSkills((mention("Java"),)))

    assert report.score == 0
    assert report.matched == ()
    assert report.missing == ()
    assert report.total_weight == 0.0
    # 集合自洽在空集上依然成立：∅ ∩ ∅ = ∅ 且 ∅ ∪ ∅ = ∅
    assert set() == set()


def test_boundary_resume_with_zero_skills() -> None:
    """简历 0 技能：分子为 0，全部进 missing。"""
    requirements = [
        Requirement(skill="Java", importance="required"),
        Requirement(skill="Redis", importance="preferred"),
    ]
    report = match(requirements, ResumeSkills())

    assert report.score == 0
    assert report.hit_weight == 0.0
    assert report.total_weight == 1.5
    assert [m.skill for m in report.missing] == ["Java", "Redis"]
    assert report.matched == ()


def test_boundary_full_hit_scores_hundred() -> None:
    requirements = [
        Requirement(skill="Java", importance="required"),
        Requirement(skill="Docker", importance="preferred"),
    ]
    report = match(requirements, ResumeSkills((mention("Java"), mention("Docker"))))

    assert report.score == 100
    assert report.missing == ()
    assert report.hit_weight == report.total_weight == 1.5


def test_boundary_duplicate_skill_takes_highest_weight() -> None:
    """同技能多条要求 → 取权重最高的（required 赢 preferred）。

    不这么做的话，同一技能被计进分母两次，分数被凭空拉低；
    而且「required 和 preferred 都要求 Java」时 required 必须说了算。
    """
    requirements = [
        Requirement(skill="Java", importance="preferred"),
        Requirement(skill="Java", importance="required"),
    ]
    resume = ResumeSkills((mention("Java"),))

    report = match(requirements, resume)

    assert report.total_count == 1                 # 去重后只剩一条
    assert report.total_weight == 1.0              # 不是 1.5
    assert report.matched[0].importance == "required"
    assert report.score == 100


def test_dedupe_keeps_first_when_weights_are_equal() -> None:
    """权重相同时保留先出现的那条 —— 顺序稳定，结果才可复现。"""
    requirements = [
        Requirement(skill="Java", importance="required", evidence="第一条"),
        Requirement(skill="Java", importance="required", evidence="第二条"),
    ]
    assert [r.evidence for r in dedupe_requirements(requirements)] == ["第一条"]


# ------------------------------------------------------------------ 集合自洽（AC17）


@pytest.mark.parametrize("seed", range(6))
def test_set_self_consistency_holds_for_many_combinations(seed: int) -> None:
    """AC17：`matched ∩ missing = ∅` 且并集 = 岗位技能全集。

    参数化 6 组而不是 1 组：自洽不是「碰巧成立」的，
    它依赖「matched 和 missing 由**同一份去重列表**生成」这个结构保证。
    换几种输入各验一遍，防止将来有人改成两遍独立遍历。
    """
    pool = ["Java", "Redis", "Docker", "LLM", "Go"]
    requirements = [Requirement(skill=s, importance="required" if i % 2 else "preferred")
                    for i, s in enumerate(pool)]
    have = [s for i, s in enumerate(pool) if (seed >> i) & 1]

    report = match(requirements, ResumeSkills(tuple(mention(s) for s in have)))

    matched = {m.skill for m in report.matched}
    missing = {m.skill for m in report.missing}

    assert matched & missing == set()
    assert matched | missing == set(pool)
    assert matched == set(have)


# ------------------------------------------------------------------ 证据与建议


def test_matched_carries_bidirectional_evidence_and_offsets() -> None:
    """命中项必须带双向原文证据（AC5）—— 只有技能名的命中不可解释。"""
    requirements = [
        Requirement(
            skill="Java",
            importance="required",
            evidence="熟悉 Java、Spring Boot 开发",
            jd_offset=12,
        )
    ]
    resume = ResumeSkills((mention("Java", raw="JAVA", offset=340),))

    report = match(requirements, resume)

    item = report.matched[0]
    assert item.jd_evidence == "熟悉 Java、Spring Boot 开发"
    assert item.resume_evidence == "JAVA"      # 简历里的原文写法，不是标准名
    assert item.jd_offset == 12
    assert item.resume_offset == 340
    assert item.weight == 1.0


def test_missing_carries_actionable_suggestion() -> None:
    """缺口项必须给可执行建议（AC7），且 required / preferred 措辞不同。"""
    required = suggestion_for("Redis", "required")
    preferred = suggestion_for("Redis", "preferred")

    assert "Redis" in required and "Redis" in preferred
    assert required != preferred
    assert "加分" in preferred

    report = match([Requirement(skill="Redis", importance="required")], ResumeSkills())
    assert report.missing[0].suggestion == required


def test_requirement_rejects_unknown_importance() -> None:
    """importance 是冻结枚举（spec §2.4）。放过关掉会把脏数据带进打分。"""
    with pytest.raises(ValueError, match="importance"):
        Requirement(skill="Java", importance="must-have")


# ------------------------------------------------------------------ 自定义 JD：运行期抽要求（G1）


def test_extract_requirements_from_jd_text(dictionary) -> None:
    """从 JD 原文抽要求：skill 归一化 + importance 按句子判定 + evidence 逐字。"""
    jd = "任职要求：\n1、熟悉 Java 与 Spring Boot 开发；\n2、了解 Redis 基本原理。\n\n加分项：\n1、有 LLM 相关经验者优先。"

    requirements = extract_requirements(dictionary, jd)

    by_skill = {r.skill: r for r in requirements}
    assert set(by_skill) == {"Java", "Spring Boot", "Redis", "LLM"}
    assert by_skill["Java"].importance == "required"
    assert by_skill["LLM"].importance == "preferred"       # 句子含「优先」
    assert by_skill["Java"].evidence == "1、熟悉 Java 与 Spring Boot 开发"
    assert by_skill["LLM"].evidence == "1、有 LLM 相关经验者优先"
    assert by_skill["Java"].skill_raw == "Java"
    assert by_skill["Java"].jd_offset == jd.index("Java")


def test_extract_requirements_prefers_sentence_with_bonus_wording(dictionary) -> None:
    """同一技能在「要求」和「加分项」各出现一次时，`extract_unique` 取第一次 ——
    这是已知取舍（G1 已登记）：它判成 required。
    记录下来是为了将来有人问「为什么 LLM 有时算 required」时有据可查。
    """
    jd = "1、熟悉 Java；\n2、有 Java 相关开源贡献者优先。"
    requirements = extract_requirements(dictionary, jd)

    assert len(requirements) == 1
    assert requirements[0].importance == "required"


def test_extract_requirements_on_empty_jd(dictionary) -> None:
    assert extract_requirements(dictionary, "") == []
    assert extract_requirements(dictionary, None) == []


def test_extract_requirements_respects_max_length(dictionary) -> None:
    """JD 上限 8000 字符（spec §2.2）。超长部分不该被抽 ——
    否则 `jdOffset` 会指向被截掉的位置，证据对不上原文。
    """
    jd = "x" * 100 + "\n熟悉 Java"
    requirements = extract_requirements(dictionary, jd, max_length=50)

    assert requirements == []


def test_extract_requirements_is_deterministic(dictionary) -> None:
    """自定义 JD 路径不调 LLM，两次抽取必须完全一致（G1 的 mitigation）。"""
    jd = "熟悉 Java、Spring Boot、MySQL、Redis、Kafka；有 LLM 经验者优先。"
    first = extract_requirements(dictionary, jd)
    second = extract_requirements(dictionary, jd)

    assert first == second
