"""内部接口 —— 统一 /internal 前缀，语义上标明「不对外」（plan.md §3.3）。

链路位置：Java(job-service) → 本服务。本服务是链路的最后一跳（再往下是 LLM）。

**本文件只做接线**：取依赖、把 DTO 交给 Service、把结果返回。
任何算法都不该出现在这里 —— 一旦出现 `re.findall(...)`，就是分层被穿透了（指南 §4.2）。
"""

import logging
import platform
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header

from app.core.config import settings
from app.core.constants import TRACE_ID_HEADER
from app.core.dependencies import get_analysis_service
from app.core.trace import get_trace_id
from app.schema.request.analyze_request import AnalyzeRequest
from app.schema.response.analyze_response import AnalyzeResponse
from app.schema.response.health_response import PingResponse
from app.service.analysis_service import AnalysisService

router = APIRouter(tags=["internal"])
logger = logging.getLogger(__name__)

AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]


@router.get("/ping", response_model=PingResponse)
async def ping(
    x_trace_id: Optional[str] = Header(default=None, alias=TRACE_ID_HEADER),
) -> PingResponse:
    """连通性探针：回显 traceId，用于验证全链贯穿（spec.md §2.8）。"""
    logger.info("ping received")
    return PingResponse(
        service=settings.service_name,
        version=settings.version,
        runtime=f"python {platform.python_version()}",
        traceId=x_trace_id,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    service: AnalysisServiceDep,
) -> AnalyzeResponse:
    """分析入口（spec.md §2.2 契约）。

    traceId 取值优先级：请求体（BFF 显式传递）→ 请求头（middleware 已写入 contextvar）。
    两者都没有时 `get_trace_id()` 会生成一个 —— 保证 `meta.traceId` 永远非空。
    """
    return service.analyze(payload, payload.traceId or get_trace_id())
