"""BFF → analyzer 的内部请求（plan.md §3.3）。"""

from typing import Optional
from pydantic import BaseModel, Field
from app.core.constants import (
    ANALYSIS_DEPTHS,
    DEFAULT_ANALYSIS_DEPTH,
    JD_MAX_LENGTH,
    MAX_TOP_N,
    RESUME_MAX_LENGTH,
)


class AnalyzeRequest(BaseModel):
    """内部接口只收**已解析好的 jdText**。

    analyzer 不认 `jobId`，也就不可能去查岗位数据（spec.md §2.6）——
    「取 JD 原文」是 BFF 编排时找 job-service 要的，不是本服务的职责。

    长度上限与 spec.md §2.1 对齐：BFF 是第一道校验，这里是第二道
    （指南 §5.3 原则 8「入口校验过了，Service 内仍守住关键不变量」）。

    ## part3 增量（v0.4）：两个可选参数

    `analysisDepth` / `topN` 与 `bff-python.yaml` 的 `AnalyzeRequest` 逐字对应。
    它们**只对同步接口的契约完整性负责**：

    ⚠️ **同步接口只提供 part2 的形状**。`deep` 会产生「逐条判定 + 六维画像」，
    而那是**流式专有**的能力（`reviewed` 阶段本身就是 SSE 概念）。
    收发一条同步 HTTP 请求里塞进两次 LLM 往返，会把连接长时间挂住，
    也给不了一条进度反馈 —— 所以 `deep` 在同步入口**明确报 400**，
    而不是悄悄按 `standard` 返回（那是最坏的一种：调用方以为拿到了画像）。
    """

    resumeText: str = Field(min_length=1, max_length=RESUME_MAX_LENGTH)
    jdText: str = Field(min_length=1, max_length=JD_MAX_LENGTH)
    traceId: Optional[str] = None
    analysisDepth: str = Field(default=DEFAULT_ANALYSIS_DEPTH, description="；".join(ANALYSIS_DEPTHS))
    topN: Optional[int] = Field(default=None, ge=1, le=MAX_TOP_N)
