"""契约形状快照 —— spec.md §2.2 的**冻结字段**。

这些用例的价值不在「验证功能」，而在「契约被改坏时立刻变红」。
字段名、层级一旦漂移，BFF 与前端会同时崩，而这类破坏在功能测试里常常看不出来。
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
    assert set(_analyze(client).keys()) == {"resume", "issues", "match", "meta"}


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
    assert set(_analyze(client)["match"].keys()) == {"score", "matched", "missing"}


def test_meta_carries_degradation_evidence(client: TestClient) -> None:
    """`llmUsed` / `degraded` 必须存在 —— 它们是 LLM 降级能力的**唯一证据**（spec.md §2.2）。"""
    meta = _analyze(client)["meta"]

    assert set(meta.keys()) == {"traceId", "llmUsed", "degraded", "elapsedMs"}
    assert meta["traceId"] == "shape-check"
    assert isinstance(meta["llmUsed"], bool)
    assert isinstance(meta["degraded"], bool)
    assert isinstance(meta["elapsedMs"], int)
