"""schema —— DTO 层：契约形状的唯一落点。

- `request/`  入站（BFF → analyzer）
- `response/` 出站（analyzer → BFF）

**不要**在这里放业务逻辑（例如 `@field_validator` 里做打分）——
校验可以，计算不行（指南 §4.2）。
"""
