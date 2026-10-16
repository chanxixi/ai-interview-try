"""HTTP 输出：响应体构造 + SSE 帧格式化。

- `response`：错误响应体的**唯一**构造点（保证所有错误形状一致）
- `sse`：SSE 帧的格式化与解析（`format_event` / `format_ping` / `parse_frames`）

两者都是「往外写字节」，与协议强相关，所以放一组。
纯数值 / 纯算法的小工具（如 `rounding`）留在 `util/` 根下，不进这里。
"""
