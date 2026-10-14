"""pytest 共享夹具。

**打桩策略**：本服务没有下游依赖（链路最后一跳），所以绝大多数用例直接打真实实现；
需要替换 Service 时用 `app.dependency_overrides[get_analysis_service]`
（组合根在 `core/dependencies.py`），不要 monkeypatch 模块内部。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """共享 TestClient。

    `raise_server_exceptions=False`：让未预期异常走我们注册的 `Exception` handler，
    而不是被 TestClient 直接抛出 —— 否则「500 兜底返回统一错误体」这条契约测不到。
    """
    return TestClient(app, raise_server_exceptions=False)
