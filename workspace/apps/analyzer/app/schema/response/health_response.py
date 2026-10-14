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
