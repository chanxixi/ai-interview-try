"""流式分析端点（M4.6）—— `POST /api/internal/analyze/stream`。

**本文件只做接线**：解析 multipart → 构造 `StreamRequest` → 交给编排层 →
用 `StreamingResponse` 把帧吐出去。任何算法都不该出现在这里。

## 三个响应头，一个都不能少

| 头 | 值 | 少了会怎样 |
|---|---|---|
| `Content-Type` | `text/event-stream` | 前端 `fetch` 的 `ReadableStream` 拿不到分帧依据 |
| `Cache-Control` | `no-cache` | 代理层可能缓存整条流，第二次请求直接回放旧结果 |
| `X-Accel-Buffering` | `no` | **Nginx 默认缓冲 SSE**，事件被攒批，前端几秒才收到一次 —— 最阴的一个 |

## 为什么入参用 `Form(...)` 而不是 Pydantic 模型

契约规定这是 `multipart/form-data`（要传二进制文件）。
Pydantic 模型描述不了「文件部分」，所以逐字段声明。
第二道校验仍要做（指南 §5.3 原则 8）：`file` 与 `resumeText` 至少一个。

## 错误分界线（spec §2.5）

**建流前能判定的**（大小 / 类型）走**同步 HTTP** —— 在 handler 里抛 `HTTPException`，
统一异常处理器收口成 `{code, message, traceId}`；
**必须读完文件才知道的**（损坏 / 加密 / 无文本层 / 页数）走 **SSE `error` 事件** ——
那已经发生在流建立之后，只能由编排层发。
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.constants import RESUME_MAX_LENGTH, TRACE_ID_HEADER
from app.core.dependencies import get_dictionary, get_llm_client
from app.llm.client import LlmClient
from app.service.analysis_stream_service import StreamRequest, stream_analysis
from app.service.matcher import Requirement
from app.service.normalizer import SkillDictionary
from app.service.recommender import JobCandidate
from app.util.response import error_body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["internal"])

DictionaryDep = Annotated[SkillDictionary, Depends(get_dictionary)]
LlmDep = Annotated[LlmClient, Depends(get_llm_client)]

#: 上传大小上限。**第二道校验** —— 第一道在 BFF（建流前同步拒绝，spec §2.5）。
#: analyzer 侧保留是為了「端点被直接调用时也有明确出口」，与 `FILE_MAX_BYTES` 同值。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _parse_candidates(raw: Optional[str]) -> tuple[JobCandidate, ...]:
    """把 multipart 里的 `jobCandidates` JSON 字符串解析成候选集。

    **解析失败返回空元组而不是抛错**：候选集是「推荐」的输入，不是「分析」的输入。
    为它让整条流失败，用户会连 `match` 都拿不到 —— 那不划算。
    （正常情况下它由 Java 装配，不会坏；坏了一定是上游 bug，所以记 WARN 让日志能查到。）
    """
    if not raw or not raw.strip():
        return ()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("jobCandidates is not valid JSON, ignoring (len=%d)", len(raw))
        return ()
    if not isinstance(payload, list):
        logger.warning("jobCandidates is not a JSON array, ignoring")
        return ()

    candidates: list[JobCandidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        job_id, title = item.get("jobId"), item.get("title")
        if not job_id or not title:
            continue

        requirements: list[Requirement] = []
        for raw_requirement in item.get("requirements") or []:
            if not isinstance(raw_requirement, dict):
                continue
            skill = raw_requirement.get("skill")
            importance = raw_requirement.get("importance")
            if not skill or importance not in ("required", "preferred"):
                continue
            requirements.append(
                Requirement(
                    skill=str(skill),
                    importance=importance,
                    evidence=str(raw_requirement.get("evidence") or ""),
                    jd_offset=raw_requirement.get("jdOffset"),
                    skill_raw=raw_requirement.get("skillRaw"),
                )
            )

        candidates.append(
            JobCandidate(
                jobId=str(job_id),
                title=str(title),
                company=item.get("company"),
                level=item.get("level"),
                category=item.get("category"),
                requirements=tuple(requirements),
            )
        )
    return tuple(candidates)


@router.post("/analyze/stream")
async def analyze_stream(
    file: Annotated[Optional[UploadFile], File()] = None,
    resumeText: Annotated[Optional[str], Form()] = None,
    jobId: Annotated[Optional[str], Form()] = None,
    jdText: Annotated[Optional[str], Form()] = None,
    jobCandidates: Annotated[Optional[str], Form()] = None,
    x_trace_id: Annotated[Optional[str], Header(alias=TRACE_ID_HEADER)] = None,
    dictionary: DictionaryDep = None,  # type: ignore[assignment]
    llm: LlmDep = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """流式分析（part2 spec §2.2 / §2.4）。

    事件序列：`meta → stage×7 → [thinking…] → result → done`。
    """
    file_bytes: bytes | None = None
    file_name: Optional[str] = None
    if file is not None:
        file_bytes = await file.read()
        file_name = file.filename
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=error_body("FILE_TOO_LARGE", "文件超过 10 MB")
            )

    if file_bytes is None and not (resumeText or "").strip():
        raise HTTPException(
            status_code=400,
            detail=error_body("INVALID_INPUT", "file 与 resumeText 至少提供一个"),
        )

    stream_request = StreamRequest(
        file_bytes=file_bytes,
        file_name=file_name,
        resume_text=(resumeText or "")[:RESUME_MAX_LENGTH] if resumeText else None,
        job_id=jobId,
        jd_text=jdText,
        job_candidates=_parse_candidates(jobCandidates),
        trace_id=x_trace_id,
    )

    async def frames():
        async for frame in stream_analysis(stream_request, dictionary=dictionary, llm=llm):
            yield frame

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            TRACE_ID_HEADER: stream_request.resolved_trace_id(),
        },
    )
