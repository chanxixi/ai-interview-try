"""能力画像（part3）：rubric 真源 + 判档兜底 + 综合分。

依赖方向（组内）：

    rubric ← advisor_rules ← ability_profile

- `rubric`：六维定义 / 档位 / 权重的**唯一**读入口（`app/data/rubric.yaml`）
- `advisor_rules`：判档与逐条判定的**规则兜底**（断 LLM 时靠它，必须非空）
- `ability_profile`：`overall` 的**唯一**计算公式

⚠️ 三者是「同一条公式的三个环节」，**不要拆到不同目录** —— 拆开后
「改 rubric 却忘了改兜底判据」会静默失效（见 tasks.md 附录 B 第 15 条）。
"""
