import request from 'supertest';

import { createApp } from '../../src/app';
import type { JobServiceClient } from '../../src/client/jobService.client';
import { containerWithJobServiceClient } from '../support/container';

/** 下游永远可用的 stub —— 用例不依赖任何真实服务。 */
const healthyJobService: JobServiceClient = {
  ping: async (traceId) => ({
    service: 'job-service',
    status: 'ok',
    version: '0.1.0',
    runtime: 'java 17.0.11',
    traceId,
    downstream: {
      service: 'analyzer',
      status: 'ok',
      version: '0.1.0',
      runtime: 'python 3.13.14',
      traceId,
    },
  }),
  capabilities: async () => ({ service: 'job-service', analyzerReachable: true, llmEnabled: true }),
};

describe('e2e · GET /healthz', () => {
  it('返回统一健康结构（spec.md §2.8）', async () => {
    const response = await request(
      createApp(containerWithJobServiceClient(healthyJobService)).callback(),
    ).get('/healthz');

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ status: 'ok', service: 'bff' });
  });

  it('响应头始终带 X-Trace-Id', async () => {
    const response = await request(
      createApp(containerWithJobServiceClient(healthyJobService)).callback(),
    ).get('/healthz');

    expect(response.headers['x-trace-id']).toBeTruthy();
  });
});
