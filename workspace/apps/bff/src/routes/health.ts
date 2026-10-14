import Router from '@koa/router';

import { config } from '../config';

/** 健康检查：spec.md §2.8 要求每个服务暴露 GET /healthz。 */
export const healthRouter = new Router();

healthRouter.get('/healthz', (ctx) => {
  ctx.body = { status: 'ok', service: config.serviceName };
});
