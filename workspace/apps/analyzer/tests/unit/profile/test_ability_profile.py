"""六维分与 `overall`（part3 N2.1 / N2.2，验收 AC27 / AC28 / AC30）。

| 守什么 | 用例 |
|---|---|
| **手算复现**（AC28） | `test_overall_matches_hand_calculation` |
| 取整口径 = 四舍五入（**不是**银行家舍入） | `test_overall_uses_half_up_not_bankers_rounding` |
| 缺维 → `score=null` + `overall` 按已有维度归一（N2.2） | `test_missing_dimension_*` |
| 全维缺 → `overall = null`（不编分） | `test_all_dimensions_missing_yields_null_overall` |
| 权重是**数据**（换岗位档位结果就变）（AC31 / DoD 12） | `test_weights_follow_job_level` |
| 每个分数都有出处（AC27） | `test_every_score_carries_provenance` |
| 可复现（AC30） | `test_profile_is_deterministic` |
"""

from __future__ import annotations
import pytest
from app.core.constants import DIMENSIONS
from app.service.profile.ability_profile import build_profile, overall_of
from app.service.profile.advisor_rules import DimensionGrade
from app.service.match.matcher import score_of
from app.service.profile.rubric import load_rubric
from app.util.rounding import round_half_up


def _grades(levels: dict[str, str]) -> list[DimensionGrade]:
    return [
        DimensionGrade(key=key, level_key=level, evidence=f"{key} 的原文片段", reason="r")
        for key, level in levels.items()
    ]


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


# ------------------------------------------------------------------ AC28 手算复现


def test_overall_matches_hand_calculation(rubric) -> None:
    """**AC28**：`overall = Σ(维度分×权重)/Σ(权重)`，手算必须与代码一致。

    校招档权重（`rubric.yaml`）：技术深度 .30 / 工程 .25 / 业务 .10 / 影响力 .10 / 协作 .10 / 成长 .15

    维度分：65、65、35、35、0、35（都是 rubric 里真实存在的档位分）

    ```
    65×.30 + 65×.25 + 35×.10 + 35×.10 + 0×.10 + 35×.15
      = 19.5 + 16.25 + 3.5 + 3.5 + 0 + 5.25 = 48.0
    ÷ 1.0 = 48
    ```
    """
    profile = build_profile(
        _grades(
            {
                "tech_depth": "L2",
                "engineering": "L2",
                "business": "L1",
                "impact": "L1",
                "collaboration": "L0",
                "growth": "L1",
            }
        ),
        rubric,
        job_level="校招",
    )

    assert profile.weight_level == "campus"
    assert [d.score for d in profile.dimensions] == [65, 65, 35, 35, 0, 35]
    assert profile.overall == 48


def test_overall_weights_are_exposed_for_audit(rubric) -> None:
    """`weights` 必须一并返回 —— 否则「可审计」只能靠翻源码。"""
    profile = build_profile(_grades({"tech_depth": "L2"}), rubric, job_level="校招")

    assert profile.weights["tech_depth"] == pytest.approx(0.30)
    assert sum(profile.weights.values()) == pytest.approx(1.0)


def test_overall_uses_half_up_not_bankers_rounding(rubric) -> None:
    """**回归守卫**：`.5` 必须进位。

    社招档下只算两维：技术深度 L3 = 80（权重 .30）、工程能力 L2 = 65（权重 .30）

    ```
    (80×.30 + 65×.30) / (.30 + .30) = 43.5 / 0.6 = 72.5  →  四舍五入 73
    ```

    若改用内置 `round`（银行家舍入）会得到 **72** —— 差 1 分，且只在恰好 `.5` 时出现，
    平时怎么测都是对的。AC28 要求「手算复现」，口算的人一定会得到 73。
    """
    profile = build_profile(
        _grades({"tech_depth": "L3", "engineering": "L2"}), rubric, job_level="社招"
    )

    assert round(72.5) == 72, "前提：内置 round 是银行家舍入（这里只是把陷阱写进断言）"
    assert profile.overall == 73


def test_rounding_helper_agrees_with_matcher(rubric) -> None:
    """取整口径**全项目唯一**：`ability_profile` 与 `matcher.score_of` 共用同一个函数。

    `matcher.score_of(1, 8)` → `12.5%` → 四舍五入 13（银行家舍入会给 12）。
    """
    assert round_half_up(12.5) == 13
    assert score_of(1, 8) == 13
    assert overall_of({"a": 12.5, "b": None}, {"a": 1.0}) == 13


# ------------------------------------------------------------------ N2.2 缺维归一


def test_missing_dimension_is_null_and_overall_renormalizes(rubric) -> None:
    """N2.2：某维**算不出** → `score = null` + `evidence = ""`，`overall` 按**已有维度**归一。

    「算不出」在本实现里的触发点是**档位在 rubric 里查不到**（rubric 被改过、
    或组装层漏了白名单校验）。此时正确的反应是留空，**不是**当 0 分。

    手算：社招档，技术深度 L2 = 65（权重 .30）、工程能力档位非法 → 不参与

    ```
    65×.30 / .30 = 65          ← 分母只有 .30，不是 1.0
    ```
    若错误地把非法维度的权重留在分母：`19.5 / (.30+.30) = 32` —— 凭空少一半分。
    """
    grades = [
        DimensionGrade(key="tech_depth", level_key="L2", evidence="有实现", reason="r"),
        DimensionGrade(key="engineering", level_key="L_NOT_A_LEVEL", evidence="x", reason="r"),
    ]

    profile = build_profile(grades, rubric, job_level="社招")
    by_key = {d.key: d for d in profile.dimensions}

    assert by_key["engineering"].score is None
    assert by_key["engineering"].evidence == ""
    assert by_key["tech_depth"].score == 65
    assert profile.overall == 65


def test_all_dimensions_missing_yields_null_overall(rubric) -> None:
    """六维全算不出 → `overall = null`。**不是 0** —— 0 是一个结论，`null` 才是「没有结论」。"""
    grades = [
        DimensionGrade(key=key, level_key="NOPE", evidence="", reason="")
        for key, _ in DIMENSIONS
    ]

    profile = build_profile(grades, rubric, job_level="社招")

    assert profile.overall is None
    assert all(d.score is None for d in profile.dimensions)


def test_overall_of_ignores_unknown_and_zero_weight_keys() -> None:
    """`overall_of` 的边界：权重表里没有的键、权重为 0 的键，一律不参与。"""
    assert overall_of({"a": 80}, {}) is None
    assert overall_of({"a": 80}, {"a": 0.0}) is None
    assert overall_of({"a": 80, "b": None}, {"a": 0.5, "b": 0.5}) == 80


# ------------------------------------------------------------------ 权重是数据


def test_weights_follow_job_level(rubric) -> None:
    """同一个人、同一批档位，换岗位档位 → `overall` 变（权重是**数据**，不是代码）。

    这正是 DoD 12 的可验证形式：改权重只改 `rubric.yaml`，代码一行不动。
    """
    levels = {
        "tech_depth": "L2",
        "engineering": "L2",
        "business": "L1",
        "impact": "L3",
        "collaboration": "L0",
        "growth": "L1",
    }

    campus = build_profile(_grades(levels), rubric, job_level="校招")
    senior = build_profile(_grades(levels), rubric, job_level="高级")

    # 校招压 impact：同样拿 L3 的影响力，在校招档里被压得比高级档轻
    assert campus.weights["impact"] < senior.weights["impact"]
    assert campus.overall != senior.overall
    assert campus.weight_level == "campus" and senior.weight_level == "senior"


def test_unknown_job_level_falls_back_to_default(rubric) -> None:
    """识别不出 level → 退回中性档（`mid`），**不返回空权重**。

    空权重会让分母为 0、`overall` 变 `null` —— 用户看到的是「没有结论」，
    而真实原因是「岗位没标级别」。默认档比空表诚实。
    """
    profile = build_profile(_grades({"tech_depth": "L2"}), rubric, job_level="不知道是什么级")

    assert profile.weight_level == "mid"
    assert profile.overall == 65


# ------------------------------------------------------------------ AC27 出处


def test_every_score_carries_provenance(rubric) -> None:
    """**AC27**：每个维度分都必须挂 `rubricRef`；有分（>0）就必须有原文 `evidence`。

    `L0`（0 分、无证据）的 `evidence` 合法地为空 —— 「无证据」就是它的证据。
    """
    profile = build_profile(
        _grades(
            {
                "tech_depth": "L2",
                "engineering": "L2",
                "business": "L1",
                "impact": "L1",
                "collaboration": "L0",
                "growth": "L1",
            }
        ),
        rubric,
        job_level="校招",
    )

    for dimension in profile.dimensions:
        assert dimension.rubric_ref == f"{dimension.key}.{dimension.level_key}"
        if dimension.score:
            assert dimension.evidence.strip(), f"{dimension.key} 有分却没有出处"


def test_profile_is_deterministic(rubric) -> None:
    """AC30 的前置条件：同输入两次 → 六个分与 `overall` 完全一致。"""
    levels = {"tech_depth": "L2", "engineering": "L1", "impact": "L2"}

    first = build_profile(_grades(levels), rubric, job_level="校招")
    second = build_profile(_grades(levels), rubric, job_level="校招")

    assert [d.score for d in first.dimensions] == [d.score for d in second.dimensions]
    assert first.overall == second.overall


# ------------------------------------------------------------------ N2.3 候选集下发的权重


def test_weights_override_is_used_when_valid(rubric) -> None:
    """Java 装配的六维权重合法 → **采用它**（而不是 silently 忽略）。

    这条是 N2.3 的 Python 半边：契约上权重「来自岗位侧」，
    所以 Python 必须真的消费它，否则那个字段就只是装饰。
    """
    override = {
        "tech_depth": 0.10,
        "engineering": 0.10,
        "business": 0.10,
        "impact": 0.60,
        "collaboration": 0.05,
        "growth": 0.05,
    }
    grades = _grades({"tech_depth": "L1", "impact": "L3"})       # 40 与 88

    profile = build_profile(grades, rubric, job_level="校招", weights_override=override)

    assert profile.weights["impact"] == pytest.approx(0.60)
    # 用覆盖权重：(40×.10 + 88×.60) / (.10 + .60) = 56.8 / 0.7 = 81.14 → 81
    assert profile.overall == 81
    # 对照：用 rubric 的校招权重会得到 (40×.30 + 88×.10) / .40 = 52 ——
    # 两个值不同，才说明 override 真的生效了（而不是恰好撞上）。
    assert build_profile(grades, rubric, job_level="校招").overall == 52


def test_weights_override_is_rejected_when_it_does_not_sum_to_one(rubric) -> None:
    """权重不合法（六维不全 / 和 ≠ 1）→ **回退 rubric**，不按可疑权重算分。

    和 ≠ 1 是最阴的一种：`overall` 会被整体放大或缩小，而用户只看到一个具体数字，
    完全看不出它错了。所以宁可回退，也不将就。
    """
    bad = {"tech_depth": 0.9, "engineering": 0.9}                # 只有两维、和为 1.8

    profile = build_profile(
        _grades({"tech_depth": "L2"}), rubric, job_level="校招", weights_override=bad
    )

    assert profile.weights == rubric.weights_for("校招")
    assert profile.overall == 65


def test_weights_override_with_unknown_dimension_key_is_rejected(rubric) -> None:
    """多一个未知维度键同样拒绝 —— 说明上游改了维度集合却没同步契约。"""
    bad = dict(rubric.weights_for("校招"))
    bad["unknown_dim"] = 0.0

    profile = build_profile(
        _grades({"tech_depth": "L2"}), rubric, job_level="校招", weights_override=bad
    )

    assert "unknown_dim" not in profile.weights
