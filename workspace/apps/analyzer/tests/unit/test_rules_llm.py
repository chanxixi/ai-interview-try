"""规则兜底（M4.5）与 LLM 客户端（M4.4）。

两批用例守的是同一件事：**降级路径必须和正常路径一样可预测**。
LLM 是外部依赖，它的任何异常都不该让分析结果变形 —— 所以这里既测
「规则能找出真问题」，也测「模型输出脏数据时不会把脏东西带进响应体」。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest

from app.llm.client import (
    LlmEvent,
    LlmFinished,
    LlmThinking,
    NullLlmClient,
    OpenAiCompatibleClient,
    parse_issues,
)
from app.llm.prompts import build_issue_prompt, system_prompt
from app.schema.response.analyze_response import Issue, IssueType, Severity
from app.service.rules import detect_issues

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
