# analyzer — Python 计算与算法层

链路位置：`Vue → BFF → job-service → **analyzer** → LLM`

## 职责

- 文本清洗、技能归一化、匹配打分
- LLM 编排与**降级**（LLM 不可用时走规则分支，`meta.degraded = true`）

## 禁止

- 鉴权、岗位数据 CRUD（spec.md §3.1）

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| GET | `/internal/ping` | 连通性探针，回显 `X-Trace-Id` |
| POST | `/internal/analyze` | 分析入口（骨架阶段返回空结构） |

## 本地运行

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
pytest
```

## 配置

见仓库根 `../.env.example`。LLM 三项留空时 `llm_enabled = false`，自动走规则降级分支。

## 骨架阶段的已知缺口

- `/internal/analyze` 返回空结构，真实实现见 `../../sdd/part1/tasks.md` T5
- 尚无技能词典（`skills.yaml`）
- 日志为自实现 JSON Formatter，未引入第三方日志库
