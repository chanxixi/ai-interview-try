"""内部接口 —— 统一 /internal 前缀，语义上标明「不对外」（plan.md §3.3）。

链路位置：Java(job-service) → 本服务。本服务是链路的最后一跳（再往下是 LLM）。

**本文件只做接线**：取依赖、把 DTO 交给 Service、把结果返回。
任何算法都不该出现在这里 —— 一旦出现 `re.findall(...)`，就是分层被穿透了（指南 §4.2）。
"""

import logging
import platform
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from app.core.config import Settings, get_settings, settings
from app.core.constants import TRACE_ID_HEADER
from app.core.wiring.dependencies import get_analysis_service
from app.core.observability.trace import get_trace_id
from app.schema.request.analyze_request import AnalyzeRequest
from app.schema.response.analyze_response import AnalysisDepth, AnalyzeResponse
from app.schema.response.health_response import CapabilitiesResponse, PingResponse
from app.service.orchestration.analysis_service import AnalysisService
from app.util.http.response import error_body

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


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> CapabilitiesResponse:
    """能力探测（part3）：上游据此决定可选功能是否放开。

    本接口是 `llm_enabled` 的**唯一对外出口** —— 前端看不到环境变量，
    不探测就只能猜「能不能做深度分析」，猜错的后果是：
    没配 LLM 也放开「深度」，用户会把规则兜底的结果当成 AI 产出的（spec §2.6 的诚实性要求）。

    **为什么用 `Depends(get_settings)` 而不是模块级 `settings`**：这里的分支
    （启用 / 未启用）是**行为契约**，必须有办法在测试里替换。默认二者是同一实例
    （`settings = get_settings()`），因此生产行为不受影响。
    """
    return CapabilitiesResponse(
        service=app_settings.service_name,
        llmEnabled=app_settings.llm_enabled,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    service: AnalysisServiceDep,
) -> AnalyzeResponse:
    """分析入口（spec.md §2.2 契约）。

    traceId 取值优先级：请求体（BFF 显式传递）→ 请求头（middleware 已写入 contextvar）。
    两者都没有时 `get_trace_id()` 会生成一个 —— 保证 `meta.traceId` 永远非空。

    ⚠️ **`deep` 只在流式接口提供**（part3 §2.2）：这里明确拒绝，而不是悄悄降级成
    `standard` —— 后者会让调用方以为拿到了画像，是比报错更糟的一种结果。
    """
    if payload.analysisDepth == AnalysisDepth.DEEP.value:
        raise HTTPException(
            status_code=400,
            detail=error_body(
                "INVALID_INPUT",
                "deep 分析只在流式接口 POST /api/internal/analyze/stream 提供",
            ),
        )
    return service.analyze(payload, payload.traceId or get_trace_id())
