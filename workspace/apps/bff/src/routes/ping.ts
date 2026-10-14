import Router from '@koa/router';

import type { JobService } from '../service/job.service';

export interface PingRouteDeps {
  jobService: JobService;
}

/**
 * 全链连通性探针 `GET /api/ping`。
 *
 * 链路：Vue → **BFF** → job-service → analyzer
 *
 * 路由层只做「路径 → 处理函数」接线，聚合逻辑在 `service/job.service.ts`。
 * 下游不可用时异常上抛，由 errorHandler 统一映射为 503 / 504（plan.md §6.4）。
 *
 * ⚠️ 本文件在 P1 第 5 步会被 `controller/job.controller.ts` + `route/index.ts` 取代。
 */
export function createPingRouter(deps: PingRouteDeps): Router {
  const router = new Router();

  router.get('/api/ping', async (ctx) => {
    ctx.state.log.info('ping received');
    ctx.body = await deps.jobService.ping(ctx.state.traceId);
  });

  return router;
}
