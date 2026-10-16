import type { JobServiceClient } from '../client/jobService.client';
import { config } from '../config';
import type { CapabilitiesResult } from '../dto/response/capabilities.response';
import type { PingResult } from '../dto/response/ping.response';

/**
 * 业务层：**编排 + 聚合**，完全不知道 HTTP 存在。
 *
 * 自检方式（指南 §A.1 第 1 条）：本文件不 import koa —— 一旦出现 `import type { Context }`，
 * 就说明 HTTP 细节漏进了业务层。
 *
 * 职责边界（spec.md §2.6）：
 *   ✅ 决定调用顺序、聚合下游结果、裁剪为前端 DTO
 *   ❌ 读 `ctx`、抛 HTTP 状态码、拼 JSON 响应
 *
 * 本期只有连通性探针；T3 起会新增 `AnalysisService`（jobId → 取 jdText → 调 analyzer）。
 */
export interface JobService {
  /** 聚合本跳信息 + job-service 及其下游的探针结果 */
  ping(traceId: string): Promise<PingResult>;
  /** 裁剪为前端决策所需的最小能力事实（见 `dto/response/capabilities.response.ts`） */
  capabilities(traceId: string): Promise<CapabilitiesResult>;
}

export function createJobService(deps: { jobService: JobServiceClient }): JobService {
  return {
    async ping(traceId: string): Promise<PingResult> {
      // 只做一次下游调用；失败时异常原样上抛，由 errorHandler 统一映射（plan.md §6.4）
      const downstream = await deps.jobService.ping(traceId);

      // 把「本跳是谁」包在外层：前端据此逐跳渲染，断在哪跳一眼可见
      return {
        service: config.serviceName,
        status: 'ok',
        version: config.version,
        runtime: `node ${process.version}`,
        traceId,
        downstream,
      };
    },

    async capabilities(traceId: string): Promise<CapabilitiesResult> {
      // 裁剪掉 `service` / `error` 等诊断字段：前端只据能力布尔值做决策，
      // 多暴露的字段迟早会被误用成「业务输入」（spec.md §2.7：Vue 不自行推断规则）
      const upstream = await deps.jobService.capabilities(traceId);

      return {
        llmEnabled: upstream.llmEnabled,
        analyzerReachable: upstream.analyzerReachable,
      };
    },
  };
}
