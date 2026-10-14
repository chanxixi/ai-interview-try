"""统一**错误**响应体（spec.md §2.3）。

成功响应**不使用**它（见 `util/response.py` 的说明：本项目是「半个」统一响应）。
"""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    traceId: str
