"""流式分析编排（M4.3）—— **一次流式分析的唯一编排位置**。

## 这个文件只做一件事：按 spec §2.4 的顺序发事件

```
meta → stage(accepted) → stage(parsed) → stage(cleaned) → stage(normalized)
     → stage(matched) → stage(recommended) → stage(llm) → [thinking × n]
     → result → done
```

算法全在别的文件里（`parser_plugin` / `cleaner` / `normalizer` / `matcher` /
`recommender` / `rules` / `llm`），这里只负责**顺序、时序、容错**。
一旦在这里看到 `re.findall(...)`，就是分层被穿透了。

## 三条硬性规则的实现方式（spec §2.4）

| 规则 | 怎么保证 |
|---|---|
| `meta` 首、`done` 尾 | 整个生成器包在 `try / except / finally`，`finally` **必定**发 `done` |
| 失败路径 `... → error → done` | `error` 在 except 里发，`done` 仍由 finally 发 —— 两者不耦合 |
| `error` 与 `result` 互斥 | `result` 只在 try 的正常末尾发一次；进过 except 就不会再发 |

## 为什么 `parsed` 失败是唯一致命错误

spec §2.4 硬性规则 3：`stage.status = fail` **不终止流**，仅致命阶段 `parsed`
失败才发 `error`。理由是后续所有阶段都依赖「简历文本」—— 文本拿不到，
匹配 / 推荐 / LLM 全是在处理空字符串，产出的 `result` 是一堆 0 分，
比诚实报错更糟。

## 断连时为什么用 try 包住 `finally` 里的 yield

Python 的异步生成器被 `aclose()` 时，`finally` 里再 `yield` 会抛
`RuntimeError: async generator ignored GeneratorExit`。那不是 bug，是
「连接已经没了」的信号 —— 记一条日志就够，不让异常冒出去污染 ASGI 错误日志。
（对应 plan §6.3 的「BFF 写失败不抛全局」，同一件事在 Python 侧的模样。）

## 心跳只在 LLM 阶段发

整条链里解析/清洗/匹配/推荐合计通常 <100ms，唯一真正慢的是等 LLM。
在其他阶段塞心跳判断只会增加没被测到的代码路径 —— 所以判断只写在 LLM 循环里。

## 为什么解析和清洗走 `run_in_threadpool`

`pypdf` 是同步 CPU 密集操作，10 页约几十毫秒。直接 await 调用会**阻塞事件循环**，
期间心跳、其他请求全被卡住。丢进线程池后事件循环还能转 —— 这是异步生成器里
少有的「必须」而不是「讲究」。
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from starlette.concurrency import run_in_threadpool

from app.core.constants import RESUME_MAX_LENGTH, SSE_HEARTBEAT_SECONDS
from app.core.exceptions import AppException, ErrorCode
from app.core.trace import get_trace_id
from app.schema.response.analyze_response import (
    AnalyzeResponse,
    Issue,
    MatchResult,
    Meta,
    NormalizedSkill,
    Recommendation,
    ResumeSections,
    ResumeView,
)
from app.schema.response.sse_event import (
    DoneData,
    ErrorData,
    MetaData,
    Source,
    SseEvent,
    SseEventType,
    StageData,
    StageName,
    StageStatus,
    ThinkingData,
)
from app.service.cleaner import CleanResult, clean
from app.service.matcher import (
    MatchReport,
    Requirement,
    ResumeSkills,
    extract_requirements,
    match,
)
from app.service.normalizer import SkillDictionary, SkillMention
from app.service.parser_plugin import ParseResult, ParserRegistry, default_registry
from app.service.recommender import JobCandidate, recommend
from app.service.rules import detect_issues
from app.llm.client import LlmClient, LlmEvent, LlmFinished, LlmThinking
from app.util.sse import format_event, format_ping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- 入参


@dataclass(frozen=True)
class StreamRequest:
    """流式分析的入参。字段与契约 `AnalyzeStreamRequest` 逐字对应。

    构造时就把「file 与 resumeText 二选一」这类不变量定死，
    后面的编排逻辑不需要再判空（指南 §5.3 原则 8：Service 内守住关键不变量）。
    """

    file_bytes: bytes | None = None
    file_name: str | None = None
    resume_text: str | None = None
    job_id: str | None = None
    jd_text: str | None = None
    job_candidates: tuple[JobCandidate, ...] = ()
    trace_id: str | None = None

    @property
    def source(self) -> Source:
        return Source.PDF if self.file_bytes is not None else Source.TEXT

    def resolved_trace_id(self) -> str:
        """traceId 优先级：显式入参 → 请求上下文 → 现生成一个。"""
        return self.trace_id or get_trace_id()


@dataclass
class _Clock:
    """阶段计时。用 `perf_counter`（单调时钟）而不是 `time.time` ——
    后者会被 NTP 校准改向后跳，可能算出负的 `elapsedMs`。"""

    started: float = 0.0

    def begin(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


# ---------------------------------------------------------------- 小工具


def _stage_frame(stage: StageName, status: StageStatus, elapsed_ms: int, **detail) -> str:
    return SseEvent(type=SseEventType.STAGE, data=StageData(
        stage=stage.value, status=status.value, elapsedMs=elapsed_ms, detail=detail
    )).to_frame()


def _sha256_8(data: bytes) -> str:
    """字节指纹前 8 位。**只记指纹不记内容**（spec §2.8：禁止日志打印简历正文）。"""
    return hashlib.sha256(data).hexdigest()[:8]


def _section_lines(section_text: str) -> list[str]:
    """章节文本 → 行列表。

    **为什么不能直接 `list(section_text)`**：`cleaner.split_sections()` 返回的是
    `dict[str, str]`（章节名 → 整段文本），而契约要求 `list[str]`。
    `list("2019.09-2023.06 某大学")` 会把它拆成**一个个字符** ——
    而且 Pydantic 的 `list[str]` 不会报错，它老老实实接受这个字符列表，
    于是响应体里出现 `"education": ["2","0","1","9",...]`。
    端到端 curl 一次才能看出来，单测里只断言 `isinstance(list)` 是抓不到的。
    """
    return [line.strip() for line in section_text.split("\n") if line.strip()]


def _resume_view(
    sections: dict[str, str],
    mentions: Sequence[SkillMention],
    dictionary: SkillDictionary,
) -> ResumeView:
    """把内部类型映射成契约形状。**这是唯一做字段名转换的地方**。"""
    return ResumeView(
        sections=ResumeSections(**{key: _section_lines(sections.get(key, "")) for key in
                                   ("education", "experience", "projects", "skills")}),
        skills=[
            NormalizedSkill(raw=m.raw, canonical=m.canonical, category=dictionary.category_of(m.canonical))
            for m in mentions
        ],
    )


def _match_report_to_contract(report: MatchReport) -> MatchResult:
    """`matcher.MatchReport` → 契约 `MatchResult`。**唯一的字段名转换点**。"""
    from app.schema.response.analyze_response import MatchedItem, MissingItem

    return MatchResult(
        score=report.score,
        matched=[
            MatchedItem(
                skill=item.skill,
                importance=item.importance,
                weight=item.weight,
                jdEvidence=item.jd_evidence,
                resumeEvidence=item.resume_evidence,
                jdOffset=item.jd_offset,
                resumeOffset=item.resume_offset,
            )
            for item in report.matched
        ],
        missing=[
            MissingItem(skill=item.skill, importance=item.importance, suggestion=item.suggestion)
            for item in report.missing
        ],
    )


def _recommendation_to_contract(item) -> Recommendation:
    from app.schema.response.analyze_response import (
        RecommendationMatchedItem,
        RecommendationMissingItem,
    )

    return Recommendation(
        jobId=item.jobId,
        title=item.title,
        company=item.company,
        level=item.level,
        score=item.score,
        matched=[
            RecommendationMatchedItem(skill=m.skill, importance=m.importance) for m in item.matched
        ],
        missing=[
            RecommendationMissingItem(skill=m.skill, importance=m.importance, suggestion=m.suggestion)
            for m in item.missing
        ],
        reason=item.reason,
    )


# ---------------------------------------------------------------- 主流程


async def stream_analysis(
    request: StreamRequest,
    *,
    dictionary: SkillDictionary,
    llm: LlmClient,
    registry: ParserRegistry | None = None,
    heartbeat_seconds: float | None = None,
) -> AsyncIterator[str]:
    """按 spec §2.4 产出 SSE 帧。**yield 的是已经格式化好的字符串**。

    之所以在编排层就格式化，是因为 `finally` 里要保证发 `done` ——
    直接 yield 帧比「构造事件对象再交给端点格式化」少一层出错可能。
    测试用 `app.util.sse.parse_frames` 还原，走的正是前端那套解析规则。
    """
    registry = registry or default_registry()
    clock = _Clock()
    clock.begin()
    trace_id = request.resolved_trace_id()
    if heartbeat_seconds is None:
        heartbeat_seconds = SSE_HEARTBEAT_SECONDS

    # ---- meta：建连后立刻发，必为首个（spec §2.4）-------------------
    yield SseEvent(type=SseEventType.META, data=MetaData(traceId=trace_id, source=request.source.value)).to_frame()

    result: AnalyzeResponse | None = None
    error_code: str | None = None
    error_message: str | None = None

    try:
        # ---- stage: accepted -----------------------------------------
        stage_started = clock.elapsed_ms()
        if request.file_bytes is not None:
            yield _stage_frame(StageName.ACCEPTED, StageStatus.START, stage_started,
                               bytes=len(request.file_bytes), sha256_8=_sha256_8(request.file_bytes))
        else:
            yield _stage_frame(StageName.ACCEPTED, StageStatus.START, stage_started,
                               chars=len(request.resume_text or ""))
        yield _stage_frame(StageName.ACCEPTED, StageStatus.OK, clock.elapsed_ms())

        # ---- stage: parsed（唯一致命阶段）-----------------------------
        parsed: ParseResult
        if request.file_bytes is not None:
            yield _stage_frame(StageName.PARSED, StageStatus.START, clock.elapsed_ms())
            try:
                parser = registry.detect(request.file_bytes)
                if parser is None:
                    raise AppException(
                        ErrorCode.UNSUPPORTED_FORMAT, "无法识别的文件格式", http_status=415
                    )
                # 同步 CPU 活丢进线程池，别阻塞事件循环（见模块 docstring）
                parsed = await run_in_threadpool(parser.parse, request.file_bytes)
                # ---- 「没有文本层」的**策略**落在这里（AC14）--------------------
                # 解析器只报事实（`has_text_layer=False` + 页数 + 抽到的字符），
                # 因为它自己不知道「上层要不要这份文件」。策略在这一层：**不达标就停**。
                # 继续往下走的后果不是「少几个技能」，而是一份看起来完全正常、
                # 却 0 技能 0 推荐的 result —— 用户会以为简历有问题，
                # 而真正的原因（文件是扫描件）被藏起来了。宁可明确报错。
                #
                # 为什么判定用 `has_text_layer` 而不是再算一次字符数：阈值
                # （`PDF_MIN_TEXT_LAYER_CHARS`）属于解析层的事实认定，上层复算一遍
                # 就有两个地方会漂移。
                if not parsed.has_text_layer:
                    raise AppException(
                        ErrorCode.PDF_NO_TEXT_LAYER,
                        "未检测到文本层：文件可能是扫描件或纯图片 PDF，请上传可复制的文本型 PDF",
                    )
            except AppException as exc:
                # 无论是「认不出格式」还是「解析器自己抛的领域错误」，都要留下 fail 记录 ——
                # 否则日志里只剩一个孤零零的 error 事件，看不出是哪一阶段炸的。
                yield _stage_frame(
                    StageName.PARSED, StageStatus.FAIL, clock.elapsed_ms(), code=exc.code.value
                )
                raise
            yield _stage_frame(StageName.PARSED, StageStatus.OK, clock.elapsed_ms(),
                               pageCount=parsed.page_count)
        else:
            # 纯文本入参：没有「解析」这一步，但仍要发 start + ok 一对 ——
            # 消费方不该为「文本入口」写特殊分支，否则前端阶段条会少一格。
            text = (request.resume_text or "")[:RESUME_MAX_LENGTH]
            yield _stage_frame(StageName.PARSED, StageStatus.START, clock.elapsed_ms())
            parsed = ParseResult(
                text=text, page_count=1, encrypted=False,
                has_text_layer=bool(text.strip()), document_format="text",
            )
            yield _stage_frame(StageName.PARSED, StageStatus.OK, clock.elapsed_ms(), chars=len(text))

        # ---- stage: cleaned ------------------------------------------
        yield _stage_frame(StageName.CLEANED, StageStatus.START, clock.elapsed_ms())
        cleaned: CleanResult = await run_in_threadpool(clean, parsed.text)
        yield _stage_frame(StageName.CLEANED, StageStatus.OK, clock.elapsed_ms(),
                           textLength=len(cleaned.text), truncated=cleaned.truncated)

        # ---- stage: normalized ---------------------------------------
        yield _stage_frame(StageName.NORMALIZED, StageStatus.START, clock.elapsed_ms())
        mentions = dictionary.extract_unique(cleaned.text)
        resume_skills = ResumeSkills(tuple(mentions))
        yield _stage_frame(StageName.NORMALIZED, StageStatus.OK, clock.elapsed_ms(),
                           skillCount=len(mentions))

        # ---- stage: matched ------------------------------------------
        # jobId / jdText 都可以不提供 —— 此时 match 为 null（part2 spec §2.2）
        target_requirements: tuple[Requirement, ...] = ()
        if request.job_id:
            for candidate in request.job_candidates:
                if candidate.jobId == request.job_id:
                    target_requirements = candidate.requirements
                    break
        elif request.jd_text:
            target_requirements = tuple(extract_requirements(dictionary, request.jd_text))

        match_report: MatchReport | None = None
        if target_requirements or request.job_id or request.jd_text:
            yield _stage_frame(StageName.MATCHED, StageStatus.START, clock.elapsed_ms())
            match_report = match(target_requirements, resume_skills)
            yield _stage_frame(StageName.MATCHED, StageStatus.OK, clock.elapsed_ms(),
                               score=match_report.score)
        else:
            # 跳过也要发 start + ok 一对：消费方（前端阶段条）不该为「没选岗位」
            # 写特殊分支，否则这一格会闪一下或者干脆不显示。
            yield _stage_frame(StageName.MATCHED, StageStatus.START, clock.elapsed_ms())
            yield _stage_frame(StageName.MATCHED, StageStatus.OK, clock.elapsed_ms(), skipped=True)

        # ---- stage: recommended --------------------------------------
        yield _stage_frame(StageName.RECOMMENDED, StageStatus.START, clock.elapsed_ms())
        recommendations = recommend(request.job_candidates, resume_skills)
        yield _stage_frame(StageName.RECOMMENDED, StageStatus.OK, clock.elapsed_ms(),
                           candidateCount=len(request.job_candidates))

        # ---- stage: llm ----------------------------------------------
        yield _stage_frame(StageName.LLM, StageStatus.START, clock.elapsed_ms())
        issues: list[Issue] = []
        llm_used = False
        degraded = True
        # 心跳只在 LLM 阶段发：这是整条链里**唯一真正慢**的阶段
        # （解析/清洗/匹配/推荐合计通常 <100ms，慢到需要心跳的程度只可能是等 LLM）。
        # 在其他阶段塞心跳判断只会增加没被测到的代码路径。
        last_emit = time.perf_counter()
        try:
            async for event in llm.stream_issues(cleaned.text, trace_id=trace_id):
                if isinstance(event, LlmThinking):
                    if time.perf_counter() - last_emit >= heartbeat_seconds:
                        yield format_ping()
                    yield SseEvent(type=SseEventType.THINKING, data=ThinkingData(delta=event.delta)).to_frame()
                    last_emit = time.perf_counter()
                elif isinstance(event, LlmFinished):
                    if event.issues is None:
                        # 降级：thinking 可能已经发了几条，但 issues 走规则兜底（AC15）
                        logger.info("llm degraded (traceId=%s, reason=%s)", trace_id, event.degraded_reason)
                        issues = detect_issues(cleaned.text, cleaned.sections)
                        llm_used, degraded = False, True
                    else:
                        issues = list(event.issues)
                        llm_used, degraded = True, False
        except Exception as exc:  # noqa: BLE001
            # **LLM 阶段永不当致命错误**（spec §2.4 硬性规则 3：只有 parsed 失败才发 error）。
            # 客户端本该自己把异常转成 `LlmFinished(issues=None)`，但那是「约定」不是「保证」——
            # 换个实现、或者将来有人在客户端里加了一段会抛的代码，这里就是最后一道防线。
            # 少了它，一个 LLM 抖动会让用户连 `recommendations` 都拿不到。
            logger.warning(
                "llm stage raised, degrading (traceId=%s, type=%s)", trace_id, type(exc).__name__
            )
            issues = detect_issues(cleaned.text, cleaned.sections)
            llm_used, degraded = False, True
        yield _stage_frame(StageName.LLM, StageStatus.OK, clock.elapsed_ms(),
                           llmUsed=llm_used, degraded=degraded)

        # ---- result（恰好一次）----------------------------------------
        result = AnalyzeResponse(
            resume=_resume_view(cleaned.sections, mentions, dictionary),
            issues=issues,
            match=_match_report_to_contract(match_report) if match_report is not None else None,
            recommendations=[_recommendation_to_contract(r) for r in recommendations],
            meta=Meta(
                traceId=trace_id,
                llmUsed=llm_used,
                degraded=degraded,
                elapsedMs=clock.elapsed_ms(),
                source=request.source.value,
                truncated=cleaned.truncated,
                recommendationCount=len(recommendations),
            ),
        )
        yield SseEvent(type=SseEventType.RESULT, data=result).to_frame()

    except AppException as exc:
        error_code = exc.code.value
        error_message = exc.message
        logger.info("stream failed with domain error (traceId=%s, code=%s)", trace_id, error_code)
    except Exception as exc:  # noqa: BLE001
        # 未预期异常也要走「error → done」，不能让连接悬挂（plan §6.3）。
        # 异常类型进日志，**不进响应体**（spec §3.3）。
        error_code = ErrorCode.ANALYSIS_FAILED.value
        error_message = "分析失败"
        logger.exception("stream failed unexpectedly (traceId=%s, type=%s)", trace_id, type(exc).__name__)
    finally:
        # 客户端提前断开时，Python 会在 finally 里 yield 的那一刻抛
        # `RuntimeError: async generator ignored GeneratorExit`。那不是 bug，是
        # 「连接已经没了」的正常信号 —— 记一条日志就够，不要让异常冒出去
        # 污染 ASGI 的错误日志（plan §6.3：BFF 写失败不抛全局，同一个道理）。
        try:
            if error_code is not None:
                yield SseEvent(type=SseEventType.ERROR, data=ErrorData(
                    code=error_code, message=error_message or "分析失败", traceId=trace_id
                )).to_frame()
            yield SseEvent(type=SseEventType.DONE, data=DoneData(elapsedMs=clock.elapsed_ms())).to_frame()
        except RuntimeError:
            logger.info("stream closed by peer before done (traceId=%s)", trace_id)
