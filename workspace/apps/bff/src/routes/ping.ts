import Router from '@koa/router';

import type { JobServiceClient } from '../client/jobService.client';
import { config } from '../config';
import type { PingResult } from '../dto/response/ping.response';

export interface PingRouteDeps {
  jobService: JobServiceClient;
}

/**
 * 全链连通性探针 `GET /api/ping`。
 *
 * 链路：Vue → **BFF** → job-service → analyzer
 *
 * BFF 在这里只做两件事：透传 traceId、把下游结果原样聚合给前端。
 * **不承载业务规则**（ADR-005），因此本路由没有任何领域判断。
 *
 * 下游不可用时抛错，由 errorHandler 统一映射为 503 / 504（plan.md §6.4）。
 *
 * ⚠️ 本文件在 P1 之后会被 `controller/job.controller.ts` + `route/index.ts` 取代。
 */
export function createPingRouter(deps: PingRouteDeps): Router {
  const router = new Router();

  router.get('/api/ping', async (ctx) => {
    const { traceId } = ctx.state;
    ctx.state.log.info('ping received');

    const downstream = await deps.jobService.ping(traceId);

    const body: PingResult = {
      service: config.serviceName,
      status: 'ok',
      version: config.version,
      runtime: `node ${process.version}`,
      traceId,
      downstream,
    };
    ctx.body = body;
  });

  return router;
}
