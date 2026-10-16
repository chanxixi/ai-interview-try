"""加权覆盖率匹配 —— **全项目唯一的打分公式实现**（tasks.md M3.3）。

```
score = Σ(命中技能权重) / Σ(该岗位全部技能权重) × 100
```

权重（ADR-002 冻结，`core/constants.py`）：`required = 1.0`、`preferred = 0.5`。

## 为什么只有这一个公式

part1 定它的时候就写明「不引入第二套公式」。到了 part2 尤其要守住：
推荐（`recommender.py`）如果自己再算一套分数，就会出现「`match.score` 82 但推荐里同一个岗位
显示 79」—— 用户第一个问题就是「这俩数怎么不一样」，而答案是「代码不同」。
所以 `recommender` **只调用本文件的 `match()`**，自己不算分。

## 集合自洽（spec §2.4 / AC17）

`matched ∩ missing = ∅` 且 `matched ∪ missing = 该岗位技能全集`。
这不是自然成立的 —— 一旦「同一技能在 JD 里出现两次」或「简历里认出了词典外的词」，
两边就会对不上。本文件用**同一份去重后的要求列表**同时生成 matched 和 missing，
从结构上保证自洽（测试里逐条断言）。

## 边界四例（tasks.md M3.3 点名）

| 场景 | 行为 | 理由 |
|---|---|---|
| 岗位 0 技能 | `score = 0`，matched/missing 均空 | 分母为 0。选 0 不选 100：没有要求可命中时给满分是误导 |
| 简历 0 技能 | `score = 0`，全部进 missing | 分子为 0 |
| 全命中 | `score = 100` | 分子 = 分母 |
| 同技能多条要求 | **取权重最高**的那条（required 赢 preferred） | 否则同一技能被计两次分母，分数被凭空拉低 |

## 自定义 JD 的 requirements 从哪来（契约 `x-known-gaps` G1）

预置岗位的 requirements 由 Java 从库里装配好下发；前端**直接粘贴 JD** 时库里没有对应数据，
Python 必须在运行期抽一次 —— 这就是 `extract_requirements()`。
它和离线落库走**同一套规则**（同一个词典、同一套加分项判定词），
所以两条路径产出的 `importance` 口径一致。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from app.core.constants import (
    JD_MAX_LENGTH,
    JD_PREFERRED_HINTS,
    SCORE_MAX,
    SCORE_MIN,
    WEIGHT_PREFERRED,
    WEIGHT_REQUIRED,
)
from app.service.skill.normalizer import SkillDictionary, SkillMention
from app.util.rounding import round_half_up

_IMPORTANCE_REQUIRED = "required"
_IMPORTANCE_PREFERRED = "preferred"

#: 抽「证据句」时的分句符号。**不含 `；`** —— JD 的一条要求常常是
#: 「熟悉 MySQL、Redis 等存储系统，理解索引、事务与缓存的基本原理；」，
#: 按 `；` 切会把半句当证据，反而不如整行可读。
_CLAUSE_BOUNDARY = "\n。！？!?"

#: 证据句首尾要剥掉的装饰字符（JD 常用「1、」「2.」「- 」起头，句末挂「；」「，」）。
#: 注意 `；` / `，` **不在** `_CLAUSE_BOUNDARY` 里（不拿它们分句），但要从证据两头剥掉 ——
#: 挂在证据尾部的标点对读者是纯噪音。
_CLAUSE_TRIM = " \t:：、.。-_—*#>；;，,"


# ---------------------------------------------------------------- 岗位侧：技能要求


@dataclass(frozen=True)
class Requirement:
    """岗位对一项技能的要求。字段名与契约 `bff-python.yaml` 的 `Requirement` 逐字一致。

    `weight` **不是**入参 —— 契约里没有这个字段，它由 `importance` 推导。
    做成 property 而不是字段，是为了让「权重只有一处定义」这件事在类型上就成立。
    """

    skill: str
    importance: str
    evidence: str = ""
    jd_offset: int | None = None
    skill_raw: str | None = None

    def __post_init__(self) -> None:
        if self.importance not in (_IMPORTANCE_REQUIRED, _IMPORTANCE_PREFERRED):
            raise ValueError(
                f"importance 必须是 required / preferred，收到 {self.importance!r}（skill={self.skill!r}）"
            )

    @property
    def weight(self) -> float:
        return WEIGHT_PREFERRED if self.importance == _IMPORTANCE_PREFERRED else WEIGHT_REQUIRED


# ---------------------------------------------------------------- 简历侧：已认出技能


@dataclass(frozen=True)
class ResumeSkills:
    """简历侧承认的技能集合。

    包一层而不是直接传 `set[str]`，是为了把「证据从哪来」也一起带走 ——
    `matched[].resumeEvidence` 需要原文片段，而 set 里只剩 canonical，取不回来。
    """

    mentions: tuple[SkillMention, ...] = ()

    @property
    def canonicals(self) -> frozenset[str]:
        return frozenset(mention.canonical for mention in self.mentions)

    def evidence_for(self, canonical: str) -> SkillMention | None:
        for mention in self.mentions:
            if mention.canonical == canonical:
                return mention
        return None

    def __len__(self) -> int:
        return len(self.mentions)


# ---------------------------------------------------------------- 结果


@dataclass(frozen=True)
class MatchedSkill:
    """命中项。必须带**双向原文证据**（AC5）—— 只有技能名的命中不可解释。"""

    skill: str
    importance: str
    weight: float
    jd_evidence: str
    resume_evidence: str
    jd_offset: int | None = None
    resume_offset: int | None = None


@dataclass(frozen=True)
class MissingSkill:
    """缺口项。必须给可执行建议（AC7），不能只列技能名。"""

    skill: str
    importance: str
    suggestion: str


@dataclass(frozen=True)
class MatchReport:
    """一次匹配的全部事实。

    `hit_weight` / `total_weight` 一起暴露出来，是为了让 AC18 的「手算复现」有据可查：
    评审当场拿这两个数除一下，就该等于 `score`。藏起来的话，分数只是个黑盒数字。
    """

    score: int
    matched: tuple[MatchedSkill, ...] = ()
    missing: tuple[MissingSkill, ...] = ()
    hit_weight: float = 0.0
    total_weight: float = 0.0

    @property
    def hit_count(self) -> int:
        return len(self.matched)

    @property
    def total_count(self) -> int:
        return len(self.matched) + len(self.missing)


# ---------------------------------------------------------------- 建议文案（规则模板，不调 LLM）

_SUGGESTION_REQUIRED = "简历中未见 {skill}，建议补充相关的项目或课程经历"
_SUGGESTION_PREFERRED = "如有 {skill} 相关经验，建议写进项目经历（该岗位标注为加分项）"


def suggestion_for(skill: str, importance: str) -> str:
    """缺口建议。**纯规则模板** —— 它要能解释「为什么推荐这个岗位」，
    而那是 `recommender` 的职责，不能让 LLM 的发挥影响确定性（spec §2.6）。
    """
    template = _SUGGESTION_PREFERRED if importance == _IMPORTANCE_PREFERRED else _SUGGESTION_REQUIRED
    return template.format(skill=skill)


# ---------------------------------------------------------------- 打分


def score_of(hit_weight: float, total_weight: float) -> int:
    """加权覆盖率 → 0–100 整数。

    **用 `util.rounding.round_half_up` 而不用内置 `round`**：Python 的 `round` 是银行家舍入，
    `round(12.5) == 12`。AC18 要求「手算复现」，评审按四舍五入口算会得到 13，
    对不上就会被当成 bug 追。舍入方式必须是能被口算复现的那一种，
    且必须**全项目只有一处**（part3 的 `ability_profile.overall` 也用它，见 `util/rounding.py`）。
    """
    if total_weight <= 0:
        return SCORE_MIN
    ratio = hit_weight / total_weight
    if ratio <= 0:
        return SCORE_MIN
    if ratio >= 1:
        return SCORE_MAX
    return max(SCORE_MIN, min(SCORE_MAX, round_half_up(ratio * 100)))


def dedupe_requirements(requirements: Iterable[Requirement]) -> list[Requirement]:
    """按技能去重，**同技能取权重最高**的一条；权重相同则保留先出现的。

    顺序保持「首次出现的顺序」—— JD 里的要求顺序是人工排的（职责顺序），
    打乱它只会让结果更难和 JD 对照。
    """
    best: dict[str, Requirement] = {}
    order: list[str] = []
    for requirement in requirements:
        current = best.get(requirement.skill)
        if current is None:
            best[requirement.skill] = requirement
            order.append(requirement.skill)
        elif requirement.weight > current.weight:
            best[requirement.skill] = requirement
    return [best[skill] for skill in order]


def match(
    requirements: Sequence[Requirement],
    resume: ResumeSkills | Iterable[SkillMention],
) -> MatchReport:
    """给一个岗位的要求集合 + 简历技能，算出 `MatchReport`。

    这是 `recommender` 的唯一算分入口 —— 它们不自己算（见模块 docstring）。
    """
    mentions = resume.mentions if isinstance(resume, ResumeSkills) else tuple(resume)
    resume_view = resume if isinstance(resume, ResumeSkills) else ResumeSkills(mentions)

    deduped = dedupe_requirements(requirements)
    known = resume_view.canonicals

    matched: list[MatchedSkill] = []
    missing: list[MissingSkill] = []
    hit_weight = 0.0
    total_weight = 0.0

    for requirement in deduped:
        total_weight += requirement.weight
        mention = resume_view.evidence_for(requirement.skill)
        if mention is None:
            missing.append(
                MissingSkill(
                    skill=requirement.skill,
                    importance=requirement.importance,
                    suggestion=suggestion_for(requirement.skill, requirement.importance),
                )
            )
            continue

        hit_weight += requirement.weight
        matched.append(
            MatchedSkill(
                skill=requirement.skill,
                importance=requirement.importance,
                weight=requirement.weight,
                jd_evidence=requirement.evidence,
                resume_evidence=mention.raw,
                jd_offset=requirement.jd_offset,
                resume_offset=mention.offset,
            )
        )

    return MatchReport(
        score=score_of(hit_weight, total_weight),
        matched=tuple(matched),
        missing=tuple(missing),
        hit_weight=hit_weight,
        total_weight=total_weight,
    )


# ---------------------------------------------------------------- 自定义 JD：运行期抽要求（G1）


def _clause_around(text: str, offset: int) -> str:
    """取 offset 所在的「一句」当证据。

    手工前后扫边界而不是 `re.split`：`split` 之后 offset 就丢了，
    而 `jdOffset` 是契约里的字段，必须回到原文坐标。
    """
    start = 0
    for position in range(offset - 1, -1, -1):
        if text[position] in _CLAUSE_BOUNDARY:
            start = position + 1
            break
    end = len(text)
    for position in range(offset, len(text)):
        if text[position] in _CLAUSE_BOUNDARY:
            end = position
            break
    return text[start:end].strip(_CLAUSE_TRIM)


def _is_preferred(clause: str) -> bool:
    lowered = clause.lower()
    return any(hint in lowered for hint in JD_PREFERRED_HINTS)


def extract_requirements(
    dictionary: SkillDictionary,
    jd_text: str,
    *,
    max_length: int = JD_MAX_LENGTH,
) -> list[Requirement]:
    """从 JD 原文抽出结构化技能要求（自定义 JD 路径，契约缺口 G1）。

    规则（与离线落库 `db/seed/jobs/*.json` 的人工标注口径对齐）：

    1. 用同一本词典扫 JD，得到技能命中；
    2. `importance` 看**所在句子**是否含加分项措辞（`JD_PREFERRED_HINTS`）——
       含则 `preferred`，否则 `required`；
    3. `evidence` = 所在句子（JD 原文逐字复制），`jdOffset` = 命中位置。

    **确定性**：不调 LLM、不抽样，同一份 JD 两次抽取结果完全一致。
    这也意味着它对「把加分项写在段落里而不是小节里」的 JD 会判成 required ——
    这是已知取舍（G1 已登记），比让 LLM 每次给出不同结果更可接受。
    """
    if not jd_text:
        return []
    text = jd_text[:max_length] if max_length else jd_text

    requirements: list[Requirement] = []
    for mention in dictionary.extract_unique(text):
        clause = _clause_around(text, mention.offset)
        importance = _IMPORTANCE_PREFERRED if _is_preferred(clause) else _IMPORTANCE_REQUIRED
        requirements.append(
            Requirement(
                skill=mention.canonical,
                importance=importance,
                evidence=clause,
                jd_offset=mention.offset,
                skill_raw=mention.raw,
            )
        )
    return requirements
