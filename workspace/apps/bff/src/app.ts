import Koa from 'koa';

import { createJobServiceClient, type JobServiceClient } from './client/jobService.client';
import { HealthController } from './controller/health.controller';
import { JobController } from './controller/job.controller';
import { errorHandlerMiddleware } from './middleware/errorHandler';
import { requestLogMiddleware } from './middleware/requestLog';
import { traceIdMiddleware } from './middleware/traceId';
import { createApiRouter } from './route';
import { createJobService } from './service/job.service';

export interface AppDeps {
  /** 下游适配器；测试时注入 stub，避免依赖真实服务 */
  jobService: JobServiceClient;
}

/**
 * 组装 Koa app（与监听分离，便于测试直接喂 app.callback()）。
 *
 * 中间件顺序（洋葱模型，不可调换）：
 *   errorHandler（最外层，兜住一切）→ traceId → 访问日志 → 路由
 *
 * ⚠️ 本函数里的装配在 P1 第 6 步会整体搬到 `container.ts`（组合根）。
 */
export function createApp(deps: AppDeps = { jobService: createJobServiceClient() }): Koa {
  const app = new Koa();

  // 关掉 Koa 自带的错误输出，统一走 errorHandler 的结构化日志
  app.silent = true;

  app.use(errorHandlerMiddleware);
  app.use(traceIdMiddleware);
  app.use(requestLogMiddleware);

  const jobService = createJobService({ jobService: deps.jobService });

  const router = createApiRouter({
    health: new HealthController(),
    job: new JobController(jobService),
  });
  app.use(router.routes()).use(router.allowedMethods());

  return app;
}
