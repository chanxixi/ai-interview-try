"""LLM 客户端（M4.4 / part3 N1.3 · N3.1）—— OpenAI 兼容网关的流式调用 + 失败即降级。

## 契约：异步生成器 + 收尾事件

```python
async for event in client.stream_issues(text, trace_id=...):
    # LlmThinking(delta="...")   0..n 次，给人看的思考增量
    # LlmFinished(issues=..., degraded_reason="")   恰好一次，收尾
```

part3 又加了两条流，**形状完全一致**（同样是「0..n 次进度事件 + 恰好一次收尾」）：

| 方法 | Prompt | 进度事件 | 收尾事件 |
|---|---|---|---|
| `stream_issues` | Prompt-2 | `LlmThinking`（带正文，打字机） | `LlmFinished` |
| `stream_review` | Prompt-3 | `LlmHeartbeat`（**空壳，不带正文** —— 输出是 JSON，spec §2.4 不发 thinking） | `LlmReviewFinished` |
| `stream_advice` | Prompt-4 | `LlmThinking`（带正文，打字机） | `LlmAdviceFinished` |

**为什么收尾事件在失败时也一定发**：编排层（`orchestration/stream`）
不需要为「LLM 挂了」写一条单独的 except 分支 —— 它只需要看 `verdicts is None`
就切到 `advisor_rules` 兜底。把失败归一成正常事件，控制流就从「try/except 森林」变成一条直线。

## 三层降级，逐层记录原因（三条流共用同一套）

| 层 | 触发 | 行为 |
|---|---|---|
| 未配置 | `settings.llm_enabled == False` | 不发任何进度事件，直接收尾（内容为 `None`） |
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
from typing import AsyncIterator
import httpx
from app.core.config import settings
from app.core.constants import MAX_GROWTH_DIRECTIONS
from app.llm.events import (
    AdviceImprovement,
    AllowedLevels,
    LlmAdviceEvent,
    LlmAdviceFinished,
    LlmEvent,
    LlmFinished,
    LlmHeartbeat,
    LlmReviewEvent,
    LlmReviewFinished,
    LlmThinking,
)
from app.llm.parsers import (
    AdvicePayload,
    ReviewPayload,
    parse_advice,
    parse_issues,
    parse_review,
)
from app.llm.prompts import (
    advice_system_prompt,
    build_advice_prompt,
    build_issue_prompt,
    build_review_prompt,
    review_system_prompt,
    system_prompt,
)

logger = logging.getLogger(__name__)

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
            #
            # `exc_info=True` 是**必须的**：只记 `type(exc).__name__` 看起来更「干净」，
            # 代价是**代码 bug 与网络故障在日志里长得一模一样**。这个坑是 part3 的降级演练
            # 逼出来的 —— `stream_advice` 里有个 `NameError`，因为被记成 `reason=NameError`
            # 而当成「LLM 挂了」，降级断言全绿、bug 静默过关。栈里不含简历正文，可以放心打。
            logger.warning(
                "llm stream failed, fallback to rules (traceId=%s, reason=%s)",
                trace_id,
                type(exc).__name__,
                exc_info=True,
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
        """Prompt-2（issues）的流式调用。"""
        async for delta in self._stream_messages(
            [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": build_issue_prompt(resume_text)},
            ],
            trace_id,
        ):
            yield delta

    async def stream_review(
        self,
        resume_text: str,
        *,
        requirements_json: str,
        rubric_slice_json: str,
        allowed_levels: AllowedLevels,
        trace_id: str,
    ) -> AsyncIterator[LlmReviewEvent]:
        """Prompt-3：判定 + 六维档。**三层降级，与 `stream_issues` 同形状。**

        ⚠️ **不出 `thinking`**（spec §2.4）：输出是 JSON，逐字推给用户只会刷屏、
        还会把结构暴露在 UI 上。这里只吐 `LlmHeartbeat`（空壳），
        让编排层照样能发 SSE 心跳 —— 否则一段 20s 的判定期间连接上零字节。
        """
        if not self.enabled:
            yield LlmReviewFinished(degraded_reason="llm_not_configured")
            return

        chunks: list[str] = []
        try:
            async for delta in self._stream_messages(
                [
                    {"role": "system", "content": review_system_prompt()},
                    {
                        "role": "user",
                        "content": build_review_prompt(
                            resume_text=resume_text,
                            requirements_json=requirements_json,
                            rubric_slice_json=rubric_slice_json,
                        ),
                    },
                ],
                trace_id,
            ):
                chunks.append(delta)
                yield LlmHeartbeat()
        except Exception as exc:                       # noqa: BLE001 —— 同 `stream_issues`
            logger.warning(
                "llm review failed, fallback to rules (traceId=%s, reason=%s)",
                trace_id,
                type(exc).__name__,
                exc_info=True,
            )
            yield LlmReviewFinished(degraded_reason=type(exc).__name__)
            return

        payload = parse_review(
            "".join(chunks), allowed_levels=allowed_levels, resume_text=resume_text
        )
        if payload is None:
            logger.warning(
                "llm review returned unusable payload, fallback to rules (traceId=%s, chars=%d)",
                trace_id,
                sum(len(chunk) for chunk in chunks),
            )
            yield LlmReviewFinished(degraded_reason="unusable_payload")
            return
        yield LlmReviewFinished(verdicts=payload.verdicts, dimensions=payload.dimensions)

    async def stream_advice(self, brief_json: str, *, trace_id: str) -> AsyncIterator[LlmAdviceEvent]:
        """Prompt-4：优化点 + 提升方向。文案阶段，**照常吐 `thinking`**（打字机效果）。"""
        if not self.enabled:
            yield LlmAdviceFinished(degraded_reason="llm_not_configured")
            return

        chunks: list[str] = []
        try:
            async for delta in self._stream_messages(
                [
                    {"role": "system", "content": advice_system_prompt()},
                    {"role": "user", "content": build_advice_prompt(brief_json=brief_json)},
                ],
                trace_id,
            ):
                chunks.append(delta)
                yield LlmThinking(delta=delta)
        except Exception as exc:                       # noqa: BLE001 —— 同 `stream_issues`
            logger.warning(
                "llm advice failed, fallback to rules (traceId=%s, reason=%s)",
                trace_id,
                type(exc).__name__,
                exc_info=True,
            )
            yield LlmAdviceFinished(degraded_reason=type(exc).__name__)
            return

        payload = parse_advice(
            "".join(chunks), max_directions=MAX_GROWTH_DIRECTIONS, evidence_source=brief_json
        )
        if payload is None:
            logger.warning(
                "llm advice returned unusable payload, fallback to rules (traceId=%s, chars=%d)",
                trace_id,
                sum(len(chunk) for chunk in chunks),
            )
            yield LlmAdviceFinished(degraded_reason="unusable_payload")
            return
        yield LlmAdviceFinished(improvements=payload.improvements, directions=payload.directions)

    async def _stream_messages(self, messages: list[dict], trace_id: str) -> AsyncIterator[str]:
        """读 SSE 流，逐段 yield `choices[0].delta.content`。**三个 prompt 共用**。"""
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
                    "messages": messages,
                    # qwen3 系列默认开 thinking。实测（阿里云百炼 compatible-mode，
                    # Prompt-4 同输入）：开 36.8s / 关 8.1s —— **慢 4.5 倍**，
                    # 三次调用累计 122s，直接顶穿 Java 的 ANALYZER_TIMEOUT_MS=110000。
                    # 而本服务的输出是**结构化 JSON**，思考链对结果无可观测收益，
                    # 只会拖慢并把推理过程混进 delta。故显式关闭。
                    # OpenAI 兼容网关忽略未知字段 —— 换 DeepSeek 等厂商不会因此报错。
                    "enable_thinking": False,
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
                    # 网关（阿里云百炼 compatible-mode 实测）在流末尾会发
                    # `{"choices":[],"usage":{...}}` 这类**无 choices 的统计帧**。
                    # 直接 `[0]` 会 IndexError —— 而它在 `except Exception` 里，
                    # 结果是「内容其实全收到了，却因为最后一帧降级」。必须跳过而不是取值。
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    # `delta` 也可能为 null（thinking 帧只有 reasoning_content）→ `or {}` 兜住。
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
        finally:
            if owns_client:
                await client.aclose()


class NullLlmClient:
    """降级客户端：不发 thinking、不返回 issues / 判定 / 文案。用于测试与本地无密钥开发。

    **三个方法都实现**（而不是只实现 `stream_issues`）：编排层永远有一个完整客户端可调，
    不需要 `if hasattr(llm, ...)` 这类分叉 —— 少一个分叉就少一条没被测到的路径。
    """

    async def stream_issues(self, resume_text: str, *, trace_id: str) -> AsyncIterator[LlmEvent]:
        yield LlmFinished(issues=None, degraded_reason="null_client")

    async def stream_review(
        self,
        resume_text: str,
        *,
        requirements_json: str,
        rubric_slice_json: str,
        allowed_levels: AllowedLevels,
        trace_id: str,
    ) -> AsyncIterator[LlmReviewEvent]:
        yield LlmReviewFinished(degraded_reason="null_client")

    async def stream_advice(self, brief_json: str, *, trace_id: str) -> AsyncIterator[LlmAdviceEvent]:
        yield LlmAdviceFinished(degraded_reason="null_client")


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
