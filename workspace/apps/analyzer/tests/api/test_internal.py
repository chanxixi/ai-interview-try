"""内部接口（plan.md §3.3）。"""

from fastapi.testclient import TestClient
from app.core.constants import TRACE_ID_HEADER


def test_ping_echoes_trace_id(client: TestClient) -> None:
    """traceId 必须在全链贯穿（spec.md §2.8）。"""
    resp = client.get("/internal/ping", headers={TRACE_ID_HEADER: "test-trace-001"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "analyzer"
    assert body["status"] == "ok"
    assert body["traceId"] == "test-trace-001"


def test_ping_works_without_trace_id_header(client: TestClient) -> None:
    """缺失 header 时不应 5xx；traceId 字段允许为 null（探针是诊断工具）。"""
    resp = client.get("/internal/ping")

    assert resp.status_code == 200
    assert resp.json()["traceId"] is None


def test_analyze_returns_ok_with_frozen_top_level_keys(client: TestClient) -> None:
    resp = client.post(
        "/internal/analyze",
        json={
            "resumeText": "张三，3 年 Java 后端开发",
            "jdText": "熟悉 Spring Boot 与 MySQL",
            "traceId": "trace-abc",
        },
    )

    assert resp.status_code == 200
    # part2 spec §2.3：五块（part1 四块 + recommendations）
    assert set(resp.json().keys()) == {
        "resume",
        "issues",
        "match",
        "recommendations",
        "meta",
    }


def test_analyze_uses_body_trace_id_over_contextvar(client: TestClient) -> None:
    """body 里的 traceId 优先级高于 header（BFF 显式传递时以它为准）。"""
    resp = client.post(
        "/internal/analyze",
        json={"resumeText": "a", "jdText": "b", "traceId": "from-body"},
        headers={TRACE_ID_HEADER: "from-header"},
    )

    assert resp.json()["meta"]["traceId"] == "from-body"
