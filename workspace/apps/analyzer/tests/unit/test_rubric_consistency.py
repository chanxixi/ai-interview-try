"""六维 rubric 一致性（part3 N0.3 / AC31）。

`app/data/rubric.yaml` 是**数据真源**，`core/constants.py` 的 `DIMENSIONS` 是**编译期镜像**。
两者一旦漂移，表现是**静默**的：权重表的键与维度对不上，某个维度永远拿不到分
（或拿到别人的分）—— 不报错，只是给出错的画像。

所以这里逐条钉死：

| # | 守什么 | 不守的后果 |
|---|---|---|
| ① | 六维与常量**逐字一致**（含顺序） | 雷达图与权重表错位 |
| ② | 每维 `signals` 非空 | 兜底判档与 rubric 裁剪注入都消费它，空了就静默退化成「全 L0」 |
| ③ | 每维 ≥3 档，且**必须有 `L0`** | 软性维度没有 L0 档 → 模型只能硬编一个分数（spec §2.5.2 ①） |
| ④ | 分数随档位**单调不减** | 高努力档反而低分，rubric 自相矛盾 |
| ⑤ | 权重**恰好覆盖六维**、每档之和 = 1.0 | `overall` 的分母错 → 分数无意义 |
| ⑥ | 权重**不得平均**（校招压 `impact`、抬 `growth`） | 校招全员的画像被压成同一个形状（spec §2.5.2 ②） |

与 `test_seed_consistency.py` 同一个思路：守的不是算法，是**数据与代码的对应关系**。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.constants import (
    ANALYSIS_DEPTHS,
    DEFAULT_ANALYSIS_DEPTH,
    DEFAULT_TOP_N,
    DIMENSIONS,
    MAX_GROWTH_DIRECTIONS,
    MAX_TOP_N,
    RECOMMEND_TOP_N,
    VERDICT_KINDS,
)
from app.core.resources import read_yaml, resource_path

RUBRIC_NAME = "rubric.yaml"

#: 权重和的浮点容差。1e-9 比 float 的表示误差宽、比「人写错一位小数」窄得多。
_WEIGHT_EPS = 1e-9


@pytest.fixture(scope="module")
def rubric() -> dict:
    """读真源。走 `core/resources.py` —— 顺便保证「路径拼接只有一处」这条约束真的成立。"""
    return read_yaml(resource_path(RUBRIC_NAME))


@pytest.fixture(scope="module")
def dimensions(rubric: dict) -> list[dict]:
    return rubric["dimensions"]


# ------------------------------------------------------------------ ① 与常量一致


def test_dimensions_match_constants(dimensions: list[dict]) -> None:
    """`rubric.yaml` 的 (key, name) 序列必须与 `constants.DIMENSIONS` **逐字且同序**一致。

    顺序也要守：它是 `abilityProfile.dimensions` 的稳定顺序，也是雷达图的顶点顺序 ——
    顺序变了，同一个人的画像在两个版本里长得不一样，而分数没变。
    """
    from_yaml = [(item["key"], item["name"]) for item in dimensions]

    assert from_yaml == list(DIMENSIONS)


def test_dimension_keys_are_unique(dimensions: list[dict]) -> None:
    keys = [item["key"] for item in dimensions]

    assert len(keys) == len(set(keys))


# ------------------------------------------------------------------ ② 可读信号非空


@pytest.mark.parametrize("field", ["strong", "weak"])
def test_every_dimension_has_signals(dimensions: list[dict], field: str) -> None:
    """`signals` 是**兜底判档**与**rubric 裁剪注入**的输入。

    空列表不会报错，只会让该维在断 LLM 时永远是 `L0`，或让 prompt 里少一段锚点 ——
    两种都是「看起来正常但质量下降」的静默故障。
    """
    for item in dimensions:
        signals = item["signals"][field]
        assert signals, f"{item['key']}.signals.{field} 为空"
        assert all(isinstance(word, str) and word.strip() for word in signals), (
            f"{item['key']}.signals.{field} 含空串"
        )


# ------------------------------------------------------------------ ③ 档位数量与 L0


def test_every_dimension_has_at_least_three_levels(dimensions: list[dict]) -> None:
    """少于 3 档就没有区分度（`L0` 无证据 + 一档低 + 一档高 已经是最小可用集）。"""
    for item in dimensions:
        levels = item["levels"]
        assert len(levels) >= 3, f"{item['key']} 只有 {len(levels)} 档"


def test_every_dimension_has_l0_no_evidence_level(dimensions: list[dict]) -> None:
    """**每维必须有 `L0` 档** —— 这是「不编分」的落点（spec §2.5.2 ①）。

    `协作沟通` / `成长性` 在简历里常常真的没有证据。没有 `L0` 档，模型只能从
    「L1 自述 / L2 有角色 / L3 有规模」里挑一个，于是**编出一个看起来合理的分数** ——
    用户会照着一个本来没问题的地方去优化。宁可显式说「无依据」。
    """
    for item in dimensions:
        by_key = {level["key"]: level for level in item["levels"]}
        assert "L0" in by_key, f"{item['key']} 缺 L0 档"
        assert by_key["L0"]["score"] == 0, f"{item['key']}.L0 的 score 必须是 0"


def test_level_keys_are_unique_within_dimension(dimensions: list[dict]) -> None:
    for item in dimensions:
        keys = [level["key"] for level in item["levels"]]
        assert len(keys) == len(set(keys)), f"{item['key']} 档位 key 重复：{keys}"


# ------------------------------------------------------------------ ④ 分数单调


def test_level_scores_are_monotonic(dimensions: list[dict]) -> None:
    """档位越高、分数不得更低 —— 否则 rubric 自相矛盾，且「档位→分数」映射失去意义。"""
    for item in dimensions:
        scores = [level["score"] for level in item["levels"]]
        assert scores == sorted(scores), f"{item['key']} 的分数非单调：{scores}"
        assert len(set(scores)) == len(scores), f"{item['key']} 有重复分数：{scores}"


def test_level_scores_within_bounds(dimensions: list[dict]) -> None:
    for item in dimensions:
        for level in item["levels"]:
            assert 0 <= level["score"] <= 100, f"{item['key']}.{level['key']} 越界"


# ------------------------------------------------------------------ ⑤ 权重完整性


def test_weights_cover_exactly_the_six_dimensions(rubric: dict) -> None:
    """权重表的键必须**恰好**是六维 —— 少一个会让 `overall` 的分母少一项，
    多一个键则说明有人在 YAML 里加了维度却忘了改常量。
    """
    expected = {key for key, _ in DIMENSIONS}

    for level_name, weights in rubric["weights"].items():
        assert set(weights) == expected, f"weights.{level_name} 的键与六维不一致"


def test_weights_sum_to_one_per_level(rubric: dict) -> None:
    """每档之和必须为 1.0 —— 否则 `overall` 会被整体放大 / 缩小，而**没人看得出来**。"""
    for level_name, weights in rubric["weights"].items():
        total = sum(weights.values())
        assert abs(total - 1.0) < _WEIGHT_EPS, f"weights.{level_name} 之和 = {total}"


def test_weight_levels_are_declared(rubric: dict) -> None:
    """至少要有校招 / 社招两档 —— 只留一档等于「权重写死」，与 spec §2.5.2 ② 相悖。"""
    assert {"campus", "mid"} <= set(rubric["weights"])


# ------------------------------------------------------------------ ⑥ 权重不得平均


def test_weights_are_not_averaged(rubric: dict) -> None:
    """校招档要**压 `impact`**、**抬 `growth`**；高级档反向（spec §2.5.2 ②）。

    这条不是「风格偏好」：校招生普遍没有可谈的影响力，`impact` 权重高会让**所有人**的
    综合分被同一个低分维度拖住，画像失去区分度；而成长性恰恰是校招最该看的。
    """
    campus = rubric["weights"]["campus"]
    senior = rubric["weights"]["senior"]

    assert campus["impact"] < senior["impact"], "校招档应压 impact"
    assert campus["growth"] > senior["growth"], "校招档应抬 growth"


# ------------------------------------------------------------------ 冻结枚举与上限


def test_verdict_kinds_frozen() -> None:
    """三档判定是**冻结契约**（spec §2.3），改它要动 spec + 三份契约 + 前端。"""
    assert VERDICT_KINDS == ("satisfied", "partial", "missing")


def test_analysis_depths_and_default() -> None:
    """缺省必须是 `standard` —— 它是「与 part2 逐字节一致」这条保证的开关（AC25）。"""
    assert ANALYSIS_DEPTHS == ("standard", "deep")
    assert DEFAULT_ANALYSIS_DEPTH == "standard"


def test_top_n_default_keeps_ac17() -> None:
    """默认仍是 3 ⇒ AC17（条数 = min(3, 岗位数)）不被破坏；上限才是 10（C7）。"""
    assert DEFAULT_TOP_N == RECOMMEND_TOP_N == 3
    assert MAX_TOP_N == 10


def test_growth_direction_cap() -> None:
    assert MAX_GROWTH_DIRECTIONS == 5


# ------------------------------------------------------------------ 真源可被加载


def test_rubric_source_is_repo_file(rubric: dict) -> None:
    """`version` 存在且 `dimensions` 是列表 —— 防止哪天路径算错、读到别的文件却「恰好能解析」。"""
    assert rubric.get("version") == 1
    assert isinstance(rubric["dimensions"], list)

    path: Path = resource_path(RUBRIC_NAME)
    assert path.is_file() and path.name == RUBRIC_NAME

