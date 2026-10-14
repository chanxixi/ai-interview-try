"""内部接口 —— 统一 /internal 前缀，语义上标明「不对外」（plan.md §3.3）。

链路位置：Java(job-service) → 本服务。本服务是链路的最后一跳（再往下是 LLM）。
"""

import logging
import platform
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header

from app.core.config import settings
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    MatchResult,
    Meta,
    PingResponse,
    ResumeView,
)

router = APIRouter(tags=["internal"])
logger = logging.getLogger(__name__)


@router.get("/ping", response_model=PingResponse)
async def ping(
    x_trace_id: Optional[str] = Header(default=None, alias="X-Trace-Id"),
) -> PingResponse:
    """连通性探针：回显 traceId，用于验证全链贯穿（spec.md §2.8）。"""
    logger.info("ping received", extra={"trace_id": x_trace_id})
    return PingResponse(
        service=settings.service_name,
        version=settings.version,
        runtime=f"python {platform.python_version()}",
        traceId=x_trace_id,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    """分析入口。

    骨架阶段返回**空结构**，仅用于打通链路与锁定契约形状。
    真实实现（清洗 → 归一化 → 匹配 → LLM 增强与降级）见 tasks.md T5。
    """
    started = time.perf_counter()
    trace_id = payload.traceId or str(uuid.uuid4())

    logger.info(
        "analyze stub called (resume=%d chars, jd=%d chars)",
        len(payload.resumeText),
        len(payload.jdText),
        extra={"trace_id": trace_id},
    )

    # TODO(T5)：清洗 → 归一化 → 匹配打分 → LLM 增强（失败则保持 degraded=True）
    return AnalyzeResponse(
        resume=ResumeView(),
        issues=[],
        match=MatchResult(score=0),
        meta=Meta(
            traceId=trace_id,
            llmUsed=False,
            degraded=True,
            elapsedMs=int((time.perf_counter() - started) * 1000),
        ),
    )
