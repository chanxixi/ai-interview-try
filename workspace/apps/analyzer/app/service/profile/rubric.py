"""六维 rubric 的**唯一**读入口与解释器（part3 spec §2.5① / ADR-204）。

## 分工（决定了本文件的边界）

| 层 | 干什么 |
|---|---|
| `app/data/rubric.yaml` | **数据真源**：维度定义 / 可读信号 / 档位分数 / 按 level 分档的权重 |
| `core/resources.py` | 只负责「把 YAML 读成 `dict`」（路径拼接、解析、顶层类型校验） |
| **本文件** | 把 `dict` **解释成领域对象**，并守住「缺失 / 损坏不炸主流程」这条策略 |

同一条约束与 `normalizer.SkillDictionary` 一致：**读成 dict 归 core，解释成领域对象归 service**
（`core` 不得依赖 `service`，指南 §4.2）。

## 为什么 `load_rubric()` 抛、`get_rubric()` 不抛

两个入口，服务两种不同的调用者：

- `load_rubric()` —— **严格**。测试与「启动自检」用它，缺文件 / 结构错就立刻红。
- `get_rubric()` —— **宽容**。运行期用它：rubric 缺失 **只降级 `abilityProfile`**，
  绝不能让整条分析链失败（plan §6.2：主流程仍有 `match` 与推荐）。失败时 `WARN` 一次并返回 `None`。

分开的代价是多一个函数；收益是「数据坏了」与「代码坏了」在日志里一眼可分。
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Mapping, Sequence
from app.core.constants import DIMENSIONS
from app.core.resources import read_yaml, resource_path

logger = logging.getLogger(__name__)

#: rubric 数据文件名。**全项目唯一**写字面量的地方。
RUBRIC_FILE = "rubric.yaml"

#: 岗位 `level` → rubric 权重档。词表来自 `db/seed/jobs/*.json`（`"校招"` / `"社招"`）。
#: **顺序即优先级**：`校招` 必须先于 `mid` 判，否则会被 `mid` 词表里的通用词吃掉。
_WEIGHT_LEVEL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("campus", ("校招", "应届", "实习", "campus", "graduate", "junior", "intern")),
    ("senior", ("高级", "资深", "专家", "架构师", "senior", "expert", "lead", "principal")),
    ("mid", ("社招", "中级", "mid", "middle", "regular")),
)

#: 识别不出岗位 level 时用哪一档。选 `mid`（社招）而不是 `campus`：
#: 岗位库里社招占多数，且「不知道级别」时用中性档比用最极端的两档更不容易误导。
DEFAULT_WEIGHT_LEVEL = "mid"


@dataclass(frozen=True)
class Level:
    """一个档位。`score` 就是**维度分的唯一来源** —— 代码不做任何二次换算。"""

    key: str
    label: str
    score: int
    hint: str = ""


@dataclass(frozen=True)
class Dimension:
    """一个能力维度。`strong_signals` / `weak_signals` 同时被两处消费：

    ① 「按岗位裁剪后的 rubric 片段」注入 Prompt-3（给模型当锚点）；
    ② 断 LLM 时的兜底判档（`advisor_rules`）。

    **所以改 signals 必须两处同步**（DoD 15）；本文件是它们的唯一来源，漂移只可能发生在测试里。
    """

    key: str
    name: str
    question: str
    strong_signals: tuple[str, ...]
    weak_signals: tuple[str, ...]
    levels: tuple[Level, ...]

    def level(self, key: str) -> Level | None:
        for item in self.levels:
            if item.key == key:
                return item
        return None

    @property
    def level_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.levels)

    def level_at(self, tier: int) -> Level:
        """按**档位序号**取档（越界自动夹到两端）。

        兜底判档产出的是「第几档」这样的序号，而不是硬编码的 `L3` ——
        这样在 `rubric.yaml` 里给某一维**多加一档**时，兜底逻辑不需要改一行代码（AC31）。
        """
        return self.levels[max(0, min(tier, len(self.levels) - 1))]

    def rubric_ref(self, level_key: str) -> str:
        """出处的规范形式：`<维度 key>.<档位 key>`，如 `tech_depth.L3`。

        ⚠️ **契约里的示例写的是 `tech.depth.L3`（点号分层）**，这里是 `tech_depth.L3`
        （直接用 rubric 的 key）。取后者是因为它**逐字可回溯**到 `rubric.yaml` 的字段值 ——
        出处的意义就是「能被机器和人一起校验」，为此宁可偏离一个纯示意性的示例。
        """
        return f"{self.key}.{level_key}"


@dataclass(frozen=True)
class Rubric:
    """整个 rubric 文件。不可变 —— 加载一次、全进程共享。"""

    dimensions: tuple[Dimension, ...]
    weights: Mapping[str, Mapping[str, float]]
    version: int = 1

    def dimension(self, key: str) -> Dimension | None:
        for item in self.dimensions:
            if item.key == key:
                return item
        return None

    def score_of(self, dimension_key: str, level_key: str) -> int | None:
        """档位 → 分数。**认不出档位返回 `None`**（不是 0）——
        `None` 会被上层翻成「该维算不出、不编分」（spec §2.6），0 则是一个假分数。"""
        dimension = self.dimension(dimension_key)
        if dimension is None:
            return None
        level = dimension.level(level_key)
        return None if level is None else level.score

    def weight_level_of(self, job_level: str | None) -> str:
        """岗位 level 字符串 → 权重档名（`campus` / `mid` / `senior`）。"""
        if not job_level:
            return DEFAULT_WEIGHT_LEVEL
        lowered = job_level.strip().lower()
        for name, hints in _WEIGHT_LEVEL_HINTS:
            if any(hint in lowered for hint in hints):
                return name if name in self.weights else DEFAULT_WEIGHT_LEVEL
        return DEFAULT_WEIGHT_LEVEL

    def weights_for(self, job_level: str | None) -> Mapping[str, float]:
        """取某一档的维度权重。档名不存在时退回默认档 —— **绝不返回空表**：
        空权重会让 `overall` 的分母变成 0，而「分母为 0」在分数里表现为 0 分，
        看起来像「这个人很差」而不是「配置错了」。
        """
        name = self.weight_level_of(job_level)
        table = self.weights.get(name) or self.weights.get(DEFAULT_WEIGHT_LEVEL)
        return table or {}

    def slice_for(self, dimension_keys: Iterable[str]) -> list[dict]:
        """**裁剪后的 rubric 片段**（注入 Prompt-3）。

        只带与本次岗位相关的维度：六个维度 × 全部档位体积不小，而绝大多数与当前岗位无关。
        少喂一部分既省 token，也**减少模型自由发挥的空间**（plan §8 风险 5）。

        返回普通 `dict`（不是领域对象）：它下一步就是 `json.dumps` 进 prompt，
        中间的领域对象只会多一层需要维护的映射。
        """
        wanted = list(dict.fromkeys(dimension_keys))       # 去重且保序
        by_key = {item.key: item for item in self.dimensions}
        fragments: list[dict] = []
        for key in wanted:
            item = by_key.get(key)
            if item is None:
                continue
            fragments.append(
                {
                    "key": item.key,
                    "name": item.name,
                    "question": item.question,
                    "strong": list(item.strong_signals),
                    "weak": list(item.weak_signals),
                    "levels": [
                        {"key": level.key, "label": level.label, "hint": level.hint}
                        for level in item.levels
                    ],
                }
            )
        return fragments


# ---------------------------------------------------------------- 解析


def _parse_level(raw: Mapping) -> Level:
    return Level(
        key=str(raw["key"]),
        label=str(raw.get("label", "")),
        score=int(raw["score"]),
        hint=str(raw.get("hint", "")),
    )


def _parse_dimension(raw: Mapping) -> Dimension:
    signals = raw.get("signals") or {}
    return Dimension(
        key=str(raw["key"]),
        name=str(raw["name"]),
        question=str(raw.get("question", "")),
        strong_signals=tuple(str(word) for word in (signals.get("strong") or ())),
        weak_signals=tuple(str(word) for word in (signals.get("weak") or ())),
        levels=tuple(_parse_level(level) for level in raw["levels"]),
    )


def _parse_weights(raw: Mapping) -> dict[str, dict[str, float]]:
    return {
        str(name): {str(key): float(value) for key, value in (table or {}).items()}
        for name, table in (raw or {}).items()
    }


def load_rubric() -> Rubric:
    """**严格**加载：缺文件 / 结构不对一律抛（由 `core/resources.py` 保证前两者）。

    额外守一条：维度集合必须与 `core/constants.DIMENSIONS` 同序同量。
    这里只守「数量与 key 的并集」这种廉价可判的部分，**逐字一致**由
    `test_rubric_consistency.py` 守（它能给出更好的失败信息，也能顺带守顺序）。
    """
    raw = read_yaml(resource_path(RUBRIC_FILE))
    dimensions = tuple(_parse_dimension(item) for item in raw["dimensions"])

    expected = {key for key, _ in DIMENSIONS}
    actual = {item.key for item in dimensions}
    if actual != expected:
        raise ValueError(
            f"rubric.yaml 的维度集合与 constants.DIMENSIONS 不一致："
            f"多 {sorted(actual - expected)}，少 {sorted(expected - actual)}"
        )

    return Rubric(
        dimensions=dimensions,
        weights=_parse_weights(raw.get("weights")),
        version=int(raw.get("version", 1)),
    )


@lru_cache
def get_rubric() -> Rubric | None:
    """**宽容**加载（进程级单例）：坏了记一条 `WARN` 并返回 `None`。

    调用方拿 `None` 时的正确反应是「`abilityProfile = null`」，**不是**抛错 ——
    rubric 只影响 part3 的画像，不该把 part1/part2 就有的匹配与推荐一起拖下水
    （plan §6.2）。测试要重置时调 `get_rubric.cache_clear()`。
    """
    try:
        return load_rubric()
    except Exception as exc:  # noqa: BLE001 —— 见 docstring：任何原因都不该阻塞主流程
        logger.warning("rubric 加载失败，abilityProfile 将降级为 null（reason=%s）", type(exc).__name__)
        return None


def dimension_keys_for_requirements(requirements: Sequence) -> list[str]:
    """按岗位要求决定**注入哪几维的 rubric 片段**。

    策略（写死、可测）：`项目影响力` 与 `成长性` 是**纯代码兜底**的两维
    （spec §2.5①），不依赖模型判档，没必要占 prompt 预算；
    其余四维与「技术/工程/业务/协作」的证据直接相关，只要岗位有要求就注入。
    """
    if not requirements:
        return []
    return [key for key, _ in DIMENSIONS if key not in ("impact", "growth")]
