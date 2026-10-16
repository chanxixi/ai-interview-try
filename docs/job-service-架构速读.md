# job-service 架构速读

> **本次产出未改动 job-service 的任何代码**（`git status` 中该目录无变化）。
> 本文只是阅读产物，随代码演进会过期 —— 拿不准时以源码注释为准。
>
> 阅读范围：`workspace/apps/job-service/` 共 41 个文件（26 个 Java 源文件 + 5 个测试 + 资源与构建）。
> 生成时间：2026-10-16。

---

## 0. 60 秒版本

**一句话定位：job-service 是「岗位领域数据 + 编排」层 —— 全链路唯一能碰数据库、也是唯一能决定「给 Python 看什么数据」的服务。**

```
Vue3  →  Koa BFF  →  job-service  →  analyzer(FastAPI)  →  LLM
                        ★ 本文        （只算不管）
```

三条铁律（违反任何一条都算架构事故）：

| # | 铁律 | 物理保证 |
|---|---|---|
| 1 | **只有它有数据访问权** | BFF 与 analyzer 的源码里没有任何 JDBC/JPA/DB 驱动 |
| 2 | **它不解析 PDF、不算分、不调 LLM** | `grep -rn "pdfbox\|PDFTextStripper" src/main/java` 为空；`client/` 只搬字节 |
| 3 | **它是唯一把岗位数据交给 Python 的地方** | 只有 `AnalysisOrchestrationService` 读岗位表装配 `jobCandidates` |

代码规模分布（`src/main/java`，共 26 个文件）：

| 包 | 文件数 | 一句话 |
|---|---|---|
| `controller/` | 3 | HTTP 入口，只做协议转换 |
| `service/` | 2 | 编排与容错，业务决策都在这里 |
| `client/` | 2 | 出站适配器，只发请求不做决策 |
| `repository/` | 4 | 只读仓储（窄接口） |
| `entity/` | 4 | JPA 表映射，**不出 repository** |
| `dto/` | 2 + `response/` 4 | 边界唯一语言 |
| `config/` | 2 + `properties/` 1 + `constants/` 1 + `rubric/` 1 | 装配逻辑与配置数据分开 |
| `exception/` | 3 | 错误码 + 领域异常 + 边界收口 |
| `web/filter/` | 1 | traceId 贯穿 |
| 根 | 1 | 启动类 |

---

## 1. 请求怎么走 —— 读懂这两条路径 = 读懂 70%

代码里只有 **4 个 HTTP 端点**（见 §4），其中 2 个是真实业务入口。把这两条路径手推一遍，整个工程就通了。

### 路径 A：探针 `GET /internal/ping`（最短，建议第一个读）

```
①  web/filter/TraceIdFilter            取 X-Trace-Id（无则 UUID），塞进 MDC，回写响应头
②  controller/internal/InternalController   @GetMapping("/ping")，一行 return
③  service/InternalService.ping()      从 MDC 读 traceId → 组装本跳信息
④  service/InternalService.probeAnalyzer()  try { 调下游 } catch { 标 down，不透传堆栈 }
⑤  client/AnalyzerClient.ping(traceId)  RestClient.get("/internal/ping") + 透传 header
⑥  → analyzer 返回 AnalyzerPingResponse (record，入站 DTO)
⑦  回到 ③ 组装 PingResponse (record，出站 DTO) → Jackson 序列化
⑧  TraceIdFilter 的 finally            MDC.remove()  ← 线程池复用必须清，否则串号
```

**关键设计**：下游挂了**不抛异常**，而是返回 `downstream.status = "down"` + 异常**类名**。
判据是「探针的语义是报告链路状态，不是执行用户请求」（`InternalService` 类注释）。

### 路径 B：主线 `POST /api/analysis/stream`（multipart 进 / SSE 出）

分四个阶段，阶段边界非常清晰：

**阶段 1 · 同步校验（建流之前，走普通 HTTP 错误）**

| 校验 | 位置 | 失败 |
|---|---|---|
| 文件 ≤ 10 MB | `AnalysisController` L114 | 413 `FILE_TOO_LARGE` |
| file 与 resumeText 至少一个 | L120 | 400 `INVALID_INPUT` |
| `analysisDepth ∈ {standard, deep}` | L126 | 400 `INVALID_INPUT` |
| `topN ∈ [1, 10]` | L130 | 400 `INVALID_INPUT` |

> 为什么要「建流之前」判：这些条件不依赖文件内容，没有任何理由推迟到 SSE 里报错 —— 否则前端要先转起进度条才收到 error。
> MIME / magic number / 页数 / 加密 / 无文本层**不在这里判**，前者归 BFF（唯一校验点），后者归 Python。

**阶段 2 · 装配（全项目唯一给 Python 数据的地方）**

```
AnalysisOrchestrationService.assembleCandidates()
  ├─ JobRepository.findActiveForCandidates()          status='active' AND deleted_at IS NULL, ORDER BY code
  ├─ JobRequirementRepository.findByJobIdIn(jobIds)   一次 IN，避免 N+1
  ├─ SkillRepository.findIdAndCanonicalByIdIn(...)    skill_id → canonical 纯查表
  ├─ JobCategoryRepository.findAllById(...)           回填分类 code（不参与打分）
  └─ RubricWeightsProvider                            level → 权重档 + 六维权重（part3）
       ↓
  List<JobCandidateDto>（★ 结构上不含 jdText 原文）
```

然后 `findJdTextByJobId(jobId).orElseThrow(JOB_NOT_FOUND)` —— 目标 JD 走**顶层 `jdText` 字段**，不进候选集。
⚠️ 这里**故意不 `orElse(null)`**：静默放行会让 analyzer 算出 `score=0` 的 match，和「真的一个技能都没命中」在响应里完全一样，用户无从知道自己填错了岗位 ID。

**阶段 3 · 建流（SSE 三件套，缺一不可）**

```java
servletResponse.setContentType(TEXT_EVENT_STREAM_VALUE);   // 必须显式设
servletResponse.setCharacterEncoding("UTF-8");
servletResponse.setHeader("Cache-Control", "no-cache");
servletResponse.setHeader("X-Accel-Buffering", "no");      // Nginx 默认会攒批 SSE
ResponseBodyEmitter emitter = new ResponseBodyEmitter(0L); // 0 = 不超时，交给 spring.mvc.async.request-timeout
```

> 为什么是 `ResponseBodyEmitter` 而不是 `SseEmitter`：后者会把每次 `send` 包成自己那套事件格式，而这里要的是**字节级透传** —— Python 发来的帧长什么样，前端就收什么样。
> 为什么必须显式设 Content-Type：`produces` 和 `send(..., MediaType)` 都**不会**落到响应头上（实测 `curl -D` 拿不到），少了它前端按 content-type 判断「走流式还是回退同步」就失效。

**阶段 4 · 转发（跑在专用线程池，不占 Servlet 线程）**

```
streamExecutor.execute(() ->            ← StreamExecutorConfig 的专用 TaskExecutor（core=4, max=8, queue=32）
    analyzerStreamClient.stream(...)
      └─ RestClient.post("/internal/analyze/stream") → exchange(...)
           ├─ status != 200 → 读掉 body 记日志，返回 status
           └─ status == 200 → pumpLines()  按行读，每行补回 "\n" 后交给回调
                 └─ onLine → emitter.send(line, TEXT_EVENT_STREAM)   逐帧 flush
```

错误处理三条出口：

| 情况 | 处理 |
|---|---|
| `BusinessException` | `GlobalExceptionHandler` → `{code, message, traceId}` + 对应 HTTP 状态码 |
| 上游非 200 | `emitter.send({code:"ANALYSIS_FAILED", ...}, APPLICATION_JSON)` —— 争取一个同步错误而不是 200+空流 |
| 客户端断开 | 记日志后 `emitter.complete()`，**不往外抛**（抛出去 Spring 会再写一次响应 → 二次错误） |

---

## 2. 分层与依赖方向（唯一不可违反的架构律）

```
controller ──→ service ──→ client ──→ 外部（analyzer）
                  │              │
                  └──→ dto ←─────┘

repository ──→ entity ──→ DB
（只被 service 调用；entity 不出 repository 包）

exception / config / web   ← 横切，可被任意层引用，自身不依赖任何业务包
```

| 层 | 做什么 | **不**做什么 | 判据 |
|---|---|---|---|
| `controller` | 接请求、校验、装配、写响应头 | 不写 `try/catch`、不写业务 `if`、不碰 Repository | 「`InternalController` 里没有任何 `try/catch` 与 `if`，一旦出现说明逻辑漏在了这一层」 |
| `service` | 编排、容错、决策、事务边界 | 不碰 `HttpServletRequest` / `ResponseEntity` | 「换成 CLI 或队列消费者时本类可原样复用」 |
| `client` | 把请求发出去、把响应拿回来 | 不做降级决策、不做业务判断 | 「失败要不要吞掉、以什么形状表达，是业务决策」 |
| `repository` | 数据访问 | 不让 `entity` 泄漏出去 | 「直接返回 Entity 会把表结构绑死成 API 契约」 |

一句话记法：**「这一段逻辑换掉传输方式后还在不在？」在 → service，不在 → controller。**

---

## 3. 文件逐个体检

### 3.1 启动类

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `JobServiceApplication.java` | `main` + `@SpringBootApplication` + `@ConfigurationPropertiesScan` | `@ConfigurationPropertiesScan` 让 `AppProperties` 不用逐个 `@EnableConfigurationProperties` —— 包扫描范围内自动生效 |

### 3.2 `controller/` —— 3 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `health/HealthController.java` | `GET /healthz` → `HealthResponse.ok(name)`。service name 由 `@Value("${spring.application.name}")` 注入 | ① `@Value` 从配置取字符串；② Controller 里没有任何业务分支；③ 刻意**不用** Actuator —— 三个服务要统一 `/healthz` 形状 |
| `internal/InternalController.java` | `GET /internal/ping` → 委托 `InternalService` | 类级 `@RequestMapping("/internal")` 统一前缀；方法体只有一行 —— **这就是「Controller 该多薄」的标尺** |
| `analysis/AnalysisController.java` (213 行，最大的一个) | `POST /api/analysis/stream`，multipart → SSE 字节透传 | 见下方「这个类值得单独读」 |

**`AnalysisController` 值得单独读的 5 个点：**

1. **字段名做成常量**：`FIELD_FILE = "file"` 等 —— 与契约 `bff-python.yaml` 逐字一致，改错编译期能发现。
2. **`produces = TEXT_EVENT_STREAM_VALUE`** 写在注解上，同时**又**在 `servletResponse` 上显式设一次 —— 注释解释了「为什么两者都不能省」。
3. **装配与 UI 校验分开**：`ALLOWED_DEPTHS` / `MAX_TOP_N` 是契约值，用 `List.of(...)` 常量表达而不是硬编码在 `if` 里。
4. **`final` 局部变量快照**：进入 `streamExecutor.execute(() -> ...)` 前把 8 个变量各抄一份 `final`。这是**闭包捕获可变变量**的经典手法 —— Lambda 只能捕获 effectively-final 变量。
5. **`onCompletion` / `onTimeout` / `onError` 三个回调**都只记日志，不改变控制流。

### 3.3 `service/` —— 2 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `InternalService.java` | 组装「本跳 + 下游一跳」探测结果；决定下游失败如何表达 | ① **容错放 service 不放 client**；② 只回传异常**类名**（探针面板会显示给前端，不透传堆栈）；③ 类注释写了「**为什么不抽接口**」—— 只有一个实现且能直接 `new`，为每个 Service 加接口只是样板 |
| `AnalysisOrchestrationService.java` (197 行) | ★ 全项目唯一的领域数据出口 | 见下 |

**`AnalysisOrchestrationService` 的 4 个手法：**

1. **批查避免 N+1**：先 `findByJobIdIn(jobIds)` 一次拿全，再在内存里 `computeIfAbsent` 分组 —— 而不是循环里逐个 `findByJobId`。
2. **`LinkedHashMap` 而非 `HashMap`**：保序，让「同一份数据两次装配出的顺序一致」可复现。
3. **数据事故不静默跳过**：`skill_id` 查不到 canonical 时 `log.error` 并 `continue`，注释说明「静默跳过会让该技能从打分里消失、分数虚高」。
4. **`private` 拆方法**：`loadCategoryCodes` / `toCandidate` 把 60 行的装配拆成可读的三段。

### 3.4 `client/` —— 2 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `AnalyzerClient.java` (39 行) | `ping(traceId)`，走 `RestClient` bean | **这是 Spring 6 新 `RestClient` 的标准链式写法**：`.get().uri().header().retrieve().body(X.class)` —— 一行一个语义 |
| `AnalyzerStreamClient.java` (194 行) | 把 multipart 发给 analyzer，把 SSE 逐行泵回 `onLine` | ① `.exchange((req, res) -> {...})` 拿到**原始响应流**；② `ByteArrayResource` 匿名子类覆写 `getFilename()` 才能带上 multipart filename；③ `SimpleClientHttpRequestFactory` 手动设 connect/read 超时；④ 用 `restClient.post()` 而不是 WebClient —— 阻塞式更配 Servlet 模型 |

### 3.5 `repository/` —— 4 个文件

| 文件 | 继承自 | 关键点 |
|---|---|---|
| `JobRepository` | `CrudRepository<JobEntity, Long>` | **故意不用 `JpaRepository`** —— 后者自带 `delete`/`deleteAll`，而 spec 禁止物理删除。**把「不能做的事」变成编译期不可能**。软删条件写在 `@Query` 里，不让调用方拼 |
| `JobRequirementRepository` | `CrudRepository` | `findByJobIdIn` 用 `@Query` 显式 JPQL；`ORDER BY` 交给调用方（属于装配策略） |
| `SkillRepository` | `CrudRepository<Integer>`... | `findIdAndCanonicalByIdIn` 返回 `List<Object[]>` —— 两列纯查表不值得建 DTO，类注释给了理由 |
| `JobCategoryRepository` | `ListCrudRepository` | ⚠️ 与另外三个不一致（Spring Data 3.0 起推荐 `List*` 变体），是历史遗留的用法差异 |

### 3.6 `entity/` —— 4 个文件

全部是 **贫血模型**（只有字段 + getter/setter），**没有任何关联注解**（没有 `@ManyToOne` / `@OneToMany`），关联全靠显式外键 `Long` 字段 + 手写查询。这是刻意的：避免懒加载代理与 N+1 的隐蔽性。

| 文件 | 表 | 最值得看的注释 |
|---|---|---|
| `JobEntity` | `job` | ★ **`@Lob` 必须配 `length`**：只写 `@Lob` 时 Hibernate 6 在 MySQL 方言下会挑最小的 LOB 档位（`tinytext`，255 字节），`ddl-auto=validate` 直接拒绝启动；关掉 validate 则 JD 原文被**静默截断**。`16_777_215` = MEDIUMTEXT 上限。这个坑只在真 MySQL 上暴露（H2 只有 CLOB 一档） |
| `JobEntity` | `job` | `columnDefinition = "CHAR(64)"` 是为了对齐库里的定长 CHAR —— 只写 `length = 64` Hibernate 会期望 `VARCHAR(64)`，validate 报类型不匹配。**这正是 validate 的价值** |
| `JobRequirementEntity` | `job_requirement` | ★ 算分依据。`skillId` NOT NULL（D3），`skillRaw` 只作展示 —— 「人看到的写法」与「机器比的键」分开 |
| `JobCategoryEntity` | `job_category` | D1「分类是数据不是代码」：**这个包里没有任何 enum**，新增一类岗位 = INSERT 一行 |
| `SkillEntity` | `skill` | 真源是 `analyzer/app/data/skills.yaml`，本表由脚本生成、禁止手改 |

### 3.7 `dto/` —— 6 个文件

| 文件 | 形态 | 学习点 |
|---|---|---|
| `JobCandidateDto.java` | class（有 setter） | `@JsonInclude(NON_NULL)`；★ 类注释是**架构断言**：「不含 jdText 原文 —— 让 Python 不可能偷读岗位数据自己重抽」 |
| `RequirementDto.java` | class + 全参构造 | 为什么不用 record 的紧凑构造：`jdOffset` 可空、契约是 `['integer','null']`，用 record 每个调用点都要判空 |
| `response/HealthResponse.java` | `record` | 用 record 而不用 `Map.of` 的理由：① Map 无序，字段顺序每次都变，快照测试不稳定；② 形状写死在代码里，改字段编译期发现调用方 |
| `response/PingResponse.java` | `record` + 嵌套 `record Downstream` | 嵌套 record 表达「固定形状的子对象」；注释解释为何不做成功/失败两个子类型（探针形状越稳定越好用） |
| `response/AnalyzerPingResponse.java` | `record` | **入站 DTO** —— 下游返回的形状属于契约，不该混在 `client/` 里 |
| `response/ApiErrorResponse.java` | `record` | ★ **刻意不加** `@JsonInclude(NON_NULL)`：契约要求三个字段恒定存在。与 `PingResponse` 的对比就是「何时该加、何时不该加」的完整教材 |

> **record 的隐藏知识**：record 的字段声明顺序 = Jackson 序列化顺序。`HealthResponse` 的注释明说「字段顺序刻意与重构前保持一致，让『逐字一致』可以用 diff 直接证明」。

### 3.8 `exception/` —— 3 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `ErrorCode.java` | enum：`code → HttpStatus → 默认文案` | ★ 枚举带字段 + 构造器 + 访问器，是 Java 里表达「常量表」的标准写法。类注释列出**刻意不收录的码**（如「数据库不可用」—— 降级在 Java 层内部消化，上游永远看不到） |
| `BusinessException.java` | `extends RuntimeException`，携带 `ErrorCode` | ★ **服务层只抛领域异常，绝不抛 HTTP 类型**。理由：① 业务单测不用造 Web 上下文；② 换传输方式不用改业务代码 |
| `GlobalExceptionHandler.java` | `@RestControllerAdvice` + 3 个 `@ExceptionHandler` | ★ 全服务唯一把异常翻译成 HTTP 的地方。三个 handler 分工：`BusinessException` → 按码映射（4xx 记 warn / 5xx 记 error+堆栈）、`MethodArgumentNotValidException` → 400、`Exception` → 兜底 500（**没有这一条，未预期异常会走 Spring 默认错误体，形状与契约不一致**） |

### 3.9 `config/` —— 5 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `RestClientConfig.java` | `@Bean RestClient analyzerRestClient(AppProperties)` | `@Configuration` + `@Bean` 的标准装配；**超时在这里统一设置**（spec 禁止无超时的外部调用） |
| `StreamExecutorConfig.java` | `@Bean(name=STREAM_EXECUTOR) TaskExecutor` | ★ **线程池参数三件套的解释值得背**：队列**必须有界**（无界队列在下游挂掉时无限堆积→OOM）；`CallerRunsPolicy`（队列满时在调用线程跑 —— 变慢但不丢请求）；`setAwaitTerminationSeconds(30)` 配合优雅停机 |
| `properties/AppProperties.java` | `@ConfigurationProperties(prefix="careerlens")` 的 **record** | ★ `@ConfigurationProperties` + record + 嵌套 record + `@DefaultValue` —— **类型安全配置的现代写法**。注释解释为什么不用 `@Value` 散落各处 |
| `constants/TraceConstants.java` | `X-Trace-Id` + MDC key 的唯一来源 | ★ **常量类**的标准形态：`public final class` + 私有构造器 + 注释「其它地方只 import、不重新定义」。解决的痛点是「某处改了 header 名、别处没改，全链静默断裂」 |
| `rubric/RubricWeightsProvider.java` | 读 `rubric.yaml` → `level` 映射到权重档 → 下发六维权重 | ★ 见下方 |

**`RubricWeightsProvider` 的 4 个亮点：**

1. **`static {}` 静态初始化块** —— 用 `LinkedHashMap` 表达「顺序即优先级」（`校招` 必须先于 `mid` 判）。
2. **跨模块共用一份数据**：`pom.xml` 把 analyzer 的 `rubric.yaml` 并入 job-service 的 classpath，而不是在 Java 里抄一张权重表。注释：「抄一份就是两处副本，改一处忘一处是**静默**的」。
3. **`Optional` 而不是空 Map**：注释写明「空 Map 会让 Python 看起来『有值但和为 0』，空 Optional 语义明确：没装配上，请回退」。
4. **降级不阻塞启动**：读不到就 `log.warn` + 留 `null`，Python 回退自己的 rubric。
5. **`instanceof` 模式匹配**（Java 16+）：`if (value instanceof Number number)` —— 新语法在本项目里有真实用例。

### 3.10 `web/filter/` —— 1 个文件

| 文件 | 干什么 | 学习点 |
|---|---|---|
| `TraceIdFilter.java` | 读/生成 `X-Trace-Id` → `MDC.put` → 回写响应头 → `finally { MDC.remove }` | ★ ① `@Component` + `@Order(Ordered.HIGHEST_PRECEDENCE)` 让过滤器最先跑；② `implements Filter`（Servlet 原生）而**不用 Interceptor** —— Filter 在 Servlet 层，能覆盖静态资源与错误转发；③ `finally` 里清 MDC 是**线程池复用场景下的必备**，否则请求间串号；④ 放在 `web/filter/` 子包，为将来 Interceptor / 参数解析器留位置 |

---

## 4. API 清单

### 4.1 已实现（3 个）

| 方法 | 路径 | 作用 | 契约 | 调用方 |
|---|---|---|---|---|
| GET | `/healthz` | 健康检查 | ✅ spec §2.8 | docker healthcheck / CI / 探针 |
| GET | `/internal/ping` | 链路探针，继续下探 analyzer | 非契约（探针） | BFF 自检面板 |
| POST | `/api/analysis/stream` | multipart → SSE 字节透传 | ✅ M5 新增 | BFF |

### 4.2 契约已冻结、**代码未实现**（4 个）

| 方法 | 路径 | 契约位置 | 说明 |
|---|---|---|---|
| GET | `/api/jobs` | `bff-java.yaml` L110 | 岗位列表 —— 四层均无实现、无消费方 |
| GET | `/api/jobs/{jobId}` | L143 | 岗位详情 |
| GET | `/api/skills` | L168 | 技能词典 |
| POST | `/api/analysis` | L196 | **同步**分析 —— 契约按 C3 推论新增（「同步链也必须过 Java」）。⚠️ 缺口 P6：当前同步接口不支持 `deep` |

> 这 4 个端点连 `repository` 层的方法都已经写好了（`findActiveByCategoryCode` 等），差的只是 controller + service 方法 —— 属于「先行落地、等接线」的状态。

### 4.3 契约与代码不一致的地方（`x-code-delta` 已登记）

| 现状 | 契约目标 | 文件 | 里程碑 |
|---|---|---|---|
| `GET /internal/ping` | `GET /api/internal/ping` | `InternalController` `@RequestMapping("/internal")` | M5（**尚未执行**） |

即：除 `/healthz` 外所有端点应该统一 `/api` 前缀，但这个改造还没做。

---

## 5. 配置体系（四层，逐层覆盖）

```
①  src/main/resources/application.yml        声明式默认值（${ENV:default}）
②  config/properties/AppProperties.java      @ConfigurationProperties record，类型安全绑定
③  环境变量 / 仓库根 .env.example            运行时覆盖
④  pom.xml <resources>                       ★ 把 analyzer 的 rubric.yaml 并入 classpath
```

**关键配置项：**

| 配置 | 默认 | 环境变量 | 说明 |
|---|---|---|---|
| `server.port` | 8080 | `JOB_SERVICE_PORT` | |
| `server.shutdown` | `graceful` | — | 优雅停机（配合线程池的 awaitTermination） |
| `spring.mvc.async.request-timeout` | 130000 | `STREAM_TIMEOUT_MS` | SSE 整条流的预算 |
| `careerlens.analyzer.base-url` | `http://localhost:8000` | `ANALYZER_URL` | |
| `careerlens.analyzer.timeout-ms` | 110000 | `ANALYZER_TIMEOUT_MS` | Java→Python 超时 |
| `spring.datasource.url` | `jdbc:h2:mem:careerlens;MODE=MySQL;...` | `JOB_DB_URL` | 默认 H2 内存库 |
| `spring.jpa.hibernate.ddl-auto` | `validate` | — | ★ **不用 `update`/`create`** |
| `spring.sql.init.mode` | `always` | — | 每次启动跑 schema + seed（幂等） |

**超时矩阵（外层必须 > 内层）：** `BFF 120s > Java→Python 110s > LLM 20s > 心跳 15s`

**`ddl-auto=validate` 为什么重要**（`application.yml` 里的注释原话）：
> 「让 Hibernate 改表等于『数据库结构的变更不走 review』—— 那正是 D1/D2/D3 想避免的。启动时校验不过就直接失败，比悄悄改表好。」

---

## 6. 存储两档（不是三档）

```
① jdbc:h2:mem:careerlens;MODE=MySQL;DATABASE_TO_LOWER=TRUE   ← 默认，零外部依赖，克隆即可运行
② jdbc:mysql://...                                            ← 生产主路径，用 JOB_DB_URL 覆盖
```

两档**共用同一份 `db/{h2,mysql}/schema.sql` + `db/seed.sql`**，所以「换存储不换数据、不换分数」天然成立。

| 资源 | 内容 |
|---|---|
| `db/mysql/schema.sql` | 6 张表（job_category / skill / skill_alias / job / job_requirement / job_tag），全 `CREATE TABLE IF NOT EXISTS` |
| `db/h2/schema.sql` | 同构副本，差异**只有** 3 类：去掉 `ENGINE/CHARSET/COLLATE/COMMENT`、去掉列级 COMMENT、`jd_raw`/`attributes` 用 `CLOB`（H2 2.3 在 MODE=MySQL 下把 TEXT 解析成 VARCHAR，与 `@Lob` 期望的 CLOB 不符） |
| `db/seed.sql` | 1034 行，由 `scripts/gen-seed.sh` 生成、**禁止手改**；幂等。种子量：分类 14 · 技能 83 · 岗位 7 · 要求 66 |

三个 `MODE=MySQL` 连接串参数都不能省（注释里逐条给了原因）：`MODE=MySQL` 解释内联 `KEY (...)` 语法、`DATABASE_TO_LOWER=TRUE` 否则标识符折成大写与实体映射对不上、`DB_CLOSE_DELAY=-1` 让内存库在连接间隙不消失。

---

## 7. 测试地图（4 个测试类，5 个测试文件）

| 测试类 | 层次 | 打桩点 | 测什么 |
|---|---|---|---|
| `unit/service/InternalServiceTest` | **纯单元，不起 Spring** | `AnalyzerClient`（最外层适配器） | 编排、容错降级、traceId 透传 |
| `web/InternalControllerTest` | `@WebMvcTest` 切片 | `InternalService`（`@MockBean`） | 序列化形状、路径 |
| `web/HealthControllerTest` | `@WebMvcTest` 切片 | — | healthz 形状、traceId 回写 |
| `JobServiceApplicationTests` | `@SpringBootTest` 冒烟 | — | 全部 Bean 可装配 |
| `repository/RequirementRepositoryTest` | `@DataJpaTest` + 内嵌 H2 | — | 12 个测试：种子导入、D1/D2/D3 约束、N+1、候选集装配、part3 权重 |

**这个测试体系最值得学的两点：**

1. **打桩点选在最外层依赖**（下游适配器），Service 与 Controller 跑**真实实现** —— 于是「重构后原断言原样通过」就等于证明了「输出逐字一致」。
2. **`InternalServiceTest` 的存在本身就是一条设计断言**：如果 Service 里混进了 `HttpServletRequest` 或 `ResponseEntity`，这个测试**根本写不出来**。构造器参数全是普通类型，所以直接 `new` 即可。

`RequirementRepositoryTest` 里几个可迁移的套路：`@DataJpaTest` + `@AutoConfigureTestDatabase(replace = NONE)` 用自己配的 `MODE=MySQL` 数据源；用 `JdbcTemplate` 直接改库再断言仓储行为；**测试里不改 `ddl-auto=validate`** —— 实体与建表脚本漂了就该让测试集体失败。

---

## 8. 从这个项目能学到的 Java / Spring 写法（16 条速查）

| # | 写法 | 为什么这么做 |
|---|---|---|
| 1 | **构造器注入**，不用 `@Autowired` 字段注入 | 依赖显式、字段可 `final`、脱离容器也能 `new` 出来测 |
| 2 | **窄接口** `CrudRepository` 代替 `JpaRepository` | 把「不能做的事」（物理删除）变成**编译期不可能** |
| 3 | **`record` 做 DTO** | 不可变 + 字段顺序 = JSON 顺序 + 免样板 |
| 4 | `@JsonInclude(NON_NULL)` **按契约决定加不加** | `PingResponse` 加（成功时不出现 `error`）；`ApiErrorResponse` **不加**（三字段必须恒定存在） |
| 5 | `@ConfigurationProperties` + `record` + `@DefaultValue` | 类型安全配置；启动即校验；Service 只接普通类型 |
| 6 | **常量收敛成类**（`TraceConstants`） | 消除字面量重复；改一处即全链生效 |
| 7 | `Filter` + `MDC` + `finally` 清理 | 横切关注点的标准落地；线程池复用必须清 |
| 8 | `@RestControllerAdvice` 全局错误收口 | 未预期异常也有契约形状的响应体 |
| 9 | 自定义 `RuntimeException` 承载 `ErrorCode` | 业务层不出现 `HttpStatus`，边界统一翻译 |
| 10 | 线程池：**有界队列 + `CallerRunsPolicy`** | 无界队列 = 慢速下游导致 OOM |
| 11 | `ResponseBodyEmitter` vs `SseEmitter` | 要字节透传就用前者，不做重新编码 |
| 12 | `@Lob` **必须配 `length`** | 否则 MySQL 方言下静默降级到 `tinytext`（255 字节） |
| 13 | `columnDefinition` 对齐库结构 | 让 `ddl-auto=validate` 能真的校验出类型漂移 |
| 14 | 一次 `IN` 批查 + 内存分组 | 避免 N+1 |
| 15 | `Optional` 表达「可能没有」 | 比返回 `null` 语义明确，且强制调用方处理 |
| 16 | `instanceof` **模式匹配**（Java 16+） | `if (value instanceof Number number)` 省掉强转 |

另有两个「注释即文档」的习惯值得抄：**类注释里写「唯一调用方 / 唯一构造方 / 职责边界」**，以及**在 `@Query` / 字段旁写出「为什么这样写」而不是「这是什么」**。

---

## 9. 已知缺口与坑

### 9.1 已登记在册（DELIVERY.md §7/§8.10）

| 编号 | 内容 |
|---|---|
| D-9 | `/healthz` 缺 `storage` 字段（契约要求返回 `mysql \| local \| mock`）；**三档自动降级只实现了两档**（没有 mock 档） |
| D-13 | `overall` 没有独立出处字段 |
| P6 | 同步接口 `/api/analysis` 不支持 `deep` 深度 |
| P7 | 权重映射词表 Java / Python 各一份（`RubricWeightsProvider.LEVEL_HINTS` ↔ `analyzer/service/rubric.py` 的 `_WEIGHT_LEVEL_HINTS`）—— 这是全项目**唯一**一处「同一个映射写了两遍」，改一处必须同步改另一处 |

### 9.2 README 已落后于代码（⚠️ 读 README 时会踩）

`README.md` 的「已知缺口」还写着：

> - 尚未接入 H2 / JPA，岗位与技能数据表未建
> - 尚无 `GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills`

但 `application.yml` 已经有完整 datasource + JPA + schema/seed 配置，`repository/` `entity/` 里共 8 个文件都在。**README 停留在 part2 早期状态**，`/api/jobs` 那三条倒是确实还没实现。

另外 `HealthResponse` 的注释写「P2-4 起经 service 层」，实际 `HealthController` 直接返回，没有 service 层。

### 9.3 静态阅读发现、**尚未登记**的 2 处（供参考，未实跑验证）

**(a) 流式路径的 traceId 在 Java → Python 断链**

```
TraceIdFilter        ✅ 写 MDC + 回写响应头
InternalService      ✅ 从 MDC 取，传给 AnalyzerClient
AnalyzerClient.ping  ✅ 设置 X-Trace-Id header
AnalyzerStreamClient.stream(...)  ❌ 签名里没有 traceId；RestClient 调用链里也没设 header
```

`AnalysisController` 把 `@RequestHeader("X-Trace-Id")` 读进来后**只用于打日志**。所以 `/internal/ping` 那条链路 traceId 是全通的，但 `/api/analysis/stream` 这条**主线**在 Java→Python 这一跳没有带 traceId。与工作记忆中记录的「traceId 在 Java→Python 断链（`analyzerStreamClient.stream()` 签名无 traceId）」一致。

**(b) 客户端断开的容错有两条路径，实际只有一条会生效**

`AnalysisController` 的 `onLine` 回调在 `emitter.send` 抛 `IOException` 时会 `throw new UncheckedIOException(ex)`，本意是让外层 `catch (UncheckedIOException)` 记 `"stream aborted by client"`。但这个异常是在 `AnalyzerStreamClient.pumpLines()` 的 `while` 循环里抛出的，**会先被 `pumpLines` 自己的 `catch (UncheckedIOException)` 接住**并记成 `"analyzer stream interrupted"`，然后方法正常返回。

结果：控制流仍然正确（`emitter.complete()` 照常执行，不会二次写响应），但**日志文案会误导** —— 明明是自己这边的客户端断了，却记成下游中断。这是个可观测性瑕疵，不是功能 bug。

### 9.4 其他值得注意的小瑕疵（不影响正确性）

| 位置 | 现象 |
|---|---|
| `AnalyzerStreamClient` | `maybeGunzip()` 直接把入参原样返回（函数体只有 `return raw;`）；`static gunzip()` 是给「将来显式禁自动解压」预留的死代码 |
| `AnalysisOrchestrationService` | `sameJob(left, right)` 这个包级静态方法没有调用方，注释自嘲「让 `Objects` import 不显得多余」 |
| `RequirementRepositoryTest` | 同样的手法：`REPLACE_NONE` 常量只为 javadoc 引用而存在 |
| `JobCategoryRepository` | 继承 `ListCrudRepository`，另外三个仓储继承 `CrudRepository` —— 用法不统一 |
| `pom.xml` | 构建 job-service **依赖 `../analyzer/app/data/rubric.yaml` 存在**（跨模块文件依赖）。单独 clone job-service 会打包失败 |

---

## 10. 上手路线（按这个顺序读，约 1 小时）

| 顺序 | 文件 | 带着什么问题读 |
|---|---|---|
| 1 | `web/filter/TraceIdFilter.java` | 一个横切组件最标准的样子 |
| 2 | `controller/internal/InternalController.java` | Controller 到底该多薄？ |
| 3 | `service/InternalService.java` | 容错为什么在 service 而不在 client？ |
| 4 | `client/AnalyzerClient.java` | Spring 6 `RestClient` 怎么写 |
| 5 | `config/properties/AppProperties.java` + `application.yml` | 配置怎么从 yml 进到代码 |
| 6 | `exception/` 三个文件 | 错误从哪来、怎么变成 HTTP |
| 7 | `entity/JobEntity.java` | ★ 读两类注释：`@Lob + length` 的坑、validate 的价值 |
| 8 | `repository/JobRepository.java` | 窄接口 + `@Query` 表达约束 |
| 9 | `service/AnalysisOrchestrationService.java` | ★ 装配逻辑与批查手法 |
| 10 | `controller/analysis/AnalysisController.java` | ★ 最复杂的一个，也是「字节透传」的落地样本 |
| 11 | `client/AnalyzerStreamClient.java` | 阻塞式流读取与 `exchange` |
| 12 | `config/StreamExecutorConfig.java` | 线程池参数怎么定、为什么 |
| 13 | `config/rubric/RubricWeightsProvider.java` | 跨模块共用一份数据 + 降级策略 |
| 14 | `src/test/.../InternalServiceTest.java` | 从测试反推设计约束 |

**验证架构没读错的两个命令**（只读，不改任何东西）：

```bash
cd E:/代码/ai求职平台全栈笔试题/workspace/apps/job-service

# ① 铁律 2 的物理证据：Java 侧只有「校验」与「multipart 字段名」两处提到 pdf
grep -rn "pdf" src/main/java

# ② 分层是否真的单向：controller 里不应出现 Repository 或 Entity
grep -rn "Repository\|Entity" src/main/java/com/careerlens/jobservice/controller/
```

---

## 附：一页速记卡

```
定位   岗位数据 + 编排层；唯一有 DB、唯一给 Python 数据
链路   Vue → BFF → [job-service] → analyzer → LLM

入口   GET  /healthz                健康检查
       GET  /internal/ping          链路探针（下游挂了也不报错）
       POST /api/analysis/stream    multipart → SSE 字节透传（主线）
未实现 GET  /api/jobs · /api/jobs/{id} · /api/skills · POST /api/analysis

分层   controller（HTTP↔DTO） → service（编排/容错） → client（出站） 
       repository（只读）→ entity（不出包）
       横切：exception / config / web

不变量 ① 不解析 PDF  ② 不算分  ③ 不调 LLM  ④ 候选集不含 jdText 原文
        ⑤ Entity 不出 Repository  ⑥ Service 只抛 BusinessException
        ⑦ 所有外部调用都有超时  ⑧ 外层超时 > 内层超时

配置   application.yml（默认） → AppProperties(record) → 环境变量 → pom resources(rubric.yaml)
存储   H2 内存库（默认）/ MySQL（生产），同一份 schema+seed
测试   纯单元(new) / @WebMvcTest 切片 / @DataJpaTest / @SpringBootTest 冒烟
       打桩点永远选在最外层依赖
```
