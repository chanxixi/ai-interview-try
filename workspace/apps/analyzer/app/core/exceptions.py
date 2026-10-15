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

    # ------------------------------------------------------------ part2 新增（spec.md §2.5）
    # 四个 PDF 类错误都出现在 **SSE `error` 事件**里（文件必须读完才知道能不能用），
    # 属于计算层职责，所以收在这里。
    # ⚠️ `FILE_TOO_LARGE`(413) / `UNSUPPORTED_FILE_TYPE`(415) **不在这里** ——
    # 它们是「建流前」的同步错误，由 BFF 判定（M6.2），analyzer 根本收不到那种请求。

    #: 损坏 / 截断 / 解析异常
    PDF_PARSE_FAILED = "PDF_PARSE_FAILED"

    #: 有密码，且空密码解不开
    PDF_ENCRYPTED = "PDF_ENCRYPTED"

    #: 抽出的文本 < 100 个非空白字符（扫描件 / 纯图片）
    PDF_NO_TEXT_LAYER = "PDF_NO_TEXT_LAYER"

    #: 页数 > 10
    PDF_TOO_MANY_PAGES = "PDF_TOO_MANY_PAGES"

    #: 字节流不属于任何已注册的解析器格式。
    #: 正常链路上它不会出现（BFF 已按 magic number 拦掉非 PDF，M6.2）；
    #: 这里留着是为了「解析器注册表」这个扩展点在被人直接调用时也有明确出口，
    #: 而不是掉进 500 兜底。HTTP 语义与 spec §2.5 的 415 保持一致。
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"


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
