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

```bash
# 依赖 analyzer 在 8000（探针会下探它；不在也能跑，只是 downstream 显示 down）
mvn spring-boot:run
# → http://localhost:8080

# 显式指定端口（本机沙箱可能注入 SERVER__PORT，会被 Spring 宽松绑定吃掉）
mvn spring-boot:run -Dspring-boot.run.arguments=--server.port=8080
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
