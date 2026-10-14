"""core —— 横切关注点（配置 / 常量 / 日志 / 追踪 / 异常 / 依赖装配）。

**依赖方向**（指南 §4.2）：core 可被任意层引用，但 **core 自身不得 import service**。
一旦 `core/config.py` 里出现 `from app.service...`，说明有业务逻辑漏进了横切层。
"""
