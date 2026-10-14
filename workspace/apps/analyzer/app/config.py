"""应用配置：全部来自环境变量 / .env。

密钥绝不硬编码（spec.md §3.3）。LLM 三项留空时，服务自动走规则降级分支（ADR-004）。
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
        """三项齐全才算启用；否则一律走规则分支。"""
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
