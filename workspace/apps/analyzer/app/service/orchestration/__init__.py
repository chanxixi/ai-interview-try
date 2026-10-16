"""编排层：把上面各组串成一次分析。

- `analysis_service`：同步接口（`/api/internal/analyze`）
- `orchestration/stream`：流式接口（SSE，8 个阶段）

**这一层只做顺序、时序、容错，不做算法**。一旦在这里看到 `re.findall(...)`
或打分公式，就是分层被穿透了 —— 算法应该属于上面某个组。
"""
