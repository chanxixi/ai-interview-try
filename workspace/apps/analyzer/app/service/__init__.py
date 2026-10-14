"""service —— 业务层：编排三步链、组装 DTO、决定降级。

**不得 import `fastapi`**（`Depends` / `HTTPException` / `Request` 都不行）——
Service 不认识框架（指南 §5.3 原则 3）。判据：把 HTTP 换成 CLI，本层原样可用。

后续（T5）会在这里增加单一职责的纯计算模块：
`cleaner.py` / `normalizer.py` / `matcher.py` / `rules.py`。
"""
