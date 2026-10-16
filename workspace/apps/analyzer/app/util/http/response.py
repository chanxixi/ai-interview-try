"""响应体的统一构造 —— 边界收口的唯一出口。

本项目是「**半个**统一响应」（指南 §6.7）：

- **错误**走统一体 `{code, message, traceId}`（spec.md §2.3 冻结）；
- **成功**直接返回业务 DTO，**不套** `{code: 0, data: {...}}` 外壳 ——
  契约（spec.md §2.2）已经定死了四块结构 `resume / issues / match / meta`，
  再包一层会让前端多剥一次壳，且与契约不符。
"""

from app.core.errors.exceptions import ErrorCode
from app.core.observability.trace import get_trace_id


def error_body(code: ErrorCode | str, message: str) -> dict[str, str]:
    """构造统一错误响应体（spec.md §2.3）。

    traceId 自动取自当前请求上下文，调用方无需传参 —— 保证三个字段恒定存在。
    """
    return {
        "code": code.value if isinstance(code, ErrorCode) else code,
        "message": message,
        "traceId": get_trace_id(),
    }
