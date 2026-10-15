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
