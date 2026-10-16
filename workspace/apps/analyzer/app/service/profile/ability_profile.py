"""六维分与 `overall` 的**唯一**公式（part3 spec §2.5② / ADR-203 · N2.1–N2.2）。

## 为什么这个文件必须存在，且必须只有一份

spec §2.7 把「算」划给 Python，并点名一条**已经踩过的坑**：
part2 里 `match.score = 82` 而推荐里同一岗位显示 79 —— 因为有两套打分代码。
part3 的 `overall` 是**第二个**分数公式，所以它落在本文件，
与 `matcher.py`（唯一的匹配公式）并列，**全项目只有这两处分数公式**。

参考施工单写的是「综合分由 Java 规则引擎算」。**本项目有意不照抄**：
Java 侧若再算一遍，就会重演上面那个 bug（用户第一个问题就是「这俩数怎么不一样」）。
Java 只负责**装配数据**（岗位的 `level` → 权重档），算术留在 Python。

## 三条硬要求（spec §2.5②）

| 要求 | 落点 |
|---|---|
| **可复现** | 输入相同则输出相同：权重来自 `rubric.yaml`（数据），无随机、无时间依赖（AC30） |
| **可审计** | 每个分数都带 `rubricRef`（档位出处）与 `evidence`（简历原文片段）（AC27） |
| **可调权** | 权重是**数据**不是代码；改权重只改 `rubric.yaml`（AC31 / DoD 12） |

## 算不出来就留空（N2.2）

`score = None` 表示「该维算不出」，`overall` 按**已有维度**重新归一。
这条与 `rules.py`「宁可漏不可编」同源：编一个看起来合理的分数比留空危险得多。
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Mapping, Sequence
from app.core.constants import DIMENSIONS, SCORE_MAX, SCORE_MIN
from app.service.profile.advisor_rules import DimensionGrade
from app.service.profile.rubric import Rubric
from app.util.rounding import round_half_up

logger = logging.getLogger(__name__)

#: 权重和的容差。比 float 表示误差宽、比「人写错一位小数」窄得多（与
#: `test_rubric_consistency.py` 的 `_WEIGHT_EPS` 同口径）。
_WEIGHT_EPS = 1e-6


@dataclass(frozen=True)
class DimensionScore:
    """一个维度的最终分数（**内部类型**，组装层再翻成契约模型）。

    `level_key` / `reason` 不进契约（契约只有 `name` / `score` / `rubricRef` / `evidence`），
    但它们在这里有实际用途：`level_key` 是 `rubricRef` 的来源，`reason` 供日志与人看。
    """

    key: str
    name: str
    level_key: str
    score: int | None
    rubric_ref: str
    evidence: str
    reason: str = ""


@dataclass(frozen=True)
class ProfileResult:
    """一次画像的完整结果。`weights` 一并带出来，是为了让 AC28 的「手算复现」有据可查 ——
    评审拿 `weights` 与 `dimensions` 乘加一遍，就该等于 `overall`。
    """

    dimensions: tuple[DimensionScore, ...]
    overall: int | None
    weight_level: str
    weights: Mapping[str, float]


def _usable_weights(weights: Mapping[str, float] | None) -> bool:
    """候选集下发的权重是否**可信**。

    三条都必须成立，否则一律回退 rubric：

    1. **键恰好是六维** —— 少一维会让 `overall` 的分母少一项，多一维说明上游加了维度却没改契约；
    2. **值都落在 [0, 1]** —— 负数或大于 1 的权重算出来的分数没法解释；
    3. **和为 1.0（±1e-6）** —— 这是「权重」这个概念的底线。不满足时 `overall` 会被整体
       放大或缩小，而用户看到的只是一个具体数字，**看不出它错了**。

    宁可回退自己那份（`rubric.yaml`，和上游读的是同一份文件，正常情况必然一致），
    也不按一张可疑的表算分 —— 与「宁可漏不可编」同源。
    """
    if not weights:
        return False
    expected = {key for key, _ in DIMENSIONS}
    if set(weights) != expected:
        return False
    if any(value < 0 or value > 1 for value in weights.values()):
        return False
    return abs(sum(weights.values()) - 1.0) < _WEIGHT_EPS


def resolve_weights(
    rubric: Rubric,
    *,
    job_level: str | None = None,
    weights_override: Mapping[str, float] | None = None,
) -> tuple[Mapping[str, float], str]:
    """确定本次画像用哪张权重表。

    :return: `(权重表, 档名)`。`weights_override` 合法就用它（**Java 装配的那份**），
             否则回退 `rubric.weights_for(job_level)`。
    """
    if weights_override is not None:
        if _usable_weights(weights_override):
            return dict(weights_override), rubric.weight_level_of(job_level)
        logger.warning(
            "候选集下发的维度权重不可用（六维不全 / 越界 / 和≠1），回退 rubric.yaml"
        )
    return rubric.weights_for(job_level), rubric.weight_level_of(job_level)


def overall_of(scores: Mapping[str, int | None], weights: Mapping[str, float]) -> int | None:
    """`Σ(维度分 × 权重) / Σ(权重)`（**只对算得出来的维度求和**）。

    两条边界：

    - `score is None` 的维度**既不进分子也不进分母** —— 这就是「重新归一」（N2.2）。
      若把它的权重留在分母里，`overall` 会被一个「未知」维度系统性拉低，
      而用户看到的是一个具体数字，会以为那是他的真实水平。
    - 没有任何维度可算 → 返回 `None`（**不是 0**）。0 是一个结论，`None` 才是「没有结论」。

    取整口径与 `matcher.score_of` **共用同一个函数**（`util.rounding.round_half_up`），
    所以 AC28 的手算结果两边一致。
    """
    weighted = 0.0
    total = 0.0
    for key, score in scores.items():
        if score is None:
            continue
        weight = weights.get(key)
        if not weight:
            continue
        weighted += score * weight
        total += weight

    if total <= 0:
        return None
    return max(SCORE_MIN, min(SCORE_MAX, round_half_up(weighted / total)))


def build_profile(
    grades: Sequence[DimensionGrade],
    rubric: Rubric,
    *,
    job_level: str | None = None,
    weights_override: Mapping[str, float] | None = None,
) -> ProfileResult:
    """档位序列 → 六维分 + `overall`（**唯一入口**）。

    :param grades: `advisor_rules.grade_dimensions` 或 LLM 判档的结果（顺序即六维顺序）
    :param rubric: 维度真源（提供「档位 → 分数」与权重表）
    :param job_level: 目标岗位的 `level`（如 `校招`），决定用哪一档权重
    :param weights_override: 候选集下发的六维权重（Java 装配）。**校验通过才采用**，
        见 `_usable_weights`；不通过就静默回退 `rubric.yaml`。
    """
    weights, weight_level = resolve_weights(
        rubric, job_level=job_level, weights_override=weights_override
    )
    dimensions: list[DimensionScore] = []
    scores: dict[str, int | None] = {}

    for grade in grades:
        dimension = rubric.dimension(grade.key)
        if dimension is None:
            # rubric 里没有这一维：**跳过而不是补 0** —— 补 0 是编分。
            continue

        score = rubric.score_of(grade.key, grade.level_key)
        # 档位认不出（rubric 被改过 / LLM 给了白名单外的档位）→ 该维留空，**不编分**
        dimensions.append(
            DimensionScore(
                key=dimension.key,
                name=dimension.name,
                level_key=grade.level_key,
                score=score,
                rubric_ref=dimension.rubric_ref(grade.level_key),
                evidence=grade.evidence if score is not None else "",
                reason=grade.reason,
            )
        )
        scores[dimension.key] = score

    return ProfileResult(
        dimensions=tuple(dimensions),
        overall=overall_of(scores, weights),
        weight_level=weight_level,
        weights=weights,
    )
