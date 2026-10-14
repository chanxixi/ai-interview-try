"""应用配置 —— 全部来自环境变量 / .env。

密钥绝不硬编码（spec.md §3.3）。LLM 三项留空时，服务自动走规则降级分支（ADR-004）。

**关于 `env_file=".env"` 的解析位置**：pydantic-settings 按**进程当前工作目录**（CWD）
解析相对路径，**不是**按本文件位置。因此把本文件从 `app/config.py` 移到
`app/core/config.py` **不需要**调整路径 —— 只要仍从 `apps/analyzer/` 启动即可。
（这一点与 BFF 的 `config/env.ts` 相反：那里用 `__dirname` 定位，移动文件必须重算层级。）
容器与 CI 里一律由真实环境变量注入，`.env` 只服务于本地开发。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "analyzer"
    version: str = "0.1.0"
    port: int = 8000
    log_level: str = "INFO"

    # LLM（OpenAI-compatible 网关）。base_url 末尾不带斜杠。
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0

    @property
    def llm_enabled(self) -> bool:
        """三项齐全才算启用；否则一律走规则分支（ADR-004 的主动降级）。"""
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    """进程级单例。

    测试里若需要改配置，用 FastAPI 的 `app.dependency_overrides[get_settings]`
    覆盖依赖，而不是改这个缓存（`get_settings.cache_clear()` 亦可）。
    """
    return Settings()


#: 模块级实例，供非 Depends 场景（如 main.py 的启动日志）直接使用。
#: 新代码优先走 `Depends(get_settings)`，便于测试替换。
settings = get_settings()
