import Koa from 'koa';
import bodyParser from 'koa-bodyparser';

import { BODY_LIMIT } from './config/constants';
import { buildContainer, type Container } from './container';
import { errorHandlerMiddleware } from './middleware/errorHandler.middleware';
import { requestLogMiddleware } from './middleware/requestLog.middleware';
import { traceIdMiddleware } from './middleware/traceId.middleware';
import { createApiRouter } from './route';

/**
 * 组装 Koa app（与监听分离，便于测试直接喂 `app.callback()`）。
 *
 * 中间件顺序（洋葱模型，**不可调换**）：
 *   errorHandler（最外层，兜住一切）
 *     → traceId（后面所有日志都需要它）
 *       → 访问日志
 *         → bodyParser
 *           → 路由
 *
 * 装配依赖由 `container.ts` 提供；测试传一个替换过某层的 container 即可。
 *
 * ⚠️ `rateLimit.middleware.ts` 是预留件，本期**刻意不挂载**（spec.md §1.4 Out of Scope）。
 */
export function createApp(container: Container = buildContainer()): Koa {
  const app = new Koa();

  // 关掉 Koa 自带的错误输出，统一走 errorHandler 的结构化日志
  app.silent = true;

  app.use(errorHandlerMiddleware);
  app.use(traceIdMiddleware);
  app.use(requestLogMiddleware);
  app.use(bodyParser({ jsonLimit: BODY_LIMIT }));

  const router = createApiRouter(container.controllers);
  app.use(router.routes()).use(router.allowedMethods());

  return app;
}
