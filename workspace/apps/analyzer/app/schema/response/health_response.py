"""运维探针响应（非契约接口，字段可自由演进）。

`/healthz` 与 `/internal/ping` 都不在对外契约内（spec.md §2.2 只管分析接口），
但它们有实际消费者：Docker healthcheck、前端「链路自检」面板。
形状变了会直接打挂这两处，所以仍用 Pydantic 模型固定下来。
"""

from typing import Literal, Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """spec.md §2.8：每个服务暴露 GET /healthz。"""

    status: Literal["ok"] = "ok"
    service: str


class PingResponse(BaseModel):
    """连通性探针响应：证明本服务可达，并回显 traceId 以验证全链贯穿。"""

    service: str
    status: Literal["ok"] = "ok"
    version: str
    runtime: str
    traceId: Optional[str] = None


class CapabilitiesResponse(BaseModel):
    """能力探测响应（非契约接口）：本跳**在链路可达之后**还能做什么。

    与 {@link PingResponse} 的分工：`/ping` 回答「通不通」，本模型回答「通了能做什么」。

    `llmEnabled` 是 part3「深度分析」的唯一开关证据（`Settings.llm_enabled` 的对外投影）：
    前端据此决定要不要放开「深度」选项 —— 它看不到环境变量，不探测就只能猜。

    ⚠️ **只暴露能力布尔值，不暴露 `base_url` / `model` 等配置值**：
    配置是内部实现，泄露出去等于把「用哪个模型」变成对外承诺。
    """

    service: str
    llmEnabled: bool
