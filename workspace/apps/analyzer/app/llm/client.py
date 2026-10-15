"""LLM 客户端（M4.4）—— OpenAI 兼容网关的流式调用 + 失败即降级。

## 契约：一个异步生成器，两种事件

```python
async for event in client.stream_issues(text, trace_id=...):
    # LlmThinking(delta="...")   0..n 次，给人看的思考增量
    # LlmFinished(issues=..., degraded_reason="")   恰好一次，收尾
```

**为什么 `LlmFinished` 在失败时也一定发**：编排层（`analysis_stream_service`）
不需要为「LLM 挂了」写一条单独的 except 分支 —— 它只需要看 `issues is None`
就切到规则兜底。把失败归一成正常事件，控制流就从「try/except 森林」变成一条直线。

## 三层降级，逐层记录原因

| 层 | 触发 | 行为 |
|---|---|---|
| 未配置 | `settings.llm_enabled == False` | 不发任何 thinking，直接 `LlmFinished(issues=None)` |
| 传输失败 | 连接错 / 超时 / 非 200 | 同上，`degraded_reason` 写真实原因 |
| 内容失败 | 累积文本不是合法 JSON / 字段不合法 | 同上 |

**日志只记原因，不记简历正文**（spec §2.8：禁止日志打印简历正文）。
`trace_id` 一定打 —— 出问题时它是唯一能把请求串起来的线索。

## 为什么不用官方 SDK

OpenAI 官方 SDK 是同步优先、且为它的响应结构做了强类型封装。
这里要的是「流式吐字 + 自己拼累积文本」，用 `httpx` 直接读 SSE 行更短也更可控，
少一个依赖少一个升级面（与选 pypdf 而不是 pdfplumber 是同一个理由）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

import httpx

from app.core.config import settings
from app.llm.prompts import build_issue_prompt, system_prompt
from app.schema.response.analyze_response import Issue, IssueType, Severity

logger = logging.getLogger(__name__)

_JSON_FENCE = ("```json", "```")


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


class LlmClient(Protocol):
    """LLM 客户端契约。Protocol 而非 ABC：测试替身不必继承。"""

    def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]: ...


# ---------------------------------------------------------------- JSON 解析（宁可严，不要宽）


def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔加的 Markdown 代码块围栏。

    只剥首尾的 ```，不改中间内容 —— Prompt 里已经明确要求「不要代码块」，
    这里只是容错，不是在鼓励。
    """
    stripped = text.strip()
    for fence in _JSON_FENCE:
        if stripped.startswith(fence):
            stripped = stripped[len(fence) :]
        if stripped.endswith("```"):
            stripped = stripped[: -len("```")]
    return stripped.strip()


def parse_issues(raw: str) -> tuple[Issue, ...] | None:
    """把模型输出解析成 issues；**任何不合法都返回 `None`（降级）**。

    严在哪：
    - 顶层必须是 `{"issues": [...]}`，不是裸数组；
    - `type` / `severity` 必须命中冻结枚举，不认识的一律丢弃整条（不是整批）；
    - `evidence` 必须是非空字符串 —— 空证据等于「模型编了一个结论但给不出依据」，
      这种比没有更糟；
    - 某一条不合法时**丢弃该条、保留其余**，只有全军覆没才返回 None。
    """
    text = _strip_code_fence(raw)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        return None

    issues: list[Issue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        try:
            issue = Issue(
                type=IssueType(item["type"]),
                severity=Severity(item["severity"]),
                evidence=str(item["evidence"]).strip(),
                suggestion=str(item["suggestion"]).strip(),
            )
        except (KeyError, ValueError, TypeError):
            continue
        if not issue.evidence:
            continue
        issues.append(issue)

    return tuple(issues) if issues else None


# ---------------------------------------------------------------- 真实客户端


class OpenAiCompatibleClient:
    """OpenAI 兼容 `/chat/completions` 的流式客户端。

    构造参数全部可注入（而不是在内部读 `settings`）—— 测试里传一个假 base_url
    和假 key 就能跑，不必 monkeypatch 全局配置。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # base_url 末尾不带斜杠：`settings.llm_base_url` 的约定（config.py 已注明）。
        # 这里再 strip 一次，是防止调用方传入带斜杠的值导致 `//chat/completions`。
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        if not self.enabled:
            yield LlmFinished(issues=None, degraded_reason="llm_not_configured")
            return

        chunks: list[str] = []
        try:
            async for delta in self._stream_deltas(resume_text, trace_id):
                chunks.append(delta)
                yield LlmThinking(delta=delta)
        except Exception as exc:                       # noqa: BLE001 —— 见下方说明
            # 故意捕获**所有**异常：LLM 是外部依赖，任何失败都只应导致降级，
            # 不该让整条分析链崩掉。但异常对象只进日志，绝不进响应体
            # （spec §3.3：不透传内部实现细节）。
            logger.warning(
                "llm stream failed, fallback to rules (traceId=%s, reason=%s)",
                trace_id,
                type(exc).__name__,
            )
            yield LlmFinished(issues=None, degraded_reason=type(exc).__name__)
            return

        issues = parse_issues("".join(chunks))
        if issues is None:
            logger.warning(
                "llm returned unusable payload, fallback to rules (traceId=%s, chars=%d)",
                trace_id,
                sum(len(c) for c in chunks),
            )
        yield LlmFinished(issues=issues, degraded_reason="" if issues else "unusable_payload")

    async def _stream_deltas(self, resume_text: str, trace_id: str) -> AsyncIterator[str]:
        """读 SSE 流，逐段 yield `choices[0].delta.content`。"""
        timeout = httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0))
        client = self._client or httpx.AsyncClient(timeout=timeout)
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json={
                    "model": self._model,
                    "stream": True,
                    "messages": [
                        {"role": "system", "content": system_prompt()},
                        {"role": "user", "content": build_issue_prompt(resume_text)},
                    ],
                },
            ) as response:
                if response.status_code != 200:
                    # 读一小段 body 帮助定位（4xx 的错误信息通常在 body 里），
                    # 但只记前 200 字符 —— body 里可能回显请求内容。
                    body = (await response.aread())[:200]
                    logger.warning(
                        "llm http %s (traceId=%s, body=%r)",
                        response.status_code,
                        trace_id,
                        body.decode("utf-8", "replace"),
                    )
                    raise httpx.HTTPStatusError(
                        f"llm returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if not payload:
                        continue
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        yield delta
        finally:
            if owns_client:
                await client.aclose()


class NullLlmClient:
    """降级客户端：不发 thinking、不返回 issues。用于测试与本地无密钥开发。"""

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        yield LlmFinished(issues=None, degraded_reason="null_client")


def create_llm_client() -> LlmClient:
    """组合根：按配置决定用真实客户端还是空客户端。

    **未配置时返回 `NullLlmClient` 而不是 `None`**：这样编排层永远有一个客户端可调，
    不必写 `if llm is not None` —— 少一个分叉就少一条没被测到的路径。
    """
    if not settings.llm_enabled:
        return NullLlmClient()
    return OpenAiCompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
