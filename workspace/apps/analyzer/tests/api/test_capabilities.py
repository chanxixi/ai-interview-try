"""GET /internal/capabilities —— 能力探测（part3 前端「深度」开关的判据）。

## 为什么这个接口值得单独一组用例

它是 `llm_enabled` 的**唯一对外出口**。前端看不到环境变量，只能靠探测；
一旦这里的取值规则漂移（例如把「三项齐全」放宽成「有 base_url 就算」），
表现不是报错，而是**前端在该禁用「深度」时放开了它** —— 用户拿到规则兜底的结果，
却以为那是 AI 判的。这类错误没有任何运行期信号，只能靠用例钉住。

## 为什么断言「等于 Settings().llm_enabled」而不写死 true/false

本地 `apps/analyzer/.env` 通常配了 LLM（CWD 相关），CI 则不配 ——
写死任一边都会让另一处环境红。这里断言的是**同源**：
接口的输出必须永远等于配置对象的判据，无论环境如何。
两侧分支再各自用 `dependency_overrides` 显式覆盖。
"""

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app


def _capabilities(client: TestClient) -> dict:
    resp = client.get("/internal/capabilities")
    assert resp.status_code == 200
    return resp.json()


def test_capabilities_mirrors_the_settings_switch(client: TestClient) -> None:
    """接口取值必须与 `Settings.llm_enabled` 逐字一致（同源，不各自实现一遍）。"""
    body = _capabilities(client)

    assert body == {"service": "analyzer", "llmEnabled": Settings().llm_enabled}


def test_capabilities_reports_disabled_when_llm_not_configured(client: TestClient) -> None:
    """三项缺失 → false。**不能默认 true**：猜错会让前端放开不可用的功能。"""
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_base_url="", llm_api_key="", llm_model=""
    )
    try:
        assert _capabilities(client)["llmEnabled"] is False
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_capabilities_reports_enabled_only_when_all_three_fields_present(client: TestClient) -> None:
    """三项齐全才算启用 —— 与 `Settings.llm_enabled` 是同一判据（缺一项即 false）。"""
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_base_url="http://gateway.invalid/v1", llm_api_key="k", llm_model="m"
    )
    try:
        assert _capabilities(client)["llmEnabled"] is True

        incomplete = lambda: Settings(  # noqa: E731 —— 只此一处，直接内联更清楚
            llm_base_url="http://gateway.invalid/v1", llm_api_key="k", llm_model=""
        )
        app.dependency_overrides[get_settings] = incomplete
        assert _capabilities(client)["llmEnabled"] is False
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_capabilities_does_not_leak_config_values(client: TestClient) -> None:
    """只暴露能力布尔值：`base_url` / `model` 等配置值绝不出现在响应里（spec §3.3）。"""
    assert set(_capabilities(client).keys()) == {"service", "llmEnabled"}
