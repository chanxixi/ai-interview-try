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

解析帧用 `app.util.sse.parse_frames` —— **和服务端发帧用的是同一份代码**，
这样「服务端怎么发」和「消费端怎么解」不会各写一遍然后对不上。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest

from app.core.exceptions import AppException, ErrorCode
from app.llm.client import LlmClient, LlmEvent, LlmFinished, LlmThinking
from app.schema.response.sse_event import STAGE_ORDER, SseEventType, StageName
from app.service.analysis_stream_service import StreamRequest, stream_analysis
from app.service.matcher import Requirement
from app.service.normalizer import get_dictionary
from app.service.recommender import JobCandidate
from app.util.sse import parse_frames

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
    """可编排的 LLM 替身：按脚本吐 thinking，最后给 issues。

    不继承 `LlmClient`（它是 Protocol）—— 结构对了就能用，
    这正是 Protocol 相对 ABC 的价值。
    """

    def __init__(self, *, thinking=(), issues=None, reason="") -> None:
        self._thinking = tuple(thinking)
        self._issues = issues
        self._reason = reason
        self.calls: list[str] = []

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        self.calls.append(resume_text)
        for delta in self._thinking:
            yield LlmThinking(delta=delta)
        yield LlmFinished(issues=self._issues, degraded_reason=self._reason)


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
    """7 个 stage 必须按 `STAGE_ORDER` 的冻结顺序出现，且每个都有 start + ok。"""
    request = StreamRequest(resume_text=RESUME, trace_id="t-2")
    events = await _drain(request, dictionary=dictionary, llm=_FakeLlm())

    stages = [(data["stage"], data["status"]) for event_type, data in events
              if event_type == SseEventType.STAGE.value]

    # 每个 stage 都有 start + ok 两条，所以序列是冻结顺序的两倍
    assert [stage for stage, _ in stages] == [s.value for s in STAGE_ORDER for _ in (0, 1)]
    assert [status for _, status in stages] == ["start", "ok"] * len(STAGE_ORDER)


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
    from app.service.matcher import ResumeSkills, match

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
    from app.service.parser_plugin import ParserRegistry

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
        from app.service.parser_plugin import ParseResult

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
