"""分析编排 —— 清洗 → 归一化 → 匹配 →（可选）LLM 增强。

**骨架阶段**：返回与契约形状一致的空结构，用于打通链路。
真实算法由 tasks.md T5 填充，但**编排位置从现在就定死**：
controller 只管接线，算法与降级决策都在这里。

**依赖注入方式**：`create_analysis_service()` 是唯一把各模块接起来的地方
（组合根，与 BFF 的 `container.ts`、Java 的构造器注入是同一个思路）。
本函数现在无参数，T5 会接收 `dictionary` 与 `llm` 两个依赖。
"""

import logging
import time
from typing import Protocol
from app.schema.request.analyze_request import AnalyzeRequest
from app.schema.response.analyze_response import (
    AnalyzeResponse,
    MatchResult,
    Meta,
    ResumeView,
)

logger = logging.getLogger(__name__)


class AnalysisService(Protocol):
    """Service 的对外契约（Protocol 而非 ABC：不强制继承，便于测试替身）。"""

    def analyze(self, request: AnalyzeRequest, trace_id: str) -> AnalyzeResponse: ...


def create_analysis_service() -> AnalysisService:
    """组合根：装配依赖并返回实现。

    T5 会扩展签名为 `create_analysis_service(*, dictionary, llm)`，
    届时只需改 `core/dependencies.py` 一处 —— 这正是把装配收在一处的价值。
    """

    class _AnalysisService:
        def analyze(self, request: AnalyzeRequest, trace_id: str) -> AnalyzeResponse:
            started = time.perf_counter()

            logger.info(
                "analyze stub called (resume=%d chars, jd=%d chars)",
                len(request.resumeText),
                len(request.jdText),
            )

            # TODO(T5)：cleaner.clean → normalizer.normalize → matcher.match
            #          → rules.detect → llm.enrich（失败则保持 degraded=True，AC3）
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

    return _AnalysisService()
