"""traceId 贯穿（spec.md §2.8）。

**为什么必须用 `ContextVar` 而不是模块级全局变量**：
FastAPI 是 async 的，同一个线程（事件循环）会并发处理多个请求。若用
`_trace_id = "..."` 这样的全局变量，请求 A 设的值会被请求 B 覆盖，
日志里就会出现「A 的日志带着 B 的 traceId」—— 这类串号在压测下才暴露，
排查成本极高。`ContextVar` 为每个 async 任务提供独立上下文，天然隔离。

**与另两个服务的对应关系**：
Koa 用 `ctx.state` + pino child，Java 用 `MDC`（ThreadLocal），
Python 用 `ContextVar` —— 三者语义相同，载体不同。
"""

import uuid
from contextvars import ContextVar
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.core.constants import TRACE_ID_HEADER

#: 当前请求的 traceId。默认 None 表示「不在请求上下文中」（例如启动日志、单元测试）。
_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def get_trace_id() -> str:
    """取当前请求的 traceId。

    正常路径下由 :class:`TraceIdMiddleware` 写入，必然非空。
    在请求上下文之外调用（启动日志等）时返回一个临时 id —— 保证契约字段
    （错误响应体的 `traceId`，spec.md §2.3）永远有值，**不写回** contextvar。
    """
    return _trace_id.get() or str(uuid.uuid4())


def peek_trace_id() -> Optional[str]:
    """不生成临时值地读取，供「有则带上、没有就算了」的日志场景使用。"""
    return _trace_id.get()


class TraceIdMiddleware(BaseHTTPMiddleware):
    """读取上游 `X-Trace-Id`，缺失则生成；写入 contextvar 并回写响应头（spec.md §2.8）。

    回写响应头是刻意为之：调用方（BFF / 前端）能据此核对「我发出的 traceId
    与下游日志里的确实是同一个」，这是全链可观测的最小验证手段。
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())
        token = _trace_id.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            # reset 而非 set(None)：正确处理嵌套/复用，避免污染下一个请求
            _trace_id.reset(token)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
