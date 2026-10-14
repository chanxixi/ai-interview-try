"""analyzer 骨架阶段的接口测试。

除验证可用性外，test_analyze_returns_frozen_contract_shape 同时锁定
spec.md §2.2 的冻结契约形状 —— 契约被改坏时该用例会红。
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "analyzer"}


def test_ping_echoes_trace_id():
    """traceId 必须在全链贯穿（spec.md §2.8）。"""
    resp = client.get("/internal/ping", headers={"X-Trace-Id": "test-trace-001"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["service"] == "analyzer"
    assert body["status"] == "ok"
    assert body["traceId"] == "test-trace-001"


def test_analyze_returns_frozen_contract_shape():
    resp = client.post(
        "/internal/analyze",
        json={
            "resumeText": "张三，3 年 Java 后端开发",
            "jdText": "熟悉 Spring Boot 与 MySQL",
            "traceId": "trace-abc",
        },
    )
    assert resp.status_code == 200

    body = resp.json()
    assert set(body.keys()) == {"resume", "issues", "match", "meta"}
    assert set(body["resume"]["sections"].keys()) == {
        "education",
        "experience",
        "projects",
        "skills",
    }
    assert set(body["match"].keys()) == {"score", "matched", "missing"}
    assert set(body["meta"].keys()) == {"traceId", "llmUsed", "degraded", "elapsedMs"}
    assert body["meta"]["traceId"] == "trace-abc"
