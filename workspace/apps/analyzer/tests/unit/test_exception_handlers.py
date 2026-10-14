"""统一错误收口（spec.md §2.3）。

三条不变量：
- 错误响应体恒为 `{code, message, traceId}`，且 traceId 非空；
- 入参校验失败是 **400 INVALID_INPUT**（不是 FastAPI 默认的 422 —— 422 在契约里属于 ANALYSIS_FAILED）；
- 未预期错误不透传堆栈（spec.md §3.3）。
"""

from fastapi.testclient import TestClient

from app.core.constants import TRACE_ID_HEADER


def _assert_error_shape(body: dict, expected_code: str) -> None:
    assert set(body.keys()) == {"code", "message", "traceId"}
    assert body["code"] == expected_code
    assert body["message"]
    assert body["traceId"]


def test_missing_field_returns_400_invalid_input(client: TestClient) -> None:
    resp = client.post("/internal/analyze", json={"resumeText": "x"})

    assert resp.status_code == 400
    _assert_error_shape(resp.json(), "INVALID_INPUT")


def test_error_body_carries_trace_id_from_header(client: TestClient) -> None:
    resp = client.post(
        "/internal/analyze",
        json={"resumeText": "x"},
        headers={TRACE_ID_HEADER: "err-trace-1"},
    )

    assert resp.json()["traceId"] == "err-trace-1"


def test_oversized_resume_is_rejected(client: TestClient) -> None:
    """spec.md §2.1：resumeText ≤ 20000。analyzer 是第二道防线（BFF 是第一道）。"""
    resp = client.post("/internal/analyze", json={"resumeText": "x" * 20_001, "jdText": "y"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


def test_oversized_jd_is_rejected(client: TestClient) -> None:
    """spec.md §2.1：jdText ≤ 8000。"""
    resp = client.post("/internal/analyze", json={"resumeText": "x", "jdText": "y" * 8_001})

    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


def test_unexpected_error_does_not_leak_stack_trace(client: TestClient) -> None:
    """未预期异常 → 500 + 统一体，且不出现堆栈/异常类名（spec.md §3.3）。"""
    from app.core.dependencies import get_analysis_service
    from app.main import app

    class Exploding:
        def analyze(self, request, trace_id):  # noqa: ANN001, ANN201
            raise RuntimeError("内部实现细节不该出网")

    app.dependency_overrides[get_analysis_service] = lambda: Exploding()
    try:
        resp = client.post("/internal/analyze", json={"resumeText": "x", "jdText": "y"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    _assert_error_shape(resp.json(), "INTERNAL_ERROR")
    assert "RuntimeError" not in resp.text
    assert "内部实现细节" not in resp.text
