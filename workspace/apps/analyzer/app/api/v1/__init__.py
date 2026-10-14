"""v1 —— 路由分组占位。

⚠️ **路径上不加 `/v1` 前缀**：spec.md §2.2 的契约已冻结，`/internal/analyze` 与
`/healthz` 的路径是契约的一部分。这里用目录表达「版本分组」的意图，
等真的需要并行维护两版契约时（本期不做，spec.md §1.4 Out of Scope），
再在 `include_router(prefix=...)` 上加前缀即可，无需改文件位置。
"""
