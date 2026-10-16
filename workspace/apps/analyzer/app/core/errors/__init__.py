"""错误码与「异常 → HTTP」的翻译。

`exceptions` 定义 `ErrorCode` 与 `AppException`（**业务能抛什么错**在这里定死），
`exception_handlers` 是**唯一**把异常翻译成 HTTP 响应的地方。

两者成对出现：加一个错误码必须同时在 handlers 里决定它映射成几个状态码，
分开两处就会漏 —— 所以放在同一组。
"""
