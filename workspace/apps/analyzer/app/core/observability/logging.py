"""结构化 JSON 日志（spec.md §2.8）。

所有服务日志必须为结构化 JSON，且 traceId 可被 grep 到。

**traceId 从哪来**：本模块直接从 `core.trace` 的 contextvar 读取，
调用方**不需要**再手写 `extra={"trace_id": ...}`。这样做的价值是
「不可能忘记带 traceId」—— 忘记传参是日志断链最常见的原因。
"""

import json
import logging
import sys
from datetime import datetime, timezone
from app.core.config import settings
from app.core.observability.trace import peek_trace_id


class JsonFormatter(logging.Formatter):
    """把 LogRecord 渲染成单行 JSON。

    字段口径与另两个服务对齐（`@timestamp` 语义的 `timestamp` / `level` /
    `service` / `message` / `traceId`），便于三服务日志汇总后用同一套规则检索。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 有请求上下文才带 traceId；启动阶段/单测里为 None，不输出空字段
        trace_id = peek_trace_id()
        if trace_id:
            payload["traceId"] = trace_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """配置 root logger，并让 uvicorn 的 logger 也走同一套 JSON 格式。

    不接管 uvicorn 的 handler 会导致启动日志是纯文本、运行日志是 JSON，
    用 grep 检索时两套格式混在一起 —— 这里统一为 JSON。
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
