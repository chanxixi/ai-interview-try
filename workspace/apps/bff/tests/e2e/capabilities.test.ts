import request from 'supertest';

import { createApp } from '../../src/app';
import type { JobServiceClient } from '../../src/client/jobService.client';
import type { UpstreamCapabilities } from '../../src/dto/response/capabilities.response';
import { AppError } from '../../src/errors/appError';
import { containerWithJobServiceClient } from '../support/container';

/** 只替换能力探测这一跳，其余保持真实装配（Service / Controller 都跑真实实现）。 */
function clientWithCapabilities(
  capabilities: JobServiceClient['capabilities'],
): JobServiceClient {
  return {
    ping: async () => {
      throw new Error('unused in this suite');
    },
    capabilities,
  };
}

function appWith(jobService: JobServiceClient) {
  return createApp(containerWithJobServiceClient(jobService)).callback();
}

describe('e2e · GET /api/capabilities —— 能力探测', () => {
  it('analyzer 可达且 LLM 启用 → 两个布尔值都为 true', async () => {
    const response = await request(
      appWith(
        clientWithCapabilities(async () => ({
          service: 'job-service',
          analyzerReachable: true,
          llmEnabled: true,
        })),
      ),
    ).get('/api/capabilities');

    expect(response.status).toBe(200);
    // 逐字相等：这是 BFF 对前端的**契约面**，多一个诊断字段都算破坏裁剪纪律
    expect(response.body).toEqual({ llmEnabled: true, analyzerReachable: true });
  });

  it('LLM 未配置 → llmEnabled=false（前端据此禁用「深度」）', async () => {
    const response = await request(
      appWith(
        clientWithCapabilities(async () => ({
          service: 'job-service',
          analyzerReachable: true,
          llmEnabled: false,
        })),
      ),
    ).get('/api/capabilities');

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ llmEnabled: false, analyzerReachable: true });
  });

  it('analyzer 不可达 → 200 + 两个 false，且不透传 error / 异常类名（spec.md §3.3）', async () => {
    const upstream: UpstreamCapabilities = {
      service: 'job-service',
      analyzerReachable: false,
      llmEnabled: false,
      error: 'ResourceAccessException',
    };

    const response = await request(
      appWith(clientWithCapabilities(async () => upstream)),
    ).get('/api/capabilities');

    // 能力未知是**正常回报**，不是错误 —— 前端需要拿到它才能禁用「深度」
    expect(response.status).toBe(200);
    expect(response.body).toEqual({ llmEnabled: false, analyzerReachable: false });
    expect(JSON.stringify(response.body)).not.toContain('ResourceAccessException');
  });

  it('响应头始终带 X-Trace-Id（spec.md §2.8）', async () => {
    const response = await request(
      appWith(
        clientWithCapabilities(async () => ({
          service: 'job-service',
          analyzerReachable: true,
          llmEnabled: true,
        })),
      ),
    )
      .get('/api/capabilities')
      .set('X-Trace-Id', 'trace-from-web');

    expect(response.headers['x-trace-id']).toBe('trace-from-web');
  });

  it('job-service 本身不可达 → 503 SERVICE_UNAVAILABLE（与 /api/ping 同一错误映射）', async () => {
    const response = await request(
      appWith(
        clientWithCapabilities(async () => {
          throw AppError.serviceUnavailable('job-service');
        }),
      ),
    ).get('/api/capabilities');

    expect(response.status).toBe(503);
    expect(response.body.code).toBe('SERVICE_UNAVAILABLE');
    expect(Object.keys(response.body).sort()).toEqual(['code', 'message', 'traceId']);
  });
});
