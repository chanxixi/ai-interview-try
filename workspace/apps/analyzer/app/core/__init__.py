"""core —— 横切关注点（配置 / 常量 / 资源 / 日志 / 追踪 / 错误 / 装配）。

**依赖方向**（指南 §4.2）：core 可被任意层引用，但 **core 自身不得 import service**。
一旦 `config.py` / `constants.py` / `resources.py` 里出现 `from app.service...`，
说明有业务逻辑漏进了横切层。

⚠️ 唯一的例外是 `wiring/`（组合根）—— 它必须认识具体实现才能装配，
这是**故意**的。除 `wiring/` 之外的子目录（`errors/` / `observability/`）出现
`from app.service` 就是违规。
"""

# 子目录分组：
#   config / constants / resources —— 与运行环境、领域无关的基础值
#   errors/                        —— 错误码 + 异常→HTTP 翻译
#   observability/                 —— 日志 + traceId
#   wiring/                        —— 组合根（唯一允许 import service 的地方）
