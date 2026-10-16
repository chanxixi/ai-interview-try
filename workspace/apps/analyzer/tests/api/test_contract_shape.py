"""契约形状快照 —— part1 spec.md §2.2 + part2 spec §2.3 的**冻结字段**。

这些用例的价值不在「验证功能」，而在「契约被改坏时立刻变红」。
字段名、层级一旦漂移，BFF 与前端会同时崩，而这类破坏在功能测试里常常看不出来。

> **part2 增量**：顶层从四块变五块（+ `recommendations`），`meta` 多三个字段
> （`source` / `truncated` / `recommendationCount`）。这两个断言在 part1 时是四块，
> 现在按 part2 spec §2.3 更新 —— 属于**契约冻结后的正常演进**，
> 改动依据写在上面的 docstring 里，不留「不知道为什么变了」的坑。
"""

from fastapi.testclient import TestClient


def _analyze(client: TestClient) -> dict:
    resp = client.post(
        "/internal/analyze",
        json={"resumeText": "张三", "jdText": "Java", "traceId": "shape-check"},
    )
    assert resp.status_code == 200
    return resp.json()


def test_top_level_shape(client: TestClient) -> None:
    """五块结构（part2 spec §2.3）：part1 四块 + `recommendations`。"""
    assert set(_analyze(client).keys()) == {
        "resume",
        "issues",
        "match",
        "recommendations",
        "meta",
    }


def test_resume_section_keys_are_frozen(client: TestClient) -> None:
    body = _analyze(client)

    assert set(body["resume"]["sections"].keys()) == {
        "education",
        "experience",
        "projects",
        "skills",
    }
    assert isinstance(body["resume"]["skills"], list)


def test_match_shape(client: TestClient) -> None:
    """`match` 的形状。注意 part2 起它**可空** —— 这里同步接口总是返回对象，
    可空那条由流式测试覆盖（未指定 jobId/jdText 时必须是 `null`）。
    """
    assert set(_analyze(client)["match"].keys()) == {"score", "matched", "missing"}


def test_recommendations_shape(client: TestClient) -> None:
    """`recommendations` 字段必须有（可为空数组），且每条的形状冻结（part2 spec §2.3）。"""
    body = _analyze(client)

    assert isinstance(body["recommendations"], list)
    # 同步 stub 不给候选集，所以是空数组 —— 但字段必须在
    assert body["recommendations"] == []


def test_meta_carries_degradation_evidence(client: TestClient) -> None:
    """`llmUsed` / `degraded` 必须存在 —— 它们是 LLM 降级能力的**唯一证据**（spec.md §2.2）。"""
    meta = _analyze(client)["meta"]

    assert set(meta.keys()) == {
        "traceId",
        "llmUsed",
        "degraded",
        "elapsedMs",
        # part2 新增三个
        "source",
        "truncated",
        "recommendationCount",
    }
    assert meta["traceId"] == "shape-check"
    assert isinstance(meta["llmUsed"], bool)
    assert isinstance(meta["degraded"], bool)
    assert isinstance(meta["elapsedMs"], int)
    assert meta["source"] in ("pdf", "text")
    assert isinstance(meta["truncated"], bool)
    assert isinstance(meta["recommendationCount"], int)


# ------------------------------------------------------------------ part3：深模型的形状边界


def test_standard_sync_response_has_no_part3_keys(client: TestClient) -> None:
    """**AC25 的同步侧**：同步端点（part2 形状）绝不出现 part3 的键。

    这条守的是「两个模型」的设计：`AnalyzeResponse` 上根本没有那 4 个字段，
    所以哪怕有人把 `DeepAnalysisResult` 顺手塞进 `response_model`，这里也会红。
    """
    body = _analyze(client)

    for key in ("verdicts", "improvements", "growthDirections", "abilityProfile"):
        assert key not in body
    for key in ("analysisDepth", "verdictCount", "directionCount"):
        assert key not in body["meta"]


def test_deep_result_declares_part3_blocks_without_touching_part2_ones() -> None:
    """`DeepAnalysisResult` 必须是「part2 五块 + part3 四块」，且**继承**自 part2 模型。"""
    from app.schema.response.analyze_response import (
        AnalyzeResponse,
        DeepAnalysisResult,
        DeepMeta,
        Meta,
    )

    assert issubclass(DeepAnalysisResult, AnalyzeResponse)
    assert issubclass(DeepMeta, Meta)

    deep_fields = set(DeepAnalysisResult.model_fields)
    part2_fields = set(AnalyzeResponse.model_fields)
    assert part2_fields <= deep_fields
    assert deep_fields - part2_fields == {
        "verdicts",
        "improvements",
        "growthDirections",
        "abilityProfile",
    }
    assert set(DeepMeta.model_fields) - set(Meta.model_fields) == {
        "analysisDepth",
        "verdictCount",
        "directionCount",
    }


def test_frozen_enums_match_their_constants() -> None:
    """枚举与 `core/constants.py` 的元组必须一致 —— 同一份契约的两种表达，防两处漂移。"""
    from app.core.constants import ANALYSIS_DEPTHS, VERDICT_KINDS
    from app.schema.response.analyze_response import AnalysisDepth, VerdictKind

    assert tuple(item.value for item in AnalysisDepth) == ANALYSIS_DEPTHS
    assert tuple(item.value for item in VerdictKind) == VERDICT_KINDS


def test_sse_stage_enum_matches_the_contract_enum() -> None:
    """`StageName` 的顺序即契约里 `SseStageName.enum` 的顺序（`reviewed` 必须在末尾）。"""
    from app.schema.response.sse_event import STAGE_ORDER, StageName

    assert [stage.value for stage in STAGE_ORDER] == [stage.value for stage in StageName]
    assert STAGE_ORDER[-1] is StageName.REVIEWED
