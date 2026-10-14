import type { JobServiceClient } from '../../src/client/jobService.client';
import { config } from '../../src/config';
import type { PingResult } from '../../src/dto/response/ping.response';
import { AppError } from '../../src/errors/appError';
import { createJobService } from '../../src/service/job.service';

/**
 * 业务层纯单测：注入 stub 适配器，不启 HTTP、不碰真实下游。
 *
 * 测什么（指南 §2.5 分层测试矩阵）：编排顺序、不变量、DTO 裁剪。
 * 不测什么：HTTP 状态码（那是 e2e 的事）。
 */
describe('unit · JobService.ping', () => {
  const downstreamResult: PingResult = {
    service: 'job-service',
    status: 'ok',
    version: '0.1.0',
    runtime: 'java 17.0.2',
    traceId: 't-1',
    downstream: { service: 'analyzer', status: 'ok', runtime: 'python 3.13.14', traceId: 't-1' },
  };

  const stubClient = (impl: JobServiceClient['ping']): JobServiceClient => ({ ping: impl });

  it('把本跳信息包在下游结果外层（前端据此逐跳渲染）', async () => {
    const service = createJobService({ jobService: stubClient(async () => downstreamResult) });

    const result = await service.ping('trace-a');

    expect(result.service).toBe(config.serviceName);
    expect(result.version).toBe(config.version);
    expect(result.runtime).toMatch(/^node v/);
    expect(result.downstream).toBe(downstreamResult);
  });

  it('traceId 以本层收到的为准，不采信下游回显', async () => {
    const service = createJobService({
      jobService: stubClient(async () => ({ ...downstreamResult, traceId: 'downstream-lying' })),
    });

    const result = await service.ping('trace-b');

    expect(result.traceId).toBe('trace-b');
  });

  it('把 traceId 原样交给下游（全链一致的前提）', async () => {
    const seen: string[] = [];
    const service = createJobService({
      jobService: stubClient(async (traceId) => {
        seen.push(traceId);
        return downstreamResult;
      }),
    });

    await service.ping('trace-c');

    expect(seen).toEqual(['trace-c']);
  });

  it('下游异常原样上抛，由 errorHandler 统一映射（本层不吞异常）', async () => {
    const service = createJobService({
      jobService: stubClient(async () => {
        throw AppError.serviceUnavailable('job-service');
      }),
    });

    await expect(service.ping('trace-d')).rejects.toMatchObject({
      status: 503,
      code: 'SERVICE_UNAVAILABLE',
    });
  });
});
