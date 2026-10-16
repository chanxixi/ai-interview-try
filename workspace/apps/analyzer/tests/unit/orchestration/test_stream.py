"""流式分析（M4.3 / M4.6 / M4.7）—— spec §2.4 的硬性规则逐条断言。

**这一批用例的重点不是「能出结果」，而是「协议没被破坏」**：

| 规则 | 用例 |
|---|---|
| `meta` 首、`done` 尾 | `test_event_sequence_*` |
| stage 齐全且按冻结顺序 | `test_stage_sequence_matches_frozen_order` |
| `error` 与 `result` 互斥 | `test_error_and_result_are_mutually_exclusive` |
| 失败路径 `error → done` | `test_parse_failure_still_emits_done` |
| LLM 降级照常出 result | `test_llm_degradation_*` |
| 确定性 | `test_two_runs_produce_identical_result` |

解析帧用 `app.util.http.sse.parse_frames` —— **和服务端发帧用的是同一份代码**，
这样「服务端怎么发」和「消费端怎么解」不会各写一遍然后对不上。
"""

from __future__ import annotations
import json
from typing import AsyncIterator
import pytest
from app.core.errors.exceptions import AppException, ErrorCode
from app.llm.events import LlmClient, LlmEvent, LlmFinished, LlmThinking
from app.schema.response.sse_event import STAGE_ORDER, SseEventType, StageName
from app.service.orchestration.stream import StreamRequest, stream_analysis
from app.service.match.matcher import Requirement
from app.service.skill.normalizer import get_dictionary
from app.service.match.recommender import JobCandidate
from app.util.http.sse import parse_frames

#: 全部用例都是 async —— 用 **anyio** 的 pytest 插件驱动，不引 `pytest-asyncio`。
#: anyio 已经作为 starlette/fastapi 的传递依赖装在环境里，再装一个专用插件
#: 只是为同一个能力多加一个需要升级的依赖。anyio 的 `anyio_backend` 夹具默认就是 asyncio。
pytestmark = pytest.mark.anyio

#: 章节标题**独立成行**、章节之间空行 —— 这是 `cleaner.split_sections()` 认标题的
#: 前提（「归一化后与别名精确相等」，见 test_cleaner.py）。写成
#: 「教育背景：2019.09-…」这种同行写法会整段落进 `header`，测不出章节切分。
RESUME = (
    "个人信息\n张三，电话 13800138000\n\n"
    "教育背景\n2019.09-2023.06 某大学 计算机科学与技术\n\n"
    "专业技能\nJava、Spring Boot、MySQL、Redis、Vue\n\n"
    "项目经历\n负责订单系统重构，接口耗时从 800ms 降到 120ms\n\n"
    "工作经历\n2023.07-2024.06 某公司 后端开发工程师\n"
)


class _FakeLlm:
    """可编排的 LLM 替身：issues（Prompt-2）、判定（Prompt-3）、文案（Prompt-4）三段都能按脚本吐。

    不继承 `LlmClient`（它是 Protocol）—— 结构对了就能用，
    这正是 Protocol 相对 ABC 的价值。

    part3 起多两个方法。**判定段故意只吐 `LlmHeartbeat`（不带正文）**，
    与真实客户端一致：Prompt-3 的输出是 JSON，spec §2.4 明确不发 `thinking`。
    """

    def __init__(
        self,
        *,
        thinking=(),
        issues=None,
        reason="",
        review_verdicts=None,
        review_dimensions=None,
        review_heartbeats=0,
        review_reason="llm_not_configured",
        advice_thinking=(),
        advice_improvements=None,
        advice_directions=None,
        advice_reason="llm_not_configured",
    ) -> None:
        self._thinking = tuple(thinking)
        self._issues = issues
        self._reason = reason
        self._review_verdicts = review_verdicts
        self._review_dimensions = review_dimensions
        self._review_heartbeats = review_heartbeats
        self._review_reason = review_reason
        self._advice_thinking = tuple(advice_thinking)
        self._advice_improvements = advice_improvements
        self._advice_directions = advice_directions
        self._advice_reason = advice_reason
        self.calls: list[str] = []
        self.review_calls: list[str] = []
        self.advice_calls: list[str] = []

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        self.calls.append(resume_text)
        for delta in self._thinking:
            yield LlmThinking(delta=delta)
        yield LlmFinished(issues=self._issues, degraded_reason=self._reason)

    async def stream_review(
        self,
        resume_text: str,
        *,
        requirements_json: str,
        rubric_slice_json: str,
        allowed_levels,
        trace_id: str,
    ) -> AsyncIterator:
        from app.llm.events import LlmHeartbeat, LlmReviewFinished


        self.review_calls.append(requirements_json)
        self.last_rubric_slice = rubric_slice_json
        for _ in range(self._review_heartbeats):
            yield LlmHeartbeat()
        if self._review_verdicts is None and self._review_dimensions is None:
            yield LlmReviewFinished(degraded_reason=self._review_reason)
            return
        yield LlmReviewFinished(
            verdicts=self._review_verdicts, dimensions=self._review_dimensions
        )

    async def stream_advice(self, brief_json: str, *, trace_id: str) -> AsyncIterator:
        from app.llm.events import LlmAdviceFinished


        self.advice_calls.append(brief_json)
        for delta in self._advice_thinking:
            yield LlmThinking(delta=delta)
        if self._advice_improvements is None and self._advice_directions is None:
            yield LlmAdviceFinished(degraded_reason=self._advice_reason)
            return
        yield LlmAdviceFinished(
            improvements=self._advice_improvements, directions=self._advice_directions
        )


class _BrokenLlm:
    """模拟 LLM 侧异常：连接失败 / 超时 / 5xx。"""

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        raise ConnectionError("boom")
        yield  # pragma: no cover —— 让这是个生成器


@pytest.fixture
def dictionary():
    return get_dictionary()


@pytest.fixture
def candidates() -> tuple[JobCandidate, ...]:
    return (
        JobCandidate(
            jobId="job-a",
            title="Java 后端",
            company="某科技",
            level="校招",
            requirements=(
                Requirement(skill="Java", importance="required", evidence="熟悉 Java", jd_offset=0),
                Requirement(skill="Redis", importance="required", evidence="熟悉 Redis", jd_offset=5),
            ),
        ),
        JobCandidate(
            jobId="job-b",
            title="前端开发",
            requirements=(Requirement(skill="Vue", importance="required", evidence="熟悉 Vue"),),
        ),
    )


async def _drain(request: StreamRequest, *, dictionary, llm, registry=None) -> list[tuple[str, dict]]:
    frames = [
        frame async for frame in stream_analysis(
            request, dictionary=dictionary, llm=llm, registry=registry
        )
    ]
    return parse_frames("".join(frames))


# ------------------------------------------------------------------ 序列完整性（AC11）


async def test_event_sequence_with_text_input(dictionary, candidates) -> None:
    """纯文本入参 → 完整事件序列（AC11）。"""
    request = StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-1")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    types = [event_type for event_type, _ in events]

    assert types[0] == SseEventType.META.value
    assert types[-1] == SseEventType.DONE.value
    assert SseEventType.RESULT.value in types
    assert types.count(SseEventType.RESULT.value) == 1
    assert types.index(SseEventType.RESULT.value) < types.index(SseEventType.DONE.value)
    assert SseEventType.ERROR.value not in types


async def test_stage_sequence_matches_frozen_order(dictionary) -> None:
    """`standard` 模式发出**前 7 个** stage，且每个都有 start + ok。

    part3 在 `STAGE_ORDER` 末尾加了 `reviewed`（C5），但**`standard` 模式不发它**
    （spec §2.4：否则进度条多一格却没内容）。所以这里的期望是「冻结顺序的前缀」，
    而不是整张表 —— `STAGE_ORDER` 定义的是**最大**阶段集。
    """
    request = StreamRequest(resume_text=RESUME, trace_id="t-2")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    stages = [(data["stage"], data["status"]) for event_type, data in events
              if event_type == SseEventType.STAGE.value]

    expected = [s.value for s in STAGE_ORDER if s is not StageName.REVIEWED]
    assert [stage for stage, _ in stages] == [stage for stage in expected for _ in (0, 1)]
    assert [status for _, status in stages] == ["start", "ok"] * len(expected)


async def test_meta_is_first_and_carries_source_and_trace(dictionary) -> None:
    request = StreamRequest(resume_text=RESUME, trace_id="trace-meta")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    event_type, data = events[0]
    assert event_type == SseEventType.META.value
    assert data == {"traceId": "trace-meta", "source": "text"}


async def test_result_carries_five_blocks(dictionary, candidates) -> None:
    """`result` 的 data 必须是 part2 spec §2.3 的五块结构。"""
    request = StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-3")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    assert set(result.keys()) == {"resume", "issues", "match", "recommendations", "meta"}
    assert result["meta"]["traceId"] == "t-3"
    assert result["meta"]["source"] == "text"
    assert result["meta"]["truncated"] is False
    assert result["meta"]["recommendationCount"] == 2      # min(3, 候选数)
    assert [r["jobId"] for r in result["recommendations"]] == ["job-a", "job-b"]


async def test_sections_are_lines_not_characters(dictionary) -> None:
    """**回归测试**：`resume.sections` 必须是**行列表**，不是逐字符列表。

    曾经用 `list(section_text)` 把整段文本拆成字符，而 Pydantic 的 `list[str]`
    不报错、老老实实接受，响应体里出现 `"education": ["2","0","1","9",...]`。
    单测只断言 `isinstance(list)` 抓不到，是端到端 curl 才看出来的。
    """
    request = StreamRequest(resume_text=RESUME, trace_id="t-sections")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    sections = result["resume"]["sections"]

    assert set(sections.keys()) == {"education", "experience", "projects", "skills"}
    for key, lines in sections.items():
        assert isinstance(lines, list)
        for line in lines:
            assert len(line) >= 2, f"{key} 里出现了逐字符拆分：{line!r}"
    # RESUME 里教育背景那一行必须完整出现
    assert any("大学" in line for line in sections["education"])


async def test_match_is_null_without_job(dictionary, candidates) -> None:
    """不指定 jobId / jdText → `match` 为 `null`（part2 spec §2.2 的关键差异）。"""
    request = StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-4")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    assert result["match"] is None

    matched_detail = next(
        data["detail"] for event_type, data in events
        if event_type == SseEventType.STAGE.value
        and data["stage"] == StageName.MATCHED.value
        and data["status"] == "ok"
    )
    assert matched_detail == {"skipped": True}


async def test_match_is_populated_with_job_id(dictionary, candidates) -> None:
    """指定 jobId → `match` 非空，且分数与直接调 matcher 一致。"""
    from app.service.match.matcher import ResumeSkills, match

    request = StreamRequest(resume_text=RESUME, job_id="job-a", job_candidates=candidates, trace_id="t-5")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    assert result["match"] is not None
    assert set(result["match"].keys()) == {"score", "matched", "missing"}

    expected = match(
        candidates[0].requirements,
        ResumeSkills(tuple(dictionary.extract_unique(RESUME))),
    )
    assert result["match"]["score"] == expected.score
    # 集合自洽（AC17）
    matched = {m["skill"] for m in result["match"]["matched"]}
    missing = {m["skill"] for m in result["match"]["missing"]}
    assert matched & missing == set()
    assert matched | missing == {"Java", "Redis"}


# ------------------------------------------------------------------ 失败路径（AC14）


async def test_error_and_result_are_mutually_exclusive(dictionary) -> None:
    """`error` 与 `result` 互斥（spec §2.4 硬性规则 3）。"""
    request = StreamRequest(resume_text=RESUME, trace_id="t-6")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    types = [event_type for event_type, _ in events]
    assert not (SseEventType.ERROR.value in types and SseEventType.RESULT.value in types)


async def test_parse_failure_still_emits_error_then_done(dictionary) -> None:
    """致命阶段失败 → `error → done`，连接 5s 内关闭（AC14）。

    用一个「认不出格式」的假注册表触发 `UNSUPPORTED_FORMAT` ——
    比构造一个真损坏 PDF 更稳定，且走的正是同一条异常路径。
    """
    from app.service.document.parser_plugin import ParserRegistry

    empty_registry = ParserRegistry()
    request = StreamRequest(file_bytes=b"%PDF-1.4 not really a pdf", file_name="x.pdf", trace_id="t-7")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm(), registry=empty_registry)

    types = [event_type for event_type, _ in events]
    assert types[0] == SseEventType.META.value
    assert SseEventType.ERROR.value in types
    assert SseEventType.RESULT.value not in types
    assert types[-1] == SseEventType.DONE.value
    assert types.index(SseEventType.ERROR.value) < types.index(SseEventType.DONE.value)

    error = next(data for event_type, data in events if event_type == SseEventType.ERROR.value)
    assert set(error.keys()) == {"code", "message", "traceId"}
    assert error["traceId"] == "t-7"

    # parsed 阶段必须留下 fail 记录 —— 否则日志里看不出是哪一阶段炸的
    parsed = [
        data for event_type, data in events
        if event_type == SseEventType.STAGE.value and data["stage"] == StageName.PARSED.value
    ]
    assert parsed[-1]["status"] == "fail"


class _ScannedParser:
    """模拟扫描件解析器：解析**成功**，但抽不到正文（`has_text_layer=False`）。

    注意它不抛异常 —— 这正是本用例的意义：**「解析成功」不等于「可以继续」**。
    """

    document_format = "pdf"
    magic_prefixes = (b"%PDF-",)

    def sniff(self, data: bytes) -> bool:
        return True

    def parse(self, data: bytes):
        from app.service.document.parser_plugin import ParseResult

        return ParseResult(
            text="1", page_count=1, encrypted=False, has_text_layer=False, document_format="pdf"
        )


class _ScannedRegistry:
    def detect(self, data: bytes):
        return _ScannedParser()


async def test_scanned_pdf_is_reported_as_no_text_layer(dictionary) -> None:
    """扫描件 / 纯图片 PDF → `error(PDF_NO_TEXT_LAYER) → done`（AC14）。

    ★ 这条守的是「解析成功 ≠ 可以继续」。解析器只报事实（`has_text_layer=False`），
    **要不要因此中止是编排层的策略**（M2 §2.2 把策略留给了 M4）。

    少了这个判断，扫描件会一路走到 `result`，产出一份「0 技能 / 0 推荐」
    但结构完全正常的响应 —— 用户只会以为简历写得不好，而真正的原因
    （文件里根本没有文字）被彻底藏起来了。
    """
    request = StreamRequest(file_bytes=b"%PDF-1.4 scanned", file_name="scan.pdf", trace_id="t-9")
    events = await _drain(
        request, dictionary=dictionary, llm=_FakeLlm(), registry=_ScannedRegistry()
    )

    types = [event_type for event_type, _ in events]
    assert SseEventType.ERROR.value in types
    assert SseEventType.RESULT.value not in types
    assert types[-1] == SseEventType.DONE.value

    error = next(data for event_type, data in events if event_type == SseEventType.ERROR.value)
    assert error["code"] == ErrorCode.PDF_NO_TEXT_LAYER.value

    # 与「认不出格式」一样：parsed 阶段必须留下 fail + 具体 code，日志里才看得出炸在哪
    parsed = [
        data for event_type, data in events
        if event_type == SseEventType.STAGE.value and data["stage"] == StageName.PARSED.value
    ]
    assert parsed[-1]["status"] == "fail"
    assert parsed[-1]["detail"]["code"] == ErrorCode.PDF_NO_TEXT_LAYER.value


class _ExplodingParser:
    """模拟「解析器内部炸了」—— 不是领域错误，是未预期异常。"""

    document_format = "pdf"
    magic_prefixes = (b"%PDF-",)

    def sniff(self, data: bytes) -> bool:
        return True

    def parse(self, data: bytes):
        raise RuntimeError("parser exploded")


class _ExplodingRegistry:
    def detect(self, data: bytes):
        return _ExplodingParser()


async def test_unexpected_exception_is_mapped_to_analysis_failed(dictionary) -> None:
    """未预期异常也必须走 `error → done`，不能让连接悬挂（plan §6.3）。

    用「解析器内部抛 `RuntimeError`」触发 —— 它不是 `AppException`，
    正好覆盖兜底映射那一条。异常类型只进日志，**不进响应体**（spec §3.3）。
    """
    request = StreamRequest(file_bytes=b"%PDF-1.4 x", file_name="x.pdf", trace_id="t-8")
    events = await _drain(
        request, dictionary=dictionary, llm=_FakeLlm(), registry=_ExplodingRegistry()
    )

    types = [event_type for event_type, _ in events]
    assert types[-1] == SseEventType.DONE.value
    error = next(data for event_type, data in events if event_type == SseEventType.ERROR.value)
    assert error["code"] == ErrorCode.ANALYSIS_FAILED.value
    assert "RuntimeError" not in error["message"], "异常类型不许透传到响应体（spec §3.3）"


# ------------------------------------------------------------------ LLM 降级（AC15）


async def test_llm_success_emits_thinking_and_marks_llm_used(dictionary) -> None:
    """LLM 可用 → thinking×n + issues 来自 LLM + `llmUsed=true, degraded=false`。"""
    from app.schema.response.analyze_response import Issue, IssueType, Severity

    issues = (
        Issue(type=IssueType.NO_QUANTIFY, severity=Severity.HIGH, evidence="负责订单系统", suggestion="补数字"),
    )
    request = StreamRequest(resume_text=RESUME, trace_id="t-9")
    events = await _drain(
        request, dictionary=dictionary, llm=_FakeLlm(thinking=("让", "我", "看看"), issues=issues)
    )

    deltas = [data["delta"] for event_type, data in events if event_type == SseEventType.THINKING.value]
    assert deltas == ["让", "我", "看看"]

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    assert result["meta"]["llmUsed"] is True
    assert result["meta"]["degraded"] is False
    assert len(result["issues"]) == 1
    assert result["issues"][0]["type"] == "NO_QUANTIFY"


async def test_llm_degradation_falls_back_to_rules(dictionary) -> None:
    """AC15：LLM 不可用 → thinking 0 次，但 result 与 done 照常，`degraded=true`。

    `recommendations` 必须**仍然完整** —— 它不依赖 LLM（spec §2.4 硬性规则 4）。
    """
    request = StreamRequest(
        resume_text=RESUME,
        job_candidates=(JobCandidate(jobId="job-a", title="Java 后端",
                                     requirements=(Requirement(skill="Java", importance="required"),)),),
        trace_id="t-10",
    )
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm(reason="llm_not_configured"))

    types = [event_type for event_type, _ in events]
    assert SseEventType.THINKING.value not in types
    assert types[-1] == SseEventType.DONE.value

    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    assert result["meta"]["llmUsed"] is False
    assert result["meta"]["degraded"] is True
    assert len(result["recommendations"]) == 1
    assert result["recommendations"][0]["jobId"] == "job-a"
    # issues 走规则兜底：这份简历有手机号，所以 MISSING_CONTACT 不该出现
    assert all(issue["type"] != "MISSING_CONTACT" for issue in result["issues"])


async def test_llm_exception_is_degraded_not_fatal(dictionary) -> None:
    """LLM 抛异常 → 降级而不是整条流失败（plan §6.2）。"""
    request = StreamRequest(resume_text=RESUME, trace_id="t-11")
    events = await _drain(request, dictionary=dictionary, llm=_BrokenLlm())

    types = [event_type for event_type, _ in events]
    assert SseEventType.ERROR.value not in types
    assert types[-1] == SseEventType.DONE.value
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    assert result["meta"]["degraded"] is True


# ------------------------------------------------------------------ 确定性（AC16）


async def test_two_runs_produce_identical_result(dictionary, candidates) -> None:
    """AC16：同一输入两次，`recommendations` 的 jobId 序列与各自 score 完全一致。"""
    first = await _drain(
        StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-12"),
        dictionary=dictionary, llm=_FakeLlm(),
    )
    second = await _drain(
        StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-12"),
        dictionary=dictionary, llm=_FakeLlm(),
    )

    def summary(events):
        result = next(d for t, d in events if t == SseEventType.RESULT.value)
        return [(r["jobId"], r["score"]) for r in result["recommendations"]]

    assert summary(first) == summary(second)


async def test_empty_input_is_rejected_before_stream(dictionary) -> None:
    """`file` 与 `resumeText` 都缺 → 400（spec §2.2），由端点层判定。"""
    from fastapi import HTTPException

    from app.api.v1.stream import analyze_stream

    with pytest.raises(HTTPException) as excinfo:
        await analyze_stream()

    assert excinfo.value.status_code == 400


async def test_oversized_file_is_rejected_before_stream(dictionary) -> None:
    """>10MB → 413，且**不建立 SSE 流**（spec §2.5 分界线 / AC13）。"""
    from fastapi import HTTPException

    from app.api.v1.stream import MAX_UPLOAD_BYTES, analyze_stream

    class _FakeUpload:
        filename = "big.pdf"

        async def read(self) -> bytes:
            return b"x" * (MAX_UPLOAD_BYTES + 1)

    with pytest.raises(HTTPException) as excinfo:
        await analyze_stream(file=_FakeUpload())

    assert excinfo.value.status_code == 413


# ================================================================== part3：deep 模式（N4.1 / N4.2）

#: part2 的响应形状（键序也算，AC25 要求**逐字节**一致）。
_PART2_RESULT_KEYS = ["resume", "issues", "match", "recommendations", "meta"]
_PART2_META_KEYS = [
    "traceId", "llmUsed", "degraded", "elapsedMs",
    "source", "truncated", "recommendationCount",
]
_PART3_META_KEYS = ["analysisDepth", "verdictCount", "directionCount"]
_PART3_BLOCK_KEYS = ["verdicts", "improvements", "growthDirections", "abilityProfile"]


@pytest.fixture
def deep_candidates() -> tuple[JobCandidate, ...]:
    """一个「有缺口」的候选集：简历命中 Java，缺 Kafka（硬性）与 Docker（加分）。

    有缺口才有 `verdicts.missing`、`improvements`、`growthDirections` 可看 ——
    全命中的简历在这三块上必然为空，测不出东西。
    """
    return (
        JobCandidate(
            jobId="job-deep",
            title="Java 后端",
            company="某科技",
            level="校招",
            requirements=(
                Requirement(skill="Java", importance="required", evidence="熟悉 Java", jd_offset=0),
                Requirement(skill="Kafka", importance="required", evidence="熟悉 Kafka", jd_offset=9),
                Requirement(skill="Docker", importance="preferred", evidence="Docker 加分", jd_offset=20),
            ),
            weight_level="campus",
            dimension_weights={
                "tech_depth": 0.30, "engineering": 0.25, "business": 0.10,
                "impact": 0.10, "collaboration": 0.10, "growth": 0.15,
            },
        ),
    )


def _deep_request(**overrides) -> StreamRequest:
    payload = {"resume_text": RESUME, "job_id": "job-deep", "trace_id": "deep-1",
               "analysis_depth": "deep"}
    payload.update(overrides)
    return StreamRequest(**payload)


async def test_deep_stage_sequence_contains_reviewed_before_result(dictionary, deep_candidates) -> None:
    """AC24：deep 的事件序列必须出现 `stage(reviewed)`，且**仍在 `result` 之前**。"""
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=_FakeLlm()
    )
    types = [event_type for event_type, _ in events]
    stages = [data["stage"] for event_type, data in events
              if event_type == SseEventType.STAGE.value]

    assert "reviewed" in stages
    assert stages.index("reviewed") < types.index(SseEventType.RESULT.value)
    # 完整的 8 个 stage（start + ok 各一条），且严格按冻结顺序
    assert stages == [stage.value for stage in STAGE_ORDER for _ in (0, 1)]


async def test_deep_result_carries_four_blocks(dictionary, deep_candidates) -> None:
    """AC24：`result` 必须含四个新块，且 `meta` 多出三个 part3 键。"""
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=_FakeLlm()
    )
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    for key in _PART3_BLOCK_KEYS:
        assert key in result, f"deep 响应缺少 {key}"
    assert list(result["meta"].keys()) == _PART2_META_KEYS + _PART3_META_KEYS
    assert result["meta"]["analysisDepth"] == "deep"


async def test_standard_result_matches_part2_shape_exactly(dictionary, candidates) -> None:
    """**AC25**：`standard`（缺省）响应与 part2 **形状逐字节一致** —— 键名与**键序**都不许多。

    这条不是「差不多就行」：多一个 `"verdicts": null` 键就足以让前端快照测试、
    契约校验、以及任何做 `Object.keys()` 比对的下游全红。
    真正的保证是结构性的 —— `standard` 走的是 `AnalyzeResponse`，
    四个新字段**在这个模型上根本不存在**（见 `analyze_response.py` 的模块 docstring）。
    """
    request = StreamRequest(resume_text=RESUME, job_candidates=candidates, trace_id="t-std")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    assert list(result.keys()) == _PART2_RESULT_KEYS
    assert list(result["meta"].keys()) == _PART2_META_KEYS
    # 一个 part3 的键都不许出现
    for key in _PART3_BLOCK_KEYS + _PART3_META_KEYS:
        assert key not in result
        assert key not in result["meta"]


async def test_judging_stage_emits_no_thinking_but_advice_does(dictionary, deep_candidates) -> None:
    """N4.1：**判定阶段（Prompt-3）一条 `thinking` 都不发，文案阶段（Prompt-4）才发**。

    为什么这么设计（spec §2.4）：Prompt-3 的输出是 JSON，逐字推给用户只会刷屏，
    还会把响应结构提前暴露在 UI 上；Prompt-4 是自然语言，打字机效果正好。

    实现上靠**两件事一起**保证：客户端在判定段只吐 `LlmHeartbeat`（空壳、不带正文），
    编排层也只对 `LlmThinking` 发 `thinking` 事件。
    """
    llm = _FakeLlm(
        review_heartbeats=2,                                    # 判定段有进展信号，但不是正文
        review_verdicts=(),
        review_dimensions=(),
        advice_thinking=("把", "缓存", "写", "具体"),
    )
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=llm
    )

    deltas = [data["delta"] for event_type, data in events
              if event_type == SseEventType.THINKING.value]
    assert deltas == ["把", "缓存", "写", "具体"]

    # `thinking` 必须落在 stage(reviewed, start) 之后（即文案段）
    reviewed_start = next(
        index for index, (event_type, data) in enumerate(events)
        if event_type == SseEventType.STAGE.value
        and data["stage"] == "reviewed" and data["status"] == "start"
    )
    thinking_positions = [index for index, (event_type, _) in enumerate(events)
                          if event_type == SseEventType.THINKING.value]
    assert thinking_positions and min(thinking_positions) > reviewed_start


async def test_deep_degrades_to_rules_and_still_finishes(dictionary, deep_candidates) -> None:
    """**AC29**：断 LLM → 四块降级（判定退化为**集合级事实**），`result` 与 `done` 照常。

    注意「降级」**不是空数组**（ADR-206 / AC29 的「退化为集合级事实」）：
    - `verdicts` 条数 = `match` 条数，每条 `reason` 非空；
    - `improvements` / `growthDirections` 走规则模板，非空；
    - `abilityProfile` 六维齐全（其中两维是纯代码算的）。
    """
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=_FakeLlm()
    )
    types = [event_type for event_type, _ in events]
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    assert types[-1] == SseEventType.DONE.value
    assert SseEventType.RESULT.value in types
    assert SseEventType.ERROR.value not in types
    assert result["meta"]["degraded"] is True

    assert len(result["verdicts"]) == len(result["match"]["matched"]) + len(
        result["match"]["missing"]
    )
    assert all(item["reason"].strip() for item in result["verdicts"])
    assert result["improvements"], "断 LLM 时优化点不该为空（规则模板兜底）"
    assert result["growthDirections"]
    assert result["abilityProfile"] is not None
    assert len(result["abilityProfile"]["dimensions"]) == 6

    # `reviewed` 阶段必须留下 fail 记录（而不是静默 ok）—— 日志与前端都要看得出这一阶段没成
    reviewed = [data for event_type, data in events
                if event_type == SseEventType.STAGE.value and data["stage"] == "reviewed"]
    assert reviewed[-1]["status"] == "fail"


async def test_deep_uses_llm_verdicts_and_profile_when_available(dictionary, deep_candidates) -> None:
    """LLM 可用时：判定与档位**真的用模型的结果**（否则那个分支等于没接线）。"""
    from app.llm.events import AdviceDirection, AdviceImprovement, ReviewDimension, ReviewVerdict
    from app.schema.response.analyze_response import Issue, IssueType, Severity

    llm = _FakeLlm(
        issues=(
            Issue(type=IssueType.NO_QUANTIFY, severity=Severity.HIGH,
                  evidence="负责订单系统重构", suggestion="补数字"),
        ),
        review_verdicts=(
            ReviewVerdict(skill="Kafka", verdict="partial", reason="提到消息队列但未点名 Kafka",
                          resume_evidence=""),
        ),
        review_dimensions=(
            ReviewDimension(key="tech_depth", level="L4", reason="有原理层面的取舍",
                            evidence="接口耗时从 800ms 降到 120ms"),
        ),
        advice_thinking=("建议", "补", "数字"),
        advice_improvements=(
            AdviceImprovement(area="项目描述", action="把耗时变化写成一行",
                              evidence="负责订单系统重构，接口耗时从 800ms 降到 120ms",
                              targets=("Kafka",)),
        ),
        advice_directions=(
            AdviceDirection(direction="消息队列", why="目标岗位硬性要求，简历零证据",
                            first_step="在一个项目里引入 Kafka 做异步解耦", priority=1),
        ),
    )
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=llm
    )
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    kafka = next(item for item in result["verdicts"] if item["skill"] == "Kafka")
    assert kafka["verdict"] == "partial"
    assert kafka["reason"] == "提到消息队列但未点名 Kafka"
    # importance 永远来自 match，不由模型决定
    assert kafka["importance"] == "required"

    tech = next(item for item in result["abilityProfile"]["dimensions"] if item["name"] == "技术深度")
    assert tech["rubricRef"] == "tech_depth.L4"
    assert tech["score"] == 95
    assert result["meta"]["llmUsed"] is True
    assert result["meta"]["degraded"] is False


async def test_deep_scores_carry_rubric_ref_and_evidence(dictionary, deep_candidates) -> None:
    """**AC27**：每个维度分都带 `rubricRef`；有分（>0）就必须有原文 `evidence`。

    ⚠️ `overall` 的出处由它的 components 承载（每个分维度都带 `rubricRef`），
    再叠加 `rubric.yaml` 的权重表 —— 这个口径与 spec §2.3 的散文表述有出入，
    已在 `DELIVERY.md` §7 登记（契约的 `abilityProfile` 是 `additionalProperties: false`，
    给 `overall` 单独挂字段等于改已冻结的契约）。
    """
    events = await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=_FakeLlm()
    )
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)
    profile = result["abilityProfile"]

    assert profile["overall"] is not None
    for dimension in profile["dimensions"]:
        assert dimension["rubricRef"], f"{dimension['name']} 没有 rubricRef"
        if dimension["score"]:
            assert dimension["evidence"].strip(), f"{dimension['name']} 有分却没有 evidence"


async def test_deep_is_deterministic_across_two_runs(dictionary, deep_candidates) -> None:
    """**AC30**：同一简历 + 同一岗位连续两次 deep → 判定顺序、各维度分、`overall` 完全一致。"""
    def summary(events):
        result = next(d for t, d in events if t == SseEventType.RESULT.value)
        return (
            [(item["skill"], item["verdict"], item["reason"]) for item in result["verdicts"]],
            [(item["name"], item["score"]) for item in result["abilityProfile"]["dimensions"]],
            result["abilityProfile"]["overall"],
        )

    first = summary(await _drain(_deep_request(job_candidates=deep_candidates),
                                 dictionary=dictionary, llm=_FakeLlm()))
    second = summary(await _drain(_deep_request(job_candidates=deep_candidates),
                                  dictionary=dictionary, llm=_FakeLlm()))

    assert first == second


async def test_deep_injects_only_the_relevant_rubric_slice(dictionary, deep_candidates) -> None:
    """N3.3：注入 Prompt-3 的 rubric 片段**小于全量**，且不含纯代码算的两维。"""
    llm = _FakeLlm(review_verdicts=(), review_dimensions=())
    await _drain(
        _deep_request(job_candidates=deep_candidates), dictionary=dictionary, llm=llm
    )

    injected = llm.last_rubric_slice
    assert "tech_depth" in injected
    assert "impact" not in injected and "growth" not in injected


async def test_deep_without_job_still_returns_profile(dictionary, candidates) -> None:
    """没选岗位也能出画像（`verdicts` 为空，因为**没有要求可判**）—— 不报错。"""
    events = await _drain(
        _deep_request(job_id=None, job_candidates=candidates), dictionary=dictionary, llm=_FakeLlm()
    )
    result = next(data for event_type, data in events if event_type == SseEventType.RESULT.value)

    assert result["match"] is None
    assert result["verdicts"] == []
    assert result["abilityProfile"] is not None


async def test_top_n_is_configurable_and_capped(dictionary) -> None:
    """**AC35**：`topN=10` → 条数 = `min(10, 候选数)`；缺省仍为 3（AC17 不破）。"""
    many = tuple(
        JobCandidate(jobId=f"job-{index:02d}", title=f"岗位 {index}",
                     requirements=(Requirement(skill="Java", importance="required"),))
        for index in range(12)
    )

    default = await _drain(StreamRequest(resume_text=RESUME, job_candidates=many),
                           dictionary=dictionary, llm=_FakeLlm())
    raised = await _drain(StreamRequest(resume_text=RESUME, job_candidates=many, top_n=10),
                          dictionary=dictionary, llm=_FakeLlm())

    def count(events):
        return len(next(d for t, d in events if t == SseEventType.RESULT.value)["recommendations"])

    assert count(default) == 3
    assert count(raised) == 10
    # 超过候选数时取 min
    few = many[:2]
    capped = await _drain(StreamRequest(resume_text=RESUME, job_candidates=few, top_n=10),
                          dictionary=dictionary, llm=_FakeLlm())
    assert count(capped) == 2


async def test_invalid_analysis_depth_is_rejected_before_stream() -> None:
    """非法 `analysisDepth` → 400，**不建立 SSE 流**（spec §2.5 的分界线）。"""
    from fastapi import HTTPException

    from app.api.v1.stream import analyze_stream

    with pytest.raises(HTTPException) as excinfo:
        await analyze_stream(resumeText="张三", analysisDepth="ultra")

    assert excinfo.value.status_code == 400


async def test_top_n_out_of_range_is_rejected_before_stream() -> None:
    """`topN` 越界 → 400。**不静默夹取** —— 静默接受会让调用方以为拿到了 100 条。"""
    from fastapi import HTTPException

    from app.api.v1.stream import analyze_stream

    for bad in (0, -3, 11):
        with pytest.raises(HTTPException) as excinfo:
            await analyze_stream(resumeText="张三", topN=bad)
        assert excinfo.value.status_code == 400


async def test_defaults_keep_part2_behaviour(dictionary, candidates) -> None:
    """**AC25 的核心**：两个新参数都不传时，`analysisDepth` 落到 `standard`、`topN` 落到 3。"""
    request = StreamRequest(resume_text=RESUME, job_candidates=candidates)

    assert request.is_deep is False
    assert request.resolved_top_n == 3
