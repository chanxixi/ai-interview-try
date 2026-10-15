# job-service — Java / Spring Boot 岗位领域层

链路位置：`Vue → BFF → **job-service** → analyzer → LLM`

## 职责与禁止

| | 内容 |
|---|---|
| **职责**（spec.md §2.6） | 岗位 JD / 技能词典领域 API、DTO 契约、服务编排、**持久化** |
| **禁止** | 文本算法、直接调用 LLM |

**数据访问权只属于本服务**（spec.md §3.1）：BFF 与 analyzer 都不许直连数据库。

## 接口

| 方法 | 路径 | 说明 | 契约 |
|---|---|---|---|
| GET | `/healthz` | 健康检查 | spec.md §2.8 |
| GET | `/internal/ping` | 连通性探针，继续下探 analyzer | 非契约（探针） |
| GET | `/api/jobs` · `/api/jobs/{id}` · `/api/skills` | 岗位 / 技能领域 API | ⬜ T4 待实现 |

## 目录结构（分层）

```
src/main/java/com/careerlens/jobservice/
├─ JobServiceApplication.java          启动类（@ConfigurationPropertiesScan）
├─ controller/                         ① 控制层：只做 HTTP ↔ DTO
│  ├─ health/HealthController.java
│  └─ internal/InternalController.java
├─ service/                            ② 业务层：编排 / 容错 / 事务边界
│  └─ InternalService.java
├─ client/                             ③ 出站适配器：只发请求，不做决策
│  └─ AnalyzerClient.java
├─ dto/response/                       ④ 边界唯一语言
│  ├─ HealthResponse.java              出站
│  ├─ PingResponse.java                出站（含 Downstream 嵌套）
│  ├─ ApiErrorResponse.java            出站（错误）
│  └─ AnalyzerPingResponse.java        入站（下游 analyzer 的返回形状）
├─ exception/                          ⑤ 错误码 + 业务异常 + 边界收口
│  ├─ ErrorCode.java                   ← spec.md §2.3 冻结表的唯一来源
│  ├─ BusinessException.java
│  └─ GlobalExceptionHandler.java
├─ config/
│  ├─ RestClientConfig.java            装配：下游客户端 + 超时
│  ├─ properties/AppProperties.java    配置数据本身
│  └─ constants/TraceConstants.java    header 名 / MDC key 的唯一来源
└─ web/filter/TraceIdFilter.java       ⑥ 横切：MDC traceId
```

**依赖方向**（唯一不可违反的架构律，指南 §1.1）：

```
controller → service → client ─┐
                │              ├→ 外部
                └→ dto ←───────┘
exception / config / web 是横切，可被任意层引用，自身不依赖业务包
```

## 溯源地图 —— 现象 → 该看哪个文件

> 用法：拿到一个现象，先看「第一个该看的文件」；若那里没问题，再顺「再看」列往下走。

| 现象 | 第一个该看的文件 | 再看 |
|---|---|---|
| 接口报错，但不知道 `code` 从哪来 | `exception/ErrorCode.java` | `exception/GlobalExceptionHandler.java` |
| 错误响应体不是 `{code,message,traceId}` | `exception/GlobalExceptionHandler.java` | `dto/response/ApiErrorResponse.java` |
| 错误响应里出现了堆栈 / 内部类名 | `exception/GlobalExceptionHandler.java` | 是否有人把 `ex.getMessage()` 当对外文案 |
| 某条 URL 由谁处理 | 在 `controller/` 下按路径找 | `@RequestMapping` 前缀 |
| 探针说下游 `down`，但下游其实活着 | `service/InternalService.java` `probeAnalyzer` | `client/AnalyzerClient.java` 的 URL / 超时 |
| 调 analyzer 超时 / 想改超时时间 | `config/properties/AppProperties.java` | `config/RestClientConfig.java`（连接超时）+ `application.yml` |
| 日志里 traceId 断了 / 是 `null` | `web/filter/TraceIdFilter.java` | `client/AnalyzerClient.java` 是否透传 header |
| 想改 traceId 的 header 名 | `config/constants/TraceConstants.java` | ⚠️ 三个服务必须同时改（spec.md §2.8 冻结） |
| 启动就崩，报配置错误 | `config/properties/AppProperties.java` | `src/main/resources/application.yml`、仓库根 `.env.example` |
| 响应字段顺序变了 / 前端解析失败 | `dto/response/` 下对应的 record | record 的字段声明顺序 = JSON 输出顺序 |
| 某个 Bean 没被装配 | 该类的构造器 | 是否在 `JobServiceApplication` 的扫描路径下 |
| 想替换某层做测试 | 看测试类的 `@MockBean` | `unit/` 用 `new`，`web/` 用 `@WebMvcTest` |

## 变更路径 —— 要改什么 → 动哪些文件 → 千万别动

| 要改什么 | 动哪些文件 | 千万别动 |
|---|---|---|
| 加一个错误码 | `exception/ErrorCode.java` **+ 先改 `spec.md` §2.3** | 不要在业务层直接 `throw new RuntimeException` |
| 加一个接口 | `controller/<域>/` 新建类 → `service/` 加方法 → `dto/` 加形状 | 不要把逻辑写进 controller |
| 换下游服务地址 | `application.yml` 或环境变量 `ANALYZER_URL` | 不要在代码里硬编码 URL |
| 改下游调用的容错策略 | `service/`（不是 `client/`） | 不要把策略写进 `client/` |
| 加配置项 | `config/properties/AppProperties.java` + `application.yml` + 仓库根 `.env.example` | 三处必须同步，缺一个就是"文档在骗人" |
| 换日志格式 | `src/main/resources/logback-spring.xml` | MDC key 由 `TraceConstants` 决定，别改字面量 |
| 引入存储（T4） | `repository/` + `entity/` + `mapper/` + `config/properties/StorageProperties.java` | 不要让 Service 直接依赖 `JpaRepository`（ADR-007） |

## 未接线清单（先行落地，等主线功能接入）

> 判据：**契约形状与横切组件可以先行；调用链必须跟功能同步进**，否则就是死代码。

| 已就位 | 接线点 | 什么时候接 |
|---|---|---|
| `exception/ErrorCode` 全 8 个码 | 目前只有 `INVALID_INPUT` / `INTERNAL_ERROR` 会被真实触发 | T4：`JOB_NOT_FOUND` 由岗位查询触发；`SERVICE_UNAVAILABLE` / `UPSTREAM_TIMEOUT` 由 BFF 侧映射（本服务不产生） |
| `exception/BusinessException` | 无任何 `throw`（本期没有会失败的只读接口） | T4：`getJob(id)` 找不到时抛 |
| `dto/response/ApiErrorResponse` | 仅 `GlobalExceptionHandler` 构造 | — |
| `AppProperties.analyzer.timeoutMs` | 已接入 `RestClientConfig` | — |

## 本地运行

### 前置：JDK 17 + Maven 已在 PATH 里（2026-10-14 配置）

本机 `mvn` / `java` 原本**不在 PATH**（工具链是隔离安装的便携版），直接跑 `mvn spring-boot:run` 会报
`无法将"mvn"项识别为 cmdlet、函数、脚本文件或可运行程序的名称`。已写入**用户级**环境变量：

| 变量 | 值 |
|---|---|
| `JAVA_HOME` | `C:\Users\Administrator\.workbuddy\binaries\tools\jdk\jdk-17.0.2` |
| `Path` 追加 | `...\jdk-17.0.2\bin`、`...\maven\apache-maven-3.9.9\bin` |

**Maven 镜像**：`~/.m2/settings.xml` 已写入阿里云公共仓库镜像（2026-10-14 补）。
此前该文件不存在，`mvn` 会直连 `repo.maven.apache.org`，国内经常卡住后报
`Could not transfer artifact ... Connection timed out`。撤销：删掉该文件即恢复直连。

> **改完必须重开终端**（环境变量对已运行的终端无效）。撤销：系统属性 → 环境变量 → 删掉这两条。
> 工具链不进仓库；`scripts/start-all.sh` 仍保留「PATH 里找不到 java 就回退到便携版」的逻辑。

### 三条命令

```powershell
cd E:\代码\ai求职平台全栈笔试题\workspace\apps\job-service

mvn spring-boot:run              # ① 开发调试：前台 + 实时日志
```

| 想做什么 | 命令 | 耗时 |
|---|---|---|
| **开发调试**（前台，实时日志，改完重起） | `mvn spring-boot:run` | 约 1–3 秒启动 |
| **跑产物**（最接近生产，需先打包） | `mvn -q clean package -DskipTests` 然后 `java -jar target/job-service-0.1.0.jar` | 打包 20–40 秒 / 启动约 2 秒 |
| **只跑测试** | `mvn test` | 约 15–30 秒 |

**端口不用手写** —— `application.yml` 里是 `${JOB_SERVICE_PORT:8080}`，默认就是 8080。

### ⚠️ `SERVER__PORT=0` 只在 AI 助手沙箱里存在，不是你的环境

`SERVER__PORT=0` / `SERVER__HOST=127.0.0.1` 是 **AI 助手执行命令时注入的进程级环境变量**。
已核对注册表 `HKCU:\Environment` —— **你的终端里没有 `SERVER*`**。

Spring Boot 的宽松绑定会把 `SERVER__PORT` 映射成 `server.port=0`，让服务跑到**随机端口**上
（表现为「进程活着但 8080 不通」）。这是**助手侧执行**才需要防的坑，所以：

- **你自己在终端跑** → 不用加任何参数；
- **助手/脚本代跑** → 显式加 `--server.port=8080 --server.address=127.0.0.1`（`start-all.sh` 已这么做）。

> Git Bash 里用 Maven 插件传参要加引号：`"-Dspring-boot.run.arguments=--server.port=8080 --server.address=127.0.0.1"`，
> 值含空格，不加引号会被拆成两个参数。PowerShell 里则不需要传参。

### 依赖关系

analyzer（`:8000`）不在也能启动 —— `/internal/ping` 会容错返回 `downstream.status = "down"`，**不报错**。
想看完整两跳，先起 analyzer：`cd ../analyzer && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`。

### 改完代码怎么生效

**Java 没有热重载**（`pom.xml` 里没有 `spring-boot-devtools`）：改完 `.java` 要 Ctrl+C 重起；
`java -jar` 那条还得先重新打包。想自动重启就加 devtools —— 代价是多一个依赖，
且 devtools 会引入独立的 restart classloader，排查类加载问题时反而是干扰。

### 坑：旧进程会锁住 jar / 占住 8080

**最常见的一种**：上一次的服务没停干净，再跑 `mvn spring-boot:run` 直接启动失败：

```
Web server failed to start. Port 8080 was already in use.
```

注意它是**启动失败**、不是编译失败 —— 日志里 `Tomcat initialized with port 8080` 之后才报错，
容易误判成代码问题。先按下面两条确认端口，再重试。

停服务再打包，否则 `mvn clean` 报 `Failed to delete ...jar`、`repackage` 报 `Unable to rename ... .jar.original`。
而且旧进程可能因端口被顶掉而**不监听你以为的端口**，所以不容易发现：

```bash
bash ../../scripts/stop-all.sh job-service          # 按端口找 PID 结束
netstat -ano | grep LISTENING | grep ":8080[[:space:]]"   # 应无输出
```

### 验证

```bash
curl -s http://127.0.0.1:8080/healthz
# {"service":"job-service","status":"ok"}

curl -s -H 'X-Trace-Id: demo-001' http://127.0.0.1:8080/internal/ping
# 响应里出现 downstream 且 traceId 与请求头一致 → 真的调到了 analyzer
```

## 测试

```bash
mvn test
```

| 测试类 | 层次 | 打桩点 | 覆盖 |
|---|---|---|---|
| `unit/service/InternalServiceTest` | 单元（**不起 Spring**） | `AnalyzerClient`（最外层适配器） | 编排、容错降级、traceId 透传 |
| `web/InternalControllerTest` | `@WebMvcTest` 切片 | `InternalService` | 序列化形状、路径 |
| `web/HealthControllerTest` | `@WebMvcTest` 切片 | — | healthz 形状、traceId 回写 |
| `JobServiceApplicationTests` | 上下文冒烟 | — | 全部 Bean 可装配 |

> 打桩点选在**最外层依赖**（下游适配器），Service 与 Controller 跑真实实现 ——
> 这样重构后原断言原样通过，就等于证明了「输出逐字一致」。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `JOB_SERVICE_PORT` | 8080 | 服务端口 |
| `ANALYZER_URL` | http://localhost:8000 | 下游 analyzer 地址 |
| `ANALYZER_TIMEOUT_MS` | 45000 | 下游读超时（plan.md §6.1） |
| `LOG_LEVEL` | INFO | 日志级别 |

## 已知缺口

- 尚未接入 H2 / JPA，岗位与技能数据表未建（tasks.md T4）
- 尚无 `GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills`（tasks.md T4）
- `/healthz` 尚无 `storage` 字段（spec.md §2.9）—— 存储层不存在时返回假字段比不返回更糟，T4 一并加
- 尚未接入 springdoc-openapi
- 未匹配路由返回 Spring 默认错误体（`{timestamp,status,error,path}`），非 spec.md §2.3 形状；
  spec 错误码表里没有「路由不存在」对应的 code，不擅自新增
