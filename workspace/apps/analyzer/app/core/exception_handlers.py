"""统一错误收口 —— 全服务**唯一**把异常翻译成 HTTP 的地方（spec.md §2.3）。

三个 handler 覆盖三类失败，顺序即优先级：

1. `AppException`          —— 业务层主动抛出的领域异常
2. `RequestValidationError` —— Pydantic 入参校验失败（含长度超限）
3. `Exception`             —— 兜底，防止原始错误栈出网（spec.md §3.3）

**与 BFF 的分工**：本层输出「analyzer 视角」的错误；BFF 会按 plan.md §6.4
再映射一层（例如把本层 4xx 收敛为 422 ANALYSIS_FAILED）。两层都收口，语义不同。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException, ErrorCode
from app.util.response import error_body

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """把三类异常处理器注册到 app 上（在 main.py 里调用一次）。"""

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("app exception: code=%s message=%s", exc.code.value, exc.message, exc_info=exc)
        else:
            logger.warning("app rejected: code=%s message=%s", exc.code.value, exc.message)
        return JSONResponse(status_code=exc.http_status, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """入参校验失败 → 400 INVALID_INPUT。

        注意 FastAPI 默认返回 **422**，而 spec.md §2.3 里 422 属于 `ANALYSIS_FAILED`
        （分析失败），校验失败应是 **400** —— 这里刻意纠正为契约口径。
        """
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}"
            for e in exc.errors()
        )
        logger.warning("validation failed: %s", detail)
        return JSONResponse(
            status_code=400, content=error_body(ErrorCode.INVALID_INPUT, detail)
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        """兜底：堆栈只进日志，不出网。"""
        logger.exception("unexpected error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body(ErrorCode.INTERNAL_ERROR, "分析服务内部错误"),
        )
