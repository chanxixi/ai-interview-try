"""SSE 线上格式 —— **唯一**把「一个事件」变成「一行半字节」的地方（M4.2）。

为什么值得单独一个文件：SSE 是**按行解析**的协议，而 `data` 里装的是 JSON。
`json.dumps` 会把字符串中的换行转义成 `\\n`，所以正常情况下一条事件占两行
（`event:` 行 + `data:` 行）。一旦哪天有人用 `json.dumps(..., indent=2)`
或者手拼字符串，一条事件就会被撕成好几行 —— 前端分帧器直接错乱，
而这种 bug 在服务端日志里完全看不出来（服务端只看到自己发出了什么字符串）。

**统一收口在这里**，测试直接断言本文件的输出，就是守住了这条边界。
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def dumps(payload: Mapping[str, Any]) -> str:
    """单行 JSON。

    - `ensure_ascii=False`：中文直接输出。转成 `\\uXXXX` 会让 `evidence` 这类
      中文片段在浏览器和日志里都不可读，而 SSE 本身就是 UTF-8。
    - `separators=(",", ":")`：紧凑输出。思考增量可能有很多条，省一点是一点。
    - **绝不用 `indent`**：见模块 docstring。
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def format_event(event_type: str, payload: Mapping[str, Any]) -> str:
    """`event: <type>\\ndata: <单行 JSON>\\n\\n`（spec §2.4 的统一形态）。"""
    return f"event: {event_type}\ndata: {dumps(payload)}\n\n"


def format_ping() -> str:
    """心跳注释行。**不产生 `event:` 行**（spec §2.4 硬性规则 2）。

    前端分帧器按 `\\n\\n` 切块后，以 `:` 开头的块直接丢弃 ——
    不会误当成一个事件，也不会打乱 `meta` 首 / `done` 尾的顺序断言。
    """
    return ": ping\n\n"


def parse_frames(raw: str) -> list[tuple[str, dict]]:
    """把 SSE 字节流还原成 `(event_type, data_dict)` 列表。**测试与前端共用同一套规则**。

    按 `\\n\\n` 分帧 → 丢掉以 `:` 开头的注释帧 → 从剩下的帧里取
    `event:` 行与 `data:` 行。写在这里而不是写在测试里，是为了让
    「服务端怎么发」和「消费端怎么解」用同一份代码定义，不会各写一遍然后对不上。
    """
    frames: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :])
        if not event_type:
            continue
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        frames.append((event_type, payload))
    return frames
