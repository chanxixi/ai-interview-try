"""LLM 事件类型与客户端协议（part3 从 client.py 拆出）。

只放**类型与契约**，不放实现 —— 这是 `llm` 包里唯一被三个模块共享的东西：
`parsers` 要产出载荷类型，`client` 要产出事件，编排层要 import 事件做 isinstance 判断。

单独成文件后 import 方向天然单向：

    client → parsers → events

不会再出现「为了拿一个 dataclass 而 import 整个 httpx 客户端」这种事。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator, Mapping, Protocol

@dataclass(frozen=True)
class LlmThinking:
    """思考增量。`delta` 是**原文片段**，前端直接追加显示（打字机效果）。"""

    delta: str


@dataclass(frozen=True)
class LlmFinished:
    """收尾事件，恰好一次。

    :param issues: 解析成功的 issues；`None` 表示**降级**（调用方走规则兜底）
    :param degraded_reason: 降级原因，仅用于日志，**不进响应体**
    """

    issues: tuple[Issue, ...] | None = None
    degraded_reason: str = ""


LlmEvent = LlmThinking | LlmFinished


# ---------------------------------------------------------------- part3：判定 / 文案事件（N1.1 / N3.1）


@dataclass(frozen=True)
class ReviewVerdict:
    """LLM 的一条逐条判定（**内部类型**，契约模型在组装层构造）。

    `importance` 不在这里：它来自 `match`（集合级事实），LLM **不允许**改它 ——
    「这条要求是硬性还是加分」是岗位数据，不是模型判断（plan §8 风险 1）。
    """

    skill: str
    verdict: str
    reason: str
    resume_evidence: str = ""


@dataclass(frozen=True)
class ReviewDimension:
    """LLM 的一个维度判档。**只有档位，没有分数** —— 分数由代码查表算（spec §2.5②）。"""

    key: str
    level: str
    reason: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class LlmHeartbeat:
    """静默进度心跳（**不带任何正文**）。

    为什么需要它：Prompt-3 的输出是 JSON，spec §2.4 明确**不发 `thinking`**
    （逐字推给用户只会刷屏，还会把结构暴露在 UI 上）。但一次判定可能耗到 20s，
    连接上长时间零字节会被代理掐掉。所以客户端在收到增量时吐一个**空壳事件**，
    由编排层决定要不要借它发一条 SSE `: ping` —— 内容不出客户端，心跳照常。
    """


@dataclass(frozen=True)
class LlmReviewFinished:
    """Prompt-3 的收尾事件，恰好一次。

    `verdicts` / `dimensions` 为 `None` 表示**降级**（编排层走 `advisor_rules` 兜底）。
    与 `LlmFinished` 同一个约定：失败归一成正常事件，控制流保持一条直线。
    """

    verdicts: tuple[ReviewVerdict, ...] | None = None
    dimensions: tuple[ReviewDimension, ...] | None = None
    degraded_reason: str = ""


@dataclass(frozen=True)
class AdviceImprovement:
    area: str
    action: str
    evidence: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdviceDirection:
    direction: str
    why: str
    first_step: str
    priority: int = 1


@dataclass(frozen=True)
class LlmAdviceFinished:
    """Prompt-4 的收尾事件。为 `None` 表示降级（走规则模板）。"""

    improvements: tuple[AdviceImprovement, ...] | None = None
    directions: tuple[AdviceDirection, ...] | None = None
    degraded_reason: str = ""


LlmReviewEvent = LlmHeartbeat | LlmReviewFinished
LlmAdviceEvent = LlmThinking | LlmAdviceFinished

#: 允许的档位集合：`{维度 key: (档位 key, ...)}`。由 `rubric.yaml` 生成，**不是**代码里的常量 ——
#: 这样在 YAML 里加一档，解析器的白名单自动跟着变（AC31）。
AllowedLevels = Mapping[str, tuple[str, ...]]


class LlmClient(Protocol):
    """LLM 客户端契约。Protocol 而非 ABC：测试替身不必继承。

    三个方法对应三个 prompt（part2 的 issues + part3 的判定 / 文案）。
    未启用 deep 时只调 `stream_issues` —— 老路径零改动。
    """

    def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]: ...

    def stream_review(
        self,
        resume_text: str,
        *,
        requirements_json: str,
        rubric_slice_json: str,
        allowed_levels: AllowedLevels,
        trace_id: str,
    ) -> AsyncIterator[LlmReviewEvent]: ...

    def stream_advice(
        self, brief_json: str, *, trace_id: str
    ) -> AsyncIterator[LlmAdviceEvent]: ...
