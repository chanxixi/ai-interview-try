"""GET /healthz（spec.md §2.8）。"""

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "analyzer"}


def test_healthz_does_not_expose_storage_field(client: TestClient) -> None:
    """analyzer **不拥有任何数据库**（spec.md §2.6 / §3.1）。

    job-service 的 healthz 会带 `storage` 字段（存储降级的唯一证据），
    analyzer 绝不能带 —— 一旦出现，说明有人把存储职责漏进了计算层。
    """
    assert "storage" not in client.get("/healthz").json()
