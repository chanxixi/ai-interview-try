"""SSE 事件与 stage 的类型定义（M4.1）—— 与 part2 spec §2.4 **逐字一致**。

**为什么事件类型和 stage 枚举要单独一个文件**：
它们是契约的一部分，三个消费方都从这里 import ——
① `service/analysis_stream_service.py`（生产）② `api/v1/stream.py`（透传）
③ `tests/unit/test_stream.py`（断言）。任何一方写字面量，就会出现
「某处把 `recommended` 写成 `recommend`」而这种只有端到端才发现的错。

**stage 顺序是冻结的**（spec §2.4）：`accepted → parsed → cleaned → normalized
→ matched → recommended → llm`。`STAGE_ORDER` 是唯一真源，测试断言
「收到的 stage 序列 == STAGE_ORDER」而不是手写一遍列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.util.sse import format_event


class SseEventType(str, Enum):
    """6 类事件（spec §2.4 冻结，不许增删改名）。"""

    META = "meta"
    STAGE = "stage"
    THINKING = "thinking"
    RESULT = "result"
    ERROR = "error"
    DONE = "done"


class StageName(str, Enum):
    """7 个 stage（spec §2.4 冻结，按序）。"""

    ACCEPTED = "accepted"
    PARSED = "parsed"
    CLEANED = "cleaned"
    NORMALIZED = "normalized"
    MATCHED = "matched"
    RECOMMENDED = "recommended"
    LLM = "llm"


#: 冻结顺序。**唯一真源** —— 测试与服务都从这里取，不手写。
STAGE_ORDER: tuple[StageName, ...] = (
    StageName.ACCEPTED,
    StageName.PARSED,
    StageName.CLEANED,
    StageName.NORMALIZED,
    StageName.MATCHED,
    StageName.RECOMMENDED,
    StageName.LLM,
)


class StageStatus(str, Enum):
    """stage 的三种状态。

    `FAIL` **不终止流**（spec §2.4 硬性规则 3）—— 只有 `parsed` 的致命失败
    才另外发 `error` 事件。别处用 FAIL 只表示「这一阶段没做成，继续往下」。
    """

    START = "start"
    OK = "ok"
    FAIL = "fail"


class Source(str, Enum):
    """入参来源（spec §2.3 的 `meta.source`）。"""

    PDF = "pdf"
    TEXT = "text"


# ---------------------------------------------------------------- data 载荷


@dataclass(frozen=True)
class MetaData:
    """`meta` 事件的 data：建连后**立刻**发，必为首个（spec §2.4）。"""

    traceId: str
    source: str

    def to_dict(self) -> dict:
        return {"traceId": self.traceId, "source": self.source}


@dataclass(frozen=True)
class StageData:
    """`stage` 事件的 data。

    `detail` 放该阶段的**事实**（页数 / 文本长度 / 分数 / 技能数…），
    不是给人看的描述 —— 前端可以拿它做进度副标题，测试可以拿它做断言。
    """

    stage: str
    status: str
    elapsedMs: int = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "elapsedMs": self.elapsedMs,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ThinkingData:
    """`thinking` 事件的 data：LLM 增量文本，0..n 次（降级时可以是 0 次）。"""

    delta: str

    def to_dict(self) -> dict:
        return {"delta": self.delta}


@dataclass(frozen=True)
class ErrorData:
    """`error` 事件的 data：致命阶段失败，**终止序列**（但后面仍发 `done`）。"""

    code: str
    message: str
    traceId: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "traceId": self.traceId}


@dataclass(frozen=True)
class DoneData:
    """`done` 事件的 data：流正常结束，**必为最后一个**。"""

    elapsedMs: int

    def to_dict(self) -> dict:
        return {"elapsedMs": self.elapsedMs}


# ---------------------------------------------------------------- 事件 → 线上帧


def _payload_of(data) -> dict:
    """把事件的 data 变成可 JSON 化的 dict。

    **为什么要这个函数**：`result` 事件的 data 是完整的 `AnalyzeResponse`
    （pydantic 模型， spec §2.4 说它装的就是 §2.3 的响应体），
    而其他事件的 data 是普通 dataclass。两种都要能序列化。

    - dataclass → `to_dict()`（各 data 类自己实现，控制字段与顺序）
    - pydantic → `model_dump(mode="json")`。`mode="json"` 是必须的：
      它会把 Enum 成员换成字符串值；用默认的 python 模式会输出
      `<IssueType.NO_STAR: 'NO_STAR'>` 这种 repr，前端拿到直接解析失败。

    写测试时第一次漏了这条，`result` 事件抛 `AttributeError` 被兜底成
    `error → done` —— 从外面看只是「没有 result」，很难猜到根因。
    """
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(data, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"事件的 data 既不是 dataclass 也不是 pydantic 模型：{type(data)!r}")


@dataclass(frozen=True)
class SseEvent:
    """一个事件 + 它的线上表示。

    `to_frame()` 委托给 `util/sse.py` —— 线上格式的唯一真源在那里。
    这里只负责「哪个事件配哪个 data 形状」，不碰字节。
    """

    type: SseEventType
    data: MetaData | StageData | ThinkingData | ErrorData | DoneData

    def to_frame(self) -> str:
        return format_event(self.type.value, _payload_of(self.data))
