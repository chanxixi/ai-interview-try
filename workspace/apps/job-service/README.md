# job-service — Java / Spring Boot 岗位领域层

链路位置：`Vue → BFF → **job-service** → analyzer → LLM`

## 职责

- 岗位 JD / 技能词典领域 API
- DTO 契约、服务编排、持久化

## 禁止

- 文本算法、直接调用 LLM（spec.md §3.1）

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| GET | `/internal/ping` | 连通性探针，继续下探 analyzer |

## 本地运行

```bash
mvn spring-boot:run
# → http://localhost:8080
```

## 测试

```bash
mvn test
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `JOB_SERVICE_PORT` | 8080 | 服务端口 |
| `ANALYZER_URL` | http://localhost:8000 | 下游 analyzer 地址 |
| `ANALYZER_TIMEOUT_MS` | 45000 | 下游读超时（plan.md §6.1） |
| `LOG_LEVEL` | INFO | 日志级别 |

## 设计说明

- **traceId**：`TraceIdFilter` 读取 `X-Trace-Id`，缺失则生成，写入 MDC 并回写响应头
- **超时**：`RestClientConfig` 为所有下游调用设置连接/读超时（spec.md §3.3 禁止无超时的外部调用）
- **日志**：`logback-spring.xml` 输出 JSON，含 `traceId` 与 `service` 字段
- **错误收口**：`GlobalExceptionHandler` 统一返回 `{code, message, traceId}`，不透传错误栈

## 骨架阶段的已知缺口

- 尚未接入 H2 / JPA，岗位与技能数据表未建（tasks.md T4）
- 尚无 `GET /api/jobs`、`GET /api/jobs/{id}`、`GET /api/skills`（tasks.md T4）
- 尚未接入 springdoc-openapi
