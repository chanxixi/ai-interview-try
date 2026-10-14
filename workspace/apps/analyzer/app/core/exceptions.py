"""领域异常与错误码 —— 与 spec.md §2.3（冻结）对齐。

**为什么 Service 只抛 `AppException` 而不抛 `HTTPException`**（指南 §4.2 关键反模式）：

若业务层直接抛 `HTTPException`，会产生两个后果 ——
① 算法单测必须造 HTTP 上下文才能跑；② 换传输层（CLI / 队列消费者）就得改业务代码。
正确做法是业务层只表达「哪一类错」，由 `exception_handlers.py` 在边界翻译成 HTTP。
"""

from enum import Enum


class ErrorCode(str, Enum):
    """analyzer 可能产生的错误码。

    **只收录本服务职责内的码**（spec.md §2.3 的 8 个码中属于计算层的那部分）：
    `JOB_NOT_FOUND` 属于 job-service、`SERVICE_UNAVAILABLE` / `UPSTREAM_TIMEOUT`
    由 BFF 在编排时映射 —— 它们出现在这里只会让「谁该负责」变模糊。
    """

    #: Pydantic 校验失败（长度超限、字段缺失）
    INVALID_INPUT = "INVALID_INPUT"

    #: 分析过程失败（清洗 / 归一化 / 匹配抛出未预期异常）
    ANALYSIS_FAILED = "ANALYSIS_FAILED"

    #: 兜底 —— 不透传原始错误栈（spec.md §3.3）
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppException(Exception):
    """领域异常：业务层只抛它，由 `exception_handlers` 翻译成 HTTP。

    :param code: 错误码，决定响应体的 `code` 字段
    :param message: 对外文案，**不得包含内部实现细节**（spec.md §3.3）
    :param http_status: HTTP 状态码；默认 422 对应 `ANALYSIS_FAILED`
    """

    def __init__(self, code: ErrorCode, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
