import Koa from 'koa';

import { createJobServiceClient, type JobServiceClient } from './client/jobService.client';
import { errorHandlerMiddleware } from './middleware/errorHandler';
import { requestLogMiddleware } from './middleware/requestLog';
import { traceIdMiddleware } from './middleware/traceId';
import { healthRouter } from './routes/health';
import { createPingRouter } from './routes/ping';

export interface AppDeps {
  /** 下游客户端；测试时注入 stub，避免依赖真实服务 */
  jobService: JobServiceClient;
}

/**
 * 组装 Koa app（与监听分离，便于测试直接喂 app.callback()）。
 *
 * 中间件顺序（洋葱模型）：
 *   errorHandler（最外层，兜住一切）→ traceId → 访问日志 → 路由
 */
export function createApp(deps: AppDeps = { jobService: createJobServiceClient() }): Koa {
  const app = new Koa();

  // 关掉 Koa 自带的错误输出，统一走 errorHandler 的结构化日志
  app.silent = true;

  app.use(errorHandlerMiddleware);
  app.use(traceIdMiddleware);
  app.use(requestLogMiddleware);

  app.use(healthRouter.routes()).use(healthRouter.allowedMethods());
  const pingRouter = createPingRouter(deps);
  app.use(pingRouter.routes()).use(pingRouter.allowedMethods());

  return app;
}
