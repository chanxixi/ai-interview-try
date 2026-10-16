import { config } from '../config';
import type { UpstreamCapabilities } from '../dto/response/capabilities.response';
import type { PingResult } from '../dto/response/ping.response';
import { requestJson } from './http';

/**
 * job-service（Java / Spring Boot）适配器。
 *
 * 只做一件事：一次下游调用 + 超时 + traceId 透传 + 错误归一。
 * **不解读业务字段**（"这是不是有效岗位"由 Service 判断），**不做重试**（本期不需要）。
 *
 * ⚠️ BFF 没有 repository / entity —— 数据访问权只属于 Java 层（spec.md §2.6 / §3.1）。
 *    本文件是全项目唯一允许出现 `job-service` baseUrl 的地方。
 *
 * T3 起本适配器会补齐 `listJobs` / `getJob`（契约见 contracts/bff-java.yaml）。
 */
export interface JobServiceClient {
  /** 全链连通性探针，返回 job-service 及其下游（analyzer）的结果 */
  ping(traceId: string): Promise<PingResult>;
  /** 能力探测：返回 job-service 及其下游（analyzer）的能力开关 */
  capabilities(traceId: string): Promise<UpstreamCapabilities>;
}

export function createJobServiceClient(): JobServiceClient {
  return {
    ping(traceId: string): Promise<PingResult> {
      return requestJson<PingResult>({
        service: 'job-service',
        url: `${config.jobService.baseUrl}/internal/ping`,
        timeoutMs: config.jobService.timeoutMs,
        traceId,
      });
    },
    capabilities(traceId: string): Promise<UpstreamCapabilities> {
      return requestJson<UpstreamCapabilities>({
        service: 'job-service',
        url: `${config.jobService.baseUrl}/internal/capabilities`,
        timeoutMs: config.jobService.timeoutMs,
        traceId,
      });
    },
  };
}
