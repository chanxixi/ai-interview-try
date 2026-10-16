"""SSE 帧构造与阶段计时（从 orchestration/stream.py 拆出）。

只管「往外写什么字节」，不含任何业务判断 ——
主流程决定**什么时候**发，这里只决定**发什么形状**。

`_Clock` 也放这儿：它唯一的用途就是给帧填 `elapsedMs`，
跟帧是同一次呼吸的事。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.schema.response.sse_event import (
    SseEvent,
    SseEventType,
    StageData,
    StageName,
    StageStatus,
)

@dataclass
class _Clock:
    """阶段计时。用 `perf_counter`（单调时钟）而不是 `time.time` ——
    后者会被 NTP 校准改向后跳，可能算出负的 `elapsedMs`。"""

    started: float = 0.0

    def begin(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


# ---------------------------------------------------------------- 小工具


def _stage_frame(stage: StageName, status: StageStatus, elapsed_ms: int, **detail) -> str:
    return SseEvent(type=SseEventType.STAGE, data=StageData(
        stage=stage.value, status=status.value, elapsedMs=elapsed_ms, detail=detail
    )).to_frame()
