import request from 'supertest';

import { createApp } from '../../src/app';
import type { JobServiceClient } from '../../src/client/jobService.client';
import type { PingResult } from '../../src/dto/response/ping.response';
import { AppError } from '../../src/errors/appError';
import { containerWithJobServiceClient } from '../support/container';

const HEALTHY_CHAIN: PingResult = {
  service: 'job-service',
  status: 'ok',
  version: '0.1.0',
  runtime: 'java 17.0.11',
  traceId: 'upstream-trace',
  downstream: {
    service: 'analyzer',
    status: 'ok',
    version: '0.1.0',
    runtime: 'python 3.13.14',
    traceId: 'upstream-trace',
  },
};

const healthyJobService: JobServiceClient = {
  ping: async (traceId) => ({ ...HEALTHY_CHAIN, traceId }),
};

function appWith(jobService: JobServiceClient) {
  return createApp(containerWithJobServiceClient(jobService)).callback();
}

describe('e2e · GET /api/ping —— 全链连通性探针', () => {
  it('返回 Vue → BFF → job-service → analyzer 三跳结构', async () => {
    const response = await request(appWith(healthyJobService)).get('/api/ping');

    expect(response.status).toBe(200);
    expect(response.body.service).toBe('bff');
    expect(response.body.status).toBe('ok');
    expect(response.body.runtime).toMatch(/^node v/);
    expect(response.body.downstream.service).toBe('job-service');
    expect(response.body.downstream.downstream.service).toBe('analyzer');
  });

  it('缺少上游 traceId 时自行生成，并回写到响应头（spec.md §2.8）', async () => {
    const response = await request(appWith(healthyJobService)).get('/api/ping');

    const headerTraceId = response.headers['x-trace-id'];
    expect(headerTraceId).toBeTruthy();
    expect(response.body.traceId).toBe(headerTraceId);
  });

  it('透传上游传入的 traceId，全链一致', async () => {
    const response = await request(appWith(healthyJobService))
      .get('/api/ping')
      .set('X-Trace-Id', 'trace-from-web');

    expect(response.headers['x-trace-id']).toBe('trace-from-web');
    expect(response.body.traceId).toBe('trace-from-web');
    expect(response.body.downstream.traceId).toBe('trace-from-web');
  });

  it('下游超时 → 504 UPSTREAM_TIMEOUT（plan.md §6.4）', async () => {
    const timingOut: JobServiceClient = {
      ping: async () => {
        throw AppError.upstreamTimeout('job-service');
      },
    };

    const response = await request(appWith(timingOut)).get('/api/ping');

    expect(response.status).toBe(504);
    expect(response.body.code).toBe('UPSTREAM_TIMEOUT');
    expect(response.body.traceId).toBe(response.headers['x-trace-id']);
  });

  it('下游 5xx → 503 SERVICE_UNAVAILABLE，且不透传原始错误栈（spec.md §3.3）', async () => {
    const broken: JobServiceClient = {
      ping: async () => {
        throw AppError.serviceUnavailable('job-service');
      },
    };

    const response = await request(appWith(broken)).get('/api/ping');

    expect(response.status).toBe(503);
    expect(response.body.code).toBe('SERVICE_UNAVAILABLE');
    expect(Object.keys(response.body).sort()).toEqual(['code', 'message', 'traceId']);
  });

  it('下游异常为未知错误时收口为 500 INTERNAL_ERROR', async () => {
    const exploding: JobServiceClient = {
      ping: async () => {
        throw new Error('boom: internal stack detail');
      },
    };

    const response = await request(appWith(exploding)).get('/api/ping');

    expect(response.status).toBe(500);
    expect(response.body.code).toBe('INTERNAL_ERROR');
    expect(JSON.stringify(response.body)).not.toContain('boom');
  });
});
