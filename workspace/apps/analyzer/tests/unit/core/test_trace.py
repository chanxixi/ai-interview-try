"""traceId 上下文（spec.md §2.8）。

重点验证两件事：
1. 上游 header 被回写（全链可核对的证据）；
2. **请求结束后 contextvar 被 reset** —— 否则下一个请求会串上上一个的 traceId，
   这类 bug 只在并发下暴露，靠人工点页面很难发现。
"""

from fastapi.testclient import TestClient
from app.core.constants import TRACE_ID_HEADER
from app.core.observability.trace import get_trace_id, peek_trace_id


def test_header_is_echoed_back(client: TestClient) -> None:
    resp = client.get("/healthz", headers={TRACE_ID_HEADER: "trace-from-upstream"})

    assert resp.headers[TRACE_ID_HEADER] == "trace-from-upstream"


def test_id_is_generated_when_header_absent(client: TestClient) -> None:
    resp = client.get("/healthz")

    generated = resp.headers.get(TRACE_ID_HEADER)
    assert generated
    assert len(generated) == 36  # UUID4 的字符串形式


def test_context_is_reset_after_request(client: TestClient) -> None:
    """请求结束后 contextvar 必须回到空 —— 证明 reset(token) 生效。"""
    client.get("/healthz", headers={TRACE_ID_HEADER: "trace-outside"})

    assert peek_trace_id() is None


def test_get_trace_id_never_returns_empty() -> None:
    """契约字段必须非空（spec.md §2.3）：无上下文时生成临时 id，但不写回。"""
    assert get_trace_id()
    assert peek_trace_id() is None
