"""规则兜底（M4.5）与 LLM 客户端（M4.4）。

两批用例守的是同一件事：**降级路径必须和正常路径一样可预测**。
LLM 是外部依赖，它的任何异常都不该让分析结果变形 —— 所以这里既测
「规则能找出真问题」，也测「模型输出脏数据时不会把脏东西带进响应体」。
"""

from __future__ import annotations
import json
from typing import AsyncIterator
import pytest
from app.llm.events import LlmEvent, LlmFinished, LlmThinking
from app.llm.parsers import parse_issues
from app.llm.client import NullLlmClient, OpenAiCompatibleClient

from app.llm.prompts import build_issue_prompt, system_prompt
from app.schema.response.analyze_response import Issue, IssueType, Severity
from app.service.advice.rules import detect_issues

RESUME_WITH_EVERYTHING = (
    "个人信息：张三 电话 13800138000 邮箱 zhangsan@example.com\n"
    "教育背景：2019.09-2023.06 某大学 计算机科学与技术\n"
    "工作经验：2023.07-2024.06 某公司 后端工程师\n"
    "2024.07-2025.06 另一公司 高级工程师\n"
    "专业技能：Java、Spring Boot、MySQL、Redis、Vue、Docker、Kafka、"
    "Linux、Git、Maven、Nginx、RabbitMQ、MongoDB、Elasticsearch、"
    "TypeScript、React、Node.js、Koa、Express、NestJS、Django、Flask、"
    "FastAPI、Gin、gRPC、Netty、Dubbo、ZooKeeper、Prometheus、Grafana\n"
    "项目经历：负责订单系统重构\n"
)

# ================================================================== rules.py


def test_detect_issues_finds_missing_contact() -> None:
    issues = detect_issues("张三\n专业技能：Java")

    assert any(i.type == IssueType.MISSING_CONTACT for i in issues)
    contact = next(i for i in issues if i.type == IssueType.MISSING_CONTACT)
    assert contact.severity == Severity.HIGH


def test_detect_issues_does_not_flag_present_contact() -> None:
    """有手机号就不该报 —— 这是唯一一条能 100% 确定的规则，误报代价最高。"""
    issues = detect_issues("张三 电话 13800138000\n专业技能：Java")

    assert all(i.type != IssueType.MISSING_CONTACT for i in issues)


def test_detect_issues_finds_no_quantify() -> None:
    issues = detect_issues("负责订单系统重构，配合团队完成交付")

    no_quantify = [i for i in issues if i.type == IssueType.NO_QUANTIFY]
    assert no_quantify
    # evidence 必须逐字来自原文
    assert no_quantify[0].evidence in "负责订单系统重构，配合团队完成交付"


def test_detect_issues_does_not_flag_quantified_sentence() -> None:
    """句子里有数字就不算缺量化。"""
    issues = detect_issues("负责订单系统重构，接口耗时从 800ms 降到 120ms")

    assert all(i.type != IssueType.NO_QUANTIFY for i in issues)


def test_detect_issues_flags_skill_stuffing_only_above_threshold() -> None:
    many = "\n".join(f"- Skill{i}" for i in range(30))
    few = "\n".join(f"- Skill{i}" for i in range(5))

    assert any(i.type == IssueType.SKILL_STUFFING for i in detect_issues("x", {"skills": many}))
    assert all(i.type != IssueType.SKILL_STUFFING for i in detect_issues("x", {"skills": few}))


def test_detect_issues_flags_reversed_time_range() -> None:
    """起 > 止：任何位置都是错。"""
    issues = detect_issues("工作经验：2024.07-2023.06 某公司")

    gap = [i for i in issues if i.type == IssueType.TIMELINE_GAP]
    assert gap
    assert gap[0].evidence == "2024.07-2023.06"


def test_detect_issues_ignores_project_overlapping_employment() -> None:
    """**回归测试**：项目区间与任职区间重叠是正常简历结构，不许判 TIMELINE_GAP。

    第一版规则全文排序后比对相邻区间，把「项目 2025.09-2026.06」和
    「工作 2023.07-2026.07」判成重叠。真实样本一跑就现形。
    """
    text = (
        "工作经验：2023.07-2026.07 某公司 工程师\n"
        "项目经历：2025.09-2026.06 某商城项目\n"
    )
    sections = {
        "experience": "2023.07-2026.07 某公司 工程师",
        "projects": "2025.09-2026.06 某商城项目",
    }

    assert all(i.type != IssueType.TIMELINE_GAP for i in detect_issues(text, sections))


def test_detect_issues_flags_overlapping_employment() -> None:
    """两段**工作经历**重叠才是真问题。"""
    text = "工作经验：2023.07-2026.07 某公司\n2024.01-2025.06 另一公司"
    sections = {"experience": "2023.07-2026.07 某公司\n2024.01-2025.06 另一公司"}

    assert any(i.type == IssueType.TIMELINE_GAP for i in detect_issues(text, sections))


def test_detect_issues_is_deterministic() -> None:
    first = detect_issues(RESUME_WITH_EVERYTHING)
    second = detect_issues(RESUME_WITH_EVERYTHING)

    assert [i.type for i in first] == [i.type for i in second]
    assert [i.evidence for i in first] == [i.evidence for i in second]


def test_detect_issues_returns_empty_for_blank_text() -> None:
    """空文本返回空数组，不抛错 —— 「没发现问题」和「没法分析」是两件事，
    但调用方只需要一个列表。"""
    assert detect_issues("") == []
    assert detect_issues("   \n  ") == []


def test_detect_issues_respects_max_and_orders_by_severity() -> None:
    from app.core.constants import MAX_ISSUES

    issues = detect_issues(RESUME_WITH_EVERYTHING)

    assert len(issues) <= MAX_ISSUES
    ranks = [{"high": 0, "medium": 1, "low": 2}[i.severity.value] for i in issues]
    assert ranks == sorted(ranks)


def test_suggestion_is_within_contract_limit() -> None:
    """`suggestion` ≤ 20 字（Prompt-2 规则 3，规则兜底同源）。"""
    from app.core.constants import SUGGESTION_MAX_CHARS

    for issue in detect_issues(RESUME_WITH_EVERYTHING):
        assert len(issue.suggestion) <= SUGGESTION_MAX_CHARS


# ================================================================== llm/client.py


def test_parse_issues_accepts_valid_payload() -> None:
    raw = json.dumps(
        {"issues": [{"type": "NO_STAR", "severity": "low",
                     "evidence": "负责订单系统", "suggestion": "补结果"}]},
        ensure_ascii=False,
    )

    issues = parse_issues(raw)

    assert issues is not None
    assert len(issues) == 1
    assert issues[0].type == IssueType.NO_STAR
    assert issues[0].severity == Severity.LOW


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json at all",
        "[]",                                    # 顶层不是对象
        '{"issues": "oops"}',                    # issues 不是数组
        '{"issues": []}',                        # 空数组 → 视作无法使用
        '{"nope": 1}',                           # 缺 issues 键
    ],
)
def test_parse_issues_returns_none_for_unusable_payload(raw: str) -> None:
    """任何不可用的输出都返回 `None` → 调用方降级。**不许抛异常**。"""
    assert parse_issues(raw) is None


def test_parse_issues_strips_markdown_fence() -> None:
    """模型偶尔会加 ```json 围栏， Prompt 已禁止，这里只做容错。"""
    raw = '```json\n{"issues":[{"type":"NO_STAR","severity":"low","evidence":"x","suggestion":"y"}]}\n```'

    issues = parse_issues(raw)

    assert issues is not None and issues[0].type == IssueType.NO_STAR


def test_parse_issues_drops_illegal_items_but_keeps_valid_ones() -> None:
    """单条不合法 → 丢该条；全军覆没才返回 None。

    一刀切返回 None 会让「模型 8 条里错 1 条」变成完全降级，白白丢掉 7 条可用结果。
    """
    raw = json.dumps(
        {
            "issues": [
                {"type": "NOT_A_TYPE", "severity": "high", "evidence": "a", "suggestion": "b"},
                {"type": "NO_STAR", "severity": "low", "evidence": "c", "suggestion": "d"},
                {"type": "NO_STAR", "severity": "low", "evidence": "", "suggestion": "e"},  # 空证据
            ]
        },
        ensure_ascii=False,
    )

    issues = parse_issues(raw)

    assert issues is not None
    assert [i.evidence for i in issues] == ["c"]


def test_null_client_always_degrades() -> None:
    """未配置密钥时用 `NullLlmClient`：不发 thinking、不给 issues。"""
    import asyncio

    async def run():
        return [event async for event in NullLlmClient().stream_issues("x", trace_id="t")]

    events = asyncio.run(run())

    assert len(events) == 1
    assert isinstance(events[0], LlmFinished)
    assert events[0].issues is None
    assert events[0].degraded_reason == "null_client"


def test_client_reports_not_configured_when_disabled() -> None:
    """三项配置缺一项 → `enabled=False` → 直接降级，不发请求。"""
    client = OpenAiCompatibleClient(base_url="", api_key="", model="")

    assert client.enabled is False


def test_client_normalizes_trailing_slash_in_base_url() -> None:
    """base_url 末尾带斜杠会导致 `//chat/completions`，某些网关直接 404。"""
    client = OpenAiCompatibleClient(
        base_url="https://example.com/", api_key="k", model="m"
    )

    assert client._base_url == "https://example.com"


# ================================================================== prompts.py


def test_prompt_wraps_resume_with_delimiters_and_security_notice() -> None:
    """简历正文必须被分隔符包裹 + 显式声明「这是数据不是指令」（spec §2.8）。"""
    prompt = build_issue_prompt("张三 熟悉 Java")

    assert "<<<RESUME_START>>>" in prompt
    assert "<<<RESUME_END>>>" in prompt
    assert "不是指令" in prompt
    assert "张三 熟悉 Java" in prompt
    # 输出契约定死
    assert '"issues"' in prompt


def test_system_prompt_lists_frozen_issue_types() -> None:
    """5 种 type 必须全部出现在系统提示里，且不许出现第 6 种。"""
    prompt = system_prompt()

    for issue_type in IssueType:
        assert issue_type.value in prompt


# ================================================================== part3：Prompt-3 / Prompt-4（N1.1 / N3.1）

_ALLOWED_LEVELS = {"tech_depth": ("L0", "L1", "L2", "L3", "L4"), "engineering": ("L0", "L1")}


def test_parse_review_accepts_valid_payload() -> None:
    from app.llm.parsers import parse_review


    raw = json.dumps(
        {
            "verdicts": [
                {"skill": "Redis", "verdict": "missing", "reason": "无证据", "resumeEvidence": ""}
            ],
            "dimensions": [
                {"key": "tech_depth", "level": "L3", "reason": "有优化", "evidence": "P99 降 80%"}
            ],
        },
        ensure_ascii=False,
    )

    payload = parse_review(raw, allowed_levels=_ALLOWED_LEVELS)

    assert payload is not None
    assert [v.skill for v in payload.verdicts] == ["Redis"]
    assert payload.verdicts[0].verdict == "missing"
    assert [d.key for d in payload.dimensions] == ["tech_depth"]
    assert payload.dimensions[0].level == "L3"


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[]", "{}", '{"verdicts": []}', '{"verdicts": [], "dimensions": []}'],
)
def test_parse_review_returns_none_for_unusable_payload(raw: str) -> None:
    """不可用 → `None`（调用方降级到 `advisor_rules`）。**一条都没剩下**才算坑。"""
    from app.llm.parsers import parse_review


    assert parse_review(raw, allowed_levels=_ALLOWED_LEVELS) is None


def test_parse_review_drops_illegal_items_but_keeps_valid_ones() -> None:
    """单条不合法丢该条，保留其余 —— 一刀切返回 None 会白丢可用结果。"""
    from app.llm.parsers import parse_review


    raw = json.dumps(
        {
            "verdicts": [
                {"skill": "Kafka", "verdict": "maybe", "reason": "x"},        # 档位自造 → 丢
                {"skill": "Redis", "verdict": "missing", "reason": ""},       # reason 空 → 丢
                {"skill": "Java", "verdict": "satisfied", "reason": "有证据"},
            ],
            "dimensions": [],
        },
        ensure_ascii=False,
    )

    payload = parse_review(raw, allowed_levels=_ALLOWED_LEVELS)

    assert payload is not None
    assert [v.skill for v in payload.verdicts] == ["Java"]


def test_parse_review_rejects_unknown_level_and_empty_evidence() -> None:
    """`level` 必须命中 rubric 白名单；**证据为空就当它没判**（plan §8 风险 8）。

    软性维度最容易被「编一个看起来合理的档位」；给不出原文证据的档位一律不采信，
    退回代码兜底 —— 那是「宁可漏不可编」的同一个取向。
    """
    from app.llm.parsers import parse_review


    raw = json.dumps(
        {
            "verdicts": [],
            "dimensions": [
                {"key": "tech_depth", "level": "L9", "evidence": "e"},        # 档位不存在
                {"key": "unknown_dim", "level": "L1", "evidence": "e"},       # 维度不存在
                {"key": "tech_depth", "level": "L2", "evidence": "   "},      # 证据为空
                {"key": "engineering", "level": "L1", "evidence": "CI 流水线"},
            ],
        },
        ensure_ascii=False,
    )

    payload = parse_review(raw, allowed_levels=_ALLOWED_LEVELS)

    assert payload is not None
    assert [(d.key, d.level) for d in payload.dimensions] == [("engineering", "L1")]


def test_parse_review_strips_markdown_fence() -> None:
    from app.llm.parsers import parse_review


    raw = '```json\n{"verdicts":[{"skill":"Java","verdict":"partial","reason":"r"}]}\n```'

    payload = parse_review(raw, allowed_levels=_ALLOWED_LEVELS)

    assert payload is not None and payload.verdicts[0].verdict == "partial"


def test_parse_advice_sorts_by_priority_and_truncates() -> None:
    """**排序与截断是代码的职责**（spec §2.7 禁 LLM 决定任何排序）。

    模型给的顺序一律忽略 —— 否则同一份输入两次推荐顺序可能不同，演示时无法复现。
    """
    from app.llm.parsers import parse_advice


    raw = json.dumps(
        {
            "improvements": [
                {"area": "项目描述", "action": "补数字", "evidence": "优化了缓存", "targets": ["Redis"]}
            ],
            "growthDirections": [
                {"direction": "C", "why": "w", "firstStep": "s", "priority": 3},
                {"direction": "A", "why": "w", "firstStep": "s", "priority": 1},
                {"direction": "B", "why": "w", "firstStep": "s", "priority": 2},
                {"direction": "D", "why": "w", "firstStep": "s", "priority": 4},
            ],
        },
        ensure_ascii=False,
    )

    payload = parse_advice(raw, max_directions=3)

    assert payload is not None
    assert [d.direction for d in payload.directions] == ["A", "B", "C"]
    assert payload.improvements[0].targets == ("Redis",)


def test_parse_advice_requires_targets_and_first_step() -> None:
    """没有 `targets` 的优化点与没有 `firstStep` 的方向都不可执行，一律丢掉。"""
    from app.llm.parsers import parse_advice


    raw = json.dumps(
        {
            "improvements": [
                {"area": "a", "action": "b", "evidence": "c", "targets": []},
                {"area": "a", "action": "b", "evidence": "c", "targets": ["Java"]},
            ],
            "growthDirections": [
                {"direction": "d", "why": "w", "firstStep": "", "priority": 1},
                {"direction": "d", "why": "w", "firstStep": "s", "priority": 1},
            ],
        },
        ensure_ascii=False,
    )

    payload = parse_advice(raw, max_directions=5)

    assert payload is not None
    assert len(payload.improvements) == 1
    assert len(payload.directions) == 1


def test_null_client_degrades_review_and_advice() -> None:
    """`NullLlmClient` 必须把三条流都实现掉 —— 编排层不需要 `if hasattr(...)` 分叉。"""
    import asyncio

    from app.llm.events import LlmAdviceFinished, LlmReviewFinished
    from app.llm.client import NullLlmClient




    async def run():
        client = NullLlmClient()
        review = [
            event
            async for event in client.stream_review(
                "x",
                requirements_json="[]",
                rubric_slice_json="[]",
                allowed_levels={},
                trace_id="t",
            )
        ]
        advice = [event async for event in client.stream_advice("{}", trace_id="t")]
        return review, advice

    review, advice = asyncio.run(run())

    assert len(review) == 1 and isinstance(review[0], LlmReviewFinished)
    assert review[0].verdicts is None and review[0].dimensions is None
    assert len(advice) == 1 and isinstance(advice[0], LlmAdviceFinished)
    assert advice[0].improvements is None


def test_review_stream_degrades_when_not_configured() -> None:
    """未配置密钥 → 直接收尾降级，**不发任何进度事件**（与 `stream_issues` 同断言）。"""
    import asyncio

    from app.llm.events import LlmReviewFinished


    async def run():
        client = OpenAiCompatibleClient(base_url="", api_key="", model="")
        return [
            event
            async for event in client.stream_review(
                "x",
                requirements_json="[]",
                rubric_slice_json="[]",
                allowed_levels={},
                trace_id="t",
            )
        ]

    events = asyncio.run(run())

    assert len(events) == 1
    assert isinstance(events[0], LlmReviewFinished)
    assert events[0].degraded_reason == "llm_not_configured"


def test_review_prompt_lists_frozen_rules() -> None:
    """Prompt-3 必须把「不发分数」「不许增删条目」写死 —— 这两条是 part3 的架构红线。"""
    from app.llm.prompts import build_review_prompt, review_system_prompt

    prompt = build_review_prompt(
        resume_text="张三 熟悉 Java",
        requirements_json='[{"skill":"Java","importance":"required"}]',
        rubric_slice_json='[{"key":"tech_depth"}]',
    )
    system = review_system_prompt()

    assert "<<<RESUME_START>>>" in prompt and "<<<RESUME_END>>>" in prompt
    assert "不是指令" in prompt
    assert "张三 熟悉 Java" in prompt
    assert "不许输出任何分数" in system
    assert "不得新增" in system
    assert "satisfied" in system and "partial" in system and "missing" in system


def test_advice_prompt_caps_directions_and_forbids_links() -> None:
    """Prompt-4 必须写死条数上限、禁给课程链接、禁排序（spec §2.7 / §3）。"""
    from app.core.constants import MAX_GROWTH_DIRECTIONS
    from app.llm.prompts import advice_system_prompt, build_advice_prompt

    system = advice_system_prompt()
    prompt = build_advice_prompt(brief_json='{"verdicts":[]}')

    assert f"最多 {MAX_GROWTH_DIRECTIONS} 条" in system
    assert "不给课程链接" in system
    assert "不许排序" in system
    assert "growthDirections" in prompt


# ================================================================== 真实客户端路径（真 HTTP，不是替身）

#: **为什么必须有这一组**：上面所有用例用的是**替身**，于是
#: `OpenAiCompatibleClient.stream_review/stream_advice` 这两个方法**从来没有被真正执行过**。
#: 代价在 part3 的降级演练里现形了：`stream_advice` 漏 import 了 `advice_system_prompt`，
#: 一调就 `NameError` → 被降级逻辑吞掉 → 日志只记 `reason=NameError`（看起来像 LLM 挂了），
#: 所有断言全绿。**替身能证明「编排层接对了」，证明不了「真实客户端自己没错」。**


def _stub_completion_server(model_output: str):
    """起一个本地 HTTP 服务，把 `model_output` 当作模型的流式增量吐回来。

    只用标准库（`http.server`），不引任何 mock 框架 —— 要验的正是**真的发 HTTP** 这条路。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 —— http.server 的约定名
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)  # 必须读完，否则 keep-alive 错位
            frame = json.dumps({"choices": [{"delta": {"content": model_output}}]})
            body = f"data: {frame}\n\ndata: [DONE]\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_real_client_stream_review_end_to_end() -> None:
    """真客户端 + 真 HTTP：Prompt-3 的整条路（建 prompt → 发请求 → 解析）都要通。

    模型输出里的 `evidence` 是简历原文片段（逐字），所以会通过解析器的「逐字」校验。
    """
    import asyncio

    from app.llm.events import LlmReviewFinished


    resume = "项目经历\n负责订单系统重构，接口耗时从 800ms 降到 120ms"
    model_output = json.dumps(
        {
            "verdicts": [
                {"skill": "Kafka", "verdict": "missing", "reason": "无证据", "resumeEvidence": ""}
            ],
            "dimensions": [
                {
                    "key": "tech_depth",
                    "level": "L3",
                    "reason": "有优化且带数字",
                    "evidence": "接口耗时从 800ms 降到 120ms",
                }
            ],
        },
        ensure_ascii=False,
    )

    server, base_url = _stub_completion_server(model_output)
    try:
        client = OpenAiCompatibleClient(base_url=base_url, api_key="k", model="m", timeout_seconds=5)

        async def run():
            return [
                event
                async for event in client.stream_review(
                    resume,
                    requirements_json='[{"skill":"Kafka","importance":"required"}]',
                    rubric_slice_json='[{"key":"tech_depth"}]',
                    allowed_levels={"tech_depth": ("L0", "L1", "L2", "L3", "L4")},
                    trace_id="t-real",
                )
            ]

        events = asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()

    final = events[-1]
    assert isinstance(final, LlmReviewFinished)
    assert final.verdicts is not None, f"真实路径必须解析成功（degraded={final.degraded_reason}）"
    assert [item.skill for item in final.verdicts] == ["Kafka"]
    assert final.dimensions is not None
    assert final.dimensions[0].level == "L3"


def test_real_client_stream_advice_end_to_end() -> None:
    """真客户端 + 真 HTTP：Prompt-4 的整条路都要通。

    ★ 这条专门守「`stream_advice` 漏 import 系统提示词」那类 bug ——
    它在替身测试里完全看不出来（替身不碰 prompt 模块）。
    """
    import asyncio

    from app.llm.events import LlmAdviceFinished, LlmThinking


    brief = json.dumps(
        {"verdicts": [{"skill": "Kafka", "verdict": "missing", "reason": "无证据",
                       "resumeEvidence": "负责订单系统重构"}]},
        ensure_ascii=False,
    )
    model_output = json.dumps(
        {
            "improvements": [
                {"area": "项目描述", "action": "补一条消息队列的实践",
                 "evidence": "负责订单系统重构", "targets": ["Kafka"]}
            ],
            "growthDirections": [
                {"direction": "消息队列", "why": "硬性要求零证据",
                 "firstStep": "在一个项目里引入异步解耦", "priority": 1}
            ],
        },
        ensure_ascii=False,
    )

    server, base_url = _stub_completion_server(model_output)
    try:
        client = OpenAiCompatibleClient(base_url=base_url, api_key="k", model="m", timeout_seconds=5)

        async def run():
            return [event async for event in client.stream_advice(brief, trace_id="t-real")]

        events = asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()

    # 文案阶段**照常吐 thinking**（与判定阶段相反，spec §2.4）
    assert any(isinstance(event, LlmThinking) for event in events)

    final = events[-1]
    assert isinstance(final, LlmAdviceFinished)
    assert final.improvements is not None, f"真实路径必须解析成功（degraded={final.degraded_reason}）"
    assert final.directions is not None
    assert final.improvements[0].targets == ("Kafka",)

