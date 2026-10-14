"""BFF → analyzer 的内部请求（plan.md §3.3）。"""

from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import JD_MAX_LENGTH, RESUME_MAX_LENGTH


class AnalyzeRequest(BaseModel):
    """内部接口只收**已解析好的 jdText**。

    analyzer 不认 `jobId`，也就不可能去查岗位数据（spec.md §2.6）——
    「取 JD 原文」是 BFF 编排时找 job-service 要的，不是本服务的职责。

    长度上限与 spec.md §2.1 对齐：BFF 是第一道校验，这里是第二道
    （指南 §5.3 原则 8「入口校验过了，Service 内仍守住关键不变量」）。
    """

    resumeText: str = Field(min_length=1, max_length=RESUME_MAX_LENGTH)
    jdText: str = Field(min_length=1, max_length=JD_MAX_LENGTH)
    traceId: Optional[str] = None
