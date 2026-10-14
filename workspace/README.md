# CareerLens

面向高校学生的 AI 求职辅导平台 —— 最小纵向闭环。

学生提交**简历文本**并**选择岗位**，系统完成 **简历数据清洗 → 技能归一化 → 岗位匹配分析**，
返回 **简历结构化问题 / 可解释的命中项 / 能力缺口 / 岗位匹配度**。

> 规范文档见 `../sdd/part1/`：`spec.md`（要什么）、`plan.md`（怎么做）、`tasks.md`（谁做、怎么算做完）。

---

## 1. 请求链（强制，不可跳层）

```
Vue 3 (web)  →  Node.js BFF (bff)  →  Java / Spring Boot (job-service)  →  Python (analyzer)  →  LLM
```

- **BFF** 面向客户端的适配层：输入校验、请求编排、超时、错误映射、结果聚合、traceId 下发
- **job-service** 面向领域的稳定层：岗位 JD / 技能词典领域 API、DTO 契约、服务编排、持久化
- **analyzer** 计算与算法层：文本清洗、技能归一化、匹配打分、LLM 编排与降级

**禁止**：前端直连 Java / Python；BFF 承载业务规则或访问数据库；Java 做文本算法或直调 LLM；Python 管岗位数据。

---

## 2. 服务与端口

| 服务 | 目录 | 技术栈 | 端口 | 健康检查 |
|---|---|---|---|---|
| web | `apps/web` | Vue 3 + TS + Vite | 5173 | — |
| bff | `apps/bff` | Node 22 + Koa2 + TS | 3000 | `GET /healthz` |
| job-service | `apps/job-service` | Java 17 + Spring Boot 3.2 | 8080 | `GET /healthz` |
| analyzer | `apps/analyzer` | Python 3.11+ + FastAPI | 8000 | `GET /healthz` |

全链 traceId 通过 HTTP header **`X-Trace-Id`** 贯穿（spec.md §2.8）。

---

## 3. 当前状态：**骨架阶段**

已完成（本阶段）：

- [x] 四服务目录骨架，各自可独立启动
- [x] 四个 `GET /healthz` 统一返回 `{"status":"ok"}`
- [x] `GET /api/ping` 贯通链：Vue → BFF → job-service → analyzer
- [x] traceId 全链透传（`X-Trace-Id`），并在响应头回写
- [x] 结构化 JSON 日志
- [x] 各层单元测试（analyzer 3 / job-service 2 / bff 8）
- [x] BFF 侧超时与错误映射骨架（`503` / `504` / `500` 收口）
- [x] `scripts/smoke.sh` 一键全链冒烟

尚未开始（后续任务）：

- [ ] `contracts/` 三份 OpenAPI 契约（T1）
- [ ] `POST /api/analysis` 竖切贯通（T3）
- [ ] `/internal/analyze` 真实实现：清洗 / 归一化 / 匹配（T2、T5）
- [ ] 岗位 JD 与技能词典领域 API（T4）
- [ ] LLM 接入与降级（T5）
- [ ] 前端结果可视化与组件库改造（T6）
- [ ] Dockerfile / docker-compose / CI/CD（T7、T8）

---

## 4. 本地运行（开发模式，四终端）

依赖：Node 22+、Python 3.11+、JDK 17+、Maven 3.9+

```bash
# 0) 准备环境变量
cp .env.example .env

# 1) analyzer  → http://localhost:8000
cd apps/analyzer
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2) job-service → http://localhost:8080
cd apps/job-service
mvn spring-boot:run

# 3) bff → http://localhost:3000
cd apps/bff
npm install
npm run dev

# 4) web → http://localhost:5173
cd apps/web
npm install
npm run dev
```

**启动顺序**：analyzer → job-service → bff → web（后者依赖前者）。

> **Windows 提示**：`mvn` 在 Git Bash 里可能因类路径分隔符报
> `找不到或无法加载主类 org.codehaus.plexus.classworlds.launcher.Launcher`，
> 改用 `mvn.cmd`（或在 PowerShell / CMD 中执行）即可。
> 另外 `JAVA_HOME` 需为 Windows 路径（如 `C:\Program Files\Java\jdk-17`）。

---

## 5. 验证链路

### 5.1 一键冒烟（推荐）

```bash
bash scripts/smoke.sh
```

检查健康检查、全链连通性与 traceId 回写；任一项失败会打印具体断点并返回非 0。

### 5.2 手工验证

```bash
# 各服务健康检查
curl http://localhost:8000/healthz
curl http://localhost:8080/healthz
curl http://localhost:3000/healthz

# 全链连通性（Vue 调的就是这个）
curl -H 'X-Trace-Id: demo-trace-001' http://localhost:3000/api/ping
```

预期返回：四层服务的连通状态，且 `traceId` 全链一致。

浏览器打开 http://localhost:5173 可看到连通性面板（前端自行生成 traceId 并逐跳展示）。

---

## 6. 测试

```bash
cd apps/analyzer    && pytest
cd apps/job-service && mvn test
cd apps/bff         && npm test
cd apps/web         && npm run type-check
```

---

## 7. 目录结构

```
workspace/
├─ apps/
│  ├─ web/            Vue 3 前端（连通性面板）
│  ├─ bff/            Node.js BFF（Koa2 + TS）
│  ├─ job-service/    Java / Spring Boot
│  └─ analyzer/       Python / FastAPI
├─ scripts/
│  └─ smoke.sh        全链冒烟
├─ .env.example       环境变量模板（单点维护，四个服务共用）
├─ .gitignore
└─ README.md
```

---

## 8. 环境变量

单点维护在仓库根 `.env`（模板 `.env.example`），四个服务都从根目录读取，避免多处配置漂移。

| 变量 | 用途 | 默认 |
|---|---|---|
| `WEB_PORT` | 前端端口 | 5173 |
| `BFF_PORT` | BFF 端口 | 3000 |
| `JOB_SERVICE_PORT` | job-service 端口 | 8080 |
| `ANALYZER_PORT` | analyzer 端口 | 8000 |
| `BFF_URL` / `JOB_SERVICE_URL` / `ANALYZER_URL` | 服务发现 | `http://localhost:<port>` |
| `JOB_SERVICE_TIMEOUT_MS` / `ANALYZER_TIMEOUT_MS` | 超时矩阵（plan.md §6.1） | 5000 / 45000 |
| `LOG_LEVEL` | 日志级别 | info |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | LLM 接入（T5）；三项留空即走规则降级 | 空 |
| `STORAGE_MODE` / `MYSQL_*` | 存储策略（T4，spec.md §2.9） | `auto` |

> `.env` 已在 `.gitignore` 中，**密钥绝不入库**（spec.md §3.3）。
