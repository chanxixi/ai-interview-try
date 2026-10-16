"""逐条判定与六维判档的**规则兜底**（part3 N1.2 / plan §5）。

## 它存在的理由

part3 的两个新结论（`verdicts` / `abilityProfile`）由 LLM 判档，而 LLM 会超时、会返回非法 JSON、
会整个不可用。spec §2.6 说降级时四块退化为**规则兜底**，`result` 与 `done` 照常 —— 就是这里。

## 三条设计约束（与 `rules.py` 同一取向）

1. **纯确定性**：同一份输入两次调用结果完全一致。不抽样、不调模型。
2. **宁可漏不可编**：判不出来就落 `L0`，绝不为了「画像好看」硬凑一个分数（spec §2.5.2 ①）。
3. **判据唯一**：`项目影响力` / `成长性` 两维的判据**复用 `rules.py` 的同源原语**
   （`quantify_facts` / `time_spans`），禁止在别处再写一套数字正则或时间正则 ——
   同一件事有两套判据必然漂移（spec §2.5.1 / plan §8 风险 9）。

## 兜底档位为什么比 LLM 粗（**已知且接受**）

它只看词与结构，读不懂语义：「主导了订单系统的重构」与「主导了团建活动」在正则里都是
「主导」命中。所以兜底档位的定位是**「断 LLM 时不至于空白」**，不是「与 LLM 等价」。
按岗位裁剪的 rubric 片段注入模型才是主路径（`rubric.py:slice_for`）。
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence
from app.core.constants import MAX_GROWTH_DIRECTIONS, VERDICT_KINDS
from app.schema.response.analyze_response import Issue
from app.service.match.matcher import MatchReport
from app.service.profile.rubric import Dimension, Rubric
from app.service.advice.rules import quantify_facts, sentences, time_spans

# ---------------------------------------------------------------- 事实与结果类型


@dataclass(frozen=True)
class ResumeFacts:
    """兜底判档需要的简历侧事实。**只读**，构造一次传下去。

    `skill_count` 单独传而不是从 `text` 里再扫一遍：技能识别是 `normalizer` 的职责，
    这里复算等于两套分词（`rules.py` 的注释里已经为同一类问题踩过一次）。
    """

    text: str
    sections: Mapping[str, str] = field(default_factory=dict)
    skill_count: int = 0


@dataclass(frozen=True)
class VerdictFact:
    """一条逐条判定（**内部类型**，不是契约模型）。"""

    skill: str
    importance: str
    verdict: str
    reason: str
    jd_evidence: str | None = None
    resume_evidence: str = ""


@dataclass(frozen=True)
class DimensionGrade:
    """一个维度的判档结果（**内部类型**）。分数不在这里 —— 档位 → 分数由 `rubric` 查表。"""

    key: str
    level_key: str
    evidence: str
    reason: str


@dataclass(frozen=True)
class ImprovementFact:
    """一条优化点（**内部类型**）。字段与契约 `Improvement` 对应。"""

    area: str
    action: str
    evidence: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class DirectionFact:
    """一条提升方向（**内部类型**）。`priority` 越小越靠前，**排序由代码定**（spec §2.7）。"""

    direction: str
    why: str
    first_step: str
    priority: int = 1


# ---------------------------------------------------------------- 文案模板

_VERDICT_SATISFIED = "satisfied"
_VERDICT_MISSING = "missing"

_REASON_SATISFIED = "简历中出现「{evidence}」，与该要求相符"
_REASON_SATISFIED_PLAIN = "简历中出现了 {skill} 的相关证据"
_REASON_MISSING = "简历中未见 {skill} 相关证据，该岗位{label}此项"

_IMPORTANCE_LABEL = {"required": "要求", "preferred": "加分项"}

#: 证据片段的截断长度。**只截断不改写** —— 「逐字复制」的承诺不能破。
_SNIPPET_LIMIT = 40

#: 协作沟通的「规模」信号：出现 `5 人` / `3 名` 这类带人数的写法。
_TEAM_SIZE_RE = re.compile(r"\d+\s*(?:人|名)")


def _snippet(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    cleaned = " ".join(text.split()).strip()
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def _hits(text: str, words: Sequence[str]) -> list[str]:
    return [word for word in words if word and word in text]


def _first_line(text: str) -> str:
    for line in (text or "").split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _sentence_with(text: str, word: str) -> str:
    for sentence in sentences(text):
        if word in sentence:
            return sentence
    return ""


# ---------------------------------------------------------------- 判定兜底（N1.2）


def verdicts_from_match(report: MatchReport | None) -> list[VerdictFact]:
    """把 `match` 的**集合级事实**翻译成逐条判定（降级路径的骨架）。

    - `match.matched` → `satisfied`，证据取 `resumeEvidence`（原文片段）
    - `match.missing` → `missing`，`jdEvidence` 为 `None`
      （`MissingSkill` 不携带 JD 证据 —— 契约里 `Verdict.jdEvidence` 本就允许为 `null`）

    **顺序即 `match()` 内部的去重顺序**（JD 要求的原序），两次调用完全一致（AC30）。
    没指定岗位（`report is None`）时返回空列表：没有要求，就没有「逐条判定」可谈。
    """
    if report is None:
        return []

    facts: list[VerdictFact] = []
    for item in report.matched:
        evidence = item.resume_evidence.strip()
        reason = (
            _REASON_SATISFIED.format(evidence=_snippet(evidence))
            if evidence
            else _REASON_SATISFIED_PLAIN.format(skill=item.skill)
        )
        facts.append(
            VerdictFact(
                skill=item.skill,
                importance=item.importance,
                verdict=_VERDICT_SATISFIED,
                reason=reason,
                jd_evidence=item.jd_evidence or None,
                resume_evidence=evidence,
            )
        )

    for item in report.missing:
        facts.append(
            VerdictFact(
                skill=item.skill,
                importance=item.importance,
                verdict=_VERDICT_MISSING,
                reason=_REASON_MISSING.format(
                    skill=item.skill, label=_IMPORTANCE_LABEL.get(item.importance, "要求")
                ),
                jd_evidence=None,
                resume_evidence="",
            )
        )
    return facts


# ---------------------------------------------------------------- 六维判档兜底（N1.2）

#: 兜底判档的「第几档」口径说明
#:
#: 各 `_tier_*` 一律返回**档位序号**（0 起），由 `Dimension.level_at()` 映射到具体档位。
#: 用序号而不是硬编码 `"L3"`：`rubric.yaml` 里多插一档时兜底逻辑不用改（AC31）。
#:
#: 上限统一到「第 3 档」——
#: `技术深度` 有 `L4`（原理 / 选型权衡 / 线上故障定位），那需要读懂语义，
#: 纯正则判不出来；硬凑 `L4` 就是「编分」。**够不到就停在能证明的那一档。**

_TIER_TOP = 3


def _tier_by_signals(dimension: Dimension, text: str, *, fallback_when_skills: int = 0) -> tuple[int, str, str]:
    """按 `signals` 命中数判档（`技术深度` / `工程能力` / `业务理解` 三维共用）。

    规则（粗，但**确定性**）：
    - `strong` 命中 ≥2 → 第 3 档
    - `strong` 命中 =1 → 第 2 档
    - `weak` 命中 ≥1（或简历里认出了技能名词）→ 第 1 档
    - 都没有 → 第 0 档（无证据）
    """
    strong = _hits(text, dimension.strong_signals)
    if len(strong) >= 2:
        word = strong[0]
        return _TIER_TOP, _sentence_with(text, word), f"命中 {len(strong)} 项「{dimension.name}」强信号（如「{word}」）"
    if len(strong) == 1:
        word = strong[0]
        return 2, _sentence_with(text, word), f"命中「{dimension.name}」强信号「{word}」"
    weak = _hits(text, dimension.weak_signals)
    if weak:
        word = weak[0]
        return 1, _sentence_with(text, word), f"仅有「{word}」这类自述，未见具体证据"
    if fallback_when_skills:
        return 1, "", f"简历列出 {fallback_when_skills} 项技能，但没有任何实现或优化的描述"
    return 0, "", "简历里找不到与该维度相关的任何证据"


def _tier_tech_depth(dimension: Dimension, facts: ResumeFacts) -> tuple[int, str, str]:
    """`技术深度`：额外接受「只列了技术名词」这一档（rubric 的 `L1` 提示词明确写了它）。

    「只有名词」时的证据取**技能章节的首行**（逐字原文）。不给证据就落档 ——
    这是 AC27 的要求：**没有出处的分数不允许出现**（在 `grade_dimension` 里还有一道总闸）。
    """
    tier, evidence, reason = _tier_by_signals(
        dimension, facts.text, fallback_when_skills=facts.skill_count
    )
    if tier > 0 and not evidence:
        evidence = _first_line(facts.sections.get("skills") or "")
    return tier, evidence, reason


def _tier_collaboration(dimension: Dimension, facts: ResumeFacts) -> tuple[int, str, str]:
    """`协作沟通`：角色词 + **团队规模** 才算第 3 档（rubric 的 L3 提示词）。

    ⚠️ 这一维**天生弱证据**：简历里常常只有「团队协作能力强」。落 `L0` 是**常态，不是缺点**
    （spec §2.5.2 ①），所以这里绝不为了雷达图好看而抬高。
    """
    strong = _hits(facts.text, dimension.strong_signals)
    weak = _hits(facts.text, dimension.weak_signals)
    if strong and _TEAM_SIZE_RE.search(facts.text):
        word = strong[0]
        return _TIER_TOP, _sentence_with(facts.text, word), f"出现协作角色词「{word}」并给出团队规模"
    if strong:
        word = strong[0]
        return 2, _sentence_with(facts.text, word), f"出现协作角色词「{word}」"
    if weak:
        word = weak[0]
        return 1, _sentence_with(facts.text, word), f"仅有「{word}」这类自述，无可查的协作事实"
    return 0, "", "简历里没有任何可查的协作证据"


def _tier_impact(dimension: Dimension, facts: ResumeFacts) -> tuple[int, str, str]:
    """`项目影响力`：**纯代码算**（spec §2.5①）—— 量化 + 规模。

    判据来自 `rules.quantify_facts`（与 `_check_no_quantify` 同源），所以
    「缺量化」这条 issue 与这一维永远指向**同一批句子**，只是粒度不同
    （issue 定位到句、维度是整体水位；spec §2.5.1）。
    """
    quantify = quantify_facts(facts.text, dict(facts.sections))
    if quantify.scaled:
        return _TIER_TOP, _snippet(quantify.scaled[0]), "量化结果中出现了规模（量级 / 吞吐 / 人数）"
    if quantify.numbered:
        return 2, _snippet(quantify.numbered[0]), "给出了量化结果（数字 / 百分比 / 耗时）"
    if quantify.action:
        return 1, _snippet(quantify.action[0]), "只有动作描述，没有任何量化结果"
    return 0, "", "简历里没有可判定的「做了什么、结果如何」"


def _tier_growth(dimension: Dimension, facts: ResumeFacts) -> tuple[int, str, str]:
    """`成长性`：**纯代码算**（spec §2.5①）—— 时间线递进。

    判据来自 `rules.time_spans`（与 `_check_timeline_gap` 同源正则），所以
    「时间线重叠」那条 issue 与这一维永远看的是同一批区间。
    """
    spans = time_spans(facts.text)
    strong = _hits(facts.text, dimension.strong_signals)
    if len(strong) >= 2:
        word = strong[0]
        return _TIER_TOP, _sentence_with(facts.text, word), f"出现 {len(strong)} 项职责 / 技术栈演进信号（如「{word}」）"

    # 「时间线连续」= 区间按序排列且互不重叠。与 `_check_timeline_gap` 的重叠判据同源。
    ordered = sorted((span.start, span.end, span.raw) for span in spans)
    continuous = len(ordered) >= 2 and all(
        nxt[0] >= prev[1] for prev, nxt in zip(ordered, ordered[1:])
    )
    if continuous:
        return 2, ordered[0][2], f"时间线连续（{len(ordered)} 段经历无断档）"
    if ordered:
        return 1, ordered[0][2], "有经历但看不出难度递进"
    return 0, "", "简历里没有可读的时间线，看不出成长轨迹"


#: 维度 key → 兜底判档策略。**没上榜的维度走 `_tier_by_signals`**。
#:
#: 只列三个特例：两维纯代码（`impact` / `growth`）与一维需要「角色词 + 团队规模」（`collaboration`）。
#: 其余维度的判据都能用「强信号个数」表达，没必要各写一份。
_TIER_STRATEGIES = {
    "tech_depth": _tier_tech_depth,
    "collaboration": _tier_collaboration,
    "impact": _tier_impact,
    "growth": _tier_growth,
}

#: 纯代码可算的两维（断 LLM 也照常出档 —— spec §2.5① 的「直接好处」）。
CODE_ONLY_DIMENSIONS: tuple[str, ...] = ("impact", "growth")


def grade_dimension(dimension: Dimension, facts: ResumeFacts) -> DimensionGrade:
    """给一个维度判档。**永远返回一个档位**（最差是第 0 档「无证据」）。

    末尾有一道**总闸**：档位 > 0 却拿不出任何原文片段时，**降回第 0 档**。
    因为 AC27 是「无出处的分数不允许出现」—— 各 `_tier_*` 已经尽力取证据了，
    但它们是启发式的，将来有人加一条策略忘了带证据，这道闸就是最后一道防线。
    宁可少给一档，也不给一个查不到出处的分。
    """
    strategy = _TIER_STRATEGIES.get(dimension.key)
    if strategy is None:
        tier, evidence, reason = _tier_by_signals(dimension, facts.text)
    else:
        tier, evidence, reason = strategy(dimension, facts)

    if tier > 0 and not (evidence or "").strip():
        tier = 0
        reason = "找不到可引用的原文片段，按无证据处理"

    level = dimension.level_at(tier)
    return DimensionGrade(
        key=dimension.key,
        level_key=level.key,
        evidence=evidence.strip() if tier > 0 else "",
        reason=reason,
    )


def grade_dimensions(facts: ResumeFacts, rubric: Rubric) -> list[DimensionGrade]:
    """六维全判。顺序 = `rubric.yaml` 的顺序 = 雷达图顺序（`constants.DIMENSIONS`）。

    **返回六条，一条不少** —— 判不出来的是第 0 档（`L0`「无证据」），不是一个缺失的键。
    契约要求 `dimensions` 是稳定六元组；少一条会让前端雷达图缺角。
    """
    return [grade_dimension(dimension, facts) for dimension in rubric.dimensions]


# ---------------------------------------------------------------- LLM 结果的合并策略（ADR-205）

#: 用 Protocol 而不是 import `llm.client` 的具体类型：
#: `advisor_rules` 的定位是「**不调 LLM** 的规则层」，让它去 import LLM 客户端会
#: 把依赖方向倒过来（规则层反而不该知道模型长什么样）。结构对了就能合并。


class VerdictLike(Protocol):
    skill: str
    verdict: str
    reason: str
    resume_evidence: str


class DimensionLike(Protocol):
    key: str
    level: str
    reason: str
    evidence: str


def merge_verdicts(
    seeds: Sequence[VerdictFact], llm_verdicts: Sequence[VerdictLike] | None
) -> list[VerdictFact]:
    """把 LLM 的判定**覆盖到集合级骨架之上**。

    两条不可谈判的规则（plan §8 风险 1）：

    1. **LLM 只能改既有条目** —— 骨架来自 `match`，不在骨架里的 `skill` 一律忽略。
       否则会出现「AI 说这人有 Kubernetes」而词典根本没命中，两边永远对不上。
    2. **`importance` 永远来自 `match`** —— 「这条是硬性还是加分」是岗位数据，
       不是模型判断。

    LLM 给的档位不合法或理由为空时，**该条退回兜底**（而不是丢掉）：
    骨架的完整性优先于「用了模型的答案」。
    """
    by_skill: dict[str, VerdictLike] = {item.skill: item for item in (llm_verdicts or ())}

    merged: list[VerdictFact] = []
    for seed in seeds:
        got = by_skill.get(seed.skill)
        if got is None or got.verdict not in VERDICT_KINDS or not got.reason.strip():
            merged.append(seed)
            continue
        merged.append(
            VerdictFact(
                skill=seed.skill,
                importance=seed.importance,
                verdict=got.verdict,
                reason=got.reason.strip(),
                jd_evidence=seed.jd_evidence,
                resume_evidence=got.resume_evidence.strip() or seed.resume_evidence,
            )
        )
    return merged


def merge_levels(
    fallback: Sequence[DimensionGrade],
    llm_dimensions: Sequence[DimensionLike] | None,
    rubric: Rubric,
) -> list[DimensionGrade]:
    """把 LLM 的档位**覆盖到代码兜底之上**。

    只接受三样都合格的结果：**维度存在**、**档位在 rubric 白名单里**、**证据非空**。
    最后一条是「不编分」的落点（plan §8 风险 8）：软性维度最容易被给一个
    「看起来合理」的档位却拿不出原文，这种一律当没判，退回兜底。

    与 `merge_verdicts` 一样：**不接受模型新增或删除维度**，六维恒定。
    """
    by_key: dict[str, DimensionLike] = {item.key: item for item in (llm_dimensions or ())}

    merged: list[DimensionGrade] = []
    for grade in fallback:
        got = by_key.get(grade.key)
        dimension = rubric.dimension(grade.key)
        if got is None or dimension is None:
            merged.append(grade)
            continue
        evidence = got.evidence.strip()
        if got.level not in dimension.level_keys or not evidence:
            merged.append(grade)
            continue
        merged.append(
            DimensionGrade(
                key=grade.key,
                level_key=got.level,
                evidence=evidence,
                reason=got.reason.strip() or grade.reason,
            )
        )
    return merged


# ---------------------------------------------------------------- 优化点 / 提升方向兜底（N3.2）

#: issue 类型 → 优化点的「区域」与「怎么改」。**键覆盖 `IssueType` 全集**，
#: 漏一个不会报错，只会让那类 issue 在降级时没有对应建议 —— 所以由测试守（见 test_advisor_rules）。
_ISSUE_AREA: Mapping[str, str] = {
    "NO_QUANTIFY": "量化描述",
    "NO_STAR": "项目描述结构",
    "SKILL_STUFFING": "技能清单",
    "TIMELINE_GAP": "时间线",
    "MISSING_CONTACT": "联系方式",
}

_ISSUE_ACTION: Mapping[str, str] = {
    "NO_QUANTIFY": "把这句补成「做了什么 + 结果数字」，例如接口耗时或提升幅度",
    "NO_STAR": "在这句后面补一句「做成了什么、结果如何」",
    "SKILL_STUFFING": "删掉与目标岗位无关的技能条目，保留能讲出细节的",
    "TIMELINE_GAP": "核对这段起止时间，写错了就改正，并行的就标注清楚",
    "MISSING_CONTACT": "补上手机号或邮箱，任何一份简历都不该省这一行",
}

#: 优化点条数上限。取 4 而不是 8：优化点是「下一步做什么」，一次给 8 条等于没给。
_MAX_IMPROVEMENTS = 4

_MISSING_AREA = "缺失能力"
_MISSING_ACTION = "在项目经历里补一条真正用到 {skill} 的实践，并写出它的作用"


def _anchor_line(facts: ResumeFacts) -> str:
    """「该往哪里加内容」的落点：项目经历 → 工作经历 → 全文的第一句。

    优化点必须带**简历原文片段**（契约要求逐字复制），所以这里取的是真实存在的一行，
    不是模板拼出来的空话。取不到（空简历）就返回空串，调用方据此跳过 —— 宁可少给一条，
    也不给一条没有落点的建议。
    """
    for key in ("projects", "experience"):
        for line in (facts.sections.get(key) or "").split("\n"):
            if line.strip():
                return line.strip()
    for sentence in sentences(facts.text):
        return sentence
    return ""


def improvements_fallback(
    verdicts: Sequence[VerdictFact],
    issues: Sequence[Issue] = (),
    *,
    facts: ResumeFacts | None = None,
    max_items: int = _MAX_IMPROVEMENTS,
) -> list[ImprovementFact]:
    """断 LLM 时的优化点（N3.2）。

    两条来源，优先级从高到低：

    1. **缺口技能** —— 每条缺口给出「补一条实践」的建议，落点取简历里真实存在的
       项目 / 工作经历首行。`targets` 就是那条技能，**天然非空**（契约硬要求）。
    2. **`issues`（规则已找出的结构性问题）** —— 证据是 issue 自带的原文片段；
       只有当它能挂到某条岗位要求上时才收（`targets` 为空则丢），
       因为「服务于哪条要求」说不清的优化点无法验证。

    **只给方向与关键词，不给课程链接 / 机构名**（spec §3 禁止项）—— 这里全是模板文案，
    结构上不可能出现链接。
    """
    seen: set[tuple[str, str]] = set()
    results: list[ImprovementFact] = []
    anchor = _anchor_line(facts) if facts is not None else ""

    def _push(item: ImprovementFact) -> None:
        key = (item.area, item.evidence)
        if key in seen or not item.targets or not item.evidence.strip():
            return
        seen.add(key)
        results.append(item)

    # 来源 1：缺口技能（targets 天然非空）
    for verdict in verdicts:
        if len(results) >= max_items:
            break
        if verdict.verdict != _VERDICT_MISSING or not anchor:
            continue
        _push(
            ImprovementFact(
                area=_MISSING_AREA,
                action=_MISSING_ACTION.format(skill=verdict.skill),
                evidence=anchor,
                targets=(verdict.skill,),
            )
        )

    # 来源 2：结构性 issues（挂不上要求就丢）
    requirement_skills = [v.skill for v in verdicts]
    for issue in issues:
        if len(results) >= max_items:
            break
        targets = tuple(skill for skill in requirement_skills if skill in issue.evidence)
        _push(
            ImprovementFact(
                area=_ISSUE_AREA.get(issue.type.value, "简历表述"),
                action=_ISSUE_ACTION.get(issue.type.value, "按该问题的建议改写这句话"),
                evidence=issue.evidence,
                targets=targets,
            )
        )

    return results[:max_items]


def directions_fallback(
    verdicts: Sequence[VerdictFact],
    *,
    max_directions: int = MAX_GROWTH_DIRECTIONS,
) -> list[DirectionFact]:
    """断 LLM 时的提升方向（N3.2）。

    只从**缺口技能**推导，并按 `(是否硬性要求, 技能名)` **升序**：
    硬性要求排前、同档按技能名字典序 —— 这样「同输入两次同顺序」（AC32）。
    顺序是**代码**定的，模型给的顺序一律不用（spec §2.7 禁 LLM 决定任何排序）。

    `firstStep` 一定写成「一周内能启动的动作」：给「去学分布式系统」等于没给方向。
    """
    missing = [v for v in verdicts if v.verdict == _VERDICT_MISSING]
    ordered = sorted(missing, key=lambda v: (0 if v.importance == "required" else 1, v.skill))

    directions: list[DirectionFact] = []
    for index, verdict in enumerate(ordered[: max(max_directions, 0)], start=1):
        label = "硬性要求" if verdict.importance == "required" else "加分项"
        directions.append(
            DirectionFact(
                direction=f"{verdict.skill} 的实战能力",
                why=f"目标岗位的{label}，简历中没有任何可查的使用证据",
                first_step=f"挑一个已有项目，真的用 {verdict.skill} 解决一个具体问题，并记下前后的差异",
                priority=index,
            )
        )
    return directions
