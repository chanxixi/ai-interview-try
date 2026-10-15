"""pytest 共享夹具。

**打桩策略**：本服务没有下游依赖（链路最后一跳），所以绝大多数用例直接打真实实现；
需要替换 Service 时用 `app.dependency_overrides[get_analysis_service]`
（组合根在 `core/dependencies.py`），不要 monkeypatch 模块内部。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _find_up(start: Path, relative: str) -> Path | None:
    """从 `start` 逐级向上找 `relative` 指向的目录，找不到返回 None。

    **为什么不用写死的相对路径**：测试文件在 `apps/analyzer/tests/`，
    而被测的仓库产物在 `workspace/db/seed/jobs`、`脱敏资料/` —— 差三层。
    写死 `../../..` 的话，将来 tests/ 下多加一层目录（比如 `tests/unit/matcher/`）
    所有路径静默错位，报出来的还是「文件不存在」这种离题的错误。
    """
    for candidate in (start, *start.parents):
        target = candidate / relative
        if target.is_dir():
            return target
    return None


@pytest.fixture(scope="session")
def seed_jobs_dir() -> Path:
    """`workspace/db/seed/jobs` —— 岗位种子 JSON（一岗一文件）。"""
    found = _find_up(Path(__file__).resolve(), Path("db") / "seed" / "jobs")
    if found is None:
        pytest.fail("找不到 workspace/db/seed/jobs —— 种子数据应该在仓库里")
    return found


@pytest.fixture(scope="session")
def real_resume_dir() -> Path | None:
    """仓库根的 `脱敏资料/`（20 份真实 PDF）。

    **缺失时返回 None 而不是 fail**：真实样本是**门禁**不是**前提** ——
    克隆仓库时可能不带这批文件（体积 / 隐私），此时应跳过相关用例，
    而不是让整套测试红掉。返回 None 后由用例自己 `pytest.skip`。
    """
    return _find_up(Path(__file__).resolve(), "脱敏资料")


@pytest.fixture
def client() -> TestClient:
    """共享 TestClient。

    `raise_server_exceptions=False`：让未预期异常走我们注册的 `Exception` handler，
    而不是被 TestClient 直接抛出 —— 否则「500 兜底返回统一错误体」这条契约测不到。
    """
    return TestClient(app, raise_server_exceptions=False)
