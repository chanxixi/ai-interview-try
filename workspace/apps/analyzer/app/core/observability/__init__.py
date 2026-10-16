"""可观测性：结构化日志 + traceId 贯穿。

- `logging`：JSON 结构化输出，traceId 自动注入每条日志
- `trace`：ContextVar + 中间件，保证 `meta.traceId` 永远非空

放在一起是因为「日志里有没有 traceId」由这两者共同决定 —— 只改一个就会漏。

⚠️ `logging.py` 与标准库同名。Python 3 用绝对导入，模块内 `import logging`
指向标准库而不是自己，所以是安全的；但**不要**在别处写 `from app.core import logging`
这种形式，容易看混。
"""
