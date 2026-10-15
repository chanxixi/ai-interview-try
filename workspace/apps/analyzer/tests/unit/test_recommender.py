"""Top-N 岗位推荐（M3.4 / M3.6）。

两条硬验收落在这里：

- **AC16 确定性**：同一份简历连续推荐两次，`jobId` 序列与各自 `score` 完全一致。
  排序键 `(-score, jobId)` 里的 `jobId` 兜底是关键 —— 同分时若用 `title` 排序，
  改个标题就会让推荐顺序变化，而那正是「不可复现」的定义。
- **AC17 排序与条数**：按 score 降序；条数 = `min(3, 候选总数)`。

另外钉死一条**架构约束**：推荐不许自己算分。`recommender` 只调 `matcher.match()`，
所以「`match.score` 与推荐里同一个岗位的分数不一致」这种事故在结构上不可能发生。
"""

from __future__ import annotations

import pytest

from app.service.matcher import Requirement, ResumeSkills, SkillMention, match
from app.service.recommender import (
    JobCandidate,
    build_reason,
    recommend,
)


def mention(canonical: str, raw: str | None = None, offset: int = 0) -> SkillMention:
    return SkillMention(raw=raw or canonical, canonical=canonical, category="tool", offset=offset)


def candidate(job_id: str, *skills: tuple[str, str]) -> JobCandidate:
    """`skills` 是 `(skill, importance)` 对，按给定顺序成为该岗位的要求。"""
    return JobCandidate(
        jobId=job_id,
        title=f"岗位 {job_id}",
        company="某公司",
        level="校招",
        requirements=tuple(Requirement(skill=s, importance=i) for s, i in skills),
    )


@pytest.fixture
def java_resume() -> ResumeSkills:
    """一份「会 Java / Spring Boot / MySQL，不会 Redis」的简历。"""
    return ResumeSkills((mention("Java"), mention("Spring Boot"), mention("MySQL")))


# ------------------------------------------------------------------ 排序（AC17）


def test_recommendations_sorted_by_score_descending(java_resume: ResumeSkills) -> None:
    """分数降序。三个岗位的期望分数可以手算：

    - A：要求 Java(req) + Redis(req)          → 命中 1/2 → 1.0/2.0 → 50
    - B：要求 Java(req) + Docker(preferred)   → 命中 1/1.5 → 0.667 → 67
    - C：要求 Go(req)                          → 命中 0/1 → 0
    """
    candidates = [
        candidate("job-a", ("Java", "required"), ("Redis", "required")),
        candidate("job-b", ("Java", "required"), ("Docker", "preferred")),
        candidate("job-c", ("Go", "required")),
    ]

    recommendations = recommend(candidates, java_resume)

    assert [r.jobId for r in recommendations] == ["job-b", "job-a", "job-c"]
    assert [r.score for r in recommendations] == [67, 50, 0]


def test_ties_broken_by_job_id_ascending(java_resume: ResumeSkills) -> None:
    """同分按 `jobId` 字典序升序 —— 这是 AC16 确定性的兜底保证。

    故意用**乱序传入**候选：如果排序不稳定，`job-c` 会排在 `job-a` 前面。
    """
    candidates = [
        candidate("job-c", ("Java", "required")),
        candidate("job-a", ("Java", "required")),
        candidate("job-b", ("Java", "required")),
    ]

    recommendations = recommend(candidates, java_resume)

    assert [r.jobId for r in recommendations] == ["job-a", "job-b", "job-c"]
    assert {r.score for r in recommendations} == {100}


def test_count_is_min_of_top_n_and_candidates(java_resume: ResumeSkills) -> None:
    """条数 = `min(N, 候选总数)`（spec §2.6）。"""
    two = [candidate("job-a", ("Java", "required")), candidate("job-b", ("Go", "required"))]
    assert len(recommend(two, java_resume)) == 2

    assert len(recommend([], java_resume)) == 0
    assert len(recommend(two, java_resume, top_n=1)) == 1
    assert len(recommend(two, java_resume, top_n=99)) == 2


# ------------------------------------------------------------------ 确定性（AC16）


def test_recommendations_are_deterministic(java_resume: ResumeSkills) -> None:
    """AC16：同一输入两次推荐，`jobId` 序列与各自 score 完全一致。

    这里连候选的**传入顺序**都故意和第二遍不同 —— 排序必须与输入顺序无关，
    否则「Java 装配候选集时换了条 SQL 顺序」就会让推荐结果变化。
    """
    pool = [
        candidate("job-a", ("Java", "required"), ("Redis", "required")),
        candidate("job-b", ("Java", "required"), ("Docker", "preferred")),
        candidate("job-c", ("Go", "required"), ("Kafka", "required")),
    ]

    first = recommend(pool, java_resume)
    second = recommend(list(reversed(pool)), java_resume)

    assert [(r.jobId, r.score) for r in first] == [(r.jobId, r.score) for r in second]
    assert [(r.jobId, r.score) for r in first] == [("job-b", 67), ("job-a", 50), ("job-c", 0)]


def test_recommendation_score_equals_match_score(java_resume: ResumeSkills) -> None:
    """推荐里的分数必须等于 `matcher.match()` 对同一岗位算出的分数。

    这条是「推荐不自己算分」的回归测试：将来若有人在 `recommender` 里另写一套公式，
    这里会立刻红。
    """
    target = candidate("job-a", ("Java", "required"), ("Redis", "required"))
    recommendations = recommend([target, candidate("job-z", ("Go", "required"))], java_resume)

    assert recommendations[0].jobId == "job-a"
    assert recommendations[0].score == match(target.requirements, java_resume).score


# ------------------------------------------------------------------ reason 模板


def test_reason_template_with_gaps() -> None:
    """`reason` 与 spec §2.3 的示例逐字同构：`命中 5/7 项要求，缺口为 Redis、Docker`。"""
    target = candidate(
        "job-x",
        ("Java", "required"),
        ("Spring Boot", "required"),
        ("MySQL", "required"),
        ("Redis", "required"),
        ("Docker", "required"),
        ("Kafka", "required"),
        ("LLM", "preferred"),
    )
    resume = ResumeSkills(
        (mention("Java"), mention("Spring Boot"), mention("MySQL"), mention("Redis"), mention("Docker"))
    )

    recommendation = recommend([target], resume)[0]

    assert recommendation.reason == "命中 5/7 项要求，缺口为 Kafka、LLM"


def test_reason_template_without_gaps() -> None:
    target = candidate("job-x", ("Java", "required"))
    recommendation = recommend([target], ResumeSkills((mention("Java"),)))[0]

    assert recommendation.reason == "命中 1/1 项要求，无缺口"
    assert recommendation.score == 100


def test_reason_for_job_without_requirements() -> None:
    """0 技能岗位要有句人能懂的话，而不是「命中 0/0 项要求」。"""
    recommendation = recommend([candidate("job-empty")], ResumeSkills((mention("Java"),)))[0]

    assert recommendation.reason == "该岗位未设置技能要求"
    assert recommendation.score == 0


def test_build_reason_counts_skills_not_weights() -> None:
    """`命中 h/t 项` 数的是**技能条数**，不是权重 ——
    写成「命中 5/6.5 项」没人看得懂。"""
    target = candidate("job-x", ("Java", "required"), ("Docker", "preferred"))
    report = match(target.requirements, ResumeSkills((mention("Java"),)))

    assert report.hit_weight == 1.0 and report.total_weight == 1.5
    assert build_reason(report) == "命中 1/2 项要求，缺口为 Docker"


# ------------------------------------------------------------------ 摘要形状（spec §2.3）


def test_recommendation_keeps_only_summary(java_resume: ResumeSkills) -> None:
    """推荐内的 matched/missing 只保留摘要，**不含双向证据**（体积考虑）。

    完整证据在 `match` 块里。这条断言同时是一道「别把大对象塞进推荐」的护栏。
    """
    target = candidate("job-x", ("Java", "required"), ("Redis", "required"))
    recommendation = recommend([target], java_resume)[0]

    hit = recommendation.matched[0]
    assert hit.skill == "Java"
    assert hit.importance == "required"
    assert not hasattr(hit, "jd_evidence")
    assert not hasattr(hit, "resume_evidence")

    gap = recommendation.missing[0]
    assert gap.skill == "Redis"
    assert gap.importance == "required"
    assert gap.suggestion            # 建议必须非空


def test_recommendation_carries_job_metadata(java_resume: ResumeSkills) -> None:
    target = JobCandidate(
        jobId="job-x",
        title="Java 后端开发工程师",
        company="某科技",
        level="校招",
        category="tech-backend",
        requirements=(Requirement(skill="Java", importance="required"),),
    )

    recommendation = recommend([target], java_resume)[0]

    assert recommendation.jobId == "job-x"
    assert recommendation.title == "Java 后端开发工程师"
    assert recommendation.company == "某科技"
    assert recommendation.level == "校招"


def test_recommendation_is_a_frozen_dataclass(java_resume: ResumeSkills) -> None:
    recommendation = recommend([candidate("job-x", ("Java", "required"))], java_resume)[0]

    with pytest.raises(Exception):
        recommendation.score = 1  # type: ignore[misc]
