"""LLM 输出的「严进」解析器（part3 从 client.py 拆出）。

原则：**宁可丢，不可编**。

- 某一条不合法 → 丢该条，保留其余；只有一条都不剩才返回 `None`。
  返回 `None` 会让编排层切到规则兜底 —— 那是我们期望的降级方向。
  反过来，「把坏数据补全成看起来对的数据」不会有任何人发现。
- `evidence` 必须非空：模型给不出原文依据时，宁可丢这条也不要留半截证据
  （part3 spec：每个分数都要能溯源到简历原文）。

排序 / 截断是**代码**的职责（spec §2.7 禁 LLM 决定任何排序），所以
`parse_advice` 里方向条数在这里就截到上限并按 `priority` 升序排好。
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Sequence
from app.core.constants import MAX_GROWTH_DIRECTIONS, VERDICT_KINDS
from app.llm.events import (
    AdviceDirection,
    AdviceImprovement,
    AllowedLevels,
    ReviewDimension,
    ReviewVerdict,
)
from app.schema.response.analyze_response import Issue, IssueType, Severity

_JSON_FENCE = ("```json", "```")

# ---------------------------------------------------------------- JSON 解析（宁可严，不要宽）


def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔加的 Markdown 代码块围栏。

    只剥首尾的 ```，不改中间内容 —— Prompt 里已经明确要求「不要代码块」，
    这里只是容错，不是在鼓励。
    """
    stripped = text.strip()
    for fence in _JSON_FENCE:
        if stripped.startswith(fence):
            stripped = stripped[len(fence) :]
        if stripped.endswith("```"):
            stripped = stripped[: -len("```")]
    return stripped.strip()


def parse_issues(raw: str) -> tuple[Issue, ...] | None:
    """把模型输出解析成 issues；**任何不合法都返回 `None`（降级）**。

    严在哪：
    - 顶层必须是 `{"issues": [...]}`，不是裸数组；
    - `type` / `severity` 必须命中冻结枚举，不认识的一律丢弃整条（不是整批）；
    - `evidence` 必须是非空字符串 —— 空证据等于「模型编了一个结论但给不出依据」，
      这种比没有更糟；
    - 某一条不合法时**丢弃该条、保留其余**，只有全军覆没才返回 None。
    """
    text = _strip_code_fence(raw)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        return None

    issues: list[Issue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        try:
            issue = Issue(
                type=IssueType(item["type"]),
                severity=Severity(item["severity"]),
                evidence=str(item["evidence"]).strip(),
                suggestion=str(item["suggestion"]).strip(),
            )
        except (KeyError, ValueError, TypeError):
            continue
        if not issue.evidence:
            continue
        issues.append(issue)

    return tuple(issues) if issues else None


# ---------------------------------------------------------------- part3：判定 / 文案解析（N1.1 / N3.1）


@dataclass(frozen=True)
class ReviewPayload:
    """Prompt-3 解析成功的产物。"""

    verdicts: tuple[ReviewVerdict, ...]
    dimensions: tuple[ReviewDimension, ...]


def parse_review(
    raw: str, *, allowed_levels: AllowedLevels, resume_text: str = ""
) -> ReviewPayload | None:
    """把 Prompt-3 的输出解析成判定 + 维度档位；**任何不合法都返回 `None`（降级）**。

    严在哪（逐条对应 Prompt-3 的规则）：

    | 规则 | 这里的落点 |
    |---|---|
    | 1 `verdict` 三选一 | 不在 `VERDICT_KINDS` 里 → 丢**该条** |
    | 2 `level` 取 rubric 的档位 key | 不在 `allowed_levels[key]` 里 → 丢**该维** |
    | 3 `reason` 必须指向简历内容 | 空 `reason` → 丢该条 |
    | 4 证据逐字复制 | `dimensions.evidence` 为空 → 丢该维（见下） |
    | 6 不得增删条目 | 不在要求清单里的 `skill` 在本函数里照收，**由组装层按 `match` 骨架过滤** |

    ⚠️ **为什么维度要求 `evidence` 非空**：模型给一个「看起来合理」的档位但给不出原文
    是最危险的情形（plan §8 风险 8）—— 软性维度尤其容易这样。**给不出证据就当它没判**，
    退回代码兜底。代价是模型无法合法地说「`L0` 无证据」（那本来就没有证据可复制），
    但兜底判档对这种情况也会给出第 0 档，结论一致。

    某一条不合法时**丢该条、保留其余**；只有**一条都没剩下**才返回 `None`。

    :param resume_text: 传了它就**强制校验 evidence 逐字来自简历**（`in` 判定）。
        契约要求所有证据「逐字复制」，但「逐字」这件事没有任何别的机制能守住 ——
        模型稍微改写一个标点就变成了「看起来像原文」的新文本，
        而下游（前端展示、`improvements.targets` 的对应关系）全都假定它是原文。
        校验放在解析器里，是因为这里本就是「严进」的地方。
    """
    text = _strip_code_fence(raw)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    def _verbatim(value: object) -> str:
        snippet = str(value or "").strip()
        if not snippet:
            return ""
        if resume_text and snippet not in resume_text:
            return ""
        return snippet

    verdicts: list[ReviewVerdict] = []
    for item in payload.get("verdicts") or []:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        verdict = str(item.get("verdict") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not skill or verdict not in VERDICT_KINDS or not reason:
            continue
        verdicts.append(
            ReviewVerdict(
                skill=skill,
                verdict=verdict,
                reason=reason,
                resume_evidence=_verbatim(item.get("resumeEvidence")),
            )
        )

    dimensions: list[ReviewDimension] = []
    for item in payload.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        level = str(item.get("level") or "").strip()
        allowed = allowed_levels.get(key)
        if not key or not allowed or level not in allowed:
            continue
        evidence = _verbatim(item.get("evidence"))
        if not evidence:
            continue
        dimensions.append(
            ReviewDimension(
                key=key,
                level=level,
                reason=str(item.get("reason") or "").strip(),
                evidence=evidence,
            )
        )

    if not verdicts and not dimensions:
        return None
    return ReviewPayload(verdicts=tuple(verdicts), dimensions=tuple(dimensions))


@dataclass(frozen=True)
class AdvicePayload:
    """Prompt-4 解析成功的产物。"""

    improvements: tuple[AdviceImprovement, ...]
    directions: tuple[AdviceDirection, ...]


def parse_advice(
    raw: str, *, max_directions: int, evidence_source: str = ""
) -> AdvicePayload | None:
    """把 Prompt-4 的输出解析成优化点 + 提升方向；不合法返回 `None`。

    严在哪：

    - `targets` 为空的 improvement → 丢（它服务于哪几条要求都不说，就没法落地）；
    - `evidence` 为空**或不是 `evidence_source` 里的逐字片段** → 丢。
      Prompt-4 只收到「结构化摘要」，摘要里的 `resumeEvidence` 是已校验过的原文片段，
      所以模型要引用证据时**只能从摘要里抄** —— 抄不出逐字片段就说明它在自己编；
    - `firstStep` 为空的 direction → 丢（方向没有第一步等于没有方向）；
    - **方向条数在这里就截到 `max_directions`**，并且**按 `priority` 升序排序** ——
      排序是**代码**的职责（spec §2.7 禁 LLM 决定任何排序）。模型给出的顺序一律忽略。
    """
    text = _strip_code_fence(raw)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    improvements: list[AdviceImprovement] = []
    for item in payload.get("improvements") or []:
        if not isinstance(item, dict):
            continue
        area = str(item.get("area") or "").strip()
        action = str(item.get("action") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        targets = tuple(
            str(target).strip() for target in (item.get("targets") or []) if str(target).strip()
        )
        if not area or not action or not evidence or not targets:
            continue
        if evidence_source and evidence not in evidence_source:
            continue
        improvements.append(
            AdviceImprovement(area=area, action=action, evidence=evidence, targets=targets)
        )

    directions: list[AdviceDirection] = []
    for item in payload.get("growthDirections") or []:
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction") or "").strip()
        why = str(item.get("why") or "").strip()
        first_step = str(item.get("firstStep") or "").strip()
        if not direction or not why or not first_step:
            continue
        try:
            priority = int(item.get("priority") or 1)
        except (TypeError, ValueError):
            priority = 1
        directions.append(
            AdviceDirection(
                direction=direction, why=why, first_step=first_step, priority=max(1, priority)
            )
        )

    # 排序 + 截断都由**代码**做（模型给的顺序与条数都不作数）
    directions.sort(key=lambda item: (item.priority, item.direction))
    directions = directions[: max(max_directions, 0)]

    if not improvements and not directions:
        return None
    return AdvicePayload(improvements=tuple(improvements), directions=tuple(directions))
