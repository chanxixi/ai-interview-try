import { config } from '../config';
import { requestJson } from './http';

/**
 * 下游连通性探针响应。
 *
 * job-service 与 analyzer 的 `/ping` 形状一致，因此共用同一类型：
 * 每一跳回显自己的 `service` / `runtime` / `traceId`，并把自己下游的结果挂在 `downstream`。
 */
export interface PingResult {
  service: string;
  status: 'ok' | 'down';
  version?: string;
  runtime?: string;
  traceId?: string | null;
  error?: string;
  downstream?: PingResult;
}

/** job-service 领域 API 客户端（骨架阶段只暴露探针）。 */
export interface JobServiceClient {
  ping(traceId: string): Promise<PingResult>;
}

export function createJobServiceClient(): JobServiceClient {
  return {
    async ping(traceId: string): Promise<PingResult> {
      return requestJson<PingResult>({
        service: 'job-service',
        url: `${config.jobService.baseUrl}/internal/ping`,
        timeoutMs: config.jobService.timeoutMs,
        traceId,
      });
    },
  };
}
