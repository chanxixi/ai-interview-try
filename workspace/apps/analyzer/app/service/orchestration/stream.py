"""流式分析编排（M4.3 / part3 N4.1）—— **一次流式分析的唯一编排位置**。

## 这个文件只做一件事：按 spec §2.4 的顺序发事件

`standard`（缺省，part2 行为一字不变）：

```
meta → stage(accepted) → stage(parsed) → stage(cleaned) → stage(normalized)
     → stage(matched) → stage(recommended) → stage(llm) → [thinking × n]
     → result → done
```

`deep`（part3 新增 `reviewed`，C5）：

```
… → stage(llm) → stage(reviewed) → [thinking × n] → result → done
```

算法全在别的文件里（`parser_plugin` / `cleaner` / `normalizer` / `matcher` /
`recommender` / `rules` / `advisor_rules` / `ability_profile` / `llm`），
这里只负责**顺序、时序、容错**。
一旦在这里看到 `re.findall(...)`，就是分层被穿透了。

## 三条硬性规则的实现方式（spec §2.4）

| 规则 | 怎么保证 |
|---|---|
| `meta` 首、`done` 尾 | 整个生成器包在 `try / except / finally`，`finally` **必定**发 `done` |
| 失败路径 `... → error → done` | `error` 在 except 里发，`done` 仍由 finally 发 —— 两者不耦合 |
| `error` 与 `result` 互斥 | `result` 只在 try 的正常末尾发一次；进过 except 就不会再发 |

## `reviewed` 阶段为什么**失败也不终止流**

spec §2.4 硬性规则 3：`stage.status = fail` 不终止流。判定 / 文案是**锦上添花**的一层：
它挂了最多让四块退化成规则兜底，而 `match` 与 `recommendations`（part2 的价值）一个都不会少。
把它做成致命错误，等于「为了让画像好看一点，牺牲掉整个分析」。

## 为什么 `parsed` 失败是唯一致命错误

spec §2.4 硬性规则 3：后续所有阶段都依赖「简历文本」—— 文本拿不到，
匹配 / 推荐 / LLM 全是在处理空字符串，产出的 `result` 是一堆 0 分，
比诚实报错更糟。

## 断连时为什么用 try 包住 `finally` 里的 yield

Python 的异步生成器被 `aclose()` 时，`finally` 里再 `yield` 会抛
`RuntimeError: async generator ignored GeneratorExit`。那不是 bug，是
「连接已经没了」的信号 —— 记一条日志就够，不让异常冒出去污染 ASGI 错误日志。
（对应 plan §6.3 的「BFF 写失败不抛全局」，同一件事在 Python 侧的模样。）

## 心跳怎么发

整条链里解析/清洗/匹配/推荐合计通常 <100ms，真正慢的只有等 LLM。
所以判断只写在两处 LLM 循环里：

- `llm` / 文案阶段：有 `thinking` 增量就检查一次间隔；
- **判定阶段（Prompt-3）：输出是 JSON，一条 `thinking` 都不发**，
  但客户端会吐 `LlmHeartbeat`（空壳、不带正文）—— 借它驱动心跳，
  否则一段 20s 的判定期间连接上零字节，代理可能直接把连接掐掉。

## 为什么解析和清洗走 `run_in_threadpool`

`pypdf` 是同步 CPU 密集操作，10 页约几十毫秒。直接 await 调用会**阻塞事件循环**，
期间心跳、其他请求全被卡住。丢进线程池后事件循环还能转 —— 这是异步生成器里
少有的「必须」而不是「讲究」。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from starlette.concurrency import run_in_threadpool

from app.core.constants import (
    DEFAULT_ANALYSIS_DEPTH,
    DEFAULT_TOP_N,
    MAX_TOP_N,
    RESUME_MAX_LENGTH,
    SSE_HEARTBEAT_SECONDS,
)
from app.core.errors.exceptions import AppException, ErrorCode
from app.core.observability.trace import get_trace_id
from app.schema.response.analyze_response import (
    AbilityDimension,
    AbilityProfile,
    AnalysisDepth,
    AnalyzeResponse,
    DeepAnalysisResult,
    DeepMeta,
    GrowthDirection,
    Improvement,
    Issue,
    MatchResult,
    Meta,
    NormalizedSkill,
    Recommendation,
    ResumeSections,
    ResumeView,
    Verdict,
    VerdictKind,
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
from app.service.profile.ability_profile import build_profile
from app.service.profile.advisor_rules import (
    ResumeFacts,
    directions_fallback,
    grade_dimensions,
    improvements_fallback,
    merge_levels,
    merge_verdicts,
    verdicts_from_match,
)
from app.service.document.cleaner import CleanResult, clean
from app.service.match.matcher import (
    MatchReport,
    Requirement,
    ResumeSkills,
    extract_requirements,
    match,
)
from app.service.skill.normalizer import SkillDictionary, SkillMention
from app.service.document.parser_plugin import ParseResult, ParserRegistry, default_registry
from app.service.match.recommender import JobCandidate, recommend
from app.service.profile.rubric import Rubric, dimension_keys_for_requirements, get_rubric
from app.service.advice.rules import detect_issues
from app.llm.events import LlmAdviceFinished, LlmClient, LlmEvent, LlmFinished, LlmHeartbeat, LlmReviewFinished, LlmThinking
from app.util.http.sse import format_event, format_ping

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
    #: part3 §2.2。缺省 `standard` ⇒ 响应与 part2 **逐字节一致**（AC25，一键回退）。
    analysis_depth: str = DEFAULT_ANALYSIS_DEPTH
    #: part3 C7。`None` = 沿用 part2 的常量 3（AC17 不被破坏）。
    top_n: int | None = None

    @property
    def source(self) -> Source:
        return Source.PDF if self.file_bytes is not None else Source.TEXT

    @property
    def is_deep(self) -> bool:
        """只有**显式**要 `deep` 才走新路径。

        用「等于 deep」而不是「不等于 standard」：将来若加第三档（如 `quick`），
        未知值会自动落回 standard，而不会意外走进还没实现的深层逻辑。
        """
        return self.analysis_depth == AnalysisDepth.DEEP.value

    @property
    def resolved_top_n(self) -> int:
        """实际生效的推荐条数上限。**缺省仍是 3**（`DEFAULT_TOP_N` = part2 常量）。"""
        if self.top_n is None:
            return DEFAULT_TOP_N
        return max(1, min(MAX_TOP_N, self.top_n))

    def target_candidate(self) -> JobCandidate | None:
        """目标岗位（用于取维度权重档位与 `level`）。没指定 jobId 时返回 `None`。"""
        if not self.job_id:
            return None
        for candidate in self.job_candidates:
            if candidate.jobId == self.job_id:
                return candidate
        return None

    def resolved_trace_id(self) -> str:
        """traceId 优先级：显式入参 → 请求上下文 → 现生成一个。"""
        return self.trace_id or get_trace_id()

from app.service.orchestration.frames import _Clock, _stage_frame
from app.service.orchestration.mappers import (
    _advice_brief,
    _direction_to_contract,
    _improvement_to_contract,
    _level_of_ref,
    _match_report_to_contract,
    _profile_to_contract,
    _recommendation_to_contract,
    _resume_view,
    _section_lines,
    _sha256_8,
    _verdict_to_contract,
)

# ---------------------------------------------------------------- 主流程


#: 「参数没传」与「显式传 None」是两件事。
#:
#: `rubric` 的缺省语义是「自己去看仓库里有没有」，而**显式 `None`** 的语义是
#: 「这次就是没有 rubric」（对应 plan §6.2 的 rubric 缺失降级路径）。
#: 用 `None` 兼作缺省值会让两条路径**在代码里长得一模一样**，
#: 于是「rubric 缺失」这条降级分支**永远测不到** —— 这是 part3 降级演练第 3 条
#: 第一次跑就暴露的问题（断言 `abilityProfile is None` 失败，因为参数被当成了「没传」）。
_RUBRIC_UNSET: object = object()


async def stream_analysis(
    request: StreamRequest,
    *,
    dictionary: SkillDictionary,
    llm: LlmClient,
    registry: ParserRegistry | None = None,
    heartbeat_seconds: float | None = None,
    rubric: Rubric | None | object = _RUBRIC_UNSET,
) -> AsyncIterator[str]:
    """按 spec §2.4 产出 SSE 帧。**yield 的是已经格式化好的字符串**。

    之所以在编排层就格式化，是因为 `finally` 里要保证发 `done` ——
    直接 yield 帧比「构造事件对象再交给端点格式化」少一层出错可能。
    测试用 `app.util.http.sse.parse_frames` 还原，走的正是前端那套解析规则。

    :param rubric: 缺省（不传）= 走 `rubric.get_rubric()` 的**宽容加载**（拿不到返回 `None`
                   → `abilityProfile = null`，不阻塞主流程）；显式传 `None` = 本次没有 rubric。
    """
    registry = registry or default_registry()
    if rubric is _RUBRIC_UNSET:
        rubric = get_rubric()
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
        job_found = False
        if request.job_id:
            # ⚠️ 这里**不能**写成「只要有 jobId 就算匹配」：JD 取不到时算出来的 `score=0`
            # 和「真的一个技能都没命中」在响应里**长得一模一样**，用户只会看到
            # 「匹配度 0」却不知道是自己填错了岗位 ID（真事：前端 placeholder 曾经
            # 写了不存在的 `job-java-01`，照抄的人永远看到 0 分且没有任何提示）。
            # 所以：jobId 在候选集里找不到 = 这个岗位无效 → **不产出 match**。
            for candidate in request.job_candidates:
                if candidate.jobId == request.job_id:
                    target_requirements = candidate.requirements
                    job_found = True
                    break
            if not job_found:
                logger.warning("jobId 不在候选集里，跳过匹配 (traceId=%s, jobId=%s)",
                               trace_id, request.job_id)
        elif request.jd_text:
            target_requirements = tuple(extract_requirements(dictionary, request.jd_text))

        match_report: MatchReport | None = None
        if (job_found if request.job_id else bool(request.jd_text)):
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
        # topN 缺省仍为 3（`DEFAULT_TOP_N`）⇒ AC17 不被破坏；显式传入时上限 10（C7 / AC35）。
        recommendations = recommend(
            request.job_candidates, resume_skills, top_n=request.resolved_top_n
        )
        yield _stage_frame(StageName.RECOMMENDED, StageStatus.OK, clock.elapsed_ms(),
                           candidateCount=len(request.job_candidates),
                           topN=request.resolved_top_n)

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

        # ---- stage: reviewed（**仅 deep**，C5 / N4.1）-------------------
        #
        # 事件顺序（spec §2.4）：`stage(reviewed, start)` → Prompt-3（**不发 thinking**）
        #   → Prompt-4（**发 thinking**）→ `stage(reviewed, ok)` → `result`。
        #
        # 为什么 `ok` 放在 Prompt-4 之后：契约把 `{verdictCount, directionCount}` 挂在
        # `reviewed` 的 detail 上，而 `directionCount` 要等文案阶段跑完才知道。
        # 于是 thinking 落在 start 与 ok 之间 —— 这不违反「判定阶段无 thinking」：
        # **Prompt-3 一条 thinking 都不发**（它的输出是 JSON），
        # 有 thinking 的那一段一定是 Prompt-4（spec §2.4 的硬性规定）。
        verdict_models: list[Verdict] = []
        improvement_models: list[Improvement] = []
        direction_models: list[GrowthDirection] = []
        ability_profile: AbilityProfile | None = None
        review_used = False

        if request.is_deep:
            yield _stage_frame(
                StageName.REVIEWED, StageStatus.START, clock.elapsed_ms(),
                requirementCount=match_report.total_count if match_report is not None else 0,
            )

            resume_facts = ResumeFacts(
                text=cleaned.text, sections=dict(cleaned.sections), skill_count=len(mentions)
            )
            target = request.target_candidate()

            # 骨架：**集合级事实**（`match`）。LLM 只能在这副骨架之上判档（plan §8 风险 1）。
            seed_verdicts = verdicts_from_match(match_report)
            fallback_grades = grade_dimensions(resume_facts, rubric) if rubric is not None else []
            allowed_levels = (
                {dimension.key: dimension.level_keys for dimension in rubric.dimensions}
                if rubric is not None
                else {}
            )
            # rubric 只注入**与本次岗位相关**的片段（N3.3）
            rubric_slice = (
                rubric.slice_for(dimension_keys_for_requirements(target_requirements))
                if rubric is not None
                else []
            )
            requirements_json = json.dumps(
                [
                    {"skill": item.skill, "importance": item.importance, "evidence": item.evidence}
                    for item in target_requirements
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )

            llm_verdicts = None
            llm_dimensions = None
            reviewed_degraded = False

            # ---- Prompt-3：判定 + 六维档（**不发 thinking**）------------
            last_emit = time.perf_counter()
            try:
                async for event in llm.stream_review(
                    cleaned.text,
                    requirements_json=requirements_json,
                    rubric_slice_json=json.dumps(rubric_slice, ensure_ascii=False, separators=(",", ":")),
                    allowed_levels=allowed_levels,
                    trace_id=trace_id,
                ):
                    if isinstance(event, LlmHeartbeat):
                        # 判定阶段不发正文，只借它驱动 SSE 心跳（否则 20s 零字节会被代理掐）
                        if time.perf_counter() - last_emit >= heartbeat_seconds:
                            yield format_ping()
                            last_emit = time.perf_counter()
                    elif isinstance(event, LlmReviewFinished):
                        llm_verdicts, llm_dimensions = event.verdicts, event.dimensions
                        # 「降级」的判据是**两块都没拿到**。只拿到维度（verdicts 被逐条刷光）
                        # 或只拿到判定，都仍然是部分成功 —— 那不是降级，不该置 fail。
                        if event.verdicts is None and event.dimensions is None:
                            reviewed_degraded = True
                            logger.info("llm review degraded (traceId=%s, reason=%s)",
                                        trace_id, event.degraded_reason)
            except Exception as exc:  # noqa: BLE001 —— reviewed 阶段永不当致命错误
                reviewed_degraded = True
                logger.warning("review stage raised, degrading (traceId=%s, type=%s)",
                               trace_id, type(exc).__name__)

            # ---- 合并：LLM 只能覆盖既有条目，不能增删 ---------------
            verdict_facts = merge_verdicts(seed_verdicts, llm_verdicts)
            grades = (
                merge_levels(fallback_grades, llm_dimensions, rubric)
                if rubric is not None
                else []
            )
            verdict_models = [_verdict_to_contract(item) for item in verdict_facts]

            profile = (
                build_profile(
                    grades,
                    rubric,
                    job_level=target.level if target is not None else None,
                    weights_override=target.dimension_weights if target is not None else None,
                )
                if rubric is not None
                else None
            )
            ability_profile = _profile_to_contract(profile) if profile is not None else None

            # ---- Prompt-4：优化点 + 提升方向（**发 thinking**）--------
            brief = _advice_brief(verdict_models, ability_profile.dimensions if ability_profile else [])
            llm_improvements = None
            llm_directions = None
            last_emit = time.perf_counter()
            try:
                async for event in llm.stream_advice(brief, trace_id=trace_id):
                    if isinstance(event, LlmThinking):
                        if time.perf_counter() - last_emit >= heartbeat_seconds:
                            yield format_ping()
                        yield SseEvent(type=SseEventType.THINKING,
                                       data=ThinkingData(delta=event.delta)).to_frame()
                        last_emit = time.perf_counter()
                    elif isinstance(event, LlmAdviceFinished):
                        llm_improvements, llm_directions = event.improvements, event.directions
                        if event.improvements is None and event.directions is None:
                            reviewed_degraded = True
                            logger.info("llm advice degraded (traceId=%s, reason=%s)",
                                        trace_id, event.degraded_reason)
            except Exception as exc:  # noqa: BLE001
                reviewed_degraded = True
                logger.warning("advice stage raised, degrading (traceId=%s, type=%s)",
                               trace_id, type(exc).__name__)

            # 优化点：LLM 给的就用，没给（或全被「逐字」校验刷掉）就用规则模板。
            # **两块分开降级**：模型可能只产出方向、产不出可落地的优化点，
            # 那种情况下把方向也一起丢掉是纯损失。
            if llm_improvements:
                improvement_models = [
                    Improvement(
                        area=item.area,
                        action=item.action,
                        evidence=item.evidence,
                        targets=list(item.targets),
                    )
                    for item in llm_improvements
                ]
            else:
                improvement_models = [
                    _improvement_to_contract(item)
                    for item in improvements_fallback(verdict_facts, issues, facts=resume_facts)
                ]

            if llm_directions:
                direction_models = [_direction_to_contract(item) for item in llm_directions]
            else:
                direction_models = [
                    _direction_to_contract(item) for item in directions_fallback(verdict_facts)
                ]

            review_used = not reviewed_degraded
            # `degraded` 是「有没有降级过」，不是「最终用的哪条路径」：
            # deep 模式下 review/advice 任一降级都必须置 true（spec §2.6 的语义）。
            degraded = degraded or reviewed_degraded
            llm_used = llm_used and review_used

            yield _stage_frame(
                StageName.REVIEWED,
                StageStatus.OK if not reviewed_degraded else StageStatus.FAIL,
                clock.elapsed_ms(),
                verdictCount=len(verdict_models),
                directionCount=len(direction_models),
                degraded=reviewed_degraded,
            )

        # ---- result（恰好一次）----------------------------------------
        meta_common = {
            "traceId": trace_id,
            "llmUsed": llm_used,
            "degraded": degraded,
            "elapsedMs": clock.elapsed_ms(),
            "source": request.source.value,
            "truncated": cleaned.truncated,
            "recommendationCount": len(recommendations),
        }
        if request.is_deep:
            result: AnalyzeResponse = DeepAnalysisResult(
                resume=_resume_view(cleaned.sections, mentions, dictionary),
                issues=issues,
                match=_match_report_to_contract(match_report) if match_report is not None else None,
                recommendations=[_recommendation_to_contract(r) for r in recommendations],
                meta=DeepMeta(
                    **meta_common,
                    analysisDepth=AnalysisDepth.DEEP,
                    verdictCount=len(verdict_models),
                    directionCount=len(direction_models),
                ),
                verdicts=verdict_models,
                improvements=improvement_models,
                growthDirections=direction_models,
                abilityProfile=ability_profile,
            )
        else:
            # ⚠️ `standard` 路径**构造的仍是 part2 的 `AnalyzeResponse`**：
            # 四个新键在这个模型上根本不存在，所以 AC25 的「逐字节一致」是**结构上**成立的，
            # 不是靠「记得别塞进去」。
            result = AnalyzeResponse(
                resume=_resume_view(cleaned.sections, mentions, dictionary),
                issues=issues,
                match=_match_report_to_contract(match_report) if match_report is not None else None,
                recommendations=[_recommendation_to_contract(r) for r in recommendations],
                meta=Meta(**meta_common),
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
