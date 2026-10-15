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

## 3. 当前状态：**part1 骨架 + part2 全量实现**

> 本文件只讲「怎么跑起来」。**每一层为什么这么做、哪里和文档不一样**，
> 看 `DELIVERY.md`（§7 是偏离登记，时间紧就先看它）；
> 单个服务的溯源地图（现象 → 看哪个文件）看各自的 `apps/*/README.md`。

part2 已完成（M0–M8）：

- [x] 契约先行：`contracts/*.yaml`（含 `x-api-conventions` / `x-api-inventory` / `x-code-delta`）
- [x] 数据模型 6 张表 + 离线种子 `db/seed.sql`（`gen-seed.sh` 确定性生成，禁止手改）
- [x] PDF 解析（pypdf）与清洗七步；真实样本 20/20 通过
- [x] 归一化 / 加权匹配 / Top-N 推荐（打分公式只有一份实现，可手算复现）
- [x] SSE 流式分析（6 事件 / 7 阶段 / 心跳）+ LLM 降级
- [x] 前端 analyzer 页（Element Plus 主题定制 + ECharts 分数环 + 打字机思考台）
- [x] 四层 CI（`.github/workflows/ci.yml`）+ 六条降级演练脚本

**尚未做**（见 `DELIVERY.md` §7）：

- [ ] Dockerfile / docker-compose（part1 T7）
- [ ] 启动 / 部署 / 回滚文档（part1 T8.3）
- [ ] `/healthz.storage` 与三档自动降级（part1 AC9/AC10）—— 见 D-9

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

### 5.1 三个冒烟脚本（推荐）

```bash
bash scripts/smoke.sh              # ① 骨架还活着吗：三个 /healthz + /api/ping 全链贯通
bash scripts/smoke-stream.sh       # ② 正常路径：真发一次流式请求，按 SSE 契约逐条验
bash scripts/drill-degradation.sh  # ③ 异常路径：六条降级演练（LLM 挂 / 假 PDF / 断连风暴…）
```

三个脚本分工刻意不同 —— ①②③ 分别回答「活着吗 / 对了吗 / 坏了会怎样」。
任一项失败都会打印具体断点并返回非 0。

```bash
SAMPLE_PDF=../脱敏资料/resume_01.pdf bash scripts/smoke-stream.sh   # 走 PDF 入口
bash scripts/drill-degradation.sh 2 3                               # 只跑第 2、3 条演练
```

> `drill-degradation.sh` 需要 analyzer 的 `LLM_*` 环境变量**留空** ——
> 第 1 条演练要的就是「LLM 不可用」这个状态。

### 5.2 手工验证

```bash
# 各服务健康检查
curl http://localhost:8000/healthz
curl http://localhost:8080/healthz
curl http://localhost:3000/healthz

# 全链连通性（Vue 调的就是这个）
curl -H 'X-Trace-Id: demo-trace-001' http://localhost:3000/api/ping

# 流式分析（-N 关掉 curl 自己的缓冲，否则看不到逐帧到达）
curl -N -H 'Accept: text/event-stream' \
     -F 'resumeText=熟悉 Java、MySQL、Redis' \
     http://localhost:3000/api/analysis/stream
```

浏览器打开 http://localhost:5173 → 首页是 **analyzer**（上传简历 / 粘贴文本 → 看阶段推进 → 看结果），
顶栏「连通性」进 part1 的连通面板。

---

## 6. 测试

```bash
cd apps/analyzer    && ./.venv/Scripts/python.exe -m pytest   # 261 passed
cd apps/job-service && mvn test                               # 18 passed
cd apps/bff         && npm test                               # 52 passed
cd apps/web         && npm test && npm run type-check         # 19 passed
```

四层都**不依赖外部服务**：analyzer 的 LLM 有降级、job-service 用内嵌 H2、
BFF 的下游在用例里被替换成 stub —— 所以 CI 里不需要 MySQL / Redis / 真 LLM。

---

## 7. 目录结构

```
workspace/
├─ apps/
│  ├─ web/            Vue 3 前端（analyzer 分析页 + 连通性面板）
│  ├─ bff/            Node.js BFF（Koa2 + TS）—— 校验 / 编排 / SSE 透传
│  ├─ job-service/    Java / Spring Boot —— 岗位领域 API + 候选集装配
│  └─ analyzer/       Python / FastAPI —— 解析 / 归一化 / 匹配 / 推荐 / LLM
├─ contracts/         OpenAPI 契约（真源：frontend-bff.yaml 含 x-api-* 扩展）
├─ db/                schema（mysql / h2）+ 岗位源 + 生成物 seed.sql
├─ scripts/
│  ├─ start-all.sh / stop-all.sh / demo.sh
│  ├─ smoke.sh              全链冒烟
│  ├─ smoke-stream.sh       流式契约冒烟
│  ├─ drill-degradation.sh  六条降级演练（+ drill_degradation.py / drill_fixtures.py）
│  └─ gen-seed.sh           离线种子编译器（+ gen_seed.py）
├─ DELIVERY.md        交付说明：每层怎么做 + **§7 偏离登记**
├─ AI_LOG.md          AI 协作留痕（人对 AI 产出改了什么、为什么）
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
| `JOB_SERVICE_TIMEOUT_MS` / `ANALYZER_TIMEOUT_MS` | 超时矩阵（plan.md §6.1） | 5000 / 110000 |
| `LOG_LEVEL` | 日志级别 | info |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | LLM 接入；**三项任一留空即走规则降级**（`meta.degraded=true`） | 空 |
| `JOB_DB_URL` | 数据源。留空 = H2 内存（零依赖）；指向 MySQL 即切主路径 | H2 |
| `JOB_DB_DRIVER` / `JOB_DB_USER` / `JOB_DB_PASSWORD` / `JOB_DB_DIALECT` | 随 `JOB_DB_URL` 一起切（`DIALECT` 选 `h2` / `mysql` 的 schema 文件） | h2 / sa / 空 / h2 |

> `.env` 已在 `.gitignore` 中，**密钥绝不入库**（spec.md §3.3）。
> ⚠️ **没有** `STORAGE_MODE` 这个变量 —— part1 spec §2.9 的三档自动降级未实现，
> 现状是「两档 + 部署期切换」，见 `DELIVERY.md` §7 **D-9**。
